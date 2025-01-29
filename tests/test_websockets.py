"""Test websockets module of FlexMeasures integration."""
# pytest ./tests/components/flexmeasures/ --cov=homeassistant.components.flexmeasures --cov-report term-missing -vv


from homeassistant.core import HomeAssistant


async def test_producer_consumer(
    hass: HomeAssistant, setup_fm_integration, fm_websocket_client
):
    """Test websocket connection."""
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
