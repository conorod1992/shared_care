"""Pure scheduling model for Shared Schedule.

The next base occurrence is persisted independently from the holiday adjustment
and manual override.  This is the central invariant of the integration.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from .const import PARTY_A, PARTY_B

HolidayChecker = Callable[[date], bool]


@dataclass(frozen=True, slots=True)
class ScheduleSettings:
    """User-configured schedule settings."""

    party_a: str
    party_b: str
    recurrence_weeks: int = 2
    shift_public_holidays: bool = True

    @property
    def interval(self) -> timedelta:
        """Return the base recurrence interval."""
        return timedelta(weeks=self.recurrence_weeks)


@dataclass(slots=True)
class ScheduleState:
    """Small, serializable set of mutable schedule state."""

    current_party: str
    next_base: datetime
    override: datetime | None = None
    date_overrides: dict[str, str] = field(default_factory=dict)


class ScheduleModel:
    """Calculate and mutate one alternating schedule."""

    def __init__(
        self,
        settings: ScheduleSettings,
        state: ScheduleState,
        is_holiday: HolidayChecker,
    ) -> None:
        if state.next_base.tzinfo is None:
            raise ValueError("next_base must be timezone-aware")
        if state.override is not None and state.override.tzinfo is None:
            raise ValueError("override must be timezone-aware")
        if state.current_party not in (PARTY_A, PARTY_B):
            raise ValueError("current_party must be 'a' or 'b'")
        if any(
            party not in (PARTY_A, PARTY_B) for party in state.date_overrides.values()
        ):
            raise ValueError("date override parties must be 'a' or 'b'")
        for value in state.date_overrides:
            date.fromisoformat(value)
        if settings.recurrence_weeks < 1:
            raise ValueError("recurrence_weeks must be at least 1")
        self.settings = settings
        self.state = state
        self._is_holiday = is_holiday
        self._prune_redundant_date_overrides()

    @property
    def base_handover(self) -> datetime:
        return self.state.next_base

    @property
    def shifted_for_public_holiday(self) -> bool:
        return self.settings.shift_public_holidays and self._is_holiday(
            self.base_handover.date()
        )

    @property
    def holiday_adjusted_handover(self) -> datetime:
        if self.shifted_for_public_holiday:
            return self.base_handover + timedelta(days=1)
        return self.base_handover

    @property
    def effective_handover(self) -> datetime:
        return self.state.override or self.holiday_adjusted_handover

    @property
    def next_party_key(self) -> str:
        return PARTY_B if self.state.current_party == PARTY_A else PARTY_A

    @property
    def current_party_name(self) -> str:
        return (
            self.settings.party_a
            if self.state.current_party == PARTY_A
            else self.settings.party_b
        )

    @property
    def next_party_name(self) -> str:
        return (
            self.settings.party_a
            if self.next_party_key == PARTY_A
            else self.settings.party_b
        )

    def party_name(self, party: str) -> str:
        """Return the configured display name for a party key."""
        if party == PARTY_A:
            return self.settings.party_a
        if party == PARTY_B:
            return self.settings.party_b
        raise ValueError("party must be 'a' or 'b'")

    def normal_party_for_date(self, value: date) -> str:
        """Return ownership from the recurring cadence for a calendar date.

        Date ownership changes on each base handover date.  This calculation is
        deliberately independent of public-holiday, handover, and date overrides.
        """
        interval_days = self.settings.interval.days
        current_period_start = self.base_handover.date() - self.settings.interval
        period_offset = (value - current_period_start).days // interval_days
        if period_offset % 2:
            return self.next_party_key
        return self.state.current_party

    def party_for_date(self, value: date) -> str:
        """Return the explicit date owner or the normal scheduled owner."""
        return self.state.date_overrides.get(
            value.isoformat(), self.normal_party_for_date(value)
        )

    def actual_party_at(self, value: datetime) -> str:
        """Return the current time-based owner, including today's date override."""
        return self.state.date_overrides.get(
            value.date().isoformat(), self.state.current_party
        )

    def set_date_overrides(self, values: list[date], party: str) -> None:
        """Set one or many date overrides without changing the cadence.

        Selecting the party that normally owns a date removes any existing
        exception instead of persisting a redundant override.
        """
        if party not in (PARTY_A, PARTY_B):
            raise ValueError("party must be 'a' or 'b'")
        for value in values:
            key = value.isoformat()
            if self.normal_party_for_date(value) == party:
                self.state.date_overrides.pop(key, None)
            else:
                self.state.date_overrides[key] = party

    def _prune_redundant_date_overrides(self) -> None:
        """Discard exceptions that now match normal cadence ownership."""
        redundant = [
            value
            for value, party in self.state.date_overrides.items()
            if self.normal_party_for_date(date.fromisoformat(value)) == party
        ]
        for value in redundant:
            self.state.date_overrides.pop(value)

    def remove_date_overrides(self, values: list[date]) -> None:
        """Remove one or many date overrides."""
        for value in values:
            self.state.date_overrides.pop(value.isoformat(), None)

    def calendar(self, start: date, days: int) -> list[dict[str, object]]:
        """Return normal and actual ownership for a range of dates."""
        if days < 1:
            raise ValueError("days must be at least 1")
        result = []
        for offset in range(days):
            value = start + timedelta(days=offset)
            normal_party = self.normal_party_for_date(value)
            actual_party = self.party_for_date(value)
            result.append(
                {
                    "date": value.isoformat(),
                    "normal_party": normal_party,
                    "normal_party_name": self.party_name(normal_party),
                    "party": actual_party,
                    "party_name": self.party_name(actual_party),
                    "overridden": value.isoformat() in self.state.date_overrides,
                }
            )
        return result

    def set_override(self, value: datetime, now: datetime) -> None:
        """Override only the active occurrence.

        Keeping the override before the next base occurrence makes its ownership
        unambiguous and prevents one exception from swallowing another handover.
        """
        if value.tzinfo is None or now.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware")
        if value <= now:
            raise ValueError("override must be in the future")
        if value >= self.base_handover + self.settings.interval:
            raise ValueError("override must be before the following base occurrence")
        self.state.override = value

    def clear_override(self) -> None:
        self.state.override = None

    def set_current_party(self, party: str) -> None:
        if party not in (PARTY_A, PARTY_B):
            raise ValueError("party must be 'a' or 'b'")
        self.state.current_party = party
        self._prune_redundant_date_overrides()

    def complete_handover(self) -> None:
        """Complete exactly one occurrence, preserving the base cadence."""
        self.state.current_party = self.next_party_key
        self.state.override = None
        self.state.next_base += self.settings.interval

    def shift_series(self, new_base: datetime) -> None:
        """Intentionally replace the recurring cadence anchor."""
        if new_base.tzinfo is None:
            raise ValueError("new base must be timezone-aware")
        self.state.next_base = new_base
        self.state.override = None
        self._prune_redundant_date_overrides()

    def reconcile(self, now: datetime) -> int:
        """Catch up in O(1), returning the number of completed handovers."""
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        if self.effective_handover > now:
            return 0

        # The active occurrence may have an override, so process it separately.
        self.complete_handover()
        completed = 1

        # Calculate how many later base occurrences have passed without replaying
        # them.  Only the final candidate can still be pending due to a one-day
        # public-holiday adjustment.
        if self.base_handover <= now:
            extra = int((now - self.base_handover) // self.settings.interval) + 1
            last_base = self.base_handover + (extra - 1) * self.settings.interval
            last_effective = last_base
            if self.settings.shift_public_holidays and self._is_holiday(
                last_base.date()
            ):
                last_effective += timedelta(days=1)
            if last_effective > now:
                extra -= 1
            if extra:
                if extra % 2:
                    self.state.current_party = self.next_party_key
                self.state.next_base += extra * self.settings.interval
                completed += extra
        return completed

    def attributes(self, now: datetime) -> dict[str, object]:
        """Return entity-friendly derived state."""
        effective = self.effective_handover
        days = (effective.date() - now.date()).days
        actual_party = self.actual_party_at(now)
        return {
            "current_party": self.current_party_name,
            "actual_current_party": self.party_name(actual_party),
            "actual_current_party_key": actual_party,
            "next_party": self.next_party_name,
            "next_handover": effective.isoformat(),
            "base_handover": self.base_handover.isoformat(),
            "holiday_adjusted_handover": self.holiday_adjusted_handover.isoformat(),
            "manual_override": self.state.override.isoformat()
            if self.state.override
            else None,
            "handover_day": effective.strftime("%A"),
            "days_until_handover": days,
            "handover_today": days == 0,
            "handover_tomorrow": days == 1,
            "shifted_for_public_holiday": self.shifted_for_public_holiday,
            "overridden": self.state.override is not None,
            "recurrence_weeks": self.settings.recurrence_weeks,
            "date_overrides": dict(sorted(self.state.date_overrides.items())),
        }
