from enum import Enum

class ZoneType(str, Enum):
    WALL = "WALL"
    HALLWAY = "HALLWAY"
    CLASSROOM = "CLASSROOM"
    LAB = "LAB"
    STAIR = "STAIR"
    PATIO = "PATIO"
    DOOR = "DOOR"
    EXIT = "EXIT"
    OUTSIDE = "OUTSIDE"
    BLOCKED = "BLOCKED"

class RiskLevel(str, Enum):
    SAFE = "SAFE"
    CAUTION = "CAUTION"
    DANGER = "DANGER"
    CRITICAL = "CRITICAL"

class SensorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"
    ERROR = "ERROR"

class SensorType(str, Enum):
    MULTI = "MULTI"
    TEMPERATURE = "TEMPERATURE"
    SMOKE = "SMOKE"
    CO = "CO"
    OCCUPANCY = "OCCUPANCY"