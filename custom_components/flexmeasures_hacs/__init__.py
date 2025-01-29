"""The FlexMeasures integration."""
from __future__ import annotations

from dataclasses import fields
import logging

from flexmeasures_client import FlexMeasuresClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .config_flow import get_host_and_ssl_from_url
from .const import DOMAIN, FRBC_CONFIG
from .control_types import FRBC_Config
from .services import (
    async_setup_services,
    async_unload_services,
    get_from_option_or_config,
)
from .websockets import WebsocketAPIView

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up FlexMeasures from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    # use entry.data directly instead of the config_data dict
    # config_data = dict(entry.data)
    # Registers update listener to update config entry when options are updated.
    # unsub_options_update_listener = entry.add_update_listener(options_update_listener)
    # Store a reference to the unsubscribe function to cleanup if an entry is unloaded.
    # config_data["unsub_options_update_listener"] = unsub_options_update_listener

    host, ssl = get_host_and_ssl_from_url(get_from_option_or_config("url", entry))
    client = FlexMeasuresClient(
        host=host,
        email=get_from_option_or_config("username", entry),
        password=get_from_option_or_config("password", entry),
        ssl=ssl,
        session=async_get_clientsession(hass),
    )

    # store config
    # if shcedule_duration is not set, throw an error
    if get_from_option_or_config("schedule_duration", entry) is None:
        raise ConfigValidationError(
            message="Schedule duration is not set", exceptions=[]
        )

    frbc_data_dict = {}

    for field in fields(FRBC_Config):
        frbc_data_dict[field.name] = get_from_option_or_config(field.name, entry)

    FRBC_data = FRBC_Config(**frbc_data_dict)
    hass.data[DOMAIN][FRBC_CONFIG] = FRBC_data

    hass.data[DOMAIN]["fm_client"] = client

    hass.http.register_view(WebsocketAPIView(entry))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    await async_setup_services(hass, entry)

    return True


async def options_update_listener(hass: HomeAssistant, config_entry: ConfigEntry):
    """Handle options update."""

    _LOGGER.debug("Configuration options updated, reloading FlexMeasures integration")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if DOMAIN not in hass.data:
        return True

    # Remove services
    await async_unload_services(hass)

    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok
