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
    my_party: str = PARTY_A

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
        if settings.my_party not in (PARTY_A, PARTY_B):
            raise ValueError("my_party must be 'a' or 'b'")
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
        """Return the scheduled/current cadence owner name."""
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

    def _effective_handover_for_base(self, base: datetime, *, first: bool) -> datetime:
        """Return an effective occurrence while preserving adjustment order."""
        if first and self.state.override is not None:
            return self.state.override
        if self.settings.shift_public_holidays and self._is_holiday(base.date()):
            return base + timedelta(days=1)
        return base

    def scheduled_party_at(self, value: datetime) -> str:
        """Return the time-based cadence owner, excluding date overrides."""
        if value.tzinfo is None:
            raise ValueError("value must be timezone-aware")
        party = self.state.current_party
        base = self.base_handover
        first = True
        # This is normally zero or one iterations. The guard keeps corrupt or
        # unexpectedly ancient queries from becoming unbounded.
        for _ in range(1000):
            handover = self._effective_handover_for_base(base, first=first)
            if handover > value:
                return party
            party = PARTY_B if party == PARTY_A else PARTY_A
            base += self.settings.interval
            first = False
        raise ValueError("value is too far beyond the active schedule")

    def actual_party_at(self, value: datetime) -> str:
        """Return the actual owner, including date overrides."""
        override_party = self.state.date_overrides.get(value.date().isoformat())
        if override_party is not None:
            return override_party

        scheduled_party = self.scheduled_party_at(value)
        normal_party = self.normal_party_for_date(value.date())

        # Find the first date of this normal ownership period.
        period_start = value.date()
        while (
            self.normal_party_for_date(period_start - timedelta(days=1))
            == normal_party
        ):
            period_start -= timedelta(days=1)

        previous_override = self.state.date_overrides.get(
            (period_start - timedelta(days=1)).isoformat()
        )

        if previous_override is None or previous_override != normal_party:
            return scheduled_party

        # A date override can flow directly into the same party's normal period,
        # avoiding a false handover at midnight / the normal handover time.
        #
        # Do not do this when that occurrence has actually been delayed by a
        # public-holiday adjustment or manual handover override: those effective
        # handover rules must continue to take precedence.
        interval_days = self.settings.interval.days
        period_offset = (
            period_start - self.base_handover.date()
        ).days // interval_days
        period_base = self.base_handover + period_offset * self.settings.interval
        period_effective = self._effective_handover_for_base(
            period_base,
            first=period_offset == 0,
        )

        if period_effective != period_base:
            return scheduled_party

        return previous_override

    def next_actual_transition(self, now: datetime) -> dict[str, object]:
        """Return the next effective ownership transition after ``now``.

        Cadence handovers remain time based. Date overrides are evaluated at
        local midnight, so a handover-day calendar allocation can still differ
        from the current owner before the configured handover time.
        """
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        candidates: set[datetime] = set()
        cadence_sources: dict[datetime, str] = {}
        end = now + timedelta(days=max(1095, self.settings.interval.days * 3))
        for value in self.state.date_overrides:
            override_date = date.fromisoformat(value)
            for boundary_date in (override_date, override_date + timedelta(days=1)):
                boundary = datetime.combine(
                    boundary_date, datetime.min.time(), now.tzinfo
                )
                if now < boundary <= end:
                    candidates.add(boundary)
        base = self.base_handover
        first = True
        while base <= end:
            candidate = self._effective_handover_for_base(base, first=first)
            if candidate > now:
                candidates.add(candidate)
                if first and self.state.override is not None:
                    cadence_sources[candidate] = "manual_override"
                elif self.settings.shift_public_holidays and self._is_holiday(
                    base.date()
                ):
                    cadence_sources[candidate] = "public_holiday"
                else:
                    cadence_sources[candidate] = "normal"
            base += self.settings.interval
            first = False

        epsilon = timedelta(microseconds=1)
        for candidate in sorted(candidates):
            before = self.actual_party_at(candidate - epsilon)
            after = self.actual_party_at(candidate)
            if before == after:
                continue
            source = cadence_sources.get(candidate, "date_override")
            return {
                "datetime": candidate,
                "from_party": before,
                "to_party": after,
                "source": source,
            }
        raise ValueError("no ownership transition found")

    def actual_transitions_between(
        self, start: datetime, end: datetime
    ) -> list[dict[str, object]]:
        """Return effective ownership transitions in a bounded interval."""
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("datetimes must be timezone-aware")
        if end <= start:
            return []
        transitions: list[dict[str, object]] = []
        cursor = start
        for _ in range(100):
            transition = self.next_actual_transition(cursor)
            when = transition["datetime"]
            if when > end:
                break
            transitions.append(transition)
            cursor = when + timedelta(microseconds=1)
        return transitions

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

    def temporary_change_dates(
        self, start: date, end: date, party: str
    ) -> list[date]:
        """Validate and return the dates for a temporary owner range."""
        if party not in (PARTY_A, PARTY_B):
            raise ValueError("party must be 'a' or 'b'")
        if end < start:
            raise ValueError("end date must not be before start date")
        return [
            start + timedelta(days=offset)
            for offset in range((end - start).days + 1)
        ]

    def set_temporary_change(self, start: date, end: date, party: str) -> list[date]:
        """Apply a temporary owner range without moving the recurrence."""
        values = self.temporary_change_dates(start, end, party)
        self.set_date_overrides(values, party)
        return values

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
        next_transition = self.next_actual_transition(now)
        next_at = next_transition["datetime"]
        with_me = actual_party == self.settings.my_party
        direction = (
            "to_me"
            if next_transition["to_party"] == self.settings.my_party
            else "from_me"
        )
        return {
            "scheduled_current_party": self.current_party_name,
            "scheduled_current_party_key": self.state.current_party,
            "scheduled_next_party": self.next_party_name,
            "scheduled_next_party_key": self.next_party_key,
            "current_party": self.party_name(actual_party),
            "current_party_key": actual_party,
            "actual_current_party": self.party_name(actual_party),
            "actual_current_party_key": actual_party,
            "next_party": self.party_name(next_transition["to_party"]),
            "next_handover": effective.isoformat(),
            "scheduled_next_handover": effective.isoformat(),
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
            "my_party": self.settings.my_party,
            "my_party_name": self.party_name(self.settings.my_party),
            "with_me": with_me,
            "next_effective_transition": next_at.isoformat(),
            "next_effective_transition_source": next_transition["source"],
            "next_effective_transition_from": self.party_name(
                next_transition["from_party"]
            ),
            "next_effective_transition_to": self.party_name(
                next_transition["to_party"]
            ),
            "next_handover_direction": direction,
            "next_time_with_me": next_at.isoformat() if not with_me else None,
            "next_time_leaving_me": next_at.isoformat() if with_me else None,
        }
