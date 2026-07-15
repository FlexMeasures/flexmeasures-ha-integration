"""View to accept incoming websocket connection."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import logging
from typing import Any, ClassVar, Final

import aiohttp
from aiohttp import web
from flexmeasures_client.s2.cem import CEM
from flexmeasures_client.s2.control_types.FRBC.frbc_tunes import (
    FillRateBasedControlTUNES,
)
from flexmeasures_client.s2.utils import get_unique_id
from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.http import KEY_HASS
from s2python.common import ControlType, EnergyManagementRole, Handshake

from .const import DOMAIN, WS_VIEW_NAME, WS_VIEW_URI
from .control_types import FRBC_Config
from .models import FlexMeasuresConfigEntry

_WS_LOGGER: Final = logging.getLogger(f"{__name__}.connection")

DATA_VIEW_REGISTERED: Final = f"{DOMAIN}_websocket_view_registered"


@callback
def async_register_websocket_view(hass: HomeAssistant) -> None:
    """Register the S2 websocket view, once for the whole integration.

    A view is registered on Home Assistant's HTTP app, not on a config entry,
    so it must not be registered again per entry. Resource Managers pick the
    config entry to talk to by connecting to /api/websocket_custom/<entry_id>;
    the bare /api/websocket_custom is served when only one entry is loaded.
    """
    if hass.data.get(DATA_VIEW_REGISTERED):
        return

    hass.http.register_view(WebsocketAPIView())
    hass.data[DATA_VIEW_REGISTERED] = True


class WebsocketAPIView(HomeAssistantView):
    """View to serve a websockets endpoint."""

    name: str = WS_VIEW_NAME
    url: str = WS_VIEW_URI
    extra_urls: ClassVar[list[str]] = [f"{WS_VIEW_URI}/{{entry_id}}"]
    requires_auth: bool = False

    async def get(
        self, request: web.Request, entry_id: str | None = None
    ) -> web.WebSocketResponse:
        """Handle an incoming websocket connection."""
        hass = request.app[KEY_HASS]
        entry = _async_resolve_entry(hass, entry_id)

        if entry.runtime_data.frbc_config.asset_id is None:
            # Better to say so than to run the S2 control path against sensor
            # ids that are not set (earlier versions silently fell back to the
            # ids of one pilot's FlexMeasures server).
            raise web.HTTPBadRequest(
                text=(
                    "The S2 section of the FlexMeasures configuration is incomplete: "
                    "set at least the asset_id, in Settings > Devices & services > "
                    "FlexMeasures > Configure."
                )
            )

        return await WebSocketHandler(hass, entry, request).async_handle()


@callback
def _async_resolve_entry(
    hass: HomeAssistant, entry_id: str | None
) -> FlexMeasuresConfigEntry:
    """Return the config entry a websocket connection is for."""
    entries = hass.config_entries.async_loaded_entries(DOMAIN)

    if entry_id is not None:
        for entry in entries:
            if entry.entry_id == entry_id:
                return entry
        raise web.HTTPNotFound(
            text=f"No loaded FlexMeasures configuration entry with entry_id {entry_id!r}."
        )

    if not entries:
        raise web.HTTPNotFound(text="No FlexMeasures configuration entry is loaded.")
    if len(entries) > 1:
        raise web.HTTPBadRequest(
            text=(
                "Several FlexMeasures configuration entries are loaded. "
                f"Connect to {WS_VIEW_URI}/<entry_id> to say which one to use."
            )
        )

    return entries[0]


class WebSocketAdapter(logging.LoggerAdapter):
    """Add connection id to websocket messages."""

    def process(self, msg: str, kwargs: Any) -> tuple[str, Any]:
        """Add connid to websocket log messages."""
        if not self.extra or "connid" not in self.extra:
            return msg, kwargs
        return f"[{self.extra['connid']}] {msg}", kwargs


class WebSocketHandler:
    """Handle an active websocket client connection."""

    cem: CEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: FlexMeasuresConfigEntry,
        request: web.Request,
    ) -> None:
        """Initialize an active connection."""
        self.hass = hass
        self.request = request
        self.entry = entry
        self.wsock = web.WebSocketResponse(heartbeat=None)

        self._logger = WebSocketAdapter(_WS_LOGGER, {"connid": id(self)})
        self._logger.debug("new websockets connection")

        runtime_data = entry.runtime_data
        frbc_data: FRBC_Config = runtime_data.frbc_config
        self._logger.info(
            "Resource in FRBC mode mapped to FlexMeasures asset %s.", frbc_data.asset_id
        )

        self.cem = CEM(
            fm_client=runtime_data.client,
            default_control_type=ControlType.FILL_RATE_BASED_CONTROL,
            logger=_WS_LOGGER,
            timers=runtime_data.timers,
            datastore=runtime_data.datastore,
            power_sensor_id={
                # todo: set up the other power sensors
                # "ELECTRIC.POWER.3_PHASE_SYMMETRIC": frbc_data.<id>,  # THP
                "ELECTRIC.POWER.L1": frbc_data.consumption_sensor_id,  # NES
                # "ELECTRIC.POWER.L2": frbc_data.<id>,
                # "ELECTRIC.POWER.L3": frbc_data.<id>,
            },
            timezone=hass.config.time_zone,
        )
        frbc = FillRateBasedControlTUNES(
            **asdict(frbc_data),
            timers=runtime_data.timers,
            datastore=runtime_data.datastore,
            timezone=hass.config.time_zone,
        )
        self.cem.register_control_type(frbc)
        runtime_data.cem = self.cem

    async def _websocket_producer(self):
        """Send the messages available at the `cem` queue."""
        cem = self.cem

        while not cem.is_closed():
            message = await cem.get_message()

            self._logger.debug(message)

            try:
                await self.wsock.send_json(message)
            except ConnectionResetError:
                self._logger.debug(
                    "Connection reset in _websocket_producer: closing CEM.."
                )
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
                        self._logger.debug("Msg.data == 'close': closing CEM..")
                        await cem.close()
                        await self.wsock.close()
                    else:
                        await cem.handle_message(message)

                elif msg.type == aiohttp.WSMsgType.ERROR:
                    self._logger.debug(
                        "Msg.type == aiohttp.WSMsgType.ERROR: closing CEM.."
                    )
                    await cem.close()
        except ConnectionError:
            # Only a failure to reach FlexMeasures says anything about our
            # credentials. Any other error here is a bug in handling the
            # message, and asking the user to re-authenticate would only
            # obscure it.
            self._logger.warning(
                "Cannot reach FlexMeasures; asking for re-authentication",
                exc_info=True,
            )
            self.entry.async_start_reauth(self.hass)
        except Exception:  # pylint: disable=broad-exception-caught
            self._logger.exception("Error while handling an incoming S2 message")
        finally:
            self._logger.debug("Finished _websocket_consumer: closing CEM..")
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
            self._logger.debug("Connection reset in async_handle: closing CEM..")
            await self.cem.close()

        return wsock
