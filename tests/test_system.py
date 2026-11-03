import json
import math
import tomllib
from datetime import date,timedelta
from pathlib import Path
import pytest
from tsa_research.store import Store,stamp
from tsa_research.data import parse_tsa,PublicHTTP
from tsa_research.rules import parse_market,review,wins,token_sides
from tsa_research.model import distribution,contract_distribution,aligned_year,holiday_position,days
from tsa_research.execution import fill,evaluate
from tsa_research.paper import Ledger
from tsa_research.backtest import walk_forward
from tsa_research.replay import replay

@pytest.fixture
def store(tmp_path): return Store(tmp_path)
@pytest.fixture
def config(): return tomllib.loads(Path('config/default.toml').read_text())['execution']
@pytest.fixture
def history():
    start=date(2024,1,1)
    return {(start+timedelta(days=i)).isoformat():round(2200000+150000*math.sin(i/7)+i*100) for i in range(500)}
@pytest.fixture
def rule():
    r=parse_market(dict(id='1',question='TSA total checkpoint throughput',description='checkpoint throughput source https://www.tsa.gov/travel/passenger-volumes',active=True,acceptingOrders=True,outcomes=['Yes','No'],clobTokenIds=['y','n']))
    a=dict(rules_version=r['rules_version'],start='2025-05-16',end='2025-05-16',timezone='America/New_York',deadline='2025-05-20T12:00:00Z',rounding='integer_exact',revision_policy='first_release',missing_policy='no_trade',cancellation_policy='no_trade',other_policy='no_trade',source='https://www.tsa.gov/travel/passenger-volumes',lower=2100000,upper=None,lower_inclusive=False,upper_inclusive=False,reviewer='test',evidence='TEST ONLY',family='week-20',payout='binary_0_1')
    r=review(r,a);r.update(minimum_order=1,fees_enabled=False,metadata_fetched_at='2025-05-16T12:00:00Z');return r
@pytest.fixture
def book(): return dict(asks=[{'price':'.6','size':'20'},{'price':'.4','size':'5'}],bids=[{'price':'.3','size':'30'}],tick_size='.01',min_order_size='1',timestamp='2025-05-16T12:00:00Z')


def test_availability_revision(store):
    store.ingest([{'date':'2025-01-01','value':2000000}],at='2025-01-02T12:00:00Z')
    store.ingest([{'date':'2025-01-01','value':2100000}],at='2025-01-03T12:00:00Z')
    assert store.asof('2025-01-02T11:00:00Z')=={}
    assert store.asof('2025-01-02T13:00:00Z')['2025-01-01']==2000000
    assert store.asof('2025-01-03T13:00:00Z')['2025-01-01']==2100000
    assert len(store.rows('throughput'))==2
    assert store.ingest([{'date':'2025-01-01','value':2100000}])==0


def test_publication_and_timezone(store):
    store.ingest([dict(date='2025-01-01',value=2000000,source_published_at='2025-01-03T00:00:00Z')],at='2025-01-02T00:00:00Z')
    assert store.asof('2025-01-02T12:00:00Z')=={}
    assert stamp('2025-11-02T01:30:00-04:00')!=stamp('2025-11-02T01:30:00-05:00')
    with pytest.raises(ValueError): stamp('2025-01-01T12:00:00')


def test_parser():
    html='<table><tr><th>Date</th><th>2025</th><th>2024</th></tr><tr><td>1/2/2025</td><td>2,100,000</td><td>999</td></tr></table>'
    assert parse_tsa(html)==[dict(date='2025-01-02',value=2100000)]
    with pytest.raises(ValueError): parse_tsa('<html>blocked</html>')
    with pytest.raises(ValueError): parse_tsa(html.replace('2,100,000','-1'))


def test_rule_safety(rule):
    assert rule['status']=='approved'
    assert not wins(2100000,rule) and wins(2100001,rule)
    rule.update(upper=2200000,upper_inclusive=True)
    assert wins(2200000,rule) and not wins(2200001,rule)
    assert parse_market(dict(id='x',question='TSA vs team',description='esports'))['status']=='irrelevant'
    assert parse_market(dict(id='x',description='TSA checkpoint throughput any date https://www.tsa.gov/travel/passenger-volumes'))['status']=='unsupported_path'
    with pytest.raises(ValueError): review(rule,dict(rules_version='changed'))
    with pytest.raises(ValueError): token_sides({'outcomes':['Other'],'clobTokenIds':['x']})


def test_dates():
    assert len(days('2024-02-28','2024-03-01'))==3
    assert aligned_year(date(2025,11,27))==date(2024,11,28)
    assert holiday_position(date(2025,11,28))==('thanksgiving',1)


