"""Test initialization of FlexMeasures integration."""

from unittest.mock import patch

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant

from custom_components.flexmeasures_hacs.const import DOMAIN
from custom_components.flexmeasures_hacs.services import SERVICE_NAMES


async def test_load_unload_config_entry(
    hass: HomeAssistant, setup_fm_integration
) -> None:
    """Test setup of integration."""

    entry = setup_fm_integration

    assert len(hass.config_entries.async_entries(DOMAIN)) == 1

    for service_name in SERVICE_NAMES:
        assert hass.services.has_service(DOMAIN, service_name)

    assert entry.state == ConfigEntryState.LOADED
    assert entry.runtime_data.client is not None

    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()

    for service_name in SERVICE_NAMES:
        assert not hass.services.has_service(DOMAIN, service_name)

    assert entry.state == ConfigEntryState.NOT_LOADED


async def test_services_act_on_the_current_entry_after_a_reload(
    hass: HomeAssistant, setup_fm_integration
) -> None:
    """A reload must not leave services bound to the entry's previous runtime data.

    Services used to be registered per config entry, and the registration list
    was mutated in place, so after a reload (which every options change causes)
    the handlers bound to the *old* entry state were re-registered.
    """
    entry = setup_fm_integration

    await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state == ConfigEntryState.LOADED

    with patch(
        "flexmeasures_client.client.FlexMeasuresClient.trigger_and_get_schedule",
        return_value={"values": [1.0], "unit": "MW"},
    ):
        await hass.services.async_call(
            DOMAIN,
            "trigger_and_get_schedule",
            service_data={"soc_at_start": 10},
            blocking=True,
        )

    # The schedule landed on the entry's *current* runtime data, i.e. the
    # service resolved the reloaded entry and not a stale closure.
    assert entry.runtime_data.schedule_state.schedule


async def test_two_entries_keep_their_own_state(
    hass: HomeAssistant, setup_fm_integration, setup_second_fm_integration
) -> None:
    """Two FlexMeasures servers can be configured side by side."""
    first = setup_fm_integration
    second = setup_second_fm_integration

    assert len(hass.config_entries.async_loaded_entries(DOMAIN)) == 2
    assert first.runtime_data is not second.runtime_data
    assert first.runtime_data.client.port == 5000
    assert second.runtime_data.client.port == 5001

    # Each entry gets its own schedule sensor.
    entity_ids = [
        state.entity_id
        for state in hass.states.async_all("sensor")
        if state.entity_id.startswith("sensor.")
    ]
    assert len(entity_ids) == 2

    # Unloading one entry keeps the services around for the other.
    await hass.config_entries.async_unload(second.entry_id)
    await hass.async_block_till_done()
    assert hass.services.has_service(DOMAIN, "trigger_and_get_schedule")


async def test_warns_when_the_flexmeasures_server_is_too_old(
    hass: HomeAssistant, caplog
) -> None:
    """An old FlexMeasures server makes the sensor-data services 404 at call time.

    flexmeasures-client >=0.8 uses endpoints that FlexMeasures only serves from
    0.28.0 on, so say so at startup instead of letting an automation find out.
    """
    from .conftest import build_entry

    entry = build_entry(unique_id="oldserver")
    entry.add_to_hass(hass)

    with patch(
        "flexmeasures_client.client.FlexMeasuresClient.get_versions",
        return_value={"server_version": "0.25.0"},
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED  # a warning, not a failure
    assert "0.25.0" in caplog.text
    assert "0.28.0 or above" in caplog.text


async def test_no_warning_for_a_recent_flexmeasures_server(
    hass: HomeAssistant, caplog
) -> None:
    """A recent enough server must not produce the version warning."""
    from .conftest import build_entry

    entry = build_entry(unique_id="newserver")
    entry.add_to_hass(hass)

    with patch(
        "flexmeasures_client.client.FlexMeasuresClient.get_versions",
        return_value={"server_version": "0.33.1"},
    ):
        await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    assert entry.state == ConfigEntryState.LOADED
    assert "or above" not in caplog.text
