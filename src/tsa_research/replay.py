"""Replay only captured journal snapshots in chronological order.
Historical last prices and midpoints are never execution substitutes.
"""
import tempfile
from .store import Store
from .paper import run_paper, Ledger


def replay(source,config,samples=500):
    inputs=[r for r in source.rows() if r['kind'] in
            ('throughput','market','book','data_status','discovery_status')]
    if not any(r['kind']=='book' for r in inputs):
        return dict(available=False,reason='No historical book snapshots',net_profit=None)
    with tempfile.TemporaryDirectory(prefix='tsa-replay-') as tmp:
        dest=Store(tmp)
        times=sorted(set(r['fetched_at'] for r in inputs))
        for at in times:
            for r in inputs:
                if r['fetched_at']==at: dest.append(r['kind'],r['payload'],at)
            run_paper(dest,config,at,samples)
        return dict(available=True,mode='recorded_snapshot_trade_replay',
            **Ledger(dest).metrics(),coverage_start=times[0],coverage_end=times[-1],
            limitation='Displayed snapshot liquidity, no queue-level cancellation feed. Settlement evidence must be imported separately.')


def sensitivity(store,config):
    cases={}
    for name,changes in {'base':{},'latency_30s':{'execution_delay_seconds':30},
        'slippage_3c':{'latency_price_stress':.03},'bias_15pp':{'probability_haircut':.15}}.items():
        cases[name]=replay(store,dict(config,**changes))
    return cases
