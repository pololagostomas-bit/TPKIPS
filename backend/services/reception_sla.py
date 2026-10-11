"""Continuous cargo SLA in Lima time, excluding Sundays and Peru holidays."""
import json
import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache

import holidays

LIMA = timezone(timedelta(hours=-5))


def local_stamp(value):
    try:
        stamp = datetime.fromisoformat(str(value).strip().replace('Z', '+00:00'))
        return stamp.astimezone(LIMA).replace(tzinfo=None) if stamp.tzinfo else stamp
    except (TypeError, ValueError, OverflowError):
        return None


@lru_cache(maxsize=32)
def _calendar(year, extra):
    calendar = holidays.Peru(years=year, observed=False, expand=False)
    dates = json.loads(extra)
    if not isinstance(dates, list) or any(not isinstance(day, str) for day in dates):
        raise ValueError('WMS_SLA_EXTRA_HOLIDAYS debe ser una lista JSON de fechas YYYY-MM-DD')
    for day in dates:
        stamp = datetime.strptime(day, '%Y-%m-%d').date()
        if stamp.isoformat() != day:
            raise ValueError('Feriado SLA invalido; usa YYYY-MM-DD')
        calendar[stamp] = 'Feriado adicional de empresa'
    return frozenset(calendar)


def counted_day(stamp):
    return stamp.weekday() != 6 and stamp.date() not in _calendar(
        stamp.year, os.getenv('WMS_SLA_EXTRA_HOLIDAYS', '[]'))


def elapsed_hours(start_value, end_value):
    start, end = local_stamp(start_value), local_stamp(end_value)
    if start is None or end is None:
        return None
    seconds = 0.0
    while start < end:
        midnight = start.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        stop = min(end, midnight)
        if counted_day(start):
            seconds += (stop-start).total_seconds()
        start = stop
    return seconds / 3600


def deadline(start_value, hours):
    cursor = local_stamp(start_value)
    if cursor is None:
        return None
    remaining = timedelta(hours=hours)
    while remaining > timedelta(0):
        midnight = cursor.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        if counted_day(cursor):
            available = midnight-cursor
            if remaining <= available:
                return (cursor+remaining).isoformat(timespec='seconds')
            remaining -= available
        cursor = midnight
    return cursor.isoformat(timespec='seconds')
