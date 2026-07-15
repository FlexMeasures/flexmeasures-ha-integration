"""Definition of the sensors of the FlexMeasures integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import UnitOfPower
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCHEDULE_ENTITY, signal_update_schedule
from .models import FlexMeasuresConfigEntry
from .services import get_from_option_or_config

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: FlexMeasuresConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor."""
    async_add_entities([FlexMeasuresScheduleSensor(entry)])


class FlexMeasuresScheduleSensor(SensorEntity):
    """Sensor to store the schedule created by FlexMeasures."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
    _attr_has_entity_name = True
    _attr_translation_key = "schedule"
    _attr_should_poll = False

    def __init__(self, entry: FlexMeasuresConfigEntry) -> None:
        """Sensor to store the schedule created by FlexMeasures."""
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{SCHEDULE_ENTITY}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer="FlexMeasures",
            name=entry.title,
            configuration_url=get_from_option_or_config("url", entry),
        )

    @property
    def native_value(self) -> float:
        """Average power."""
        commands = self._entry.runtime_data.schedule_state.schedule
        if not commands:
            return 0
        return sum(command["value"] for command in commands) / len(commands)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return default attributes for the FlexMeasures Schedule sensor."""
        return self._entry.runtime_data.schedule_state.as_dict()

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                signal_update_schedule(self._entry.entry_id),
                self._update_callback,
            )
        )

    @callback
    def _update_callback(self) -> None:
        """Update the state."""
        self.async_write_ha_state()
