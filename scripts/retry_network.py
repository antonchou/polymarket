"""User-authorized local mihomo diagnostics; never prints proxy secrets."""
import json
import urllib.request
from urllib.parse import quote
from pathlib import Path
import yaml
cfg=yaml.safe_load(Path('/home/startai/.config/mihomo/config.yaml').read_text())
headers={'Authorization':'Bearer '+str(cfg.get('secret','')),'Content-Type':'application/json'}
def controller(path,method='GET',data=None):
    req=urllib.request.Request('http://127.0.0.1:9090'+path,headers=headers,method=method,
        data=json.dumps(data).encode() if data else None)
    with urllib.request.urlopen(req,timeout=10) as r:
        body=r.read();return json.loads(body) if body else {'status':r.status}
groups=controller('/proxies')['proxies']
before={k:groups[k].get('now') for k in ('良心云','自建节点','预测市场')}
Path('reports/network-before.json').write_text(json.dumps(before,ensure_ascii=False,indent=2))
for group,target in [('良心云','🇺🇸美国高速01|CTCU|0.1x'),('自建节点','usjd'),('预测市场','🇭🇰香港高速01|BGP|CMCU')]:
    try:print('select',group,target,controller('/proxies/'+quote(group,safe=''),'PUT',{'name':target}))
    except Exception as exc:print('select_failed',group,str(exc))
proxy=urllib.request.build_opener(urllib.request.ProxyHandler({'https':'http://127.0.0.1:7890','http':'http://127.0.0.1:7890'}))
results=[]
for url in ['https://gamma-api.polymarket.com/markets?closed=false&limit=1','https://www.tsa.gov/travel/passenger-volumes','https://pypi.org/simple/duckdb/']:
    try:
        with proxy.open(urllib.request.Request(url,headers={'User-Agent':'TSA-Research/0.1'}),timeout=25) as r:
            body=r.read();result={'url':url,'status':r.status,'bytes':len(body)}
    except Exception as exc:result={'url':url,'error':str(exc)}
    print(result);results.append(result)
Path('reports/network-retry.json').write_text(json.dumps(results,indent=2))
print('selected', {k:v.get('now') for k,v in controller('/proxies')['proxies'].items() if k in before})
