import pytest

from app.models import RiskLevel, ZoneState, ZoneType


def test_create_zone_state():
    zone = ZoneState(
        zone_id="LAB_A1",
        zone_type=ZoneType.LAB,
    )

    assert zone.zone_id == "LAB_A1"
    assert zone.zone_type == ZoneType.LAB
    assert zone.risk_level == RiskLevel.SAFE


def test_invalid_smoke_value():
    with pytest.raises(ValueError):
        ZoneState(
            zone_id="LAB_A1",
            zone_type=ZoneType.LAB,
            smoke=1.5,
        )


def test_invalid_occupancy():
    with pytest.raises(ValueError):
        ZoneState(
            zone_id="LAB_A1",
            zone_type=ZoneType.LAB,
            occupancy=-1,
        )