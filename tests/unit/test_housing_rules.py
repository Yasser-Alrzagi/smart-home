"""Pure D4 derivation rules, no database required."""

import pytest

from app.models.enums import RoomStatus
from app.services.housing import status_for


def test_status_for_detects_empty_room():
    assert status_for(0, 1) == RoomStatus.available
    assert status_for(0, 4) == RoomStatus.available


def test_status_for_partial_occupancy_requires_capacity_above_one():
    assert status_for(1, 2) == RoomStatus.partially_occupied
    assert status_for(2, 4) == RoomStatus.partially_occupied


def test_status_for_full_occupancy():
    assert status_for(1, 1) == RoomStatus.fully_occupied
    assert status_for(4, 4) == RoomStatus.fully_occupied
    assert status_for(5, 4) == RoomStatus.fully_occupied  # defensive bound


@pytest.mark.parametrize(
    ("occupancy", "capacity", "expected"),
    [
        # Single-occupancy rooms never report partially occupied.
        (1, 1, RoomStatus.fully_occupied),
        (0, 1, RoomStatus.available),
        (2, 2, RoomStatus.fully_occupied),
        (1, 3, RoomStatus.partially_occupied),
    ],
)
def test_status_for_table(occupancy, capacity, expected):
    assert status_for(occupancy, capacity) == expected
