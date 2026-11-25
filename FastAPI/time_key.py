"""Convert naive Gregorian timestamps to the existing integer time-key scale.

The scale uses a Julian-day-style integer multiplied by 86400, plus seconds
since midnight. It is not a Unix timestamp or an astronomical Julian date.
Timezone-aware input is rejected; microseconds are discarded. Keeping these
semantics explicit avoids silently shifting historical feature cutoffs.
"""

from __future__ import annotations

from datetime import datetime


def datetime_to_transaction_time_key(
    transaction_time: datetime,
) -> int:
    """Return the integer key without timezone conversion."""

    if (
        transaction_time.tzinfo is not None
        and transaction_time.utcoffset() is not None
    ):
        raise ValueError(
            "transactionTime must not include a timezone offset. "
            "Provide the timestamp using the same local/naive semantics "
            "as the historical transaction data."
        )

    year = transaction_time.year
    month = transaction_time.month
    day = transaction_time.day

    hour = transaction_time.hour
    minute = transaction_time.minute
    second = transaction_time.second

    month_adjustment = (
        14 - month
    ) // 12

    adjusted_year = (
        year
        + 4800
        - month_adjustment
    )

    adjusted_month = (
        month
        + 12 * month_adjustment
        - 3
    )

    day_number = (
        day
        + (
            (
                153
                * adjusted_month
                + 2
            )
            // 5
        )
        + 365
        * adjusted_year
        + adjusted_year
        // 4
        - adjusted_year
        // 100
        + adjusted_year
        // 400
        - 32045
    )

    return (
        day_number
        * 86400
        + hour
        * 3600
        + minute
        * 60
        + second
    )


def transaction_time_key_to_datetime(transaction_time_key: int) -> datetime:
    """Convert the integer day/seconds key back to a naive Gregorian time."""

    if type(transaction_time_key) is not int:
        raise TypeError("transaction_time_key must be an integer.")

    day_number, seconds_of_day = divmod(transaction_time_key, 86400)
    shifted_day = day_number + 32044
    century = (4 * shifted_day + 3) // 146097
    day_within_century = shifted_day - (146097 * century) // 4
    year_day = (4 * day_within_century + 3) // 1461
    day_within_year = day_within_century - (1461 * year_day) // 4
    month_index = (5 * day_within_year + 2) // 153
    day = day_within_year - (153 * month_index + 2) // 5 + 1
    month = month_index + 3 - 12 * (month_index // 10)
    year = 100 * century + year_day - 4800 + month_index // 10
    hour, seconds_of_hour = divmod(seconds_of_day, 3600)
    minute, second = divmod(seconds_of_hour, 60)
    return datetime(year, month, day, hour, minute, second)