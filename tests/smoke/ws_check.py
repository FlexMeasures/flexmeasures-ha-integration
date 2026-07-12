"""Connect to the integration's S2 websocket endpoint and await the CEM Handshake.

Receiving the Handshake proves, end to end inside a real Home Assistant:
- the manifest requirements were pip-installed by HA (the failure mode that
  broke v0.3.7 on real installs while in-process tests stayed green),
- the config entry migrated and set up,
- the websocket view is registered and the CEM started.

Usage: python3 ws_check.py [base_url]   (default http://localhost:8123)
"""

import asyncio
import json
import sys

import aiohttp

WS_PATH = "/api/websocket_custom"
TIMEOUT = 300  # seconds; includes HA pip-installing the manifest requirements
RETRY_INTERVAL = 5


async def try_handshake(base_url: str) -> bool:
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(base_url + WS_PATH) as ws:
            msg = await ws.receive(timeout=30)
            if msg.type != aiohttp.WSMsgType.TEXT:
                print(f"Unexpected websocket message type: {msg.type}")
                return False
            handshake = json.loads(msg.data)
            print(f"Received: {handshake}")
            assert handshake["message_type"] == "Handshake", handshake
            assert handshake["role"] == "CEM", handshake
            return True


async def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8123"
    deadline = asyncio.get_event_loop().time() + TIMEOUT
    last_error: Exception | None = None
    while asyncio.get_event_loop().time() < deadline:
        try:
            if await try_handshake(base_url):
                print("Smoke test OK: CEM Handshake received.")
                return 0
        except (aiohttp.ClientError, asyncio.TimeoutError, AssertionError) as exc:
            last_error = exc
        await asyncio.sleep(RETRY_INTERVAL)
    print(f"Smoke test FAILED: no CEM Handshake within {TIMEOUT}s: {last_error!r}")
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
