"""Test the FlexMeasures config flow."""

from unittest.mock import patch

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flexmeasures_hacs.config_flow import (
    S2_SCHEMA,
    SCHEMA,
    schema_defaults,
)
from custom_components.flexmeasures_hacs.const import DOMAIN

from .conftest import CURRENT_VERSION

CONFIG = {
    "username": "admin@admin.com",
    "password": "admin",
    "url": "http://localhost:5000",
    "power_sensor": 1,
    "soc_sensor": 3,
    "schedule_duration": "PT24H",
    "consumption_price_sensor": 2,
    "production_price_sensor": 2,
    "soc_unit": "kWh",
    "soc_min": 0.0,
    "soc_max": 0.001,
}

S2_CONFIG = {
    "asset_id": 20,
    "consumption_sensor_id": 21,
    "soc_minima_sensor_id": 1,
    "soc_maxima_sensor_id": 2,
    "fill_level_sensor_id": 3,
    "fill_rate_sensor_id": 4,
    "usage_forecast_sensor_id": 5,
    "thp_fill_rate_sensor_id": 6,
    "thp_efficiency_sensor_id": 7,
    "nes_fill_rate_sensor_id": 8,
    "nes_efficiency_sensor_id": 9,
    "rm_discharge_sensor_id": 10,
    "active_actuator_id_sensor_id": 15,
    "state_of_charge_sensor_id": 16,
    "leakage_behaviour_sensor_id": 17,
}


async def test_form(hass: HomeAssistant) -> None:
    """Test that the form pops up on loading."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert (result["errors"] == {}) or result["errors"] is None

    with (
        patch(
            "flexmeasures_client.FlexMeasuresClient.get_access_token",
        ) as mock_validate_input,
        patch(
            "custom_components.flexmeasures_hacs.async_setup_entry",
            return_value=True,
        ) as mock_setup_entry,
    ):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            CONFIG,
        )
        await hass.async_block_till_done()

        assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result2["title"] == "FlexMeasures"

        defaults = schema_defaults(SCHEMA)

        for key, val in result2["options"].items():
            if key in CONFIG:
                assert val == CONFIG[key]
            else:
                assert val == defaults[key]

        mock_setup_entry.assert_called_once()
        mock_validate_input.assert_called_once()


async def test_no_hardcoded_sensor_ids_as_defaults() -> None:
    """The schemas must not default to the sensor ids of somebody's server.

    Up to v0.3.9 the config flow defaulted to one pilot's FlexMeasures URL and
    to the asset and sensor ids on that server, so a fresh install silently
    pointed at somebody else's asset.
    """
    assert schema_defaults(S2_SCHEMA) == {}

    defaults = schema_defaults(SCHEMA)
    assert set(defaults) == {"schedule_duration", "soc_unit"}
    assert "seita.energy" not in str(defaults)


async def test_migration(hass: HomeAssistant) -> None:
    """Test migrating v1 config to the current version, moving S2_CONFIG into an s2 section."""

    # Simulate an old entry with CONFIG in data and some options
    old_entry = MockConfigEntry(
        version=1,
        minor_version=1,
        domain="flexmeasures_hacs",
        title="FlexMeasures",
        data=CONFIG,  # Old config data
        options=CONFIG | S2_CONFIG,  # Simulating missing S2_CONFIG in options
        source="user",
    )
    old_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(old_entry.entry_id)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries("flexmeasures_hacs")

    assert len(entries) == 1
    assert entries[0].version == CURRENT_VERSION
    assert "s2" in entries[0].data
    assert all(S2_CONFIG[k] == v for (k, v) in entries[0].data["s2"].items())


async def test_migration_v2_renames_the_misspelled_leakage_key(
    hass: HomeAssistant,
) -> None:
    """Test migrating a v2 entry: rename the misspelled leakage key.

    v2 entries were created by releases up to v0.3.7, whose S2 section used
    leakage_beaviour_sensor_id (sic), which client versions >=0.8 reject.
    """
    old_s2 = {
        k: v
        for k, v in S2_CONFIG.items()
        if k not in ("asset_id", "consumption_sensor_id", "leakage_behaviour_sensor_id")
    }
    old_s2["leakage_beaviour_sensor_id"] = 99
    old_entry = MockConfigEntry(
        version=2,
        minor_version=1,
        domain="flexmeasures_hacs",
        title="FlexMeasures",
        data=CONFIG | {"s2": old_s2},
        options={"s2": {"leakage_beaviour_sensor_id": 99}},
        source="user",
    )
    old_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(old_entry.entry_id)
    await hass.async_block_till_done()

    entries = hass.config_entries.async_entries("flexmeasures_hacs")

    assert len(entries) == 1
    assert entries[0].version == CURRENT_VERSION
    s2 = entries[0].data["s2"]
    # The configured value survives under the corrected key
    assert "leakage_beaviour_sensor_id" not in s2
    assert s2["leakage_behaviour_sensor_id"] == 99
    assert entries[0].options["s2"] == {"leakage_behaviour_sensor_id": 99}
    # Pre-existing values are preserved
    assert s2["soc_minima_sensor_id"] == S2_CONFIG["soc_minima_sensor_id"]
    # Fields that did not exist in v2 stay unset: they identify entities on the
    # user's own FlexMeasures server, so there is nothing sensible to fill in.
    assert s2.get("asset_id") is None
