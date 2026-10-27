"""Request-date presentation scopes; never changes episode identity or clocks."""
from datetime import date

CUTOFF = '2026-10-01'
PERIODS = ('recent', 'historical', 'undated', 'all')


def source_period(source):
    try:
        value = source.get('request_date')
        day = date.fromisoformat(value)
        if day.isoformat() != value or day.year < 1900:
            raise ValueError('Not an ISO request date')
        return 'recent' if value >= CUTOFF else 'historical'
    except (ValueError, TypeError):
        return 'undated'


def scoped(case, period):
    if period not in PERIODS:
        raise ValueError('Periodo de seguimiento no valido.')
    sources = case.get('sources') or [{}]
    chosen = sources if period == 'all' else [s for s in sources if source_period(s) == period]
    return {**case, 'sources': chosen, 'rows': len(chosen)} if chosen else None


def newest(case):
    return max((s['request_date'] for s in case.get('sources', [])
                if source_period(s) != 'undated'), default='')


def cases(snapshot, period):
    items = [item for case in snapshot['cases'] if (item := scoped(case, period))]
    return sorted(items, key=lambda item: (newest(item), item.get('key', '')), reverse=True)


def eligible_keys(snapshot):
    # Undated cases remain explicitly visible, never silently dropped by a date filter.
    return {case['key'] for period in ('recent', 'undated') for case in cases(snapshot, period)}


def sql_scope(period):
    """Parameterized SQLite JSON predicates, applied before ordering/pagination."""
    if period not in PERIODS:
        raise ValueError('Periodo de seguimiento no valido.')
    value = "json_extract(source.value,'$.request_date')"
    valid = f"(length({value})=10 AND {value}>='1900-01-01' AND date({value},'+0 days')={value})"
    predicate, params = {
        'all': ('1', []),
        'recent': (f'{valid} AND {value}>=?', [CUTOFF]),
        'historical': (f'{valid} AND {value}<?', [CUTOFF]),
        'undated': (f'NOT COALESCE({valid},0)', []),
    }[period]
    sources = "json_each(payload,'$.sources') AS source"
    exists = f'EXISTS(SELECT 1 FROM {sources} WHERE {predicate})'
    if period == 'undated':
        exists = f"(COALESCE(json_array_length(payload,'$.sources'),0)=0 OR {exists})"
    latest = f'(SELECT MAX(CASE WHEN {valid} AND ({predicate}) THEN {value} END) FROM {sources})'
    return exists, latest, params
