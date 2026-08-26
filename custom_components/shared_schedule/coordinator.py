"""Coordinator and persistence for Shared Schedule."""

from __future__ import annotations

import asyncio
import logging
import re
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
    CONF_MY_PARTY,
    CONF_PARTY_A,
    CONF_PARTY_A_COLOR,
    CONF_PARTY_B,
    CONF_PARTY_B_COLOR,
    CONF_RECURRENCE_WEEKS,
    CONF_SHIFT_HOLIDAYS,
    DEFAULT_PARTY_A_COLOR,
    DEFAULT_PARTY_B_COLOR,
    DOMAIN,
    EVENT_HANDOVER_COMPLETED,
    EVENT_SCHEDULE_CHANGED,
    HANDOVER_NOTE_MAX_LENGTH,
    PARTY_A,
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
_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


def _display_settings(stored: dict[str, Any]) -> dict[str, str]:
    """Return validated display settings with backwards-compatible defaults."""
    values = stored.get("display_settings", {})
    values = values if isinstance(values, dict) else {}
    result = {
        CONF_PARTY_A_COLOR: DEFAULT_PARTY_A_COLOR,
        CONF_PARTY_B_COLOR: DEFAULT_PARTY_B_COLOR,
    }
    for key in result:
        value = values.get(key)
        if isinstance(value, str) and _COLOR_PATTERN.fullmatch(value):
            result[key] = value
    return result


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
        self.display_settings = {
            CONF_PARTY_A_COLOR: DEFAULT_PARTY_A_COLOR,
            CONF_PARTY_B_COLOR: DEFAULT_PARTY_B_COLOR,
        }
        self.fallback_holidays: list[dict[str, str]] = []
        self.handover_notes: dict[str, str] = {}
        self._emitted_handover_ids: list[str] = []
        self._last_actual_party: str | None = None
        self._last_actual_observed: datetime | None = None
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
            my_party=data.get(CONF_MY_PARTY, PARTY_A),
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
        self.display_settings = _display_settings(stored)
        self.fallback_holidays = normalize_fallback_holidays(
            stored.get("fallback_holidays", [])
        )
        notes = stored.get("handover_notes", {})
        self.handover_notes = (
            {
                str(key): str(value)[:HANDOVER_NOTE_MAX_LENGTH]
                for key, value in notes.items()
                if isinstance(key, str) and isinstance(value, str) and value.strip()
            }
            if isinstance(notes, dict)
            else {}
        )
        emitted = stored.get("emitted_handover_ids", [])
        self._emitted_handover_ids = (
            [str(value) for value in emitted[-50:]]
            if isinstance(emitted, list)
            else []
        )
        stored_party = stored.get("last_actual_party")
        self._last_actual_party = (
            stored_party if stored_party in ("a", "b") else None
        )
        stored_observed = stored.get("last_actual_observed")
        try:
            self._last_actual_observed = (
                self._local_datetime(datetime.fromisoformat(stored_observed))
                if isinstance(stored_observed, str)
                else None
            )
        except ValueError:
            self._last_actual_observed = None
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
        offline_transitions = (
            self.model.actual_transitions_between(self._last_actual_observed, now)
            if self._last_actual_party is not None
            and self._last_actual_observed is not None
            else []
        )
        due = self._due_handovers(now)
        completed = self.model.reconcile(now)
        if completed:
            _LOGGER.info("Reconciled %s missed handover(s)", completed)
            self._discard_completed_notes()
            self._emit_due_handovers(due, reconciled=True)
        self._emit_offline_date_override_transitions(offline_transitions)
        await self._async_commit()

    async def _async_save(self) -> None:
        observed = self._now()
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
                "display_settings": dict(self.display_settings),
                "handover_notes": dict(self.handover_notes),
                "emitted_handover_ids": self._emitted_handover_ids[-50:],
                "last_actual_party": self.model.actual_party_at(observed),
                "last_actual_observed": observed.isoformat(),
            }
        )

    @property
    def active_handover_id(self) -> str:
        """Return the stable identifier for the upcoming cadence occurrence."""
        return self.model.base_handover.isoformat()

    @property
    def active_handover_note(self) -> str | None:
        """Return the private note for the upcoming cadence occurrence."""
        return self.handover_notes.get(self.active_handover_id)

    def _handover_source(self, model: ScheduleModel) -> str:
        if model.state.override is not None:
            return "manual_override"
        if model.shifted_for_public_holiday:
            return "public_holiday"
        return "normal"

    def _due_handovers(self, now: datetime) -> list[dict[str, object]]:
        """Describe due occurrences before reconciliation mutates the model."""
        state = ScheduleState(
            current_party=self.model.state.current_party,
            next_base=self.model.state.next_base,
            override=self.model.state.override,
            date_overrides=dict(self.model.state.date_overrides),
        )
        probe = ScheduleModel(self._settings(), state, self.holiday_provider)
        due: list[dict[str, object]] = []
        for _ in range(100):
            effective = probe.effective_handover
            if effective > now:
                break
            occurrence_id = probe.base_handover.isoformat()
            from_party = probe.actual_party_at(effective - timedelta(microseconds=1))
            to_party = probe.actual_party_at(effective)
            due.append(
                {
                    "occurrence_id": occurrence_id,
                    "effective": effective,
                    "from_party": from_party,
                    "to_party": to_party,
                    "source": self._handover_source(probe),
                }
            )
            probe.complete_handover()
        return due

    def _emit_due_handovers(
        self, due: list[dict[str, object]], *, reconciled: bool
    ) -> None:
        for item in due:
            occurrence_id = str(item["occurrence_id"])
            if occurrence_id in self._emitted_handover_ids:
                continue
            self._emitted_handover_ids.append(occurrence_id)
            if item["from_party"] == item["to_party"]:
                continue
            self._fire_handover_event(
                str(item["from_party"]),
                str(item["to_party"]),
                item["effective"],
                str(item["source"]),
                occurrence_id,
                reconciled=reconciled,
            )

    def _emit_offline_date_override_transitions(
        self, transitions: list[dict[str, object]]
    ) -> None:
        """Reconcile date-override boundaries crossed while HA was offline."""
        for transition in transitions:
            if transition["source"] != "date_override":
                continue
            effective = transition["datetime"]
            occurrence_id = f"date-boundary:{effective.isoformat()}"
            if occurrence_id in self._emitted_handover_ids:
                continue
            self._emitted_handover_ids.append(occurrence_id)
            self._fire_handover_event(
                str(transition["from_party"]),
                str(transition["to_party"]),
                effective,
                "date_override",
                occurrence_id,
                reconciled=True,
            )

    def _fire_handover_event(
        self,
        from_party: str,
        to_party: str,
        effective: object,
        source: str,
        occurrence_id: str,
        *,
        reconciled: bool,
    ) -> None:
        self.hass.bus.async_fire(
            EVENT_HANDOVER_COMPLETED,
            {
                "entry_id": self.entry.entry_id,
                "occurrence_id": occurrence_id,
                "from_party_key": from_party,
                "from_party_name": self.model.party_name(from_party),
                "to_party_key": to_party,
                "to_party_name": self.model.party_name(to_party),
                "effective_handover": effective.isoformat(),
                "source": source,
                "reconciled_after_downtime": reconciled,
            },
        )

    def _fire_schedule_change(self, action: str, **data: object) -> None:
        self.hass.bus.async_fire(
            EVENT_SCHEDULE_CHANGED,
            {"entry_id": self.entry.entry_id, "action": action, **data},
        )

    def _discard_completed_notes(self) -> None:
        active = self.active_handover_id
        self.handover_notes = {
            key: value for key, value in self.handover_notes.items() if key == active
        }

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
            local_now = now.astimezone(self._tz)
            due = self._due_handovers(local_now)
            completed = self.model.reconcile(local_now)
            if completed:
                self._discard_completed_notes()
                self._emit_due_handovers(due, reconciled=False)
            elif local_now.time() == time.min:
                before = self.model.actual_party_at(
                    local_now - timedelta(microseconds=1)
                )
                after = self.model.actual_party_at(local_now)
                occurrence_id = f"date-boundary:{local_now.isoformat()}"
                if (
                    before != after
                    and occurrence_id not in self._emitted_handover_ids
                ):
                    self._emitted_handover_ids.append(occurrence_id)
                    self._fire_handover_event(
                        before,
                        after,
                        local_now,
                        "date_override",
                        occurrence_id,
                        reconciled=False,
                    )
            await self._async_commit()

    async def async_set_override(self, value: datetime) -> None:
        async with self._lock:
            previous = self.model.state.override
            self.model.set_override(self._local_datetime(value), self._now())
            await self._async_commit()
            if previous != self.model.state.override:
                self._fire_schedule_change(
                    (
                        "handover_override_changed"
                        if previous
                        else "handover_override_added"
                    ),
                    effective_handover=self.model.effective_handover.isoformat(),
                )

    async def async_clear_override(self) -> None:
        async with self._lock:
            previous = self.model.state.override
            self.model.clear_override()
            await self._async_commit()
            if previous is not None:
                self._fire_schedule_change(
                    "handover_override_cleared",
                    effective_handover=self.model.effective_handover.isoformat(),
                )

    async def async_set_date_overrides(self, values: list[date], party: str) -> None:
        """Add or replace one or many date ownership overrides."""
        async with self._lock:
            previous = dict(self.model.state.date_overrides)
            self.model.set_date_overrides(values, party)
            await self._async_commit()
            if previous != self.model.state.date_overrides:
                self._fire_schedule_change(
                    "date_overrides_changed",
                    dates=[value.isoformat() for value in values],
                    party=party,
                )

    async def async_remove_date_overrides(self, values: list[date]) -> None:
        """Remove one or many date ownership overrides."""
        async with self._lock:
            previous = dict(self.model.state.date_overrides)
            self.model.remove_date_overrides(values)
            await self._async_commit()
            if previous != self.model.state.date_overrides:
                self._fire_schedule_change(
                    "date_overrides_removed",
                    dates=[value.isoformat() for value in values],
                )

    async def async_set_temporary_change(
        self,
        start: date,
        end: date,
        party: str,
        replace_values: list[date] | None = None,
    ) -> None:
        """Apply a temporary date range and report one meaningful change."""
        async with self._lock:
            values = self.model.temporary_change_dates(start, end, party)
            previous = dict(self.model.state.date_overrides)
            if replace_values:
                self.model.remove_date_overrides(replace_values)
            self.model.set_date_overrides(values, party)
            await self._async_commit()
            if previous != self.model.state.date_overrides:
                self._fire_schedule_change(
                    "date_overrides_changed",
                    ui_source="temporary_change",
                    operation="edit" if replace_values else "create",
                    start=start.isoformat(),
                    end=end.isoformat(),
                    party=party,
                    affected_dates=[value.isoformat() for value in values],
                )

    async def async_set_handover_note(self, occurrence_id: str, note: str) -> None:
        """Add, edit, or remove the private note for the active occurrence."""
        async with self._lock:
            if occurrence_id != self.active_handover_id:
                raise ValueError("the handover occurrence is no longer upcoming")
            value = note.strip()
            if len(value) > HANDOVER_NOTE_MAX_LENGTH:
                raise ValueError(
                    "handover note must be at most "
                    f"{HANDOVER_NOTE_MAX_LENGTH} characters"
                )
            if value:
                self.handover_notes[occurrence_id] = value
            else:
                self.handover_notes.pop(occurrence_id, None)
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

    async def async_set_party_colors(
        self, party_a_color: str, party_b_color: str
    ) -> None:
        """Persist display-only party colours without changing schedule state."""
        async with self._lock:
            self.display_settings = _display_settings(
                {
                    "display_settings": {
                        CONF_PARTY_A_COLOR: party_a_color,
                        CONF_PARTY_B_COLOR: party_b_color,
                    }
                }
            )
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
            occurrence_id = self.active_handover_id
            effective = self._now()
            source = self._handover_source(self.model)
            date_override = self.model.state.date_overrides.get(
                effective.date().isoformat()
            )
            from_party = date_override or self.model.state.current_party
            self.model.complete_handover()
            to_party = date_override or self.model.state.current_party
            self._discard_completed_notes()
            if occurrence_id not in self._emitted_handover_ids:
                self._emitted_handover_ids.append(occurrence_id)
                if from_party != to_party:
                    self._fire_handover_event(
                        from_party,
                        to_party,
                        effective,
                        source,
                        occurrence_id,
                        reconciled=False,
                    )
            await self._async_commit()

    async def async_shift_series(self, value: datetime) -> None:
        async with self._lock:
            value = self._local_datetime(value)
            if value <= self._now():
                raise ValueError("the new base handover must be in the future")
            self.model.shift_series(value)
            self._discard_completed_notes()
            await self._async_commit()
            self._fire_schedule_change(
                "series_shifted", base_handover=self.model.base_handover.isoformat()
            )

    async def async_shutdown(self) -> None:
        if self._cancel_timer:
            self._cancel_timer()
            self._cancel_timer = None
