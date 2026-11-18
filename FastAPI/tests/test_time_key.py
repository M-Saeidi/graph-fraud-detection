"""Time-key tests using calendar anchors and synthetic timestamps only."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from time_key import datetime_to_transaction_time_key


@pytest.mark.unit
@pytest.mark.parametrize("timestamp, day_number", [
    (datetime(2000, 1, 1), 2_451_545),
    (datetime(1970, 1, 1), 2_440_588),
])
def test_calendar_anchor_matches_integer_day_scale(timestamp, day_number):
    assert datetime_to_transaction_time_key(timestamp) == day_number * 86_400


@pytest.mark.unit
@pytest.mark.parametrize("tzinfo", [timezone.utc, timezone(timedelta(hours=5, minutes=30))])
def test_timezone_aware_timestamp_is_rejected(tzinfo):
    with pytest.raises(ValueError, match="must not include a timezone"):
        datetime_to_transaction_time_key(datetime(2000, 1, 1, tzinfo=tzinfo))


@pytest.mark.unit
@pytest.mark.parametrize("start", [
    datetime(2000, 2, 28, 23, 59, 59),
    datetime(2000, 2, 29, 23, 59, 59),
    datetime(1900, 2, 28, 23, 59, 59),
    datetime(2000, 12, 31, 23, 59, 59),
])
def test_one_second_step_across_calendar_boundaries(start):
    end = start + timedelta(seconds=1)
    assert datetime_to_transaction_time_key(end) - datetime_to_transaction_time_key(start) == 1


@pytest.mark.unit
def test_time_of_day_adds_seconds_since_midnight():
    midnight = datetime(2000, 1, 1)
    timestamp = midnight.replace(hour=6, minute=7, second=8)
    assert datetime_to_transaction_time_key(timestamp) - datetime_to_transaction_time_key(midnight) == 22_028


@pytest.mark.unit
def test_microseconds_are_discarded_for_backward_compatibility():
    timestamp = datetime(2000, 1, 1, 6, 7, 8)
    assert datetime_to_transaction_time_key(timestamp.replace(microsecond=999_999)) == datetime_to_transaction_time_key(timestamp)