"""Coordinator and persistence for Shared Schedule."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ANCHOR_DATE,
    CONF_COUNTRY,
    CONF_CURRENT_PARTY,
    CONF_HANDOVER_TIME,
    CONF_PARTY_A,
    CONF_PARTY_B,
    CONF_RECURRENCE_WEEKS,
    CONF_SHIFT_HOLIDAYS,
    DOMAIN,
)
from .holiday import (
    HolidayProvider,
    normalize_fallback_holidays,
    remove_fallback_holiday,
    resolve_holiday_provider,
    upsert_fallback_holiday,
)
from .model import ScheduleModel, ScheduleSettings, ScheduleState

_LOGGER = logging.getLogger(__name__)
_STORE_VERSION = 1


class SharedScheduleCoordinator(DataUpdateCoordinator[dict[str, object]]):
    """Own persisted state, calculations and the next timer."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, name=entry.title, config_entry=entry)
        self.entry = entry
        self._store: Store[dict[str, Any]] = Store(
            hass, _STORE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        self._lock = asyncio.Lock()
        self._cancel_timer = None
        self._tz = ZoneInfo(hass.config.time_zone)
        self.fallback_holidays: list[dict[str, str]] = []
        self.holiday_provider: HolidayProvider
        self.model: ScheduleModel

    @property
    def settings_data(self) -> dict[str, Any]:
        """Return config data with editable options overlaid."""
        return {**self.entry.data, **self.entry.options}

    def _now(self) -> datetime:
        return dt_util.utcnow().astimezone(self._tz)

    @property
    def today(self) -> date:
        """Return today's date in Home Assistant's configured timezone."""
        return self._now().date()

    @property
    def actual_current_party(self) -> str:
        """Return current ownership including a date override for today."""
        return self.model.actual_party_at(self._now())

    def _settings(self) -> ScheduleSettings:
        data = self.settings_data
        return ScheduleSettings(
            party_a=data[CONF_PARTY_A],
            party_b=data[CONF_PARTY_B],
            recurrence_weeks=int(data[CONF_RECURRENCE_WEEKS]),
            shift_public_holidays=data[CONF_SHIFT_HOLIDAYS],
        )

    def _local_datetime(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            return value.replace(tzinfo=self._tz)
        return value.astimezone(self._tz)

    def _initial_base(self, now: datetime) -> datetime:
        data = self.settings_data
        anchor = date.fromisoformat(data[CONF_ANCHOR_DATE])
        handover_time = time.fromisoformat(data[CONF_HANDOVER_TIME])
        candidate = datetime.combine(anchor, handover_time, self._tz)
        interval = self._settings().interval
        if candidate < now:
            candidate += (int((now - candidate) // interval) + 1) * interval
        return candidate

    async def async_initialize(self) -> None:
        """Load state, reconcile downtime, publish, and arm a timer."""
        stored = await self._store.async_load()
        stored = stored or {}
        self.fallback_holidays = normalize_fallback_holidays(
            stored.get("fallback_holidays", [])
        )
        shift_holidays = self._settings().shift_public_holidays
        if shift_holidays:
            self.holiday_provider = await self.hass.async_add_executor_job(
                resolve_holiday_provider,
                True,
                self.settings_data[CONF_COUNTRY],
                self.fallback_holidays,
            )
            if self.holiday_provider.error:
                _LOGGER.warning(
                    "Automatic holiday data is unavailable for %s: %s",
                    self.settings_data[CONF_COUNTRY],
                    self.holiday_provider.error,
                )
        else:
            self.holiday_provider = resolve_holiday_provider(
                False,
                self.settings_data[CONF_COUNTRY],
                self.fallback_holidays,
            )
        now = self._now()
        if stored:
            next_base = self._local_datetime(
                datetime.fromisoformat(stored["next_base"])
            )
            override = stored.get("override")
            state = ScheduleState(
                current_party=stored["current_party"],
                next_base=next_base,
                override=(
                    self._local_datetime(datetime.fromisoformat(override))
                    if override
                    else None
                ),
                date_overrides=dict(stored.get("date_overrides", {})),
            )
        else:
            state = ScheduleState(
                current_party=self.settings_data[CONF_CURRENT_PARTY],
                next_base=self._initial_base(now),
            )
        self.model = ScheduleModel(self._settings(), state, self.holiday_provider)
        completed = self.model.reconcile(now)
        if completed:
            _LOGGER.info("Reconciled %s missed handover(s)", completed)
        await self._async_commit()

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "current_party": self.model.state.current_party,
                "next_base": self.model.state.next_base.isoformat(),
                "override": (
                    self.model.state.override.isoformat()
                    if self.model.state.override
                    else None
                ),
                "date_overrides": dict(sorted(self.model.state.date_overrides.items())),
                "fallback_holidays": [dict(item) for item in self.fallback_holidays],
            }
        )

    def _schedule_timer(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
        now = self._now()
        next_midnight = datetime.combine(
            now.date() + timedelta(days=1), time.min, self._tz
        )
        when = dt_util.as_utc(min(self.model.effective_handover, next_midnight))
        self._cancel_timer = async_track_point_in_utc_time(
            self.hass, self._async_timer_fired, when
        )

    async def _async_commit(self) -> None:
        await self._async_save()
        self.async_set_updated_data(self.model.attributes(self._now()))
        self._schedule_timer()

    async def _async_timer_fired(self, now: datetime) -> None:
        async with self._lock:
            self.model.reconcile(now.astimezone(self._tz))
            await self._async_commit()

    async def async_set_override(self, value: datetime) -> None:
        async with self._lock:
            self.model.set_override(self._local_datetime(value), self._now())
            await self._async_commit()

    async def async_clear_override(self) -> None:
        async with self._lock:
            self.model.clear_override()
            await self._async_commit()

    async def async_set_date_overrides(self, values: list[date], party: str) -> None:
        """Add or replace one or many date ownership overrides."""
        async with self._lock:
            self.model.set_date_overrides(values, party)
            await self._async_commit()

    async def async_remove_date_overrides(self, values: list[date]) -> None:
        """Remove one or many date ownership overrides."""
        async with self._lock:
            self.model.remove_date_overrides(values)
            await self._async_commit()

    async def async_set_fallback_holiday(
        self, value: date, name: str | None = None
    ) -> None:
        """Create or update a stored fallback holiday."""
        async with self._lock:
            self.fallback_holidays = upsert_fallback_holiday(
                self.fallback_holidays, value, name
            )
            self.holiday_provider.set_fallback_holidays(self.fallback_holidays)
            await self._async_commit()

    async def async_remove_fallback_holiday(self, value: date) -> None:
        """Remove a stored fallback holiday."""
        async with self._lock:
            self.fallback_holidays = remove_fallback_holiday(
                self.fallback_holidays, value
            )
            self.holiday_provider.set_fallback_holidays(self.fallback_holidays)
            await self._async_commit()

    def calendar(self, start: date, days: int) -> list[dict[str, object]]:
        """Return an ownership calendar for frontend consumers."""
        return self.model.calendar(start, days)

    async def async_set_current_party(self, party: str) -> None:
        async with self._lock:
            self.model.set_current_party(party)
            await self._async_commit()

    async def async_complete_handover(self) -> None:
        async with self._lock:
            self.model.complete_handover()
            await self._async_commit()

    async def async_shift_series(self, value: datetime) -> None:
        async with self._lock:
            value = self._local_datetime(value)
            if value <= self._now():
                raise ValueError("the new base handover must be in the future")
            self.model.shift_series(value)
            await self._async_commit()

    async def async_shutdown(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
