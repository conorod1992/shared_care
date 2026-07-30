"""Binary sensor entities for Shared Schedule."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import PARTY_A, PARTY_B
from .coordinator import SharedScheduleCoordinator
from .entity import SharedScheduleEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: SharedScheduleCoordinator = entry.runtime_data
    async_add_entities(
        [
            SharedSchedulePartySensor(coordinator, PARTY_A),
            SharedSchedulePartySensor(coordinator, PARTY_B),
            SharedScheduleTimingSensor(coordinator, "today"),
            SharedScheduleTimingSensor(coordinator, "tomorrow"),
        ]
    )


class SharedSchedulePartySensor(SharedScheduleEntity, BinarySensorEntity):
    """Whether responsibility is currently with one party."""

    _attr_icon = "mdi:account"

    def __init__(self, coordinator: SharedScheduleCoordinator, party: str) -> None:
        super().__init__(coordinator, f"with_party_{party}")
        self._party = party
        self._attr_translation_key = f"with_party_{party}"

    @property
    def is_on(self) -> bool:
        return self.coordinator.model.state.current_party == self._party


class SharedScheduleTimingSensor(SharedScheduleEntity, BinarySensorEntity):
    """Whether the effective handover is today or tomorrow."""

    _attr_icon = "mdi:calendar-alert"

    def __init__(self, coordinator: SharedScheduleCoordinator, timing: str) -> None:
        super().__init__(coordinator, f"handover_{timing}")
        self._timing = timing
        self._attr_translation_key = f"handover_{timing}"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data[f"handover_{self._timing}"])
