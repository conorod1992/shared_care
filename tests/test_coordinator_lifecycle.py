"""Focused coordinator tests for occurrence-scoped state and events."""

import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest

from custom_components.shared_schedule.const import (
    EVENT_HANDOVER_COMPLETED,
    PARTY_A,
    PARTY_B,
)
from custom_components.shared_schedule.coordinator import SharedScheduleCoordinator
from custom_components.shared_schedule.model import (
    ScheduleModel,
    ScheduleSettings,
    ScheduleState,
)

TZ = ZoneInfo("Europe/Dublin")
BASE = datetime(2026, 8, 3, 18, 0, tzinfo=TZ)


class FakeBus:
    """Collect fired events."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, object]]] = []

    def async_fire(self, event_type: str, data: dict[str, object]) -> None:
        self.events.append((event_type, data))


def make_coordinator() -> SharedScheduleCoordinator:
    coordinator = object.__new__(SharedScheduleCoordinator)
    coordinator.model = ScheduleModel(
        ScheduleSettings("Alex", "Jordan"),
        ScheduleState(PARTY_A, BASE),
        lambda value: False,
    )
    coordinator.holiday_provider = lambda value: False
    coordinator._settings = lambda: coordinator.model.settings
    coordinator.handover_notes = {}
    coordinator._emitted_handover_ids = []
    coordinator.entry = SimpleNamespace(entry_id="test-entry")
    coordinator.hass = SimpleNamespace(bus=FakeBus())
    return coordinator


def test_handover_note_does_not_follow_the_next_occurrence() -> None:
    coordinator = make_coordinator()
    coordinator.handover_notes[coordinator.active_handover_id] = "Bring school bag"
    coordinator.model.complete_handover()
    coordinator._discard_completed_notes()
    assert coordinator.active_handover_note is None
    assert coordinator.handover_notes == {}


def test_handover_event_fires_once_with_from_to_semantics() -> None:
    coordinator = make_coordinator()
    due = [
        {
            "occurrence_id": BASE.isoformat(),
            "effective": BASE + timedelta(days=1),
            "from_party": PARTY_A,
            "to_party": PARTY_B,
            "source": "public_holiday",
        }
    ]
    coordinator._emit_due_handovers(due, reconciled=True)
    coordinator._emit_due_handovers(due, reconciled=True)

    assert len(coordinator.hass.bus.events) == 1
    event_type, data = coordinator.hass.bus.events[0]
    assert event_type == EVENT_HANDOVER_COMPLETED
    assert data["from_party_name"] == "Alex"
    assert data["to_party_name"] == "Jordan"
    assert data["source"] == "public_holiday"
    assert data["reconciled_after_downtime"] is True


def test_offline_date_override_boundary_emits_once_on_restart() -> None:
    coordinator = make_coordinator()
    coordinator.model.set_current_party(PARTY_B)
    stopped = datetime(2026, 8, 1, 23, 0, tzinfo=TZ)
    override_date = stopped.date() + timedelta(days=1)
    coordinator.model.set_date_overrides([override_date], PARTY_A)
    restarted = datetime(2026, 8, 2, 1, 0, tzinfo=TZ)

    transitions = coordinator._actual_transitions_between(stopped, restarted)
    coordinator._emit_offline_date_override_transitions(transitions)
    coordinator._emit_offline_date_override_transitions(transitions)

    assert len(coordinator.hass.bus.events) == 1
    event_type, data = coordinator.hass.bus.events[0]
    assert event_type == EVENT_HANDOVER_COMPLETED
    assert data["from_party_key"] == PARTY_B
    assert data["to_party_key"] == PARTY_A
    assert data["source"] == "date_override"
    assert data["reconciled_after_downtime"] is True


def test_due_handover_replay_is_not_truncated_at_100() -> None:
    coordinator = make_coordinator()

    due = coordinator._due_handovers(BASE + timedelta(weeks=208))

    assert len(due) == 105
    assert due[0]["occurrence_id"] == BASE.isoformat()
    assert due[-1]["occurrence_id"] == (BASE + timedelta(weeks=208)).isoformat()


def test_offline_transition_replay_is_not_truncated_at_100() -> None:
    coordinator = make_coordinator()

    class DenseTransitionModel:
        @staticmethod
        def next_actual_transition(cursor: datetime) -> dict[str, object]:
            when = cursor.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
            return {
                "datetime": when,
                "from_party": PARTY_A,
                "to_party": PARTY_B,
                "source": "date_override",
            }

    coordinator.model = DenseTransitionModel()
    end = BASE + timedelta(hours=150)

    transitions = coordinator._actual_transitions_between(BASE, end)

    assert len(transitions) == 150
    assert transitions[-1]["datetime"] == end


def test_invalid_temporary_edit_preserves_existing_overrides() -> None:
    coordinator = make_coordinator()
    existing_dates = [BASE.date() + timedelta(days=1), BASE.date() + timedelta(days=2)]
    coordinator.model.set_date_overrides(existing_dates, PARTY_A)
    original = dict(coordinator.model.state.date_overrides)
    coordinator._lock = asyncio.Lock()
    coordinator._async_commit = AsyncMock()

    with pytest.raises(ValueError, match="end date must not be before start date"):
        asyncio.run(
            coordinator.async_set_temporary_change(
                BASE.date() + timedelta(days=5),
                BASE.date() + timedelta(days=4),
                PARTY_B,
                replace_values=existing_dates,
            )
        )

    assert coordinator.model.state.date_overrides == original
    coordinator._async_commit.assert_not_awaited()