def test_distribution_known_and_cumulative(history,rule):
    targets=['2025-05-14','2025-05-15','2025-05-16']
    paths=distribution(history,targets,samples=100)
    assert len(paths)==100
    assert all(p[0]==history[targets[0]] for p in paths)
    rule.update(start=targets[0],end=targets[-1])
    d=contract_distribution(history,rule,100)
    assert d['known_total']==history[targets[0]]
    assert 0<=d['probability']<=1
    assert d==contract_distribution(history,rule,100)
    rule['revision_policy']='revisions_until_deadline'
    with pytest.raises(ValueError): contract_distribution(history,rule)


def test_fee_vwap_partial(book):
    f=fill(book,10,.05)
    assert f['vwap']==.5
    assert f['fee']==pytest.approx(.12)
    assert f['max_quantity']==25
    assert fill(book,100,0)['quantity']==25
    assert not fill(book,100,0)['full']
    with pytest.raises(ValueError): fill(book,10,None)


def test_no_duplicate_impact_or_stale_signal(rule,book,config):
    row=dict(payload=dict(book=book,side='Yes',rules_version=rule['rules_version']))
    s=evaluate(rule,.9,row,0,config,'2025-05-16T12:00:01Z',True,1,1)
    assert s['accepted'] and s['net_edge']==pytest.approx(.4)
    s=evaluate(rule,.9,row,0,config,'2025-05-16T12:01:00Z',True,1,1)
    assert not s['accepted'] and 'book_stale' in s['reasons']
    s=evaluate(rule,.9,row,None,config,'2025-05-16T12:00:01Z',False,1,1)
    assert not s['accepted']


def test_duplicate_correlated_risk(store,rule,config):
    l=Ledger(store);signal=dict(accepted=True,side='Yes',quantity=60,conservative_probability=.9)
    assert l.submit(signal,rule,'2025-05-16T12:00:00Z',config)=='pending'
    assert l.submit(signal,rule,'2025-05-16T12:00:01Z',config)=='duplicate_signal'
    other=dict(rule,market_id='2',family='different-name')
    assert l.submit(signal,other,'2025-05-16T12:00:01Z',config)=='family_risk_limit'


def test_delay_and_cancellation(store,rule,config):
    l=Ledger(store);signal=dict(accepted=True,side='Yes',quantity=10,conservative_probability=.9)
    l.submit(signal,rule,'2025-05-16T12:00:00Z',config)
    l.advance('2025-05-16T12:00:03Z',config)
    assert next(iter(l.orders().values()))['status']=='pending'
    l.advance('2025-05-16T12:01:00Z',config)
    assert next(iter(l.orders().values()))['status']=='cancelled'


def test_post_delay_fill_settlement(store,rule,book,config):
    l=Ledger(store);signal=dict(accepted=True,side='Yes',quantity=10,conservative_probability=.9)
    l.submit(signal,rule,'2025-05-16T12:00:00Z',config)
    store.append('market',rule,'2025-05-16T12:00:05Z')
    store.append('data_status',{'ok':True},'2025-05-16T12:00:05Z')
    book['timestamp']='2025-05-16T12:00:06Z'
    store.append('book',dict(market_id='1',side='Yes',book=book,rules_version=rule['rules_version']),'2025-05-16T12:00:06Z')
    l.advance('2025-05-16T12:00:07Z',config)
    key,o=next(iter(l.orders().items()));assert o['status']=='open'
    with pytest.raises(ValueError): l.settle(key,1,'2025-05-17T00:00:00Z',config,'test')
    l.settle(key,1,'2025-05-21T00:00:00Z',config,'TEST evidence')
    assert l.orders()[key]['reserved']>0
    l.advance('2025-05-25T00:00:00Z',config)
    assert l.orders()[key]['reserved']==0
    assert l.metrics()['net_profit']==pytest.approx(5)


def test_no_historical_book_no_profit(store,config):
    assert replay(store,config)['net_profit'] is None
    b=walk_forward(store)
    assert b['trading']['net_profit'] is None and b['event_families']==0


def test_strict_history_cannot_backdate(store,history):
    store.ingest([dict(date=k,value=v) for k,v in history.items()],at='2026-01-01T00:00:00Z')
    assert walk_forward(store,samples=20)['event_families']==0
    r=walk_forward(store,reanalysis=True,samples=20)
    assert r['event_families']>0 and r['mode']=='revised_history_reanalysis'
    assert all(x['decision'][:10]<=x['date'] for x in r['rows'])


def test_duckdb_projection_if_available(store):
    pytest.importorskip('duckdb')
    store.ingest([dict(date='2025-01-01',value=2000000)])
    assert store.export()==1
    import duckdb
    con=duckdb.connect(str(store.root/'research.duckdb'))
    assert con.execute('select value from throughput').fetchone()[0]==2000000
    assert con.execute('select count(*) from read_parquet(?)',[str(store.root/'snapshots.parquet')]).fetchone()[0]==1
    con.close()


