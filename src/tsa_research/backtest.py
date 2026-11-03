"""Forecast verification only; trades require recorded post-delay books."""
import math
import random
from collections import defaultdict
from datetime import date, timedelta, datetime, timezone
from statistics import mean
from .model import distribution, point, holiday_position
from .store import stamp


def metrics(rows):
    if not rows: return dict(n=0,mae=None,brier=None,log_loss=None)
    return dict(n=len(rows),mae=mean(abs(r['prediction']-r['actual']) for r in rows),
        brier=mean((r['p']-r['y'])**2 for r in rows),
        log_loss=mean(-r['y']*math.log(max(1e-6,r['p']))-(1-r['y'])*math.log(max(1e-6,1-r['p'])) for r in rows))


def paired_improvement(rows):
    pairs={}
    for r in rows:
        if r['split']=='test': pairs.setdefault((r['family'],r['date'],r['horizon']),{})[r['model']]=r
    families=defaultdict(list)
    for (family,_,_),p in pairs.items():
        if set(p)=={'baseline','weekday'}:
            a,b=p['baseline'],p['weekday']
            families[family].append((abs(b['prediction']-b['actual'])-abs(a['prediction']-a['actual']),
                (b['p']-b['y'])**2-(a['p']-a['y'])**2))
    if not families: return dict(families=0,mae_improvement=None,brier_improvement=None,ci95=None)
    # Resample event families, not individual correlated horizon/outcome rows.
    values=[(mean(x[0] for x in v),mean(x[1] for x in v)) for v in families.values()]
    rng=random.Random(42)
    boot=[]
    for _ in range(500):
        sample=rng.choices(values,k=len(values));boot.append((mean(x[0] for x in sample),mean(x[1] for x in sample)))
    bounds=lambda j:[sorted(x[j] for x in boot)[12],sorted(x[j] for x in boot)[487]]
    return dict(families=len(values),mae_improvement=mean(x[0] for x in values),
        brier_improvement=mean(x[1] for x in values),
        ci95=dict(mae=bounds(0),brier=bounds(1)) if len(values)>=10 else None,
        warning='Cluster bootstrap is descriptive; overlapping weeks and short samples reduce effective sample size')


def walk_forward(store, reanalysis=False, lag=2, samples=500, horizons=(1,3,7), test_fraction=.2):
    all_rows = store.rows('throughput')
    final = {}
    for row in all_rows: final[row['payload']['date']] = row['payload']['value']
    dates = sorted(final)
    result = []
    for i in range(120,len(dates)-max(horizons),7):
        origin = date.fromisoformat(dates[i])
        decision = datetime.combine(origin,datetime.min.time(),timezone.utc).isoformat()
        history = ({k:v for k,v in final.items() if date.fromisoformat(k) <= origin-timedelta(days=lag)}
                   if reanalysis else store.asof(decision))
        # strict observed history always wins; final values only serve as outcomes
        history = {k:v for k,v in history.items() if k < origin.isoformat()}
        for h in horizons:
            target = (origin+timedelta(days=h-1)).isoformat()
            if target not in final: continue
            try:
                threshold = round(point(history,target,True)/100000)*100000
                for simple in (False,True):
                    values = [p[0] for p in distribution(history,[target],samples,42,lag,simple)]
                    p = mean(v>threshold for v in values)
                    result.append(dict(decision=decision,date=target,horizon=h,
                        holiday=bool(holiday_position(date.fromisoformat(target))),
                        family=origin.isoformat(),model='weekday' if simple else 'baseline',
                        prediction=mean(values),actual=final[target],p=p,
                        y=int(final[target]>threshold),threshold=threshold))
            except ValueError: continue
    families = sorted(set(r['family'] for r in result))
    # Chronological split. Fixed defaults, no threshold optimization on final test.
    validation_start = int(len(families)*.6)
    test_start = int(len(families)*(1-test_fraction))
    groups = defaultdict(list)
    for r in result:
        index = families.index(r['family'])
        r['split'] = 'train' if index<validation_start else 'validation' if index<test_start else 'test'
        groups[f"{r['split']}/{r['model']}/h{r['horizon']}/holiday={r['holiday']}"].append(r)
    calibration = []
    for key,items in groups.items():
        for b in range(10):
            subset = [r for r in items if min(9,int(r['p']*10))==b]
            if subset: calibration.append(dict(group=key,bin=b,n=len(subset),
                predicted=mean(r['p'] for r in subset),observed=mean(r['y'] for r in subset)))
    report = dict(mode='revised_history_reanalysis' if reanalysis else 'observed_information_forecast_validation',
        assumptions={'publication_lag_days':lag if reanalysis else None,
            'revision_vintages_reconstructed':False,'threshold':'training weekday forecast rounded to 100k',
            'multi_day_error_model':'one-step residual blocks; horizon calibration provisional'},
        metrics={k:metrics(v) for k,v in groups.items()},calibration=calibration,
        baseline_comparison=paired_improvement(result),event_families=len(families), uncertainty='Report grouped samples; insufficient evidence for stable returns',
        market_comparison=None,market_comparison_reason='No matched historical executable books',
        trading={'net_profit':None,'maximum_drawdown':None,'fill_rate':None,
            'peak_capital':None,'average_holding_days':None,'reason':'Forecast validation is not trade replay'},
        sensitivity={'execution_latency':None,'slippage':None,'model_bias':None,
            'reason':'Requires historical books for execution sensitivity'},rows=result)
    store.append('backtest',report)
    return report
