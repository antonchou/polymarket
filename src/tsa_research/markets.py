from urllib.parse import urlencode
from .data import PublicHTTP, GAMMA, CLOB
from .rules import parse_market, token_sides


def discover(store, max_pages=10000):
    http = PublicHTTP(store)
    cursor, seen, count, relevant = None, set(), 0, 0
    try:
        for _ in range(max_pages):
            params = dict(closed='false', limit=100)
            if cursor: params['after_cursor'] = cursor
            page = http.get(GAMMA + '/markets/keyset?' + urlencode(params))
            if not isinstance(page, dict) or 'markets' not in page:
                raise ValueError('Unexpected Gamma page schema')
            for market in page['markets']:
                count += 1
                rule = parse_market(market)
                if rule['relevant']:
                    relevant += 1
                    previous = next((r['payload'] for r in reversed(store.rows('market')) if r['payload']['market_id']==rule['market_id']), None)
                    if previous and previous['status']=='approved' and previous['rules_version']==rule['rules_version']:
                        for key in ('start','end','timezone','deadline','rounding','revision_policy','missing_policy','cancellation_policy','other_policy','source','lower','upper','lower_inclusive','upper_inclusive','reviewer','evidence','family','payout'):
                            rule[key]=previous[key]
                        rule['status']='approved'
                    store.append('market', rule)
            cursor = page.get('next_cursor')
            if not cursor:
                status = 'candidates_require_review' if relevant else 'no_tradable_markets'
                return store.append('discovery_status', dict(ok=True, complete=True,
                    status=status, scanned=count, relevant=relevant))['payload']
            if cursor in seen: raise ValueError('Repeated Gamma cursor')
            seen.add(cursor)
        raise ValueError('Page cap reached; discovery incomplete')
    except (RuntimeError, ValueError) as exc:
        return store.append('discovery_status', dict(ok=False, complete=False,
            status='unknown', scanned=count, relevant=relevant, error=str(exc)))['payload']


def latest_markets(store):
    result = {}
    for row in store.rows('market'):
        result[row['payload']['market_id']] = row
    return list(result.values())


def collect_books(store):
    http, count, errors = PublicHTTP(store), 0, []
    for row in latest_markets(store):
        rule = row['payload']
        if not rule['open'] or rule['status'] == 'unsupported_path': continue
        try:
            for side, token in token_sides(rule['metadata']).items():
                book = http.get(CLOB + '/book?' + urlencode({'token_id': token}))
                if str(book.get('asset_id')) != str(token): raise ValueError('Book token mismatch')
                # Fee parameters remain market-specific; unknown parameters block valuation.
                store.append('book', dict(market_id=rule['market_id'], side=side,
                    token=token, book=book, rules_version=rule['rules_version']))
                count += 1
        except (RuntimeError, ValueError, KeyError) as exc:
            errors.append(str(exc))
    return store.append('book_status', dict(ok=not errors, count=count, status='collected' if count else 'no_books_collected', errors=errors))['payload']
