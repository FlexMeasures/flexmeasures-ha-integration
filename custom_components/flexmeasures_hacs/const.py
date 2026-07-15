"""Constants for the FlexMeasures integration."""

DOMAIN = "flexmeasures_hacs"
WS_VIEW_URI = "/api/websocket_custom"
WS_VIEW_NAME = "websocket_custom"

# SERVICES
SERVICE_CHANGE_CONTROL_TYPE = "change_control_type"
RESOLUTION = "PT15M"
SIGNAL_UPDATE_SCHEDULE = "flexmeasures_hacs_update_schedule"
SCHEDULE_ENTITY = "flexmeasures_schedule"
SOC_UNIT = "kWh"

# Service data field naming the config entry to act on, needed only when more
# than one FlexMeasures server is configured.
ATTR_ENTRY_ID = "entry_id"


def signal_update_schedule(entry_id: str) -> str:
    """Return the dispatcher signal for schedule updates of one config entry."""
    return f"{SIGNAL_UPDATE_SCHEDULE}_{entry_id}"
