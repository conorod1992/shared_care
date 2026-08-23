"""Focused tests for optional holiday providers and fallback persistence."""

from datetime import date
from types import SimpleNamespace

import pytest

from custom_components.shared_schedule import holiday

CHRISTMAS = date(2026, 12, 25)
BOXING_DAY = date(2026, 12, 26)


def test_automatic_holiday_lookup_succeeds() -> None:
    provider = holiday.resolve_holiday_provider(
        True, "IE", [], lambda country: {CHRISTMAS}
    )

    assert provider.source == holiday.HOLIDAY_SOURCE_AUTOMATIC
    assert provider(CHRISTMAS) is True


def test_holidays_import_failure_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_import(name: str) -> object:
        raise ImportError(name)

    monkeypatch.setattr(holiday, "import_module", fail_import)

    provider = holiday.resolve_holiday_provider(True, "IE", [])

    assert provider.source == holiday.HOLIDAY_SOURCE_UNAVAILABLE
    assert provider(CHRISTMAS) is False


def test_country_holidays_failure_is_optional(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_country(country: str) -> object:
        raise KeyError(country)

    monkeypatch.setattr(
        holiday,
        "import_module",
        lambda name: SimpleNamespace(country_holidays=fail_country),
    )

    provider = holiday.resolve_holiday_provider(True, "XX", [])

    assert provider.source == holiday.HOLIDAY_SOURCE_UNAVAILABLE


def test_fallback_dates_are_used_after_automatic_failure() -> None:
    def fail(country: str) -> object:
        raise RuntimeError(country)

    provider = holiday.resolve_holiday_provider(
        True, "IE", [{"date": CHRISTMAS.isoformat(), "name": "Christmas"}], fail
    )

    assert provider.source == holiday.HOLIDAY_SOURCE_MANUAL
    assert provider(CHRISTMAS) is True
    assert provider(BOXING_DAY) is False


def test_no_fallback_dates_still_returns_a_safe_provider() -> None:
    provider = holiday.resolve_holiday_provider(
        True, "IE", [], lambda country: (_ for _ in ()).throw(RuntimeError(country))
    )

    assert provider.source == holiday.HOLIDAY_SOURCE_UNAVAILABLE
    assert provider(CHRISTMAS) is False


def test_disabled_holiday_adjustment_bypasses_lookup() -> None:
    called = False

    def loader(country: str) -> object:
        nonlocal called
        called = True
        return {CHRISTMAS}

    provider = holiday.resolve_holiday_provider(
        False, "IE", [{"date": CHRISTMAS.isoformat()}], loader
    )

    assert called is False
    assert provider.source == holiday.HOLIDAY_SOURCE_DISABLED
    assert provider(CHRISTMAS) is False


def test_automatic_source_takes_precedence_over_fallback_dates() -> None:
    provider = holiday.resolve_holiday_provider(
        True, "IE", [{"date": CHRISTMAS.isoformat()}], lambda country: set()
    )

    assert provider.source == holiday.HOLIDAY_SOURCE_AUTOMATIC
    assert provider(CHRISTMAS) is False


def test_broken_automatic_calendar_falls_back_during_use() -> None:
    class BrokenCalendar:
        def __contains__(self, value: date) -> bool:
            raise RuntimeError("broken calendar")

    provider = holiday.resolve_holiday_provider(
        True,
        "IE",
        [{"date": CHRISTMAS.isoformat()}],
        lambda country: BrokenCalendar(),
    )

    assert provider(CHRISTMAS) is True
    assert provider.source == holiday.HOLIDAY_SOURCE_MANUAL


def test_fallback_holiday_persistence_and_crud() -> None:
    stored = holiday.normalize_fallback_holidays(
        [
            {"date": BOXING_DAY.isoformat()},
            {"date": CHRISTMAS.isoformat(), "name": " Christmas "},
            {"date": "not-a-date", "name": "Ignored"},
        ]
    )
    assert stored == [
        {"date": CHRISTMAS.isoformat(), "name": "Christmas"},
        {"date": BOXING_DAY.isoformat()},
    ]

    stored = holiday.upsert_fallback_holiday(stored, CHRISTMAS, "Christmas Day")
    assert stored[0] == {
        "date": CHRISTMAS.isoformat(),
        "name": "Christmas Day",
    }

    stored = holiday.remove_fallback_holiday(stored, BOXING_DAY)
    assert stored == [{"date": CHRISTMAS.isoformat(), "name": "Christmas Day"}]
