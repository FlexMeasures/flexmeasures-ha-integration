"""Persistent storage for the S2 CEM, surviving Home Assistant restarts."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN

STORAGE_VERSION = 1
LEGACY_STORAGE_KEY = f"{DOMAIN}_datastore"

SAVE_DELAY = 5.0


def storage_key(entry_id: str) -> str:
    """Return the storage key holding the datastore of one config entry."""
    return f"{DOMAIN}_{entry_id}_datastore"


class PersistentDatastore(dict):
    """A dict that persists itself, so the CEM keeps its state across restarts.

    Writes are debounced: the CEM mutates the datastore per incoming S2 message,
    and we do not want a disk write for each of them.
    """

    def __init__(
        self, hass: HomeAssistant, key: str, save_delay: float = SAVE_DELAY
    ) -> None:
        """Initialize the datastore, backed by the store under the given key."""
        super().__init__()
        self.hass = hass
        self._store: Store = Store(hass, version=STORAGE_VERSION, key=key)
        self._save_delay = save_delay
        self._initialized = False

    async def async_load(self) -> None:
        """Load the persisted contents into this dict."""
        data = await self._store.async_load() or {}
        self.clear()
        self.update(data)
        self._initialized = True

    async def async_save(self) -> None:
        """Persist the current contents immediately."""
        if not self._initialized:
            raise RuntimeError("Datastore not loaded yet")
        await self._store.async_save(dict(self))

    def _data_to_save(self) -> dict[str, Any]:
        return dict(self)

    def _schedule_save(self) -> None:
        if not self._initialized:
            return
        # The CEM may mutate the datastore from another thread's event loop, so
        # hand the (loop-bound) delayed save back to Home Assistant's own loop.
        self.hass.loop.call_soon_threadsafe(
            self._store.async_delay_save, self._data_to_save, self._save_delay
        )

    def __setitem__(self, key: Any, value: Any) -> None:
        """Set a key and schedule a save."""
        super().__setitem__(key, value)
        self._schedule_save()

    def __delitem__(self, key: Any) -> None:
        """Delete a key and schedule a save."""
        super().__delitem__(key)
        self._schedule_save()
