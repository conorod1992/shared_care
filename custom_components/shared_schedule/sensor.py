"""Sensor entities for Shared Schedule."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import (
    PARTY_A,
    PARTY_B,
    SERVICE_CLEAR_OVERRIDE,
    SERVICE_COMPLETE_HANDOVER,
    SERVICE_SET_CURRENT_PARTY,
    SERVICE_SET_OVERRIDE,
    SERVICE_SHIFT_SERIES,
)
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
            SharedScheduleStatusSensor(coordinator),
            SharedScheduleNextHandoverSensor(coordinator),
        ]
    )

    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        SERVICE_SET_OVERRIDE,
        {vol.Required("datetime"): cv.datetime},
        "async_set_handover_override",
    )
    platform.async_register_entity_service(
        SERVICE_CLEAR_OVERRIDE, {}, "async_clear_handover_override"
    )
    platform.async_register_entity_service(
        SERVICE_SET_CURRENT_PARTY,
        {vol.Required("party"): vol.In([PARTY_A, PARTY_B])},
        "async_set_current_party",
    )
    platform.async_register_entity_service(
        SERVICE_COMPLETE_HANDOVER, {}, "async_complete_handover"
    )
    platform.async_register_entity_service(
        SERVICE_SHIFT_SERIES,
        {vol.Required("datetime"): cv.datetime},
        "async_shift_series",
    )


class SharedScheduleStatusSensor(SharedScheduleEntity, SensorEntity):
    """Current responsibility and full schedule status."""

    _attr_translation_key = "status"
    _attr_icon = "mdi:account-switch"

    def __init__(self, coordinator: SharedScheduleCoordinator) -> None:
        super().__init__(coordinator, "status")

    @property
    def native_value(self) -> str:
        return self.coordinator.model.current_party_name

    @property
    def extra_state_attributes(self) -> dict[str, object]:
        return self.coordinator.data


class SharedScheduleNextHandoverSensor(SharedScheduleEntity, SensorEntity):
    """Timestamp of the effective next handover."""

    _attr_translation_key = "next_handover"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: SharedScheduleCoordinator) -> None:
        super().__init__(coordinator, "next_handover")

    @property
    def native_value(self):
        return dt_util.as_utc(self.coordinator.model.effective_handover)