def test_pagination_and_empty_discovery(store,monkeypatch):
    from tsa_research.markets import discover
    calls=[]
    def get(self,url,is_json=True):
        calls.append(url)
        if len(calls)==1: return dict(markets=[],next_cursor='abc')
        return dict(markets=[],next_cursor=None)
    monkeypatch.setattr(PublicHTTP,'get',get)
    r=discover(store)
    assert r['complete'] and r['status']=='no_tradable_markets'
    assert 'after_cursor=abc' in calls[1]
    monkeypatch.setattr(PublicHTTP,'get',lambda *a,**k:dict(markets=[],next_cursor='abc'))
    assert discover(store)['status']=='unknown'


def test_retry_status(store,monkeypatch):
    import tsa_research.data as data
    monkeypatch.setattr(data.time,'sleep',lambda _:None)
    def fail(*a,**k): raise OSError('TEST outage')
    monkeypatch.setattr(data,'urlopen',fail)
    with pytest.raises(RuntimeError): PublicHTTP(store,retries=3).get('https://example.invalid')
    assert len(store.rows('request_error'))==3


def test_six_known_days_remaining_threshold(history,rule):
    target=days('2025-05-14','2025-05-20')
    history=dict(history)
    for d in target[:-1]: history[d]=2400000
    rule.update(start=target[0],end=target[-1],lower=16500000)
    r=contract_distribution(history,rule,200)
    assert r['known_total']==14400000
    assert r['unknown_dates']==[target[-1]]
    assert r['probability']==sum(v-14400000>2100000 for v in r['totals'])/200


def test_probability_mass_not_renormalized(history,rule):
    a=contract_distribution(history,dict(rule,lower=2000000,upper=2100000),100)
    b=contract_distribution(history,dict(rule,lower=2300000,upper=2400000),100)
    assert a['probability']+b['probability']<=1


def test_unknown_fee_shape_blocks(rule):
    from tsa_research.paper import fee_rate
    assert fee_rate(dict(rule,fees_enabled=True,fee_parameters={'rate':.05,'exponent':2})) is None
    assert fee_rate(dict(rule,fees_enabled=True,fee_parameters={'rate':.05,'exponent':1}))==.05


def test_correlated_blocks(history):
    # Block bootstrap should retain contiguous errors, not independently draw days.
    from tsa_research.model import residuals,point
    targets=['2025-05-16','2025-05-17']
    paths=distribution(history,targets,samples=100)
    errors=residuals(history)
    pairs=[(e[1],errors[i+1][1]) for i,e in enumerate(errors[:-1])]
    centers=[point(history,d) for d in targets]
    for p in paths:
        delta=(p[0]-centers[0],p[1]-centers[1])
        assert any(abs(a-delta[0])<=.51 and abs(b-delta[1])<=.51 for a,b in pairs)


def test_snapshot_order_uses_absolute_time(store):
    store.ingest([dict(date='2025-01-01',value=2000000)],at='2025-01-02T09:00:00+08:00')
    store.ingest([dict(date='2025-01-01',value=2100000)],at='2025-01-02T02:00:00Z')
    assert store.asof('2025-01-02T03:00:00Z')['2025-01-01']==2100000
    store.ingest([dict(date='2025-01-01',value=2200000)],at='2025-01-02T02:00:00Z')
    assert store.asof('2025-01-02T03:00:00Z')['2025-01-01']==2200000


def test_export_streams_and_keeps_previous_projection_on_error(store,monkeypatch):
    duckdb=pytest.importorskip('duckdb')
    store.ingest([dict(date='2025-01-01',value=2000000)])
    for _ in range(12):store.append('raw',dict(body='test-only '*8000))
    def forbidden(*a,**k):raise AssertionError('Export must not materialize the entire journal')
    monkeypatch.setattr(store,'rows',forbidden)
    assert store.export()==13
    import hashlib
    probe=duckdb.connect(str(store.root/'research.duckdb'),read_only=True)
    payload=json.loads(probe.execute("select payload from snapshots where kind='raw' limit 1").fetchone()[0])
    raw=json.loads((store.root/payload['body_ref']).read_text())['payload']['body']
    assert payload['body_sha256']==hashlib.sha256(raw.encode()).hexdigest()
    assert 'body' not in payload
    probe.close()
    store.append('throughput',{'invalid_test_record':True})
    with pytest.raises(KeyError):store.export()
    con=duckdb.connect(str(store.root/'research.duckdb'),read_only=True)
    assert con.execute('select count(*) from snapshots').fetchone()[0]==13
    assert con.execute('select count(*) from read_parquet(?)',[str(store.root/'snapshots.parquet')]).fetchone()[0]==13
    con.close()
