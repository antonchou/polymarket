import argparse
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path
from .store import Store, now


def output(x): print(json.dumps(x,ensure_ascii=False,indent=2,allow_nan=False))


def main(argv=None):
    parser=argparse.ArgumentParser(description='TSA public research / paper only')
    parser.add_argument('--data-dir',default=os.getenv('TSA_DATA_DIR','data'))
    parser.add_argument('--config',default='config/default.toml')
    sub=parser.add_subparsers(dest='cmd',required=True)
    p=sub.add_parser('fetch-data'); p.add_argument('--url',action='append'); p.add_argument('--html',type=Path)
    sub.add_parser('discover-markets'); sub.add_parser('collect-books')
    p=sub.add_parser('review-rules'); p.add_argument('annotation',type=Path)
    p=sub.add_parser('train'); p.add_argument('--start',required=True); p.add_argument('--end',required=True)
    p=sub.add_parser('backtest'); p.add_argument('--revised-history',action='store_true')
    sub.add_parser('replay'); sub.add_parser('paper'); sub.add_parser('status'); sub.add_parser('export'); sub.add_parser('dashboard')
    p=sub.add_parser('settle'); p.add_argument('settlement',type=Path)
    args=parser.parse_args(argv); store=Store(args.data_dir)
    config=tomllib.loads(Path(args.config).read_text())
    try:
        if args.cmd=='fetch-data':
            from .data import fetch_tsa,parse_tsa
            if args.html:
                body=args.html.read_text(); store.append('raw',dict(url=str(args.html),body=body,local_import=True))
                count=store.ingest(parse_tsa(body),source='local_TSA_import_unverified')
                output(dict(new_versions=count,warning='Local import cannot establish live freshness'))
            else: output(fetch_tsa(store,args.url))
        elif args.cmd=='discover-markets':
            from .markets import discover
            output(discover(store))
        elif args.cmd=='collect-books':
            from .markets import collect_books
            output(collect_books(store))
        elif args.cmd=='review-rules':
            from .rules import review
            from .markets import latest_markets
            a=json.loads(args.annotation.read_text())
            r=next(r['payload'] for r in latest_markets(store) if r['payload']['market_id']==a['market_id'])
            output(store.append('market',review(r,a))['payload'])
        elif args.cmd=='train':
            from .model import distribution,days
            at=now(); history=store.asof(at)
            paths=distribution(history,days(args.start,args.end),config['research']['samples'],config['research']['seed'])
            row=dict(decision_at=at,input=history,targets=days(args.start,args.end),paths=paths)
            store.append('model',row); output(dict(paths=len(paths),targets=row['targets']))
        elif args.cmd=='backtest':
            from .backtest import walk_forward
            r=walk_forward(store,args.revised_history,config['research']['assumed_publication_lag_days'])
            Path('reports').mkdir(exist_ok=True)
            Path('reports/reanalysis_backtest.json' if args.revised_history else 'reports/latest_backtest.json').write_text(json.dumps(r,ensure_ascii=False,indent=2))
            output({k:v for k,v in r.items() if k!='rows'})
        elif args.cmd=='replay':
            from .replay import sensitivity
            r=sensitivity(store,config['execution']); store.append('replay',r); output(r)
        elif args.cmd=='paper':
            import fcntl
            from .paper import run_paper
            with (store.root/'paper.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX); output(run_paper(store,config['execution'],samples=config['research']['samples']))
        elif args.cmd=='settle':
            from .paper import Ledger
            a=json.loads(args.settlement.read_text())
            Ledger(store).settle(a['key'],a['payout'],now(),config['execution'],a['evidence']); output({'settled':a['key']})
        elif args.cmd=='export': output({'exported_snapshots':store.export()})
        elif args.cmd=='status':
            output({kind:(store.latest(kind) or {}).get('payload') for kind in
                    ('data_status','discovery_status','book_status','paper_run')})
        elif args.cmd=='dashboard':
            os.environ['TSA_DATA_DIR']=str(store.root.resolve())
            raise SystemExit(subprocess.call([sys.executable,'-m','streamlit','run',str(Path(__file__).with_name('dashboard.py'))]))
    except (ValueError,RuntimeError,ImportError,StopIteration,KeyError) as exc:
        store.append('command_error',dict(command=args.cmd,error=str(exc)))
        output({'ok':False,'error':str(exc),'signals_enabled':False}); return 1
    return 0


if __name__=='__main__': raise SystemExit(main())
