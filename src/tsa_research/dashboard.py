import streamlit as st
from tsa_research.store import Store
from tsa_research.paper import Ledger

st.set_page_config(page_title='TSA Research',layout='wide')
st.title('TSA checkpoint throughput · 研究与纸面交易')
s=Store()
st.caption('公开数据 · 无真实下单 · checkpoint throughput 不代表独立旅客人数')
status=s.latest('discovery_status')
if not status or not status['payload']['ok']: st.warning('市场状态无法确认；禁止交易信号')
elif status['payload']['status']=='no_tradable_markets': st.info('无可交易市场')
else: st.info('发现候选市场；仅审核通过的规则允许估值')
tabs=st.tabs(['数据状态','合约规则','预测分布','信号','模拟持仓及收益','验证与校准'])
with tabs[0]:
    for kind in ('data_status','discovery_status','book_status'):
        st.write(kind); st.json(s.latest(kind) or {})
with tabs[1]:
    for r in s.rows('market'): st.json(r['payload'])
with tabs[2]:
    f=s.latest('forecast') or s.latest('model')
    if f:
        p=dict(f['payload']); st.write({k:v for k,v in p.items() if k not in ('input','totals','paths')})
        if 'totals' not in p:
            p['totals']=[sum(path) for path in p['paths']]
            st.caption('研究模型的区间累计分布；尚未关联通过审核的合约或交易信号')
        from collections import Counter
        counts=Counter(round(v/100000)*100000 for v in p['totals'])
        st.bar_chart([{'checkpoint_throughput':k,'samples':v} for k,v in sorted(counts.items())],x='checkpoint_throughput',y='samples')
    else: st.info('无有效预测')
with tabs[3]: st.json((s.latest('paper_run') or {}).get('payload',{}))
with tabs[4]: st.json(Ledger(s).metrics()); st.json(Ledger(s).orders())
with tabs[5]:
    b=s.latest('backtest')
    if b:
        st.write(b['payload']['mode']); st.json(b['payload']['metrics'])
        st.dataframe(b['payload']['calibration'])
        if b['payload']['calibration']:
            st.scatter_chart(b['payload']['calibration'],x='predicted',y='observed',color='group')
        st.caption('校准表按提前期、节假日和时间划分；预测验证不等于交易回放')
    else: st.info('暂无预测验证；不显示推测收益')
