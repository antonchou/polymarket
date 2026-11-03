"""Supplementary metadata search. Full market scan remains authoritative."""
import json
from pathlib import Path
from urllib.parse import urlencode
from tsa_research.data import PublicHTTP,GAMMA
from tsa_research.store import Store
from tsa_research.rules import parse_market
s=Store();http=PublicHTTP(s);events={};related={};page=1
while page<=100:
    p=http.get(GAMMA+'/public-search?'+urlencode({'q':'TSA','limit_per_type':50,'page':page,'search_tags':'false','search_profiles':'false'}))
    for e in p.get('events',[]):
        events[str(e['id'])]=e
        for m in e.get('markets',[]):
            rule=parse_market(dict(m,events=[{'id':e['id']}]))
            if rule['relevant']:
                related[rule['market_id']]=rule
    if not p.get('pagination',{}).get('hasMore'):break
    page+=1
if page>100:raise RuntimeError('Search incomplete')
for rule in related.values():s.append('historical_market' if not rule['open'] else 'market',rule)
r=dict(search_complete=True,pages=page,events=len(events),tsa_markets=len(related),
       open_tsa_markets=[r['market_id'] for r in related.values() if r['open']],
       note='Supplementary keyword search; full keyset scan is the absence check')
s.append('search_audit',r);Path('reports/tsa-search.json').write_text(json.dumps(r,indent=2));print(r)
