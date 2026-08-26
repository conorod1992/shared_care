"""Config flow for Shared Schedule."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
from homeassistant.util import dt as dt_util

from .const import (
    CONF_ANCHOR_DATE,
    CONF_COUNTRY,
    CONF_CURRENT_PARTY,
    CONF_HANDOVER_TIME,
    CONF_MY_PARTY,
    CONF_PARTY_A,
    CONF_PARTY_B,
    CONF_RECURRENCE_WEEKS,
    CONF_SHIFT_HOLIDAYS,
    CONF_SUBJECT_NAME,
    CONF_WEEKDAY,
    DOMAIN,
    PARTY_A,
)

WEEKDAYS = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


def _next_monday() -> str:
    today = dt_util.now().date()
    return (today + timedelta(days=(-today.weekday()) % 7)).isoformat()


def _schema(defaults: dict[str, Any] | None = None) -> vol.Schema:
    defaults = defaults or {}
    return vol.Schema(
        {
            vol.Required(
                CONF_NAME, default=defaults.get(CONF_NAME, "Shared Schedule")
            ): str,
            vol.Required(
                CONF_PARTY_A, default=defaults.get(CONF_PARTY_A, "Party A")
            ): str,
            vol.Required(
                CONF_PARTY_B, default=defaults.get(CONF_PARTY_B, "Party B")
            ): str,
            vol.Required(
                CONF_CURRENT_PARTY, default=defaults.get(CONF_CURRENT_PARTY, PARTY_A)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="a", label="Party A"),
                        selector.SelectOptionDict(value="b", label="Party B"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Required(
                CONF_MY_PARTY, default=defaults.get(CONF_MY_PARTY, PARTY_A)
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value="a", label="Party A"),
                        selector.SelectOptionDict(value="b", label="Party B"),
                    ],
                    mode=selector.SelectSelectorMode.DROPDOWN,
                )
            ),
            vol.Optional(
                CONF_SUBJECT_NAME, default=defaults.get(CONF_SUBJECT_NAME, "")
            ): str,
            vol.Required(
                CONF_ANCHOR_DATE, default=defaults.get(CONF_ANCHOR_DATE, _next_monday())
            ): selector.DateSelector(),
            vol.Required(
                CONF_RECURRENCE_WEEKS,
                default=defaults.get(CONF_RECURRENCE_WEEKS, 2),
            ): vol.All(vol.Coerce(int), vol.Range(min=1, max=52)),
            vol.Required(
                CONF_WEEKDAY, default=str(defaults.get(CONF_WEEKDAY, 0))
            ): selector.SelectSelector(
                selector.SelectSelectorConfig(
                    options=[
                        selector.SelectOptionDict(value=str(index), label=day.title())
                        for index, day in enumerate(WEEKDAYS)
                    ]
                )
            ),
            vol.Required(
                CONF_HANDOVER_TIME,
                default=defaults.get(CONF_HANDOVER_TIME, "18:00:00"),
            ): selector.TimeSelector(),
            vol.Required(CONF_COUNTRY, default=defaults.get(CONF_COUNTRY, "IE")): str,
            vol.Required(
                CONF_SHIFT_HOLIDAYS,
                default=defaults.get(CONF_SHIFT_HOLIDAYS, True),
            ): bool,
        }
    )


def _normalize(data: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(data)
    normalized[CONF_ANCHOR_DATE] = str(data[CONF_ANCHOR_DATE])
    normalized[CONF_HANDOVER_TIME] = str(data[CONF_HANDOVER_TIME])
    normalized[CONF_WEEKDAY] = int(data[CONF_WEEKDAY])
    normalized[CONF_COUNTRY] = data[CONF_COUNTRY].strip().upper()
    normalized[CONF_SUBJECT_NAME] = data.get(CONF_SUBJECT_NAME, "").strip()
    return normalized


def _validate(data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    try:
        anchor = dt_util.parse_date(data[CONF_ANCHOR_DATE])
        if anchor is None or anchor.weekday() != data[CONF_WEEKDAY]:
            errors[CONF_ANCHOR_DATE] = "weekday_mismatch"
    except (TypeError, ValueError):
        errors[CONF_ANCHOR_DATE] = "invalid_date"
    if not data[CONF_PARTY_A].strip() or not data[CONF_PARTY_B].strip():
        errors["base"] = "party_name_required"
    return errors


class SharedScheduleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input = _normalize(user_input)
            errors = _validate(user_input)
            if not errors:
                return self.async_create_entry(
                    title=user_input[CONF_NAME], data=user_input
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(user_input), errors=errors
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        return SharedScheduleOptionsFlow(config_entry)


class SharedScheduleOptionsFlow(config_entries.OptionsFlow):
    """Edit display names and holiday behaviour without replacing state."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self._entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        current = {**self._entry.data, **self._entry.options}
        schema = vol.Schema(
            {
                vol.Required(CONF_PARTY_A, default=current[CONF_PARTY_A]): str,
                vol.Required(CONF_PARTY_B, default=current[CONF_PARTY_B]): str,
                vol.Required(
                    CONF_MY_PARTY, default=current.get(CONF_MY_PARTY, PARTY_A)
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            selector.SelectOptionDict(value="a", label="Party A"),
                            selector.SelectOptionDict(value="b", label="Party B"),
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    CONF_SUBJECT_NAME, default=current.get(CONF_SUBJECT_NAME, "")
                ): str,
                vol.Required(
                    CONF_RECURRENCE_WEEKS,
                    default=current[CONF_RECURRENCE_WEEKS],
                ): vol.All(vol.Coerce(int), vol.Range(min=1, max=52)),
                vol.Required(CONF_COUNTRY, default=current[CONF_COUNTRY]): str,
                vol.Required(
                    CONF_SHIFT_HOLIDAYS, default=current[CONF_SHIFT_HOLIDAYS]
                ): bool,
            }
        )
        errors: dict[str, str] = {}
        if user_input is not None:
            user_input[CONF_COUNTRY] = user_input[CONF_COUNTRY].strip().upper()
            user_input[CONF_SUBJECT_NAME] = user_input.get(
                CONF_SUBJECT_NAME, ""
            ).strip()
            if (
                not user_input[CONF_PARTY_A].strip()
                or not user_input[CONF_PARTY_B].strip()
            ):
                errors["base"] = "party_name_required"
            if not errors:
                return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(step_id="init", data_schema=schema, errors=errors)
