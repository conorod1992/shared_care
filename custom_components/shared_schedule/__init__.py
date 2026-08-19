"""Shared Schedule integration."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .const import PLATFORMS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

    from .coordinator import SharedScheduleCoordinator

    type SharedScheduleConfigEntry = ConfigEntry[SharedScheduleCoordinator]
else:
    SharedScheduleConfigEntry = Any


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up the integration-level authenticated frontend."""
    from .frontend import async_setup_frontend

    await async_setup_frontend(hass)
    return True


async def async_setup_entry(
    hass: HomeAssistant, entry: SharedScheduleConfigEntry
) -> bool:
    """Set up Shared Schedule from a config entry."""
    from .coordinator import SharedScheduleCoordinator
    from .frontend import register_coordinator

    coordinator = SharedScheduleCoordinator(hass, entry)
    await coordinator.async_initialize()
    entry.runtime_data = coordinator
    register_coordinator(hass, coordinator)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: SharedScheduleConfigEntry
) -> bool:
    """Unload a config entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        from .frontend import unregister_coordinator

        unregister_coordinator(hass, entry.entry_id)
        await entry.runtime_data.async_shutdown()
    return unloaded


async def _async_update_listener(
    hass: HomeAssistant, entry: SharedScheduleConfigEntry
) -> None:
    """Reload when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
