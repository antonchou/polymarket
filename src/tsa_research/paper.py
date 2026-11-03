"""Persistent paper ledger. BUY intents are re-priced only on a later book.
No latency fill is inferred from the decision-time snapshot. No live orders.
"""
from datetime import timedelta, date
from statistics import mean
from .store import stamp, digest, now
from .execution import fill, book_time, evaluate
from .markets import latest_markets
from .model import contract_distribution


def fee_rate(rule):
    if rule['fees_enabled'] is False: return 0
    schedule = rule.get('fee_parameters')
    if rule['fees_enabled'] is True and schedule and schedule.get('exponent') == 1:
        return schedule.get('rate')
    return None


class Ledger:
    def __init__(self, store): self.store = store
    def orders(self):
        result = {}
        for row in self.store.rows('paper_order'):
            result[row['payload']['key']] = row['payload']
        return result
    def submit(self, signal, rule, at, config):
        key = digest([rule['market_id'],rule['rules_version'],signal['side']])
        orders = self.orders()
        if key in orders: return 'duplicate_signal'
        active = [o for o in orders.values() if o['status'] in ('pending','open','settling')]
        # Overlapping statistical windows are correlated even with different event IDs.
        exposure = sum(o['reserved'] for o in active
            if o['family']==rule['family'] or not(o['end']<rule['start'] or o['start']>rule['end']))
        reserve = signal['quantity']  # worst-case $1/share reserved until fill
        if exposure+reserve > config['max_family_capital']: return 'family_risk_limit'
        if sum(o['reserved'] for o in active)+reserve > config['max_portfolio_capital']: return 'portfolio_risk_limit'
        if not signal['accepted']: return 'rejected_signal'
        self.store.append('paper_order',dict(key=key,market_id=rule['market_id'],
            family=rule['family'],start=rule['start'],end=rule['end'],rule=rule,
            side=signal['side'],signal=signal,status='pending',reserved=reserve,
            created_at=at,execute_after=(stamp(at)+timedelta(seconds=config['execution_delay_seconds'])).isoformat()),at)
        return 'pending'
    def advance(self, at, config):
        for key,o in self.orders().items():
            if o['status']=='settling' and stamp(at)>=stamp(o['release_at']):
                self.store.append('paper_order',dict(o,status='closed',reserved=0),at)
            if o['status'] != 'pending' or stamp(at)<stamp(o['execute_after']): continue
            candidates = [r for r in self.store.rows('book') if
                r['payload']['market_id']==o['market_id'] and r['payload']['side']==o['side']
                and stamp(o['execute_after'])<=stamp(r['fetched_at'])<=stamp(at)]
            if not candidates:
                if (stamp(at)-stamp(o['execute_after'])).total_seconds()>config['book_max_age_seconds']:
                    self.store.append('paper_order',dict(o,status='cancelled',reserved=0,reason='no_post_delay_book'),at)
                continue
            r = candidates[0]
            try:
                b = r['payload']
                if b['rules_version']!=o['rule']['rules_version']: raise ValueError('rules_changed')
                if not stamp(o['execute_after'])<=book_time(b['book'])<=stamp(at): raise ValueError('pre_delay_book')
                if (stamp(at)-book_time(b['book'])).total_seconds()>config['book_max_age_seconds']: raise ValueError('stale_execution_book')
                if stamp(at)>=stamp(o['rule']['deadline']): raise ValueError('deadline_passed')
                current = next((m for m in latest_markets(self.store) if m['payload']['market_id']==o['market_id']),None)
                if not current or current['payload']['status']!='approved' or current['payload']['rules_version']!=o['rule']['rules_version'] or not current['payload']['open']:
                    raise ValueError('metadata_missing_or_changed')
                if not 0 <= (stamp(at)-stamp(current['payload'].get('metadata_fetched_at',current['fetched_at']))).total_seconds() <= config['metadata_max_age_seconds']:
                    raise ValueError('metadata_stale')
                ds = self.store.latest('data_status')
                if not ds or not ds['payload']['ok'] or (stamp(at)-stamp(ds['fetched_at'])).total_seconds()>config['source_max_age_hours']*3600:
                    raise ValueError('data_stale')
                price_limit = o['signal']['conservative_probability']-config['safety_margin']-config['latency_price_stress']
                f = fill(b['book'],o['signal']['quantity'],fee_rate(current['payload']),limit=price_limit)
                if current['payload'].get('minimum_order') is None or f['quantity'] and f['quantity']*f['vwap']<float(current['payload']['minimum_order']): raise ValueError('minimum_notional_not_met_or_unknown')
                if not f['minimum_met'] or not f['quantity']: raise ValueError('withdrawn_or_insufficient_depth')
                if o['signal']['conservative_probability']-f['vwap']-f['fee_per_share']<=config['safety_margin']:
                    raise ValueError('edge_disappeared')
                self.store.append('paper_order',dict(o,status='open',fill=f,
                    filled_at=at,reserved=f['capital'],execution_book_id=r['id']),at)
            except (ValueError,KeyError) as exc:
                self.store.append('paper_order',dict(o,status='cancelled',reserved=0,reason=str(exc)),at)
    def settle(self, key, payout, at, config, evidence):
        o = self.orders()[key]
        if o['status']!='open' or payout not in (0,1) or not evidence: raise ValueError('Invalid reviewed settlement')
        if stamp(at)<stamp(o['rule']['deadline']): raise ValueError('Settlement before deadline is not supported')
        quantity = o['fill']['quantity']
        pnl = quantity*payout-o['fill']['capital']
        self.store.append('paper_order',dict(o,status='settling',payout=payout,pnl=pnl,
            settlement_evidence=evidence,settled_at=at,
            release_at=(stamp(at)+timedelta(days=config['settlement_delay_days'])).isoformat()),at)
    def exit(self,key,bookrow,at,rate):
        o = self.orders()[key]
        b = bookrow['payload']
        if o['status']!='open' or b['market_id']!=o['market_id'] or b['side']!=o['side']:
            raise ValueError('Exit book mismatch')
        if (stamp(at)-book_time(b['book'])).total_seconds()>30: raise ValueError('Stale exit book')
        if not stamp(o['filled_at'])<book_time(b['book'])<=stamp(at): raise ValueError('Exit requires later book')
        f = fill(b['book'],o['fill']['quantity'],rate,side='sell')
        if not f['full']: raise ValueError('Partial exits unsupported; hold position')
        pnl = f['quantity']*f['vwap']-f['fee']-o['fill']['capital']
        self.store.append('paper_order',dict(o,status='closed',reserved=0,pnl=pnl,
            settled_at=at,exit_fill=f,exit_book_id=bookrow['id']),at)
    def metrics(self):
        orders=list(self.orders().values()); closed=[o for o in orders if 'pnl' in o]
        peak=drawdown=equity=high=0
        timeline={}
        for row in self.store.rows('paper_order'):
            o=row['payload']; timeline[o['key']]=o
            peak=max(peak,sum(v['reserved'] for v in timeline.values()))
        for o in sorted(closed,key=lambda o:o['settled_at']):
            equity+=o['pnl']; high=max(high,equity); drawdown=max(drawdown,high-equity)
        filled=[o for o in orders if 'fill' in o]
        return dict(net_profit=equity if closed else None,maximum_drawdown=drawdown if closed else None,
            drawdown_basis='realized_ledger_only; open_positions_not_marked_to_market',
            fill_rate=len(filled)/len(orders) if orders else None,peak_capital=peak,
            average_holding_days=mean((stamp(o['settled_at'])-stamp(o['filled_at'])).total_seconds()/86400 for o in closed) if closed else None,
            event_families=len(set(o['family'] for o in filled)),orders=len(orders),closed=len(closed),
            uncertainty='Paper fills use displayed snapshots, queue/cancellation timing remains unobserved')


