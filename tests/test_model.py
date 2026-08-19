"""Tests for the pure shared schedule model."""

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from custom_components.shared_schedule.const import PARTY_A, PARTY_B
from custom_components.shared_schedule.model import (
    ScheduleModel,
    ScheduleSettings,
    ScheduleState,
)

TZ = ZoneInfo("Europe/Dublin")
BASE = datetime(2026, 8, 3, 18, 0, tzinfo=TZ)


def make_model(
    *,
    base: datetime = BASE,
    current: str = PARTY_A,
    holidays: set[date] | None = None,
    shift: bool = True,
    date_overrides: dict[str, str] | None = None,
) -> ScheduleModel:
    settings = ScheduleSettings("Party A", "Party B", 2, shift)
    return ScheduleModel(
        settings,
        ScheduleState(current, base, date_overrides=date_overrides or {}),
        lambda value: value in (holidays or set()),
    )


def test_normal_fortnightly_handover() -> None:
    model = make_model()
    assert model.effective_handover == BASE
    assert model.reconcile(BASE - timedelta(seconds=1)) == 0
    assert model.reconcile(BASE) == 1
    assert model.state.current_party == PARTY_B
    assert model.base_handover == datetime(2026, 8, 17, 18, 0, tzinfo=TZ)


def test_monday_bank_holiday_moves_to_tuesday() -> None:
    model = make_model(holidays={BASE.date()})
    assert model.holiday_adjusted_handover == BASE + timedelta(days=1)
    assert model.shifted_for_public_holiday


def test_override_moves_holiday_adjusted_handover_to_thursday() -> None:
    model = make_model(holidays={BASE.date()})
    thursday = BASE + timedelta(days=3)
    model.set_override(thursday, BASE - timedelta(days=1))
    assert model.effective_handover == thursday
    attrs = model.attributes(BASE)
    assert attrs["shifted_for_public_holiday"] is True
    assert attrs["overridden"] is True


def test_override_does_not_move_next_base_occurrence() -> None:
    model = make_model(holidays={BASE.date()})
    model.set_override(BASE + timedelta(days=3), BASE - timedelta(days=1))
    model.reconcile(BASE + timedelta(days=3))
    assert model.base_handover == BASE + timedelta(weeks=2)
    assert model.state.override is None


def test_clear_override_restores_holiday_adjustment() -> None:
    model = make_model(holidays={BASE.date()})
    model.set_override(BASE + timedelta(days=3), BASE - timedelta(days=1))
    model.clear_override()
    assert model.effective_handover == BASE + timedelta(days=1)


def test_automatic_completion_switches_party() -> None:
    model = make_model()
    model.reconcile(BASE)
    assert model.current_party_name == "Party B"
    assert model.next_party_name == "Party A"


def test_restart_after_missed_handover_reconciles() -> None:
    model = make_model()
    assert model.reconcile(BASE + timedelta(days=1)) == 1
    assert model.state.current_party == PARTY_B
    assert model.base_handover > BASE + timedelta(days=1)


def test_multiple_missed_periods_are_calculated_with_correct_parity() -> None:
    model = make_model()
    assert model.reconcile(BASE + timedelta(weeks=7)) == 4
    assert model.state.current_party == PARTY_A
    assert model.base_handover == BASE + timedelta(weeks=8)


def test_manual_current_party_correction() -> None:
    model = make_model()
    model.set_current_party(PARTY_B)
    assert model.current_party_name == "Party B"
    assert model.base_handover == BASE


def test_deliberate_series_shift_replaces_base_and_clears_override() -> None:
    model = make_model()
    model.set_override(BASE + timedelta(days=2), BASE - timedelta(days=1))
    shifted = BASE + timedelta(days=7)
    model.shift_series(shifted)
    assert model.base_handover == shifted
    assert model.state.override is None


def test_dst_keeps_local_wall_clock_time() -> None:
    before_dst = datetime(2026, 3, 23, 18, 0, tzinfo=TZ)
    model = make_model(base=before_dst)
    model.complete_handover()
    assert model.base_handover == datetime(2026, 4, 6, 18, 0, tzinfo=TZ)
    assert model.base_handover.utcoffset() != before_dst.utcoffset()


