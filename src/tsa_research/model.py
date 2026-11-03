"""Transparent additive baseline, chronological residual block bootstrap.
Counts are checkpoint events, not unique persons. No external covariates.
"""
import calendar
import math
import random
from datetime import date, timedelta
from statistics import mean
from .rules import wins


def days(start, end):
    a, b = date.fromisoformat(start), date.fromisoformat(end)
    return [(a + timedelta(days=i)).isoformat() for i in range((b-a).days + 1)]


def holidays(year):
    def nth(month, weekday, n):
        d = date(year, month, 1)
        return d + timedelta(days=(weekday-d.weekday()) % 7 + 7*(n-1))
    may = date(year, 5, 31)
    return dict(new_year=date(year,1,1), independence=date(year,7,4),
        christmas=date(year,12,25), thanksgiving=nth(11,3,4),
        labor=nth(9,0,1), memorial=may-timedelta(days=may.weekday()),
        mlk=nth(1,0,3), presidents=nth(2,0,3), juneteenth=date(year,6,19),
        veterans=date(year,11,11), columbus=nth(10,0,2))


def holiday_position(d):
    for year in (d.year-1, d.year, d.year+1):
        for name, h in holidays(year).items():
            delta = (d-h).days
            if abs(delta) <= 3: return name, delta
    return None


def aligned_year(d):
    hp = holiday_position(d)
    if hp:
        return holidays(d.year-1)[hp[0]] + timedelta(days=hp[1])
    # 364-day alignment preserves weekday; holiday-relative alignment wins above.
    return d - timedelta(days=364)


def point(history, target, simple=False):
    d = date.fromisoformat(target)
    eligible = sorted((date.fromisoformat(k), v) for k,v in history.items()
                      if date.fromisoformat(k) < d)
    same = [(k,v) for k,v in eligible if k.weekday() == d.weekday()]
    if len(same) < 4: raise ValueError('Insufficient weekday history')
    recent = mean(v for _,v in same[-8:])
    if simple: return recent
    # Recent weekday level plus clipped local trend, and holiday/weekday-aligned YoY.
    slope = (mean(v for _,v in same[-4:]) - mean(v for _,v in same[-8:-4])) / 28
    horizon = (d-eligible[-1][0]).days
    trend = max(-150000, min(150000, slope*horizon))
    old_date = aligned_year(d)
    old = history.get(old_date.isoformat())
    growth = []
    for k,v in eligible[-28:]:
        prior = history.get(aligned_year(k).isoformat())
        if prior and prior > 0: growth.append(v/prior)
    if old is not None and len(growth) >= 14:
        yoy = old * max(.7, min(1.4, mean(growth)))
        weight = .65 if holiday_position(d) else .35
        return max(0, (1-weight)*(recent+trend)+weight*yoy)
    return max(0, recent+trend)


def residuals(history, lag=2, simple=False, limit=180):
    dates = sorted(history)
    out = []
    for target in dates[-limit:]:
        cutoff = date.fromisoformat(target)-timedelta(days=lag)
        available = {k:v for k,v in history.items() if date.fromisoformat(k) <= cutoff}
        try: out.append((target, history[target]-point(available,target,simple)))
        except ValueError: continue
    if len(out) < 30: raise ValueError('At least 30 chronological residuals required')
    return out


def distribution(history, targets, samples=2000, seed=42, lag=2, simple=False):
    if len(history) < 120: raise ValueError('At least 120 observations required')
    rng = random.Random(seed)
    errors = residuals(history,lag,simple)
    centers = [history.get(d) if d in history else point(history,d,simple) for d in targets]
    unknown = [i for i,d in enumerate(targets) if d not in history]
    width = len(targets)
    # Contiguous dated residual blocks preserve observed cross-day dependence.
    blocks = [errors[i:i+width] for i in range(len(errors)-width+1)
              if (date.fromisoformat(errors[i+width-1][0])-date.fromisoformat(errors[i][0])).days == width-1]
    if unknown and not blocks: raise ValueError('Insufficient contiguous residual blocks')
    paths = []
    for _ in range(samples):
        block = rng.choice(blocks) if unknown else None
        paths.append([centers[i] if i not in unknown else
                      max(0, round(centers[i]+block[i][1])) for i in range(width)])
    return paths


def contract_distribution(history, rule, samples=2000, seed=42, revision_sd=None):
    targets = days(rule['start'],rule['end'])
    paths = distribution(history,targets,samples,seed)
    if rule['revision_policy'] == 'revisions_until_deadline':
        if revision_sd is None: raise ValueError('Revision uncertainty not estimated; signal blocked')
        rng = random.Random(seed+1)
        # Shared revision shock is conservative for cumulative counts.
        for path in paths:
            shock = rng.gauss(0, revision_sd)
            for i,d in enumerate(targets):
                if d in history: path[i] = max(0,round(path[i]+shock))
    totals = [sum(p) for p in paths]
    probability = mean(wins(v,rule) for v in totals)
    return dict(probability=probability, totals=totals, targets=targets,
                known_total=sum(history.get(d,0) for d in targets),
                unknown_dates=[d for d in targets if d not in history],
                method='chronological_residual_blocks_v1')
