"""Optional automatic and manual holiday support."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from importlib import import_module
from typing import Any

HOLIDAY_SOURCE_AUTOMATIC = "automatic"
HOLIDAY_SOURCE_MANUAL = "manual_fallback"
HOLIDAY_SOURCE_UNAVAILABLE = "unavailable"
HOLIDAY_SOURCE_DISABLED = "disabled"

AutomaticHolidayLoader = Callable[[str], object]


def load_automatic_holidays(country: str) -> object:
    """Import python-holidays and create a country calendar."""
    holiday_module = import_module("holidays")
    return holiday_module.country_holidays(country)


def normalize_fallback_holidays(values: object) -> list[dict[str, str]]:
    """Return valid, unique stored fallback holidays sorted by date."""
    normalized: dict[str, dict[str, str]] = {}
    if not isinstance(values, list):
        return []
    for item in values:
        if not isinstance(item, Mapping) or not isinstance(item.get("date"), str):
            continue
        try:
            value = date.fromisoformat(item["date"])
        except ValueError:
            continue
        holiday = {"date": value.isoformat()}
        name = item.get("name")
        if isinstance(name, str) and (name := name.strip()):
            holiday["name"] = name
        normalized[holiday["date"]] = holiday
    return [normalized[value] for value in sorted(normalized)]


def upsert_fallback_holiday(
    values: Iterable[Mapping[str, str]], value: date, name: str | None = None
) -> list[dict[str, str]]:
    """Create or update a fallback holiday."""
    holidays_by_date = {item["date"]: dict(item) for item in values}
    holiday = {"date": value.isoformat()}
    if name and (name := name.strip()):
        holiday["name"] = name
    holidays_by_date[holiday["date"]] = holiday
    return [holidays_by_date[key] for key in sorted(holidays_by_date)]


def remove_fallback_holiday(
    values: Iterable[Mapping[str, str]], value: date
) -> list[dict[str, str]]:
    """Remove a fallback holiday by date."""
    target = value.isoformat()
    return [dict(item) for item in values if item["date"] != target]


@dataclass(slots=True)
class HolidayProvider:
    """Select automatic holidays when possible, otherwise stored fallbacks."""

    enabled: bool
    fallback_dates: frozenset[date] = field(default_factory=frozenset)
    automatic_calendar: Any | None = None
    error: str | None = None

    @property
    def source(self) -> str:
        """Return the active holiday data source."""
        if not self.enabled:
            return HOLIDAY_SOURCE_DISABLED
        if self.automatic_calendar is not None:
            return HOLIDAY_SOURCE_AUTOMATIC
        if self.fallback_dates:
            return HOLIDAY_SOURCE_MANUAL
        return HOLIDAY_SOURCE_UNAVAILABLE

    def __call__(self, value: date) -> bool:
        """Return whether a date is a holiday without propagating provider errors."""
        if not self.enabled:
            return False
        if self.automatic_calendar is not None:
            try:
                return value in self.automatic_calendar
            except Exception as err:  # noqa: BLE001 - third-party failures are optional
                self.error = str(err)
                self.automatic_calendar = None
        return value in self.fallback_dates

    def set_fallback_holidays(self, values: Iterable[Mapping[str, str]]) -> None:
        """Refresh fallback dates without replacing a working automatic calendar."""
        self.fallback_dates = frozenset(
            date.fromisoformat(item["date"]) for item in values
        )


def resolve_holiday_provider(
    enabled: bool,
    country: str,
    fallback_holidays: Iterable[Mapping[str, str]],
    loader: AutomaticHolidayLoader = load_automatic_holidays,
) -> HolidayProvider:
    """Build a holiday provider, treating all automatic lookup failures as optional."""
    provider = HolidayProvider(enabled=enabled)
    provider.set_fallback_holidays(fallback_holidays)
    if not enabled:
        return provider
    try:
        provider.automatic_calendar = loader(country)
    except Exception as err:  # noqa: BLE001 - third-party failures are optional
        provider.error = str(err)
    return provider
