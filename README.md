# Shared Schedule

A Home Assistant custom integration for a simple alternating shared-care
schedule. It keeps the recurring cadence separate from public-holiday changes
and one-off overrides, so exceptions never silently move the series.

## Install

### HACS

1. In HACS, open **Integrations**, select the three-dot menu, and choose
   **Custom repositories**.
2. Add `https://github.com/conorod1992/shared_care` with the category
   **Integration**.
3. Download **Shared Schedule**, restart Home Assistant, then add it from
   **Settings → Devices & services → Add integration**.

### Manual installation

Copy `custom_components/shared_schedule` into the matching `custom_components`
directory in your Home Assistant configuration, restart Home Assistant, then go
to **Settings → Devices & services → Add integration → Shared Schedule**.

The setup form asks for:

- a neutral schedule name and the two display names;
- which party currently has responsibility;
- a reference handover date, weekday, local time, and recurrence in weeks;
- a two-letter holiday country code (`IE` by default); and
- whether a handover on a public holiday moves to the following day.

The reference date must match the chosen weekday. If the reference date is in
the past when the integration is first created, the first future occurrence on
that cadence is used. After that, the next base occurrence and current party are
stored by the integration and restored across restarts.

## Entities

For a schedule named **Example Schedule**, Home Assistant creates a device with:

- `sensor.example_schedule_status` — state is the current display name, with
  attributes for the base, holiday-adjusted, overridden, and effective dates;
- `sensor.example_schedule_next_handover` — timestamp of the effective handover;
- binary sensors for Party A, Party B, handover today, and handover tomorrow.

The exact entity IDs can vary if similarly named entities already exist.

## Actions

Actions target either sensor belonging to the schedule.

Set a one-off override:

```yaml
action: shared_schedule.set_handover_override
target:
  entity_id: sensor.example_schedule_status
data:
  datetime: "2026-08-06 18:00:00"
```

The override must be in the future and before the following base occurrence. It
changes only the active handover. `shared_schedule.clear_handover_override`
restores its public-holiday-adjusted time.

Correct the current party without changing dates:

```yaml
action: shared_schedule.set_current_party
target:
  entity_id: sensor.example_schedule_status
data:
  party: b
```

`shared_schedule.complete_handover` switches party immediately, clears an
override, and advances exactly one base occurrence.

To intentionally establish a new cadence, use:

```yaml
action: shared_schedule.shift_series
target:
  entity_id: sensor.example_schedule_status
data:
  datetime: "2026-08-10 18:00:00"
```

This is deliberately different from a one-off override.

## Schedule panel and date overrides

The integration adds a **Shared Schedule** page to the Home Assistant sidebar.
It is an admin-only native panel using Home Assistant's authenticated WebSocket
connection; it does not run or expose a separate web server.

The **Schedule** view shows the current actual owner, the normal and effective
next handovers, and six weeks of normal ownership. Choose a party and select one
date, or two endpoints for a contiguous range. Dates already belonging to that
party on the normal cadence are disabled. Existing exceptions are outlined and
can be removed or changed by selecting them.

Date overrides apply only to the selected ISO calendar dates. They do not alter
the recurring cadence, public-holiday adjustment, or the separate next-handover
override. Redundant overrides are not stored when the selected party already
owns the date normally. The **Overrides** view groups upcoming exceptions for
quick editing or deletion. The **Settings** view summarizes the useful schedule
configuration and links to Home Assistant's standard integration options.

## Restart and time handling

All stored datetimes are restored into Home Assistant's configured timezone.
At startup, an overdue effective handover is processed automatically. If
several complete recurrence periods elapsed while Home Assistant was offline,
the model advances them mathematically and applies the correct odd/even party
change rather than replaying each event.

Holiday calculation uses the maintained `holidays` Python package. Handover
timing remains base recurrence → public-holiday adjustment → manual override →
effective handover. Date ownership overrides are evaluated separately.

## Development

The schedule model is pure Python and its tests cover normal and holiday
handovers, overrides, restart reconciliation, missed periods, manual correction,
series shifts, date ownership, persistence, and daylight-saving changes.

```text
python -m pytest
python -m ruff check .
```
