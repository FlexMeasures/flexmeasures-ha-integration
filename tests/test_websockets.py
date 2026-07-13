"""Test websockets module of FlexMeasures integration."""

# pytest ./tests/components/flexmeasures/ --cov=homeassistant.components.flexmeasures --cov-report term-missing -vv

from http import HTTPStatus
import logging

from aiohttp import WSServerHandshakeError
from homeassistant.core import HomeAssistant
import pytest


async def test_websocket_connection_does_not_log_credentials(
    hass: HomeAssistant,
    setup_fm_integration,
    fm_ws_client,
    caplog: pytest.LogCaptureFixture,
):
    """Opening a websocket connection must not leak the FlexMeasures credentials.

    Up to v0.3.8, the handler logged the whole FlexMeasuresClient at WARNING
    level. It is a dataclass, so its repr contains the password in plain text,
    which ended up in the Home Assistant log on every connection.
    """
    password = setup_fm_integration.data["password"]
    with caplog.at_level(logging.DEBUG):
        await fm_ws_client(hass)
        await hass.async_block_till_done()

    assert password not in caplog.text
    assert setup_fm_integration.data["username"] not in caplog.text


async def test_websocket_connection_does_not_log_credentials(
    hass: HomeAssistant,
    setup_fm_integration,
    fm_ws_client,
    caplog: pytest.LogCaptureFixture,
):
    """Opening a websocket connection must not leak the FlexMeasures credentials.

    Up to v0.3.8, the handler logged the whole FlexMeasuresClient at WARNING
    level. It is a dataclass, so its repr contains the password in plain text,
    which ended up in the Home Assistant log on every connection.
    """
    password = setup_fm_integration.data["password"]
    with caplog.at_level(logging.DEBUG):
        await fm_ws_client(hass)
        await hass.async_block_till_done()

    assert password not in caplog.text
    assert setup_fm_integration.data["username"] not in caplog.text


async def test_cem_processes_websocket_msg(
    hass: HomeAssistant, setup_fm_integration, fm_websocket_client
):
    """
    Test that the CEM gets a S2 message sent via WebSockets through HomeAssistant
    """
    message = {
        "message_id": "2bdec96b-be3b-4ba9-afa0-c4a0632cced3",
        "role": "RM",
        "supported_protocol_versions": ["0.1.0"],
        "message_type": "Handshake",
    }
    await fm_websocket_client.send_json(message)
    msg = await fm_websocket_client.receive_json()

    assert msg["message_type"] == "Handshake"
    assert msg["role"] == "CEM"


async def test_websocket_targets_the_requested_entry(
    hass: HomeAssistant, setup_fm_integration, setup_second_fm_integration, fm_ws_client
) -> None:
    """A Resource Manager picks its FlexMeasures server by entry id in the path."""
    second = setup_second_fm_integration

    # With two entries loaded, the bare endpoint cannot know which one to use.
    with pytest.raises(WSServerHandshakeError) as err:
        await fm_ws_client(hass)
    assert err.value.status == HTTPStatus.BAD_REQUEST

    websocket = await fm_ws_client(hass, entry_id=second.entry_id)
    msg = await websocket.receive_json()

    assert msg["message_type"] == "Handshake"
    assert msg["role"] == "CEM"
    assert second.runtime_data.cem is not None
    assert setup_fm_integration.runtime_data.cem is None
