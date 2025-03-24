"""S2 Control types for the CEM."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass
class FRBC_Config:
    """Dataclass for FRBC configuration."""

    soc_minima_sensor_id: int
    soc_maxima_sensor_id: int

    consumption_sensor_id: int
    production_sensor_id: int

    active_actuador_id_sensor_id: int

    fill_level_sensor_id: int
    fill_rate_sensor_id: int

    usage_forecast_sensor_id: int

    thp_fill_rate_sensor_id: int
    thp_efficiency_sensor_id: int

    nes_fill_rate_sensor_id: int
    nes_efficiency_sensor_id: int

    rm_discharge_sensor_id: int

    schedule_duration: timedelta
