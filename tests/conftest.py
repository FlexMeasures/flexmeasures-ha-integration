"""Fixtures for websocket tests."""
from collections.abc import Coroutine, Generator
from typing import Any, cast

import pytest

from homeassistant.components.flexmeasures.const import DOMAIN, WS_VIEW_URI
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component

from tests.common import MockConfigEntry
from tests.typing import (
    ClientSessionGenerator,
    MockHAClientWebSocket,
    WebSocketGenerator,
)


@pytest.fixture
async def setup_fm_integration(hass: HomeAssistant):
    """FlexMeasures integration setup."""

    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
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
        },
        unique_id=1212121,
        state=ConfigEntryState.NOT_LOADED,
    )

    entry.add_to_hass(hass)
    assert await async_setup_component(hass, DOMAIN, {})
    await hass.async_block_till_done()

    return entry


@pytest.fixture
def fm_ws_client(
    aiohttp_client: ClientSessionGenerator,
    hass: HomeAssistant,
    socket_enabled: None,
) -> WebSocketGenerator:
    """Websocket client fixture connected to websocket server."""

    async def create_client(hass: HomeAssistant = hass) -> MockHAClientWebSocket:
        """Create a websocket client."""

        client = await aiohttp_client(hass.http.app)
        websocket = await client.ws_connect(WS_VIEW_URI)

        def _get_next_id() -> Generator[int, None, None]:
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
