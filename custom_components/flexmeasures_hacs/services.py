"""Services of the FlexMeasures integration.

Services are registered once for the integration, not per config entry. Each
call resolves the config entry it acts on: implicitly when only one
FlexMeasures server is configured, or explicitly through the `entry_id` field.
Registering per entry used to re-register handlers bound to a stale entry on
every options change (which reloads the entry).
"""

from __future__ import annotations

from datetime import datetime
import json
import logging
from typing import cast
import uuid

from flexmeasures_client import FlexMeasuresClient
from flexmeasures_client.s2.cem import CEM
from flexmeasures_client.s2.control_types.FRBC.frbc_tunes import (
    FillRateBasedControlTUNES,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfPower
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.dispatcher import async_dispatcher_send
import homeassistant.util.dt as dt_util
import pandas as pd
from s2python.common import ControlType
from s2python.frbc import FRBCInstruction
import voluptuous as vol

from .const import (
    ATTR_ENTRY_ID,
    DOMAIN,
    RESOLUTION,
    SERVICE_CHANGE_CONTROL_TYPE,
    SOC_UNIT,
    signal_update_schedule,
)
from .exception import UndefinedCEMError, UnknownControlType
from .models import FlexMeasuresConfigEntry

LOGGER = logging.getLogger(__name__)

ENTRY_ID_SCHEMA = {vol.Optional(ATTR_ENTRY_ID): str}

CHANGE_CONTROL_TYPE_SCHEMA = vol.Schema(
    {vol.Optional("control_type"): str, **ENTRY_ID_SCHEMA}
)

SERVICE_TRIGGER_AND_GET_SCHEDULE = "trigger_and_get_schedule"
SERVICE_POST_MEASUREMENTS = "post_measurements"
SERVICE_SEND_FRBC_INSTRUCTION = "send_frbc_instruction"
SERVICE_GET_MEASUREMENTS = "get_measurements"
SERVICE_CALL_CEM_TRIGGER_SCHEDULE = "call_cem_trigger_schedule"

SERVICE_NAMES = (
    SERVICE_CHANGE_CONTROL_TYPE,
    SERVICE_TRIGGER_AND_GET_SCHEDULE,
    SERVICE_POST_MEASUREMENTS,
    SERVICE_SEND_FRBC_INSTRUCTION,
    SERVICE_GET_MEASUREMENTS,
    SERVICE_CALL_CEM_TRIGGER_SCHEDULE,
)


@callback
def _async_resolve_entry(
    hass: HomeAssistant, call: ServiceCall
) -> FlexMeasuresConfigEntry:
    """Return the config entry a service call acts on."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)
    entry_id = call.data.get(ATTR_ENTRY_ID)

    if entry_id is not None:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise ServiceValidationError(
            f"No loaded FlexMeasures configuration entry with entry_id {entry_id!r}."
        )

    if not entries:
        raise ServiceValidationError("No FlexMeasures configuration entry is loaded.")
    if len(entries) > 1:
        raise ServiceValidationError(
            "Several FlexMeasures configuration entries are loaded. "
            f"Pass '{ATTR_ENTRY_ID}' to say which one this service call is for."
        )

    return entries[0]


@callback
def _async_get_cem(entry: FlexMeasuresConfigEntry) -> CEM:
    """Return the CEM of a config entry, which exists once an RM connected."""
    cem = entry.runtime_data.cem
    if cem is None:
        raise UndefinedCEMError()
    return cem


async def change_control_type(call: ServiceCall) -> None:
    """Change control type S2 Protocol."""
    entry = _async_resolve_entry(call.hass, call)
    cem = _async_get_cem(entry)

    control_type = cast(str, call.data.get("control_type"))
    if not hasattr(ControlType, control_type):
        raise UnknownControlType()

    await cem.activate_control_type(control_type=ControlType[control_type])

    call.hass.states.async_set(
        f"{DOMAIN}.cem", json.dumps({"control_type": str(cem.control_type)})
    )


async def trigger_and_get_schedule(call: ServiceCall) -> None:
    """Trigger a schedule at FlexMeasures and store the result on the sensor."""
    hass = call.hass
    entry = _async_resolve_entry(hass, call)
    runtime_data = entry.runtime_data
    client: FlexMeasuresClient = runtime_data.client

    resolution = pd.Timedelta(RESOLUTION)
    tzinfo = dt_util.get_time_zone(hass.config.time_zone)
    start = time_ceil(datetime.now(tz=tzinfo), resolution)

    flex_model = client.create_storage_flex_model(
        soc_at_start=call.data.get("soc_at_start"),
        soc_unit=SOC_UNIT,
        soc_max=get_from_option_or_config("soc_max", entry),
        soc_min=get_from_option_or_config("soc_min", entry),
        soc_targets=call.data.get("soc_targets"),
    )
    flex_context = client.create_storage_flex_context(
        consumption_price_sensor=get_from_option_or_config(
            "consumption_price_sensor", entry
        ),
        production_price_sensor=get_from_option_or_config(
            "production_price_sensor", entry
        ),
    )

    flex_model.update(call.data.get("flex_model", {}))
    flex_context.update(call.data.get("flex_context", {}))

    duration = get_from_option_or_config("schedule_duration", entry)
    schedule_input = {
        "sensor_id": get_from_option_or_config("power_sensor", entry),
        "start": start,
        "duration": duration,
        "flex_model": flex_model,
        "flex_context": flex_context,
    }
    LOGGER.debug("Triggering a schedule with %s", schedule_input)
    schedule = await client.trigger_and_get_schedule(**schedule_input)

    values = client.convert_units(
        schedule["values"],
        from_unit=schedule["unit"],
        to_unit=UnitOfPower.KILO_WATT,
    )

    schedule_state = runtime_data.schedule_state
    schedule_state.schedule = [
        {"start": start + resolution * i, "value": value}
        for i, value in enumerate(values)
    ]
    schedule_state.start = start
    schedule_state.duration = duration

    async_dispatcher_send(hass, signal_update_schedule(entry.entry_id))


async def post_measurements(call: ServiceCall) -> None:
    """Post measurements to FlexMeasures."""
    entry = _async_resolve_entry(call.hass, call)

    await entry.runtime_data.client.post_measurements(
        sensor_id=call.data.get("sensor_id"),
        start=call.data.get("start"),
        duration=call.data.get("duration"),
        values=call.data.get("values"),
        unit=call.data.get("unit"),
        prior=call.data.get("prior"),
    )


async def send_frbc_instruction(call: ServiceCall) -> None:
    """Send an S2 Fill Rate Based Control message to the Resource Manager."""
    hass = call.hass
    entry = _async_resolve_entry(hass, call)
    cem = _async_get_cem(entry)

    dt_format = "%Y-%m-%d %H:%M:%S"
    tzinfo = dt_util.get_time_zone(hass.config.time_zone)
    execution_time = datetime.strptime(
        call.data.get("execution_time", datetime.now(tz=tzinfo).strftime(dt_format)),
        dt_format,
    ).replace(tzinfo=tzinfo)

    await cem.send_message(
        FRBCInstruction(
            id=call.data.get("id", uuid.uuid4()),
            message_id=call.data.get("message_id", uuid.uuid4()),
            actuator_id=call.data.get("actuator_id", uuid.uuid4()),
            operation_mode=call.data.get("operation_mode", uuid.uuid4()),
            operation_mode_factor=call.data.get("operation_mode_factor", 1.0),
            execution_time=execution_time,
            abnormal_condition=call.data.get("abnormal_condition", False),
        )
    )


async def get_measurements(call: ServiceCall) -> ServiceResponse:
    """Get sensor data from FlexMeasures."""
    entry = _async_resolve_entry(call.hass, call)

    data_query = {
        "sensor_id": call.data.get("sensor_id"),
        "start": call.data.get("start"),
        "duration": call.data.get("duration"),
        "unit": call.data.get("unit"),
        "resolution": call.data.get("resolution"),
    }
    if "source" in call.data:
        data_query["source"] = call.data["source"]

    return await entry.runtime_data.client.get_sensor_data(**data_query)


async def call_cem_trigger_schedule(call: ServiceCall) -> None:
    """Let the CEM's FRBC handler trigger a schedule."""
    entry = _async_resolve_entry(call.hass, call)
    cem = _async_get_cem(entry)

    if cem.control_type == ControlType.FILL_RATE_BASED_CONTROL:
        frbc: FillRateBasedControlTUNES = cast(
            FillRateBasedControlTUNES,
            cem._control_types_handlers[ControlType.FILL_RATE_BASED_CONTROL],
        )
        await frbc.trigger_schedule()


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Register the services, once for the whole integration."""
    if hass.services.has_service(DOMAIN, SERVICE_CHANGE_CONTROL_TYPE):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_CHANGE_CONTROL_TYPE,
        change_control_type,
        schema=CHANGE_CONTROL_TYPE_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_TRIGGER_AND_GET_SCHEDULE, trigger_and_get_schedule
    )
    hass.services.async_register(DOMAIN, SERVICE_POST_MEASUREMENTS, post_measurements)
    hass.services.async_register(
        DOMAIN, SERVICE_SEND_FRBC_INSTRUCTION, send_frbc_instruction
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_MEASUREMENTS,
        get_measurements,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_CALL_CEM_TRIGGER_SCHEDULE, call_cem_trigger_schedule
    )


@callback
def async_unload_services(hass: HomeAssistant) -> None:
    """Remove the services."""
    for service_name in SERVICE_NAMES:
        if hass.services.has_service(DOMAIN, service_name):
            hass.services.async_remove(DOMAIN, service_name)


def time_mod(time, delta, epoch=None):
    """From https://stackoverflow.com/a/57877961/13775459."""
    if epoch is None:
        epoch = datetime(1970, 1, 1, tzinfo=time.tzinfo)
    return (time - epoch) % delta


def time_ceil(time, delta, epoch=None):
    """From https://stackoverflow.com/a/57877961/13775459."""
    mod = time_mod(time, delta, epoch)
    if mod:
        return time + (delta - mod)
    return time


def get_from_option_or_config(key: str, entry: ConfigEntry, section: str | None = None):
    """Get value from the options and, if not found, return the config value."""

    if section:
        return entry.options.get(section, {}).get(
            key, entry.data.get(section, {}).get(key)
        )

    return entry.options.get(key, entry.data.get(key))
