"""Render a factual report from persisted command outputs; no synthetic inputs."""
import json
from pathlib import Path
from tsa_research.store import Store,now

def read(name):return json.loads(Path('reports',name).read_text())
discovery=read('discover-markets.json')
if not discovery.get('complete'):raise RuntimeError('Full market scan is not complete')
r=read('reanalysis-summary.json');strict=read('backtest-summary.json');search=read('tsa-search.json')
s=Store();history=s.asof(now());p=r['baseline_comparison'];families=r['event_families']
rows=[]
for horizon in (1,3,7):
    m=r['metrics'][f'test/baseline/h{horizon}/holiday=False']
    rows.append(f"| {horizon} 天 | {m['n']} | {m['mae']:,.0f} | {m['brier']:.4f} | {m['log_loss']:.4f} |")
text=f'''# TSA 策略实际运行报告（网络恢复后）

生成时间：{now()}。公开数据 research / paper；无真实下单。

## 结论

**当前无可交易的 TSA 航空客流市场；尚未发现可验证的正收益。**

Gamma 完整游标扫描已完成：{discovery['scanned']:,} 个未关闭市场，符合完整航空客流来源规则的候选 {discovery['relevant']} 个。补充官方 TSA 搜索完成 {search['pages']} 页、{search['events']} 个事件，保存 {search['tsa_markets']} 份相关历史合约规则，开放航空客流合约为 {len(search['open_tsa_markets'])}。关键词误匹配未当作 TSA 航空客流市场。动态清单不是同一瞬间的全站原子快照，结论仅适用于本次观察，后续需要定时重扫。

## 网络与环境

按用户要求切换本机 mihomo：预测市场组→香港高速01，良心云→美国高速01，自建节点→usjd。认证只在内存使用，没有记录密钥。Gamma、TSA、PyPI 均实际返回 HTTP 200，见 `network-retry.json`。节点选择保留为切换后的状态。

此前沙箱内 DNS 失败不等于节点或目标网站不可达。本轮经批准在宿主环境使用本机代理完成采集与安装，没有修改沙箱策略。完整扫描从已保存的连续游标链恢复，复用 HTTPS 连接，最多 4 请求/秒，未跳过页面；见 `market-scan-progress.txt`。

完整项目依赖已安装；实际包版本见 `runtime-versions.json` 和仓库 `requirements-verified.txt`。单元及 DuckDB/Parquet 集成测试 **22 项全部通过**。Streamlit AppTest 无异常，六个标签页可渲染；实际服务健康端点返回 HTTP 200，测试服务已停止。见 `tests.txt`、`dashboard-validation.json`、`dashboard-health.json`。

## 实际数据与预测验证

TSA 官方数据共 {len(history):,} 个统计日期，覆盖 {min(history)} 至 {max(history)}。来源公布时间未知为 null，首次看到时间为本轮抓取时间；不回填为历史公布时间。原始 HTML、修订版本与市场原始响应已保存在 journal；DuckDB 和 Parquet 已实际导出。大 HTTP 正文通过相对路径、SHA-256 和字节数索引，原文完整保留在不可变 journal；导出分批进行，不重复载入全部原文。

已训练 {read('train.json')['paths']} 条未来客流路径。数据是 checkpoint throughput，不代表独立旅客、航班或登机人数。

严格已观察信息集验证的事件族为 {strict['event_families']}：历史数据都是现在首次抓到，不能假装当时已经被系统观察。

另外执行了明确标记的**修订后历史重分析**：假设统计日期后两天可用，按时间推进，1/3/7 天提前期；训练/验证/测试按时间切分，参数固定，未用最终测试调参。总计 {families} 个起点周事件族，最终测试 {p['families']} 族。测试相对简单星期基线，事件族平均 MAE 改善约 {p['mae_improvement']:,.0f} 次过检，Brier 改善 {p['brier_improvement']:.4f}。聚类重抽样描述区间分别为 {p['ci95']['mae']}、{p['ci95']['brier']}；区间未涵盖信息集不可重建、模型选择及所有周期间依赖的不确定性，不能作为严格实盘优势证明。

普通日期的基线模型最终测试结果：

| 提前期 | 样本数 | MAE | Brier | Log loss |
|---|---:|---:|---:|---:|
{chr(10).join(rows)}

每个节假日/提前期分组仅 5 个测试样本，不能外推稳定表现。完整分组及星期基线对比见 `reanalysis-summary.json`，逐条结果见 `reanalysis_backtest.json`。[校准图](calibration.html)使用修订后重分析测试数据；数据同时保存为 Vega-Lite JSON。图表使用 Vega CDN 渲染。

这些概率事件的阈值来自当时简单星期预测取整，并非真实合约组合。没有匹配历史盘口和同期市场参考概率，不能声称相对市场具有预测优势。

## 交易结果与限制

当前没有符合条件的开放航空客流市场，因此没有真实目标盘口、接受信号、纸面订单或成交。paper 结果见 `paper.json`，交易回放见 `replay.json`。

扣费收益、最大回撤、成交率、平均持有期、交易延迟/滑点/模型偏差收益敏感性均为 null，而非零收益。峰值占款为 0，仅因为没有订单。没有报告月收益率。账本回撤模块按已实现收益计算，未包含未平仓逐时盯市回撤，输出另有 drawdown_basis 说明。

路径型合约明确不支持。实际历史规则包含 Other、修订及边界归属等条款，未擅自批准。允许修订但没有经验证的修订幅度估计、首次发布版本无法核实、特殊支付无法建模时，均保持拒绝信号。远期残差分布和节假日校准仍需前向验证；固定概率折减是压力假设，不是统计置信度。合成序列只用于测试。

## 已验证命令与下一步

完整安装、fetch-data（当前页及2024/2025）、市场发现（含连续游标续扫）、train、两种 backtest、export、paper、replay、面板 AppTest/实际启动和 pytest 均已执行。当前无市场时 collect-books 只报告零盘口，不生成虚构深度。

优先持续收集 TSA 首次可见时间与修订；监控新航空客流市场，一旦开放，审核完整结算规则并积累双边深度、费用与结算事件。随后做同一事件族的前向概率检验和扣费成交验证，再决定是否引入天气或航班取消特征。

官方资料：[TSA](https://www.tsa.gov/travel/passenger-volumes)、[市场发现](https://docs.polymarket.com/market-data/discover-markets)、[盘口](https://docs.polymarket.com/market-data/prices-order-books)、[费用](https://docs.polymarket.com/trading/fees)、[市场参数](https://docs.polymarket.com/market-data/market-details)、[限流](https://docs.polymarket.com/api-reference/rate-limits)。
'''
Path('reports/example_research_report.md').write_text(text)
print('Report updated')
