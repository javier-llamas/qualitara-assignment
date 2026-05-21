from datetime import UTC, datetime

import pytest

from app.anomalies import TelemetrySample, detect
from app.config import settings
from app.models import IncidentType, VehicleStatus

NOW = datetime(2026, 5, 21, 12, 0, 0, tzinfo=UTC)


def sample(**overrides: object) -> TelemetrySample:
    defaults: dict[str, object] = dict(
        vehicle_id="v-1",
        timestamp=NOW,
        battery_pct=80,
        speed_mps=1.0,
        status=VehicleStatus.MOVING,
        error_codes=[],
    )
    defaults.update(overrides)
    return TelemetrySample(**defaults)  # type: ignore[arg-type]


def types(drafts: list) -> set[IncidentType]:
    return {d.incident_type for d in drafts}


def test_no_incidents_for_clean_sample() -> None:
    assert detect(sample(), previous=None) == []


@pytest.mark.parametrize(
    "speed,expected",
    [
        (settings.speed_limit_mps, False),  # equal to limit is not over
        (settings.speed_limit_mps + 0.01, True),
        (settings.speed_limit_mps - 0.01, False),
    ],
)
def test_over_speed_boundary(speed: float, expected: bool) -> None:
    drafts = detect(sample(speed_mps=speed), previous=None)
    assert (IncidentType.OVER_SPEED_LIMIT in types(drafts)) is expected


@pytest.mark.parametrize(
    "battery,expected",
    [
        (settings.low_battery_pct, False),  # exactly at threshold is not low
        (settings.low_battery_pct - 1, True),
        (settings.low_battery_pct + 1, False),
    ],
)
def test_low_battery_boundary(battery: int, expected: bool) -> None:
    drafts = detect(sample(battery_pct=battery), previous=None)
    assert (IncidentType.LOW_BATTERY in types(drafts)) is expected


def test_movement_under_fault_fires_only_when_moving() -> None:
    moving = detect(sample(status=VehicleStatus.FAULT, speed_mps=0.5), previous=None)
    stopped = detect(sample(status=VehicleStatus.FAULT, speed_mps=0.0), previous=None)
    assert IncidentType.MOVEMENT_UNDER_FAULT in types(moving)
    assert IncidentType.MOVEMENT_UNDER_FAULT not in types(stopped)


def test_error_codes_present() -> None:
    drafts = detect(sample(error_codes=["E_TILT"]), previous=None)
    assert IncidentType.ERROR_CODE_PRESENT in types(drafts)


def test_no_error_codes_no_incident() -> None:
    drafts = detect(sample(error_codes=[]), previous=None)
    assert IncidentType.ERROR_CODE_PRESENT not in types(drafts)


@pytest.mark.parametrize(
    "prev_pct,curr_pct,expected",
    [
        (
            80,
            80 - settings.rapid_battery_drop_pct,
            False,
        ),  # equal to threshold is not "more than"
        (80, 80 - settings.rapid_battery_drop_pct - 1, True),
        (80, 79, False),
        (50, 60, False),  # increase, no drain
    ],
)
def test_rapid_battery_drain_boundary(
    prev_pct: int, curr_pct: int, expected: bool
) -> None:
    prev = sample(battery_pct=prev_pct)
    curr = sample(battery_pct=curr_pct)
    drafts = detect(curr, previous=prev)
    assert (IncidentType.RAPID_BATTERY_DRAIN in types(drafts)) is expected


def test_rapid_battery_drain_requires_previous() -> None:
    drafts = detect(sample(battery_pct=10), previous=None)
    # LOW_BATTERY will fire, but not RAPID_BATTERY_DRAIN without history
    assert IncidentType.RAPID_BATTERY_DRAIN not in types(drafts)


def test_multiple_incidents_in_one_event() -> None:
    prev = sample(battery_pct=80)
    curr = sample(
        battery_pct=5,
        speed_mps=10.0,
        status=VehicleStatus.FAULT,
        error_codes=["E_OVERHEAT"],
    )
    drafts = detect(curr, previous=prev)
    got = types(drafts)
    assert got == {
        IncidentType.OVER_SPEED_LIMIT,
        IncidentType.LOW_BATTERY,
        IncidentType.MOVEMENT_UNDER_FAULT,
        IncidentType.ERROR_CODE_PRESENT,
        IncidentType.RAPID_BATTERY_DRAIN,
    }
