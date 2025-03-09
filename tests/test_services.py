"""Test FlexMeasures integration services."""

from datetime import datetime
from unittest.mock import patch

import pytest
from s2python.common import ControlType

from custom_components.flexmeasures_hacs.const import (
    DOMAIN,
    RESOLUTION,
    SERVICE_CHANGE_CONTROL_TYPE,
)
from custom_components.flexmeasures_hacs.services import time_ceil
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util
from homeassistant.util.dt import parse_duration


@pytest.mark.skip(
    reason="This test passed only when the test `test_load_unload_config_entry` does not run before."
)
async def test_change_control_type_service(
    hass: HomeAssistant, fm_websocket_client
) -> None:
    """Test that the method activate_control_type is called when calling the service active_control_type."""

    with patch(
        "flexmeasures_client.s2.cem.CEM.activate_control_type"
    ) as activate_control_type:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_CHANGE_CONTROL_TYPE,
            service_data={"control_type": "NO_SELECTION"},
            blocking=True,
        )
        await hass.async_block_till_done()

        activate_control_type.assert_awaited_once_with(
            control_type=ControlType.NO_SELECTION
        )


async def test_trigger_and_get_schedule(
    hass: HomeAssistant, setup_fm_integration
) -> None:
    """Test that the method trigger_and_get_schedule is awaited when calling the service trigger_and_get_schedule."""
    with patch(
        "flexmeasures_client.client.FlexMeasuresClient.trigger_and_get_schedule",
        return_value={"values": [0.5, 0.41492, -0.0, -0.0], "unit": "MW"},
    ) as mocked_FlexmeasuresClient:
        await hass.services.async_call(
            DOMAIN,
            "trigger_and_get_schedule",
            service_data={"soc_at_start": 10},
            blocking=True,
        )
        tzinfo = dt_util.get_time_zone(hass.config.time_zone)
        mocked_FlexmeasuresClient.assert_awaited_with(
            sensor_id=1,
            start=time_ceil(datetime.now(tz=tzinfo), parse_duration(RESOLUTION)),
            duration="PT24H",
            flex_model={
                "soc-unit": "kWh",
                "soc-at-start": 10,
                "soc-max": 0.001,
                "soc-min": 0.0,
            },
            flex_context={"consumption-price-sensor": 2, "production-price-sensor": 2},
        )


async def test_post_measurements(hass: HomeAssistant, setup_fm_integration) -> None:
    """Test that the method post measurements is called when calling the service post_measurements."""

    with patch(
        "flexmeasures_client.client.FlexMeasuresClient.post_measurements",
        return_value=None,
    ) as mocked_FlexmeasuresClient:
        await hass.services.async_call(
            DOMAIN,
            "post_measurements",
            service_data={
                "sensor_id": 1,
                "start": None,
                "duration": "PT24H",
                "values": [1, 1, 1, 3],
                "unit": "kWh",
                "prior": None,
            },
            blocking=True,
        )
        mocked_FlexmeasuresClient.assert_called_with(
            sensor_id=1,
            start=None,
            duration="PT24H",
            values=[1, 1, 1, 3],
            unit="kWh",
            prior=None,
        )


async def test_get_measurements(hass: HomeAssistant, setup_fm_integration) -> None:
    """Test that the method get measurements is called when calling the service get_measurements."""
    tzinfo = dt_util.get_time_zone(hass.config.time_zone)

    get_sensor_data_response = {
        "values": [2.15, 3, 2],
        "start": "2015-06-02T10:00:00+00:00",
        "duration": "PT45M",
        "unit": "MW",
    }

    with patch(
        "flexmeasures_client.client.FlexMeasuresClient.get_sensor_data",
        return_value=get_sensor_data_response,
    ) as mocked_FlexmeasuresClient:
        service_call_response = await hass.services.async_call(
            DOMAIN,
            "get_measurements",
            service_data={
                "sensor_id": 1,
                "start": datetime(2025, 1, 1, tzinfo=tzinfo),
                "duration": "PT24H",
                "unit": "kWh",
                "resolution": "PT15M",
            },
            blocking=True,
            return_response=True,
        )

        # check that the service response is equal to FlexMeasures response
        assert service_call_response == get_sensor_data_response

        # check that the service is called with the right data
        mocked_FlexmeasuresClient.assert_called_with(
            sensor_id=1,
            start=datetime(2025, 1, 1, tzinfo=tzinfo),
            duration="PT24H",
            unit="kWh",
            resolution="PT15M",
        )