@pytest.mark.parametrize("offset_days", [0, 2])
def test_override_before_and_after_holiday_adjusted_time(offset_days: int) -> None:
    model = make_model(holidays={BASE.date()})
    override = BASE + timedelta(days=offset_days, hours=1)
    model.set_override(override, BASE - timedelta(days=1))
    assert model.effective_handover == override
    assert model.reconcile(override) == 1
    assert model.base_handover == BASE + timedelta(weeks=2)


def test_override_cannot_consume_the_following_occurrence() -> None:
    model = make_model()
    with pytest.raises(ValueError, match="following base"):
        model.set_override(BASE + timedelta(weeks=2), BASE - timedelta(days=1))


def test_normal_date_ownership_follows_the_recurring_cadence() -> None:
    model = make_model()
    assert model.party_for_date(date(2026, 8, 2)) == PARTY_A
    assert model.party_for_date(date(2026, 8, 3)) == PARTY_B
    assert model.party_for_date(date(2026, 8, 16)) == PARTY_B
    assert model.party_for_date(date(2026, 8, 17)) == PARTY_A


def test_single_date_override_replaces_normal_owner() -> None:
    model = make_model()
    value = date(2026, 8, 8)
    model.set_date_overrides([value], PARTY_A)
    assert model.normal_party_for_date(value) == PARTY_B
    assert model.party_for_date(value) == PARTY_A
    assert model.state.date_overrides == {value.isoformat(): PARTY_A}


def test_current_actual_owner_respects_time_and_date_override() -> None:
    model = make_model()
    before_handover = BASE - timedelta(days=1)
    assert model.actual_party_at(before_handover) == PARTY_A
    model.set_date_overrides([before_handover.date()], PARTY_B)
    assert model.actual_party_at(before_handover) == PARTY_B


def test_multi_day_override() -> None:
    model = make_model()
    values = [date(2026, 8, day) for day in range(7, 10)]
    model.set_date_overrides(values, PARTY_A)
    assert [model.party_for_date(value) for value in values] == [PARTY_A] * 3


def test_removing_one_or_many_date_overrides() -> None:
    model = make_model()
    values = [date(2026, 8, day) for day in range(7, 10)]
    model.set_date_overrides(values, PARTY_A)
    model.remove_date_overrides([values[1]])
    assert model.party_for_date(values[1]) == PARTY_B
    assert model.party_for_date(values[0]) == PARTY_A
    model.remove_date_overrides([values[0], values[2]])
    assert model.state.date_overrides == {}


def test_overrides_across_successive_normal_ownership_periods() -> None:
    model = make_model()
    normally_b = date(2026, 8, 8)
    normally_a = date(2026, 8, 19)
    model.set_date_overrides([normally_b], PARTY_A)
    model.set_date_overrides([normally_a], PARTY_B)
    assert model.party_for_date(normally_b) == PARTY_A
    assert model.party_for_date(normally_a) == PARTY_B
    assert model.normal_party_for_date(normally_b) == PARTY_B
    assert model.normal_party_for_date(normally_a) == PARTY_A


def test_pointless_date_override_is_not_stored() -> None:
    model = make_model(date_overrides={"2026-08-08": PARTY_A})
    value = date(2026, 8, 8)
    model.set_date_overrides([value], PARTY_B)
    assert model.state.date_overrides == {}


def test_date_overrides_restore_on_restart() -> None:
    stored = {"2026-08-08": PARTY_A, "2026-08-19": PARTY_B}
    restarted = make_model(date_overrides=dict(stored))
    assert restarted.state.date_overrides == stored
    assert restarted.party_for_date(date(2026, 8, 8)) == PARTY_A
    assert restarted.party_for_date(date(2026, 8, 19)) == PARTY_B


def test_date_overrides_never_shift_the_recurring_cadence() -> None:
    model = make_model()
    original_base = model.base_handover
    model.set_date_overrides(
        [date(2026, 8, 8), date(2026, 8, 19)], PARTY_A
    )
    assert model.base_handover == original_base
    model.reconcile(BASE)
    assert model.base_handover == original_base + timedelta(weeks=2)
    assert model.state.date_overrides


def test_calendar_distinguishes_normal_and_overridden_ownership() -> None:
    model = make_model()
    model.set_date_overrides([date(2026, 8, 8)], PARTY_A)
    days = model.calendar(date(2026, 8, 8), 2)
    assert days[0] == {
        "date": "2026-08-08",
        "normal_party": PARTY_B,
        "normal_party_name": "Party B",
        "party": PARTY_A,
        "party_name": "Party A",
        "overridden": True,
    }
    assert days[1]["overridden"] is False
