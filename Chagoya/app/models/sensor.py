from dataclasses import dataclass
from datetime import datetime

from app.models.enums import SensorType, SensorStatus

@dataclass
class Sensor:
    sensor_id: str
    zone_id: str
    sensor_type: SensorType
    position_x: int
    position_y: int
    status: SensorStatus = SensorStatus.ACTIVE

@dataclass
class SensorReading:
    sensor_id: str
    zone_id: str
    sensor_type: SensorType
    timestamp: datetime
    temperature: float
    smoke: float
    co: float
    fire_detected: bool
    fire_intensity: float
    occupancy: int