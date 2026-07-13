"""Runtime data of a FlexMeasures config entry."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from flexmeasures_client import FlexMeasuresClient
from flexmeasures_client.s2.cem import CEM
from homeassistant.config_entries import ConfigEntry

from .control_types import FRBC_Config
from .datastore import PersistentDatastore


@dataclass
class ScheduleState:
    """The latest schedule fetched from FlexMeasures, as shown by the sensor."""

    schedule: list[dict[str, Any]] = field(default_factory=list)
    start: datetime | None = None
    duration: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the state as the sensor's extra attributes."""
        return {
            "schedule": self.schedule,
            "start": self.start,
            "duration": self.duration,
        }


@dataclass
class FlexMeasuresRuntimeData:
    """Everything one config entry needs at runtime.

    Kept on the config entry itself (entry.runtime_data) rather than in a
    global hass.data[DOMAIN], so that several FlexMeasures servers can be
    configured side by side.
    """

    client: FlexMeasuresClient
    frbc_config: FRBC_Config
    datastore: PersistentDatastore
    timers: dict[str, datetime] = field(default_factory=dict)
    schedule_state: ScheduleState = field(default_factory=ScheduleState)
    cem: CEM | None = None


type FlexMeasuresConfigEntry = ConfigEntry[FlexMeasuresRuntimeData]
