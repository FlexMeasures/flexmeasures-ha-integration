"""Test the FlexMeasures config flow."""

from unittest.mock import patch
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.flexmeasures_hacs.config_flow import SCHEMA
from custom_components.flexmeasures_hacs.const import DOMAIN

from homeassistant import config_entries, data_entry_flow
from homeassistant.core import HomeAssistant


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
}


async def test_form(hass: HomeAssistant) -> None:
    """Test that the form pops up on loading."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["type"] == data_entry_flow.FlowResultType.FORM
    assert (result["errors"] == {}) or result["errors"] is None

    with patch(
        "flexmeasures_client.FlexMeasuresClient.get_access_token",
    ) as mock_validate_input, patch(
        "custom_components.flexmeasures_hacs.async_setup_entry",
        return_value=True,
    ) as mock_setup_entry:
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            CONFIG,
        )
        await hass.async_block_till_done()

        assert result2["type"] == data_entry_flow.FlowResultType.CREATE_ENTRY
        assert result2["title"] == "FlexMeasures"

        fields = {str(key): key for key in SCHEMA.schema}

        for key, val in result2["options"].items():
            if key in CONFIG:
                assert val == CONFIG[key]
            else:
                assert val == fields[key].default()

        mock_setup_entry.assert_called_once()
        mock_validate_input.assert_called_once()


async def test_migration(hass: HomeAssistant) -> None:
    """Test migrating v1 config to v1 config to include S2_CONFIG in options."""

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
    assert entries[0].version == 2
    assert "s2" in entries[0].data
    assert all(S2_CONFIG[k] == v for (k, v) in entries[0].data["s2"].items())
