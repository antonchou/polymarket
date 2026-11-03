"""Conservative extraction plus explicit, hash-bound human review.
No NLP confidence score grants approval. Original metadata is always preserved.
"""
import json
import re
from datetime import date
from zoneinfo import ZoneInfo
from .store import digest, stamp, now


def parse_market(m):
    text = (m.get('question', '') + '\n' + m.get('description', ''))
    description = m.get('description', '')
    relevant = bool(re.search(r'tsa\.gov/travel/passenger-volumes', description, re.I)
                    and re.search(r'checkpoint throughput', description, re.I))
    path = bool(re.search(r'any (?:one )?day|any date|at least one day', text, re.I))
    dates = re.findall(r'\b20\d{2}-\d{2}-\d{2}\b', text)
    return dict(market_id=str(m['id']), event_ids=[str(e['id']) for e in m.get('events', [])],
        condition_id=m.get('conditionId'), tokens=m.get('clobTokenIds'),
        original_rules=description, rules_version=digest({k:m.get(k) for k in ('question','description','resolutionSource','outcomes','clobTokenIds')}), relevant=relevant,
        status='unsupported_path' if relevant and path else 'pending_review' if relevant else 'irrelevant',
        kind='cumulative' if re.search(r'total|sum|cumulative', text, re.I) else 'daily',
        extracted_dates=dates, timezone=None, deadline=None, start=None, end=None,
        lower=None, upper=None, lower_inclusive=None, upper_inclusive=None,
        rounding=None, source=m.get('resolutionSource'), revision_policy=None,
        missing_policy=None, cancellation_policy=None, other_policy=None,
        open=bool(m.get('active') and not m.get('closed') and m.get('acceptingOrders')),
        fees_enabled=m.get('feesEnabled'), fee_parameters=m.get('feeSchedule'),
        minimum_order=m.get('orderMinSize'), tick_size=m.get('orderPriceMinTickSize'), metadata=m, metadata_fetched_at=now())


REQUIRED = ('start', 'end', 'timezone', 'deadline', 'rounding', 'revision_policy',
            'missing_policy', 'cancellation_policy', 'other_policy', 'source',
            'lower_inclusive', 'upper_inclusive', 'reviewer', 'evidence', 'family')


def review(rule, annotation):
    if rule['status'] in ('unsupported_path', 'irrelevant'):
        raise ValueError('Unsupported contract')
    if annotation.get('rules_version') != rule['rules_version']:
        raise ValueError('Review hash differs from current metadata')
    if any(annotation.get(k) is None for k in REQUIRED):
        raise ValueError('Incomplete review')
    if annotation.get('payout') != 'binary_0_1' or annotation['rounding'] != 'integer_exact':
        raise ValueError('Special payouts/rounding require a dedicated implementation')
    if annotation['missing_policy'] != 'no_trade' or annotation['cancellation_policy'] != 'no_trade' or annotation['other_policy'] != 'no_trade':
        raise ValueError('Special settlement must be modeled; this release blocks it')
    if annotation['revision_policy'] not in ('first_release', 'revisions_until_deadline'):
        raise ValueError('Unknown revision policy')
    ZoneInfo(annotation['timezone']); stamp(annotation['deadline'])
    start, end = date.fromisoformat(annotation['start']), date.fromisoformat(annotation['end'])
    if end < start or (rule['kind'] == 'daily' and end != start):
        raise ValueError('Invalid statistical dates')
    low, high = annotation.get('lower'), annotation.get('upper')
    if low is None and high is None or low is not None and high is not None and low > high:
        raise ValueError('Invalid bounds')
    if any(x is not None and (not isinstance(x, int) or x < 0) for x in (low, high)):
        raise ValueError('Bounds must be integer checkpoint counts')
    merged = dict(rule); merged.update(annotation); merged['status'] = 'approved'
    return merged


def wins(value, rule):
    low, high = rule.get('lower'), rule.get('upper')
    return ((low is None or (value >= low if rule['lower_inclusive'] else value > low))
        and (high is None or (value <= high if rule['upper_inclusive'] else value < high)))


def token_sides(m):
    def array(x): return json.loads(x) if isinstance(x, str) else x
    outcomes, tokens = array(m.get('outcomes', [])), array(m.get('clobTokenIds', []))
    if len(outcomes) != 2 or set(outcomes) != {'Yes', 'No'} or len(tokens) != 2:
        raise ValueError('Not a standard binary market')
    return dict(zip(outcomes, tokens))
