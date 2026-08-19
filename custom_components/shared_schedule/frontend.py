"""Authenticated frontend API and panel registration."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any

import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, PARTY_A, PARTY_B
from .coordinator import SharedScheduleCoordinator

PANEL_URL_PATH = "shared-schedule"
PANEL_STATIC_PATH = "/shared_schedule_frontend"
PANEL_COMPONENT = "shared-schedule-panel"
DATA_COORDINATORS = "coordinators"


async def async_setup_frontend(hass: HomeAssistant) -> None:
    """Register the static module, sidebar panel, and WebSocket commands."""
    frontend_dir = Path(__file__).parent / "frontend"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(PANEL_STATIC_PATH, str(frontend_dir), True)]
    )
    if not frontend.async_panel_exists(hass, PANEL_URL_PATH):
        await panel_custom.async_register_panel(
            hass,
            frontend_url_path=PANEL_URL_PATH,
            webcomponent_name=PANEL_COMPONENT,
            sidebar_title="Shared Schedule",
            sidebar_icon="mdi:calendar-account",
            module_url=f"{PANEL_STATIC_PATH}/shared-schedule-panel.js",
            require_admin=True,
            handle_safe_area=True,
        )
    websocket_api.async_register_command(hass, websocket_get_schedule)
    websocket_api.async_register_command(hass, websocket_set_date_overrides)
    websocket_api.async_register_command(hass, websocket_remove_date_overrides)


def _coordinators(hass: HomeAssistant) -> dict[str, SharedScheduleCoordinator]:
    return hass.data.setdefault(DOMAIN, {}).setdefault(DATA_COORDINATORS, {})


def register_coordinator(
    hass: HomeAssistant, coordinator: SharedScheduleCoordinator
) -> None:
    """Make a loaded config entry available to the panel API."""
    _coordinators(hass)[coordinator.entry.entry_id] = coordinator


def unregister_coordinator(hass: HomeAssistant, entry_id: str) -> None:
    """Remove an unloaded config entry from the panel API."""
    _coordinators(hass).pop(entry_id, None)


def _payload(
    coordinator: SharedScheduleCoordinator, start: date, days: int
) -> dict[str, Any]:
    model = coordinator.model
    actual_party = coordinator.actual_current_party
    settings = coordinator.settings_data
    return {
        "entry_id": coordinator.entry.entry_id,
        "title": coordinator.entry.title,
        "parties": {
            PARTY_A: model.settings.party_a,
            PARTY_B: model.settings.party_b,
        },
        "current_party": model.state.current_party,
        "current_party_name": model.current_party_name,
        "actual_current_party": actual_party,
        "actual_current_party_name": model.party_name(actual_party),
        "base_handover": model.base_handover.isoformat(),
        "normal_handover": model.holiday_adjusted_handover.isoformat(),
        "effective_handover": model.effective_handover.isoformat(),
        "handover_overridden": model.state.override is not None,
        "shifted_for_public_holiday": model.shifted_for_public_holiday,
        "date_overrides": dict(sorted(model.state.date_overrides.items())),
        "calendar": coordinator.calendar(start, days),
        "settings": settings,
    }


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/get",
        vol.Optional("entry_id"): str,
        vol.Optional("start"): cv.date,
        vol.Optional("days", default=42): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=366)
        ),
    }
)
@callback
def websocket_get_schedule(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return loaded schedules and calendar data."""
    start = msg.get("start") or date.today()
    coordinators = _coordinators(hass)
    if entry_id := msg.get("entry_id"):
        coordinator = coordinators.get(entry_id)
        if coordinator is None:
            connection.send_error(
                msg["id"], websocket_api.ERR_NOT_FOUND, "Schedule not found"
            )
            return
        selected = [coordinator]
    else:
        selected = list(coordinators.values())
    connection.send_result(
        msg["id"],
        {"schedules": [_payload(item, start, msg["days"]) for item in selected]},
    )


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/date_overrides/set",
        vol.Required("entry_id"): str,
        vol.Required("party"): vol.In([PARTY_A, PARTY_B]),
        vol.Required("dates"): vol.All(cv.ensure_list, [cv.date]),
    }
)
@websocket_api.async_response
async def websocket_set_date_overrides(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Add or replace date ownership overrides."""
    coordinator = _coordinators(hass).get(msg["entry_id"])
    if coordinator is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Schedule not found"
        )
        return
    await coordinator.async_set_date_overrides(msg["dates"], msg["party"])
    connection.send_result(msg["id"])


@websocket_api.require_admin
@websocket_api.websocket_command(
    {
        vol.Required("type"): f"{DOMAIN}/date_overrides/remove",
        vol.Required("entry_id"): str,
        vol.Required("dates"): vol.All(cv.ensure_list, [cv.date]),
    }
)
@websocket_api.async_response
async def websocket_remove_date_overrides(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Remove one or many date ownership overrides."""
    coordinator = _coordinators(hass).get(msg["entry_id"])
    if coordinator is None:
        connection.send_error(
            msg["id"], websocket_api.ERR_NOT_FOUND, "Schedule not found"
        )
        return
    await coordinator.async_remove_date_overrides(msg["dates"])
    connection.send_result(msg["id"])
