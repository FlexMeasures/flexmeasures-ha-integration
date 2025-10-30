"""The FlexMeasures integration."""

from __future__ import annotations

from dataclasses import fields
import asyncio
import logging

from flexmeasures_client import FlexMeasuresClient

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store

from .config_flow import get_host_and_ssl_from_url
from .const import DATASTORE, DOMAIN, FM_CLIENT, FRBC_CONFIG, TIMERS
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

    # Reload integration when the options are updated
    entry.async_on_unload(entry.add_update_listener(options_update_listener))

    host, ssl = get_host_and_ssl_from_url(get_from_option_or_config("url", entry))
    client = FlexMeasuresClient(
        host=host,
        email=get_from_option_or_config("username", entry),
        password=get_from_option_or_config("password", entry),
        ssl=ssl,
        session=async_get_clientsession(hass),
        logger=_LOGGER,
    )

    # store config
    # if schedule_duration is not set, throw an error
    if get_from_option_or_config("schedule_duration", entry) is None:
        raise ConfigValidationError(
            message="Schedule duration is not set", exceptions=[]
        )

    frbc_data_dict = {}

    non_s2_fields = [
        "consumption_price_sensor",
        "production_price_sensor",
        "schedule_duration",
    ]

    for field in fields(FRBC_Config):
        if field.name in non_s2_fields:
            frbc_data_dict[field.name] = get_from_option_or_config(field.name, entry)
        else:
            frbc_data_dict[field.name] = get_from_option_or_config(
                field.name, entry, section="s2"
            )

    FRBC_data = FRBC_Config(**frbc_data_dict)
    hass.data[DOMAIN][FRBC_CONFIG] = FRBC_data

    hass.data[DOMAIN][FM_CLIENT] = client
    hass.data[DOMAIN][TIMERS] = {}

    # Create a persistent datastore
    datastore = PersistentDatastore(hass, DOMAIN)
    await datastore.async_load()
    hass.data[DOMAIN][DATASTORE] = datastore

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


async def async_migrate_entry(hass, config_entry: ConfigEntry):
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version > 2:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 1:
        from .config_flow import S2_SCHEMA

        new_data = {**config_entry.data} | {**config_entry.options}
        new_data["s2"] = {}

        for field in S2_SCHEMA.schema.keys():
            field_name = str(field)
            if field_name in new_data:
                new_data["s2"][field_name] = new_data[field_name]
            elif hasattr(field, "default"):
                new_data["s2"][field_name] = field.default()

        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )

    return True


class PersistentDatastore(dict):
    def __init__(self, hass, domain: str, version: int = 1, save_delay: float = 5.0):
        super().__init__()
        self.hass = hass
        self._store = Store(hass, version=version, key=f"{domain}_datastore")
        self._initialized = False
        self._save_handle = None
        self._save_delay = save_delay

    async def async_load(self):
        data = await self._store.async_load() or {}
        self.clear()
        self.update(data)
        self._initialized = True

    async def async_save(self):
        if not self._initialized:
            raise RuntimeError("Datastore not loaded yet")
        await self._store.async_save(dict(self))

    def _schedule_save(self):
        if self._save_handle:
            self._save_handle()  # cancel previous
        self._save_handle = async_call_later(
            self.hass, self._save_delay, lambda _: self.hass.async_create_task(self.async_save())
        )

    def __setitem__(self, key, value):
        super().__setitem__(key, value)
        if self._initialized:
            if self.hass.loop.is_running() and not asyncio.get_event_loop().is_running():
                # We are in a worker thread
                self.hass.loop.call_soon_threadsafe(self._schedule_save)
            else:
                # Already in main loop
                self._schedule_save()

    def __delitem__(self, key):
        super().__delitem__(key)
        if self._initialized:
            if self.hass.loop.is_running() and not asyncio.get_event_loop().is_running():
                # We are in a worker thread
                self.hass.loop.call_soon_threadsafe(self._schedule_save)
            else:
                # Already in main loop
                self._schedule_save()
