"""Resume a captured full Gamma keyset scan, with pooled HTTPS connections.
Use only with a contiguous prefix of the same closed=false, limit=100 scan.
"""
import json,time
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import requests
from tsa_research.store import Store
from tsa_research.data import GAMMA
from tsa_research.rules import parse_market
s=Store();pages=[]
for r in s.rows('raw'):
    url=r['payload'].get('url','');q=parse_qs(urlsplit(url).query)
    if url.startswith(GAMMA+'/markets/keyset?') and q.get('limit')==['100'] and q.get('closed')==['false'] and 'order' not in q:
        if 'after_cursor' not in q:pages=[]
        pages.append((q,json.loads(r['payload']['body'])))
if not pages:raise RuntimeError('No saved scan prefix')
cursor=None;ids=set();candidates={};seen=set()
def consume(page):
    for m in page['markets']:
        ids.add(str(m['id']));rule=parse_market(m)
        if rule['relevant']:candidates[rule['market_id']]=rule
for q,p in pages:
    if q.get('after_cursor',[None])[0]!=cursor:raise RuntimeError('Non-contiguous saved cursor chain')
    consume(p);cursor=p.get('next_cursor')
    if cursor:seen.add(cursor)
print('Resuming',len(ids),'markets,',len(pages),'captured pages',flush=True)
http=requests.Session();http.headers['User-Agent']='TSA-Research/0.1 (public research)'
status=None
try:
    while cursor:
        params={'closed':'false','limit':100,'after_cursor':cursor}
        for attempt in range(3):
            try:
                r=http.get(GAMMA+'/markets/keyset',params=params,timeout=25)
                s.append('raw',dict(url=r.url,status=r.status_code,headers=dict(r.headers),body=r.text))
                r.raise_for_status();p=r.json()
                if not isinstance(p.get('markets'),list):raise ValueError('Unexpected Gamma schema')
                break
            except (requests.RequestException,ValueError) as e:
                s.append('request_error',dict(url=GAMMA+'/markets/keyset',attempt=attempt+1,error=str(e)))
                if attempt==2:raise
                time.sleep(2**attempt)
        consume(p);cursor=p.get('next_cursor');pages.append((params,p))
        if cursor in seen:raise ValueError('Repeated Gamma cursor')
        if cursor:seen.add(cursor)
        if len(pages)%25==0:print('Scanned',len(ids),'markets',flush=True)
        time.sleep(.25)  # <=4 req/s, below documented Gamma limit
    for rule in candidates.values():s.append('market',rule)
    status=dict(ok=True,complete=True,status='candidates_require_review' if candidates else 'no_tradable_markets',scanned=len(ids),relevant=len(candidates),pages=len(pages),resumed=True)
except Exception as e:
    status=dict(ok=False,complete=False,status='unknown',scanned=len(ids),relevant=len(candidates),error=str(e),resumed=True)
finally:http.close()
s.append('discovery_status',status)
Path('reports/discover-markets.json').write_text(json.dumps(status,indent=2))
print(status,flush=True)
