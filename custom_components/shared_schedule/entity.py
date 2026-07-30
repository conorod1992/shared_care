"""Base entity for Shared Schedule."""

from datetime import datetime

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import SharedScheduleCoordinator


class SharedScheduleEntity(CoordinatorEntity[SharedScheduleCoordinator]):
    """Common entity metadata."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: SharedScheduleCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=coordinator.entry.title,
            manufacturer="Shared Schedule",
            model="Alternating schedule",
        )

    async def async_set_handover_override(self, datetime: datetime) -> None:
        try:
            await self.coordinator.async_set_override(datetime)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_clear_handover_override(self) -> None:
        await self.coordinator.async_clear_override()

    async def async_set_current_party(self, party: str) -> None:
        try:
            await self.coordinator.async_set_current_party(party)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_complete_handover(self) -> None:
        await self.coordinator.async_complete_handover()

    async def async_shift_series(self, datetime: datetime) -> None:
        try:
            await self.coordinator.async_shift_series(datetime)
        except ValueError as err:
            raise HomeAssistantError(str(err)) from err
