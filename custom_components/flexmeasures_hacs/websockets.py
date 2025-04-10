"""View to accept incoming websocket connection."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import logging
from typing import Any, Final

import aiohttp
from aiohttp import web
from flexmeasures_client.s2.cem import CEM
from flexmeasures_client.s2.control_types.FRBC.frbc_tunes import (
    FillRateBasedControlTUNES,
)
from flexmeasures_client.s2.utils import get_unique_id
from s2python.common import EnergyManagementRole, Handshake, ControlType

from homeassistant.components.http import HomeAssistantView
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, WS_VIEW_NAME, WS_VIEW_URI
from .control_types import FRBC_Config

_WS_LOGGER: Final = logging.getLogger(f"{__name__}.connection")


class WebsocketAPIView(HomeAssistantView):
    """View to serve a websockets endpoint."""

    name: str = WS_VIEW_NAME
    url: str = WS_VIEW_URI
    requires_auth: bool = False

    def __init__(self, entry: ConfigEntry) -> None:
        """Initialize websocket view."""
        super().__init__()
        self.entry = entry

    async def get(self, request: web.Request) -> web.WebSocketResponse:
        """Handle an incoming websocket connection."""

        return await WebSocketHandler(
            request.app["hass"], self.entry, request
        ).async_handle()


class WebSocketAdapter(logging.LoggerAdapter):
    """Add connection id to websocket messages."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Add connid to websocket log messages."""
        if not self.extra or "connid" not in self.extra:
            return msg, kwargs
        return f'[{self.extra["connid"]}] {msg}', kwargs


class WebSocketHandler:
    """Handle an active websocket client connection."""

    cem: CEM

    def __init__(
        self, hass: HomeAssistant, entry: ConfigEntry, request: web.Request
    ) -> None:
        """Initialize an active connection."""
        self.hass = hass
        self.request = request
        self.entry = entry
        self.wsock = web.WebSocketResponse(heartbeat=None)

        self.cem = CEM(
            fm_client=hass.data[DOMAIN][entry.entry_id]["fm_client"],
            default_control_type=ControlType.FILL_RATE_BASED_CONTROL,
        )
        frbc_data: FRBC_Config = hass.data[DOMAIN][entry.entry_id]["frbc_config"]
        frbc = FillRateBasedControlTUNES(**asdict(frbc_data))
        hass.data[DOMAIN][entry.entry_id]["cem"] = self.cem
        self.cem.register_control_type(frbc)

        self._logger = WebSocketAdapter(_WS_LOGGER, {"connid": id(self)})

        self._logger.debug("new websockets connection")

    async def _websocket_producer(self):
        """Send the messages available at the `cem` queue."""
        cem = self.cem

        while not cem.is_closed():
            message = await cem.get_message()

            self._logger.debug(message)

            try:
                await self.wsock.send_json(message)
            except ConnectionResetError:
                await cem.close()

    async def _websocket_consumer(self):
        """Process incoming messages."""
        cem = self.cem

        handshake_message = Handshake(
            message_id=get_unique_id(),
            role=EnergyManagementRole.CEM,
            supported_protocol_versions=[cem.__version__],
        )
        await cem.send_message(handshake_message)
        try:
            async for msg in self.wsock:
                message = msg.json()

                self._logger.debug(message)
                self._logger.debug(msg.type)

                if msg.type == aiohttp.WSMsgType.TEXT:
                    if msg.data == "close":
                        await cem.close()
                        await self.wsock.close()
                    else:
                        await cem.handle_message(message)

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    await cem.close()
        except Exception:  # pylint: disable=broad-exception-caught
            self.entry.async_start_reauth(self.hass)
        finally:
            await cem.close()

    async def async_handle(self) -> web.WebSocketResponse:
        """Handle a websocket response."""

        request = self.request
        wsock = self.wsock

        try:
            await wsock.prepare(request)

            # create "parallel" tasks for the message producer and consumer
            await asyncio.gather(
                self._websocket_consumer(),
                self._websocket_producer(),
            )

        except ConnectionResetError:
            await self.cem.close()
            self.entry.async_start_reauth(self.hass)

        return wsock
