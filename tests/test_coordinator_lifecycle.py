"""Focused coordinator tests for occurrence-scoped state and events."""

from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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

    transitions = coordinator.model.actual_transitions_between(stopped, restarted)
    coordinator._emit_offline_date_override_transitions(transitions)
    coordinator._emit_offline_date_override_transitions(transitions)

    assert len(coordinator.hass.bus.events) == 1
    event_type, data = coordinator.hass.bus.events[0]
    assert event_type == EVENT_HANDOVER_COMPLETED
    assert data["from_party_key"] == PARTY_B
    assert data["to_party_key"] == PARTY_A
    assert data["source"] == "date_override"
    assert data["reconciled_after_downtime"] is True
