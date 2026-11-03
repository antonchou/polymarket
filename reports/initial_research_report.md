# TSA 策略首版实际运行报告

日期：2026-11-03。模式：公开数据 research / paper。所有数字均来自实际命令或单元测试；无合成数据实证收益。

## 结论

**尚未发现可验证的正收益。预测优势和交易优势均无法证明。**

当前市场状态为 **无法确认（unknown）**。完整市场扫描未能连接 Gamma，因此不能确认有符合条件的开放 TSA 市场，也不能宣称“无可交易市场”。系统未生成交易信号或纸面订单。

## 环境与证据

初始仓库为空，没有发现仓库或父路径 AGENTS.md。Python 3.14.4，系统 pytest 可用。管理环境状态工具未提供，网络策略文件不存在；未尝试绕过网络限制。

- 执行器请求 Gamma 时域名解析失败；市场扫描 0 条、不完整。见 `discover-markets.json`。
- TSA 公开页面在执行器同样无法访问。网页检索工具访问当前页和 2025 历史页均返回 HTTP 403。见 `fetch-data.json`。
- pip 从配置源安装 duckdb 等依赖时 DNS 失败；没有下载成功。DuckDB/Parquet 导出和 Streamlit 服务未完成运行验证。见 `export.json`、`dashboard-startup.txt`。
- 文档已通过网页工具核实：游标分页、真实盘口字段、费用参数、限流。没有将搜索页概率当成成交价格。
- 检索出现已结算的 2025 年 TSA 累计与路径型合约，以及电竞队伍 TSA 的同名结果；这些不是当前可交易市场证据。

## 本次结果

| 项目 | 实际结果 |
|---|---|
| TSA 新增有效观测 | 0 |
| 完整扫描市场 | 未完成 |
| 取得真实盘口 | 0 |
| 可审核真实合约 | 0 |
| 严格历史预测样本/事件族 | 0 |
| MAE / Brier / log loss | 无法计算 |
| 同期市场预测比较 | 无匹配数据 |
| 接受信号/订单/成交 | 0 / 0 / 0 |
| 扣费收益/最大回撤/成交率 | null / null / null |
| 资金占用峰值 | 0（没有订单，不代表策略低风险） |
| 平均持有期 | null |
| 延迟/滑点/模型偏差敏感性 | 无盘口，无法计算交易结果 |

`backtest-summary.json` 与 `latest_backtest.json` 保存预测验证输出，`paper.json` 保存本次零信号结果，`replay.json` 明确标记没有历史盘口。空值不按零收益解释。无校准样本，因此没有可报告的实证校准图；面板在有样本时按组画图。

## 验证覆盖

核心测试：20 passed，1 skipped（缺少 DuckDB）。包括修订不覆盖、当时可用性、来源公布时间、夏令时、闰日、规则阈值、误匹配、累计已知部分、残差相关性、费用、深度、延迟、取消、结算资金占用、重复意向与相关风险、分页和重试。合成序列仅存在测试中，绝不计入上表。

项目已通过无依赖本地 editable 安装，`.venv/bin/tsa status` 正常启动（见 `install-core.txt`、`installed-status.json`），完整依赖安装仍失败。标准库 CLI 的 status、fetch-data、discover-markets、collect-books、backtest、paper、replay 均已执行。网络采集命令的执行不代表成功取得数据。export、dashboard 实际尝试后报告依赖缺失。train 无真实输入可训练；模型预测逻辑已用测试验证，未获得真实 TSA 样本预测验证。

## 假设和限制

默认美国东部统计日期须按实际规则审核，保存时间用 UTC。历史重分析假设公布滞后两天；严格模式不采用该假设回填 first_seen。模型固定参数，未用测试集调参。8pp 概率折减为压力假设，不是统计置信度。远期误差和节假日校准未验证。

首版支持正常二元单日与累计阈值/区间的分布计算；路径型明确排除。特殊结算、无法验证的首次发布版本、没有修订不确定性估计的合约均阻止信号。数据表不能重建未观察的历史修订。纸面成交依赖后续快照，仍无法观察两个快照间的精确撤单轨迹。

## 下一阶段最有价值的数据

1. 恢复官方 TSA 连续抓取：积累首次可见时间和每次修订，首先解决真实信息集与修订不确定性。
2. 恢复 Gamma 全量扫描及规则审核，定时记录 YES/NO 双边深度、市场费用与 tick 变更。
3. 积累真实结算事件和资金释放时间，使同一事件族的预测、盘口、成交和结果能完整对齐。
4. 获取至少跨节假日的足够事件族后，检验基线相对星期模型及同期市场参考概率的改善，再决定是否加入取消航班、天气数据。

官方资料：[Polymarket 发现市场](https://docs.polymarket.com/market-data/discover-markets)、[盘口](https://docs.polymarket.com/market-data/prices-order-books)、[费用](https://docs.polymarket.com/trading/fees)、[市场参数](https://docs.polymarket.com/market-data/market-details)、[限流](https://docs.polymarket.com/api-reference/rate-limits)、[TSA 原始数据](https://www.tsa.gov/travel/passenger-volumes)。核实日期同报告日期。

存档说明：本报告记录首次执行时的网络失败。后续已切换 mihomo 恢复访问；同名 JSON 附件可能已更新，原始失败记录仍保存在 data/journal。最新结果以 example_research_report.md 为准。