def run_paper(store,config,at=None,samples=2000):
    at=at or now(); ledger=Ledger(store); ledger.advance(at,config)
    ds=store.latest('data_status'); discovery=store.latest('discovery_status')
    status = discovery['payload']['status'] if discovery else 'unknown'
    results=[]
    for row in latest_markets(store):
        rule=row['payload']
        if rule['status']!='approved':
            results.append(dict(market_id=rule['market_id'],accepted=False,reasons=[rule['status']]))
            continue
        try:
            history=store.asof(at)
            if any(r['payload'].get('source')!='TSA' for r in store.rows('throughput')
                   if stamp(r['payload']['first_seen_at'])<=stamp(at)):
                raise ValueError('unverified_local_data_in_information_set')
            if rule['revision_policy']=='first_release':
                history={}
                for r in store.rows('throughput'):
                    if stamp(r['payload']['first_seen_at'])<=stamp(at): history.setdefault(r['payload']['date'],r['payload']['value'])
            latest_date=max(history) if history else '1900-01-01'
            if (stamp(at).date()-date.fromisoformat(latest_date)).days>3:
                raise ValueError('statistical_data_stale')
            from .model import days
            if any(d<latest_date and d not in history for d in days(rule['start'],rule['end'])):
                raise ValueError('missing_past_observation')
            # An observed first version from an archive is not proof of first release.
            if rule['revision_policy']=='first_release' and any(
                not r['payload'].get('source_published_at') for r in store.rows('throughput')
                if r['payload']['date'] in days(rule['start'],rule['end'])):
                raise ValueError('first_release_vintage_not_verifiable')
            pred=contract_distribution(history,rule,samples)
            store.append('forecast',dict(market_id=rule['market_id'],rules_version=rule['rules_version'],
                decision_at=at,input=history,input_hash=digest(history),**pred),at)
            books={}
            for r in store.rows('book'):
                if r['payload']['market_id']==rule['market_id'] and stamp(r['fetched_at'])<=stamp(at): books[r['payload']['side']]=r
            if not books: raise ValueError('no_real_book')
            for side,b in books.items():
                age=(stamp(at)-stamp(ds['fetched_at'])).total_seconds() if ds else float('inf')
                signal=evaluate(rule,pred['probability'],b,fee_rate(rule),config,at,
                    bool(ds and ds['payload']['ok'] and discovery and discovery['payload']['ok']),
                    age,(stamp(at)-stamp(rule.get('metadata_fetched_at',row['fetched_at']))).total_seconds())
                if signal['accepted']:
                    reason=ledger.submit(signal,rule,at,config)
                    signal['paper_action']=reason
                    if reason!='pending': signal.update(accepted=False,reasons=[reason])
                store.append('signal',signal,at); results.append(signal)
        except (ValueError,KeyError) as exc:
            signal=dict(market_id=rule['market_id'],accepted=False,reasons=[str(exc)])
            store.append('signal',signal,at); results.append(signal)
    result=dict(market_status=status,signals=results,paper=ledger.metrics())
    store.append('paper_run',result,at)
    return result
