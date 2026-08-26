"""Constants for the Shared Schedule integration."""

DOMAIN = "shared_schedule"
PLATFORMS = ["sensor", "binary_sensor"]

CONF_PARTY_A = "party_a"
CONF_PARTY_B = "party_b"
CONF_CURRENT_PARTY = "current_party"
CONF_ANCHOR_DATE = "anchor_date"
CONF_RECURRENCE_WEEKS = "recurrence_weeks"
CONF_WEEKDAY = "weekday"
CONF_HANDOVER_TIME = "handover_time"
CONF_COUNTRY = "country"
CONF_SHIFT_HOLIDAYS = "shift_public_holidays"
CONF_PARTY_A_COLOR = "party_a_color"
CONF_PARTY_B_COLOR = "party_b_color"
CONF_MY_PARTY = "my_party"
CONF_SUBJECT_NAME = "subject_name"

DEFAULT_PARTY_A_COLOR = "#3f8fc9"
DEFAULT_PARTY_B_COLOR = "#b06ab3"

PARTY_A = "a"
PARTY_B = "b"

EVENT_HANDOVER_COMPLETED = f"{DOMAIN}_handover_completed"
EVENT_SCHEDULE_CHANGED = f"{DOMAIN}_schedule_changed"

HANDOVER_NOTE_MAX_LENGTH = 500

SERVICE_SET_OVERRIDE = "set_handover_override"
SERVICE_CLEAR_OVERRIDE = "clear_handover_override"
SERVICE_SET_CURRENT_PARTY = "set_current_party"
SERVICE_COMPLETE_HANDOVER = "complete_handover"
SERVICE_SHIFT_SERIES = "shift_series"
