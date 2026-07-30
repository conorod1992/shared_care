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
) -> ScheduleModel:
    settings = ScheduleSettings("Party A", "Party B", 2, shift)
    return ScheduleModel(
        settings,
        ScheduleState(current, base),
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
