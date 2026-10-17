from dataclasses import dataclass

from app.models.enums import RiskLevel, ZoneType

@dataclass
class ZoneState:
    zone_id: str
    zone_type: ZoneType
    temperature: float = 20.0
    smoke: float = 0.0
    co: float = 0.0
    fire_intensity: float = 0.0
    occupancy: int = 0
    hazardous_materials: bool = False
    risk_level: RiskLevel = RiskLevel.SAFE

