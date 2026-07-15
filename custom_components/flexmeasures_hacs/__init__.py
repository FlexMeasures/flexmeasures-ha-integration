"""The FlexMeasures integration."""

from __future__ import annotations

from dataclasses import fields
import logging

from flexmeasures_client import FlexMeasuresClient
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ConfigValidationError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from packaging.version import Version

from .config_flow import get_host_and_ssl_from_url
from .const import DOMAIN, SCHEDULE_ENTITY
from .control_types import FRBC_Config
from .datastore import (
    LEGACY_STORAGE_KEY,
    STORAGE_VERSION,
    PersistentDatastore,
    storage_key,
)
from .models import FlexMeasuresConfigEntry, FlexMeasuresRuntimeData
from .services import (
    async_setup_services,
    async_unload_services,
    get_from_option_or_config,
)
from .websockets import async_register_websocket_view

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# flexmeasures-client >=0.8 posts and reads sensor data through endpoints that
# FlexMeasures only serves from 0.28.0 on (scheduling needs 0.27.0). Against an
# older server those calls 404 at the moment a service runs, so check the server
# version once at startup and say so, rather than let a nightly automation be
# the one to find out.
MINIMUM_SERVER_VERSION = "0.28.0"

# Fields of FRBC_Config that live outside the "s2" section of the config entry.
NON_S2_FIELDS = (
    "consumption_price_sensor",
    "production_price_sensor",
    "schedule_duration",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: FlexMeasuresConfigEntry
) -> bool:
    """Set up FlexMeasures from a config entry."""

    # Reload integration when the options are updated
    entry.async_on_unload(entry.add_update_listener(options_update_listener))

    if get_from_option_or_config("schedule_duration", entry) is None:
        raise ConfigValidationError(
            message="Schedule duration is not set", exceptions=[]
        )

    host, ssl = get_host_and_ssl_from_url(get_from_option_or_config("url", entry))
    client = FlexMeasuresClient(
        host=host,
        email=get_from_option_or_config("username", entry),
        password=get_from_option_or_config("password", entry),
        ssl=ssl,
        session=async_get_clientsession(hass),
        logger=_LOGGER,
    )

    frbc_config = FRBC_Config(
        **{
            f.name: get_from_option_or_config(
                f.name,
                entry,
                section=None if f.name in NON_S2_FIELDS else "s2",
            )
            for f in fields(FRBC_Config)
        }
    )

    datastore = PersistentDatastore(hass, storage_key(entry.entry_id))
    await datastore.async_load()

    entry.runtime_data = FlexMeasuresRuntimeData(
        client=client,
        frbc_config=frbc_config,
        datastore=datastore,
    )

    async_register_websocket_view(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_setup_services(hass)

    entry.async_create_background_task(
        hass,
        _async_check_server_version(client),
        name=f"{DOMAIN}_check_server_version",
    )

    return True


async def _async_check_server_version(client: FlexMeasuresClient) -> None:
    """Warn when the FlexMeasures server is too old for the client we ship.

    Deliberately does not block or fail the setup: an unreachable server is a
    separate problem, and the schedule sensor and the S2 path are useful even
    while we cannot tell the version.
    """
    try:
        versions = await client.get_versions()
        server_version = versions.get("server_version")
        if server_version is None:
            return
        if Version(server_version) < Version(MINIMUM_SERVER_VERSION):
            _LOGGER.warning(
                "This FlexMeasures server runs version %s, but posting and reading"
                " sensor data needs %s or above (scheduling needs 0.27.0). Those"
                " service calls will fail until the server is upgraded",
                server_version,
                MINIMUM_SERVER_VERSION,
            )
    except Exception:
        _LOGGER.debug(
            "Could not determine the FlexMeasures server version", exc_info=True
        )


async def options_update_listener(
    hass: HomeAssistant, config_entry: FlexMeasuresConfigEntry
) -> None:
    """Handle options update."""

    _LOGGER.debug("Configuration options updated, reloading FlexMeasures integration")
    await hass.config_entries.async_reload(config_entry.entry_id)


async def async_unload_entry(
    hass: HomeAssistant, entry: FlexMeasuresConfigEntry
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Services are registered for the integration as a whole, so only drop
        # them once the last entry goes away.
        remaining = [
            other
            for other in hass.config_entries.async_loaded_entries(DOMAIN)
            if other.entry_id != entry.entry_id
        ]
        if not remaining:
            async_unload_services(hass)

    return unload_ok


async def async_migrate_entry(
    hass: HomeAssistant, config_entry: FlexMeasuresConfigEntry
) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating configuration from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.version > 4:
        # This means the user has downgraded from a future version
        return False

    if config_entry.version == 1:
        from .config_flow import S2_SCHEMA, schema_defaults

        new_data = {**config_entry.data} | {**config_entry.options}
        s2_defaults = schema_defaults(S2_SCHEMA)
        new_data["s2"] = {
            field: new_data.get(field, s2_defaults.get(field))
            for field in (str(field) for field in S2_SCHEMA.schema)
            if field in new_data or field in s2_defaults
        }

        hass.config_entries.async_update_entry(config_entry, data=new_data, version=2)

    if config_entry.version == 2:
        # v3 renames the misspelled leakage_beaviour_sensor_id (which client
        # versions >=0.8 no longer accept) and fills S2 fields that did not
        # exist when the entry was created (e.g. asset_id).
        from .config_flow import S2_SCHEMA, schema_defaults

        def migrate_s2_section(s2: dict, fill_defaults: bool) -> dict:
            s2 = {**s2}
            if "leakage_beaviour_sensor_id" in s2:
                s2.setdefault(
                    "leakage_behaviour_sensor_id",
                    s2.pop("leakage_beaviour_sensor_id"),
                )
            if fill_defaults:
                for field, default in schema_defaults(S2_SCHEMA).items():
                    s2.setdefault(field, default)
            return s2

        new_data = {**config_entry.data}
        if "s2" in new_data:
            new_data["s2"] = migrate_s2_section(new_data["s2"], fill_defaults=True)
        new_options = {**config_entry.options}
        if "s2" in new_options:
            # Options override data per key, so only rename here; missing keys
            # fall back to the defaults filled into data above.
            new_options["s2"] = migrate_s2_section(
                new_options["s2"], fill_defaults=False
            )

        hass.config_entries.async_update_entry(
            config_entry, data=new_data, options=new_options, version=3
        )

    if config_entry.version == 3:
        # v4 makes runtime state per config entry, so that several FlexMeasures
        # servers can be configured side by side. The schedule sensor and the
        # datastore used to be shared; give them entry-scoped identities while
        # keeping the existing entity (and its history) and the stored S2 state.
        await _async_migrate_unique_ids(hass, config_entry)
        await _async_migrate_datastore(hass, config_entry)

        hass.config_entries.async_update_entry(config_entry, version=4)

    _LOGGER.debug(
        "Migration to configuration version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )

    return True


async def _async_migrate_unique_ids(
    hass: HomeAssistant, entry: FlexMeasuresConfigEntry
) -> None:
    """Scope the schedule sensor's unique id to the config entry."""

    @callback
    def _migrate(entity_entry: er.RegistryEntry) -> dict[str, str] | None:
        if entity_entry.unique_id == SCHEDULE_ENTITY:
            return {"new_unique_id": f"{entry.entry_id}_{SCHEDULE_ENTITY}"}
        return None

    await er.async_migrate_entries(hass, entry.entry_id, _migrate)


async def _async_migrate_datastore(
    hass: HomeAssistant, entry: FlexMeasuresConfigEntry
) -> None:
    """Copy the shared S2 datastore into a store belonging to this config entry.

    The legacy store is deliberately left in place. Home Assistant does not
    support downgrading a config entry across a major version, so rolling back
    to an older release means removing and re-adding the entry -- and that older
    release reads the S2 state from exactly this legacy store.
    """
    legacy_store: Store = Store(hass, version=STORAGE_VERSION, key=LEGACY_STORAGE_KEY)
    legacy_data = await legacy_store.async_load()
    if not legacy_data:
        return

    entry_store: Store = Store(
        hass, version=STORAGE_VERSION, key=storage_key(entry.entry_id)
    )
    if await entry_store.async_load():
        # Already migrated (or this entry has state of its own); don't clobber it.
        return

    await entry_store.async_save(legacy_data)
    _LOGGER.debug("Copied the S2 datastore to config entry %s", entry.entry_id)


__all__ = [
    "ConfigEntry",
    "FlexMeasuresConfigEntry",
    "async_migrate_entry",
    "async_setup_entry",
    "async_unload_entry",
]
