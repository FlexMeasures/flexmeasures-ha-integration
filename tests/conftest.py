"""Fixtures for websocket tests."""

from collections.abc import Coroutine, Generator
from typing import Any, cast

from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import (
    ClientSessionGenerator,
    MockHAClientWebSocket,
    WebSocketGenerator,
)

from custom_components.flexmeasures_hacs.config_flow import ConfigFlowHandler
from custom_components.flexmeasures_hacs.const import DOMAIN, WS_VIEW_URI

CURRENT_VERSION = ConfigFlowHandler.VERSION


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    yield


S2_ENTRY_DATA = {
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

ENTRY_DATA = {
    "url": "http://localhost:5000",
    "username": "admin@admin.com",
    "password": "admin",
    "schedule_duration": "PT24H",
    "power_sensor": 1,
    "soc_sensor": 3,
    "rm_discharge_sensor": 4,
    "consumption_price_sensor": 2,
    "production_price_sensor": 2,
    "soc_unit": "kWh",
    "soc_min": 0.0,
    "soc_max": 0.001,
    "s2": S2_ENTRY_DATA,
}


def build_entry(**overrides) -> MockConfigEntry:
    """Build a config entry of the current version."""
    data = {**ENTRY_DATA, **overrides.pop("data", {})}
    return MockConfigEntry(
        domain=DOMAIN,
        version=CURRENT_VERSION,
        data=data,
        state=ConfigEntryState.NOT_LOADED,
        **overrides,
    )


@pytest.fixture
async def setup_fm_integration(hass: HomeAssistant):
    """FlexMeasures integration setup."""
    entry = build_entry(unique_id="1212121")

    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    return entry


@pytest.fixture
async def setup_second_fm_integration(hass: HomeAssistant, setup_fm_integration):
    """A second FlexMeasures server, configured alongside the first."""
    entry = build_entry(
        unique_id="3434343",
        title="FlexMeasures 2",
        data={"url": "http://localhost:5001", "power_sensor": 7},
    )

    entry.add_to_hass(hass)
    await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    return entry


@pytest.fixture
def fm_ws_client(
    aiohttp_client: ClientSessionGenerator,
    hass: HomeAssistant,
    socket_enabled: None,
) -> WebSocketGenerator:
    """Websocket client fixture connected to websocket server."""

    async def create_client(
        hass: HomeAssistant = hass, entry_id: str | None = None
    ) -> MockHAClientWebSocket:
        """Create a websocket client, optionally for a specific config entry."""

        client = await aiohttp_client(hass.http.app)
        url = WS_VIEW_URI if entry_id is None else f"{WS_VIEW_URI}/{entry_id}"
        websocket = await client.ws_connect(url)

        def _get_next_id() -> Generator[int]:
            i = 0
            while True:
                yield (i := i + 1)

        id_generator = _get_next_id()

        def _send_json_auto_id(data: dict[str, Any]) -> Coroutine[Any, Any, None]:
            data["id"] = next(id_generator)
            return websocket.send_json(data)

        # wrap in client
        wrapped_websocket = cast(MockHAClientWebSocket, websocket)
        wrapped_websocket.client = client
        wrapped_websocket.send_json_auto_id = _send_json_auto_id
        return wrapped_websocket

    return create_client


@pytest.fixture
async def fm_websocket_client(
    hass: HomeAssistant, setup_fm_integration, fm_ws_client: WebSocketGenerator
) -> MockHAClientWebSocket:
    """Create a websocket client."""
    return await fm_ws_client(hass)
