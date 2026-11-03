from decimal import Decimal, ROUND_CEILING
from datetime import datetime, timezone
from .store import stamp

D = lambda x: Decimal(str(x))


def fill(book, quantity, fee_rate, side='buy', limit=None):
    if fee_rate is None: raise ValueError('Unknown market-specific fee rate')
    qty, rate = D(quantity), D(fee_rate)
    if qty <= 0 or rate < 0: raise ValueError('Invalid quantity/fee')
    levels = book.get('asks' if side=='buy' else 'bids', [])
    levels = sorted([(D(x['price']),D(x['size'])) for x in levels], reverse=side=='sell')
    filled = cost = fee = D(0)
    capacity = D(0)
    tick = D(book['tick_size'])
    if tick <= 0: raise ValueError('Invalid tick')
    for p,s in levels:
        if not 0 < p < 1 or s < 0 or p % tick != 0: raise ValueError('Invalid book level')
        if limit is not None and (p>D(limit) if side=='buy' else p<D(limit)): continue
        capacity += s
        q = min(qty-filled,s)
        if q <= 0: continue
        filled += q; cost += q*p; fee += q*rate*p*(1-p)
    # Conservative monetary rounding; apply to aggregate fee, not VWAP.
    fee = fee.quantize(D('0.00001'),rounding=ROUND_CEILING)
    return dict(quantity=float(filled), vwap=float(cost/filled) if filled else None,
        fee=float(fee), fee_per_share=float(fee/filled) if filled else None,
        capital=float(cost+fee), max_quantity=float(capacity), full=filled==qty,
        minimum_met=filled>=D(book['min_order_size']))


def book_time(book):
    t = str(book['timestamp'])
    return datetime.fromtimestamp(float(t)/1000,timezone.utc) if t.replace('.','').isdigit() else stamp(t)


def evaluate(rule, p, bookrow, fee_rate, config, at, data_ok, source_age, metadata_age):
    reasons = []
    b = bookrow['payload']
    book = b['book']
    age = (stamp(at)-book_time(book)).total_seconds()
    side = b['side']
    probability = p if side=='Yes' else 1-p
    conservative = max(0,probability-config['probability_haircut'])
    if rule['status'] != 'approved': reasons.append('rules_not_approved')
    if b['rules_version'] != rule['rules_version']: reasons.append('rules_changed')
    if not rule['open'] or stamp(at) >= stamp(rule['deadline']): reasons.append('market_closed')
    if not data_ok or source_age > config['source_max_age_hours']*3600 or source_age < 0: reasons.append('data_invalid_or_stale')
    if metadata_age < 0 or metadata_age > config['metadata_max_age_seconds']: reasons.append('metadata_stale')
    if age < 0 or age > config['book_max_age_seconds']: reasons.append('book_stale')
    try:
        f = fill(book,config['quantity'],fee_rate)
        if rule.get('minimum_order') is None or f['quantity'] and f['quantity']*f['vwap'] < float(rule['minimum_order']): reasons.append('minimum_notional_not_met_or_unknown')
        if not f['quantity'] or not f['minimum_met']: reasons.append('insufficient_depth')
    except (ValueError, KeyError) as exc:
        reasons.append(str(exc)); f = {}
    edge = probability-f['vwap']-f['fee_per_share'] if f.get('quantity') else None
    stress = conservative-f['vwap']-f['fee_per_share']-config['latency_price_stress'] if edge is not None else None
    if stress is None or stress <= config['safety_margin']: reasons.append('stress_edge_below_margin')
    return dict(market_id=rule['market_id'],family=rule.get('family'),side=side,
        probability=probability,conservative_probability=conservative,
        net_edge=edge,stressed_edge=stress,book_age_seconds=age,
        source_age_seconds=source_age,accepted=not reasons,reasons=reasons,**f)
