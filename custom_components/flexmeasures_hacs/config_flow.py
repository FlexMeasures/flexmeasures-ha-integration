"""Config flow for FlexMeasures integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from flexmeasures_client import FlexMeasuresClient
from flexmeasures_client.exceptions import EmailValidationError
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import async_get_hass
from homeassistant.data_entry_flow import FlowResult, section
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.schema_config_entry_flow import (
    SchemaCommonFlowHandler,
    SchemaConfigFlowHandler,
    SchemaFlowError,
    SchemaFlowFormStep,
)
import voluptuous as vol

from .const import DOMAIN

# The asset and sensor ids below identify entities on *your* FlexMeasures
# server, so there is no sensible default for them: earlier versions shipped
# the ids of one pilot's server, which silently pointed fresh installs at
# somebody else's asset. They are optional because they are only needed when
# the S2 (FRBC/TUNES) control path is used.
S2_FIELDS = (
    "asset_id",
    "consumption_sensor_id",
    "soc_minima_sensor_id",
    "soc_maxima_sensor_id",
    "fill_level_sensor_id",
    "fill_rate_sensor_id",
    "usage_forecast_sensor_id",
    "thp_fill_rate_sensor_id",
    "thp_efficiency_sensor_id",
    "nes_fill_rate_sensor_id",
    "nes_efficiency_sensor_id",
    "active_actuator_id_sensor_id",
    "rm_discharge_sensor_id",
    "state_of_charge_sensor_id",
    "leakage_behaviour_sensor_id",
)

S2_SCHEMA = vol.Schema({vol.Optional(field): vol.Any(int, None) for field in S2_FIELDS})

SCHEMA = vol.Schema(
    {
        vol.Required("url"): str,
        vol.Required("username"): str,
        vol.Required("password"): str,
        vol.Optional("power_sensor"): int,
        vol.Optional("schedule_duration", default="PT24H"): str,
        vol.Optional("consumption_price_sensor"): int,
        vol.Optional("production_price_sensor"): int,
        vol.Optional("soc_sensor"): int,
        vol.Optional("soc_unit", default="kWh"): str,
        vol.Optional("soc_min"): vol.Coerce(float),
        vol.Optional("soc_max"): vol.Coerce(float),
        vol.Optional("s2"): section(S2_SCHEMA, {"collapsed": True}),
    }
)


def schema_defaults(schema: vol.Schema) -> dict[str, Any]:
    """Return the fields of a schema that have a default, and their defaults.

    Voluptuous sets `Marker.default` to a non-callable sentinel when a field has
    no default, so callers cannot just call `field.default()`.
    """
    defaults: dict[str, Any] = {}
    for field in schema.schema:
        default = getattr(field, "default", vol.UNDEFINED)
        if default is not vol.UNDEFINED and callable(default):
            defaults[str(field)] = default()
    return defaults


def get_host_and_ssl_from_url(url: str) -> tuple[str, bool]:
    """Get the host and ssl from the url."""
    if url.startswith("http://"):
        ssl = False
        host = url.removeprefix("http://")
    elif url.startswith("https://"):
        ssl = True
        host = url.removeprefix("https://")
    else:
        ssl = True
        host = url

    return host, ssl


async def validate_input(
    handler: SchemaCommonFlowHandler, data: dict[str, Any]
) -> dict:
    """Validate if the user input allows us to connect.

    Data has the keys from SCHEMA with values provided by the user.
    """

    host, ssl = get_host_and_ssl_from_url(data["url"])

    hass = async_get_hass()

    # Currently used here solely for config validation (i.e. not returned to be stored in the config entry)
    try:
        client = FlexMeasuresClient(
            session=async_get_clientsession(hass),
            host=host,
            email=data["username"],
            password=data["password"],
            ssl=ssl,
        )
    except EmailValidationError as exception:
        raise SchemaFlowError("invalid_email") from exception

    except Exception as exception:
        raise SchemaFlowError("invalid_auth") from exception

    try:
        await client.get_access_token()
    except Exception as exception:
        raise SchemaFlowError("invalid_auth") from exception

    # Return info that you want to store in the config entry.
    return data


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(schema=SCHEMA, validate_user_input=validate_input)
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(schema=SCHEMA, validate_user_input=validate_input)
}


class ConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config or options flow for FlexMeasures."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    reauth_entry: ConfigEntry

    VERSION = 4

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title."""
        return "FlexMeasures"

    async def async_step_reauth(self, user_input=None):
        """Dialog that informs the user that reauth is required."""

        self.reauth_entry = cast(
            ConfigEntry,
            self.hass.config_entries.async_get_entry(self.context["entry_id"]),
        )

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, str] | None = None
    ) -> FlowResult:
        """Handle re-auth completion."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.reauth_entry, data=user_input
            )
            # Reload the FlexMeasures config entry otherwise devices will remain unavailable
            self.hass.async_create_task(
                self.hass.config_entries.async_reload(self.reauth_entry.entry_id)
            )

            return self.async_abort(reason="reauth_successful")

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=SCHEMA,
        )
