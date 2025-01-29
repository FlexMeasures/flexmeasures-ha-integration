"""Test the FlexMeasures config flow."""

from unittest.mock import patch

from homeassistant import config_entries, data_entry_flow
from custom_components.flexmeasures_hacs.config_flow import SCHEMA
from custom_components.flexmeasures_hacs.const import DOMAIN
from homeassistant.core import HomeAssistant

CONFIG = {
    "username": "admin@admin.com",
    "password": "admin",
    "url": "http://localhost:5000",
    "power_sensor": 1,
    "soc_sensor": 3,
    "rm_discharge_sensor_id": 4,
    "schedule_duration": "PT24H",
    "consumption_price_sensor": 2,
    "production_price_sensor": 2,
    "soc_unit": "kWh",
    "soc_min": 0.0,
    "soc_max": 0.001,
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
