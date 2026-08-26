# Shared Schedule

A Home Assistant custom integration for a simple alternating shared-care
schedule. It keeps the recurring cadence separate from public-holiday changes
and one-off overrides, so exceptions never silently move the series.

## Install

### HACS

1. In HACS, open **Integrations**, select the three-dot menu, and choose
   **Custom repositories**.
2. Copy this repository's URL from the browser and add it with the category
   **Integration**.
3. Download **Shared Schedule**, restart Home Assistant, then add it from
   **Settings → Devices & services → Add integration**.

### Manual installation

Copy `custom_components/shared_schedule` into the matching `custom_components`
directory in your Home Assistant configuration, restart Home Assistant, then go
to **Settings → Devices & services → Add integration → Shared Schedule**.

The setup form asks for:

- a neutral schedule name and the two party display names;
- an optional care-subject display name;
- which Party A/Party B value represents **me** (Party A for existing entries);
- which party currently has responsibility;
- a reference handover date, weekday, local time, and recurrence in weeks;
- a two-letter holiday country code (`IE` by default); and
- whether a handover on a public holiday moves to the following day.

The reference date must match the chosen weekday. If the reference date is in
the past when the integration is first created, the first future occurrence on
that cadence is used. After that, the next base occurrence and current party are
stored by the integration and restored across restarts.

The care-subject display name is presentation-only and can be edited later in
the integration options. Existing entries that predate this option continue to
load unchanged and use neutral “care subject” wording until a value is set.
Party names, current state, cadence, overrides, notes, and the configured
**my party** value are never inferred from or replaced by the subject name.

## Entities

For a schedule named **Example Schedule**, Home Assistant creates a device with:

- `sensor.example_schedule_status` — state is the **actual current owner**,
  including a date override applying today. Its attributes include the
  `scheduled_current_party` cadence owner, `actual_current_party`, `with_me`,
  `next_time_with_me`, `next_time_leaving_me`, `next_handover_direction`, and
  the base, holiday-adjusted, overridden, and effective dates;
- `sensor.example_schedule_next_handover` — timestamp of the effective handover;
- binary sensors for Party A and Party B (both use the actual current owner),
  handover today, and handover tomorrow.

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

The top of the **Schedule** view answers where the configured care subject is
now, what happens next, and when from the configured **my party** perspective.
Normal cadence details remain available as secondary information. A private
note can be attached to the upcoming handover occurrence; it is bounded to 500
characters, stored locally in Home Assistant, and discarded when that
occurrence completes.

The temporary schedule change wizard applies one party to a selected date
range, previews every affected date, and explicitly leaves the recurring
cadence unchanged afterwards. Existing overrides in the range are replaced,
dates already assigned to that party are not stored redundantly, and the
resulting group can be edited or removed from **Overrides**.

The view also shows six weeks of normal ownership. Choose a party and select one
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

## Events

The integration emits two Home Assistant event types for automations:

- `shared_schedule_handover_completed` fires once per actual ownership
  transition. Data includes `entry_id`, a deduplicating `occurrence_id`,
  `from_party_key`/`from_party_name`, `to_party_key`/`to_party_name`,
  `effective_handover`, `source` (`normal`, `public_holiday`,
  `manual_override`, or `date_override`), and
  `reconciled_after_downtime`. The last observed actual owner and observation
  time are stored. If a date-override midnight boundary is crossed while Home
  Assistant is offline, startup reconciliation emits the corresponding event
  once with its real boundary time and `reconciled_after_downtime: true`.
  Entries upgrading from data without a last observation establish the
  baseline on their first startup rather than guessing and emitting an event.
- `shared_schedule_schedule_changed` fires for meaningful schedule edits. Its
  `action` identifies `handover_override_added`,
  `handover_override_changed`, `handover_override_cleared`,
  `date_overrides_changed`, `date_overrides_removed`, or `series_shifted`.
  The temporary-change wizard still mutates only date overrides; changes it
  initiates therefore use `action: date_overrides_changed` with
  `ui_source: temporary_change` and an `operation` of `create` or `edit`.
  No persistent temporary-change object or provenance is implied.

Frontend reads and display-only colour changes do not emit lifecycle events.

## Development

The schedule model is pure Python and its tests cover normal and holiday
handovers, overrides, restart reconciliation, missed periods, manual correction,
series shifts, date ownership, persistence, and daylight-saving changes.

```text
python -m pytest
python -m ruff check .
```
