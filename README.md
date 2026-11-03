# Polymarket TSA 客流研究系统

这是公开数据、research / paper 专用的最小系统，没有钱包、签名或真实下单接口。TSA 指标是 **checkpoint throughput（安检通行次数）**，不等于独立旅客、航班或登机人数。

本次切换 mihomo 节点后，TSA、Gamma 和 PyPI 均已恢复 HTTP 200。已采集真实 TSA 2024-01-01 至 2026-11-01 共 1,036 天数据，完成完整依赖安装、DuckDB/Parquet 导出、模型训练、历史重分析和 Streamlit 验证。**尚未证明可交易的正收益**；历史重分析不能恢复当时信息集。最新市场扫描和研究结果见 [研究报告](reports/example_research_report.md)。最初的网络失败记录另存为 [初次报告](reports/initial_research_report.md)。

## 安装与启动

Python >=3.11，建议在有正常公网访问的环境安装：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[test]'
tsa fetch-data
tsa discover-markets
tsa collect-books
tsa status
tsa export
tsa dashboard
```

`.env.example` 仅列出可选数据目录；程序直接读取环境变量，不自动加载 .env。默认无需任何交易凭证。配置为 `config/default.toml`，全局选项放在子命令前：

```bash
tsa --data-dir data --config config/default.toml paper
tsa train --start 2026-11-05 --end 2026-11-11
tsa backtest
tsa backtest --revised-history
tsa replay
```

网络受限时可运行标准库核心并保存 journal；没有安装 DuckDB 时，不会假装生成 DuckDB/Parquet，也不会替换成其他数据库。

本次已经在恢复网络后验证完整安装及上述 CLI。`export` 已实际生成 DuckDB 和 Parquet；面板通过 Streamlit AppTest，且实际 HTTP 健康检查返回 200（测试服务已停止）。本次测试 **22 项全部通过**。

本机可在 mihomo 代理下采集及安装：

```bash
HTTP_PROXY=http://127.0.0.1:7890 HTTPS_PROXY=http://127.0.0.1:7890 .venv/bin/tsa fetch-data
HTTP_PROXY=http://127.0.0.1:7890 HTTPS_PROXY=http://127.0.0.1:7890 .venv/bin/tsa discover-markets
HTTP_PROXY=http://127.0.0.1:7890 HTTPS_PROXY=http://127.0.0.1:7890 .venv/bin/python -m pip install -e '.[test]'
.venv/bin/tsa dashboard
```

实际验证的包版本保存在 `requirements-verified.txt`，运行环境版本见 `reports/runtime-versions.json`。`reports/reanalysis_backtest.json` 与 `reports/latest_backtest.json` 分别保存修订后重分析和严格已观察信息集结果；两种结果不会互相覆盖。校准图见 [交互图](reports/calibration.html)，使用 Vega CDN 渲染，图表数据另存为 `reports/calibration.vl.json`。

## 数据与审计

- `data/journal/<uuid>.json` 为原子写入的不可变记录，保存原始 HTTP 正文、请求错误、标准化观测、规则、盘口、模型输入、信号和纸面账本。
- 每个观测保留统计日期、来源公布时间（未知为 null）、首次观察该版本时间、抓取时间、版本哈希及前一版本。相同当前值不重复写入；A→B→A 仍有三条时间记录。
- `Store.asof()` 只返回决策时已观察、且来源公布时间未晚于决策的版本。UTC 存时间；统计日期和规则时区独立，明确支持带 UTC 偏移的夏令时边界。
- 安装 DuckDB 后，`tsa export` 重建 `research.duckdb` 的 JSON 快照表、带类型的 throughput 表，以及两个 Parquet 文件。journal 是故障恢复来源，导出不改旧版本。原始 HTTP 大正文在 DuckDB/Parquet 快照中以相对路径 body_ref、SHA-256 和字节数索引，完整正文保留在不可变 journal，避免重复存储全站响应。导出小批次构建临时数据库并设置 512MB 数据库缓存限制，全部成功后替换派生文件。迁移数据时须连同 journal 一起保留。
- TSA HTML 只读取明确日期旁边的本年人数列。旧年对比列可能按星期对齐，绝不把它误当作同一行的日历日期。
- 解析结构异常、冲突重复、异常值会拒绝该响应。每次失败记录状态，指数退避，支持数字 Retry-After；公开接口串行限速 1 请求/秒。403 不反复请求。
- 默认抓当前页。可用 `tsa fetch-data --url https://www.tsa.gov/travel/passenger-volumes/2025` 指定历史页，多次 `--url` 顺序抓取；历史地址是否可用以实际响应为准。
- `--html saved.html` 支持离线审计导入，标记来源未经在线验证，不建立实时新鲜度；paper 拒绝混有此类未验证来源的信息集。不要将合成数据导入实际数据目录。

## 市场与规则

`discover-markets` 对 `/markets/keyset?closed=false&limit=100` 逐页遍历，使用 `next_cursor` → `after_cursor`。页结构错误、游标循环、页数上限或网络失败均标记扫描不完整，输出 `unknown`。 大规模扫描中断后，可用 `scripts/resume_market_scan.py` 验证已保存游标链并续扫；它复用连接且最多每秒 4 次请求，不跳页。当前动态清单扫描不是全站同一瞬间的原子快照。只有完整扫描且没有航空客流候选才输出 `no_tradable_markets`（面板显示“无可交易市场”）。候选状态不代表具备真实深度。

筛选要求完整 description 同时包含 TSA 官方数据链接和 checkpoint throughput，排除电竞缩写误匹配。任意一天/任意日期路径型合约标记 `unsupported_path`。其余只做保守字段提取，**不会自动批准规则**。

审核流程：

1. 从保存的市场快照读取完整原文和 rules_version。
2. 根据 `config/review.example.json` 填写真实的日期、时区、截止、边界、修订与特殊结算处理，说明证据和审核人。
3. `tsa review-rules reviewed.json`。只有与当前规则版本匹配的完整审核才可批准。元数据刷新保留规则未变的审核；规则变化使审核失效。

示例文件只是格式说明，不代表真实市场。`no_trade` 的含义是只估值正常二元支付，在缺失/取消/Other 情况中不持仓；如果规则的异常状态有实质概率，应保留待审核。首版只支持整数精确比较及二元 0/1 支付；特殊支付、其他舍入、无法核实的边界均拒绝，不猜测。不会把不穷尽的区间概率强制归一化。

`collect-books` 读取每个 YES/NO token 的真实 `/book` 深度、时间戳、最小数量和 tick，保存全部快照。费用读取当前 Gamma `feesEnabled`、`feeSchedule`；费率未知或指数不是已支持的 1 时拒绝信号。未启用费用必须是明确的 false，不能把字段缺失当作免费。还同时检查 Gamma 最小金额与 CLOB 最小数量，取保守约束。

## 模型与概率验证

可解释基线：最近八个同星期日均值、最近四周相对之前四周的趋势（限制外推幅度）、前一年对齐值乘近期同比。普通日期按 364 天保留星期；固定日期节假日和感恩节等移动节假日按名称及前后位置对齐。包含主要联邦节假日，未处理全部学校假期、复活节或极端天气。

预测分布使用最多 180 个按日期推进计算的残差，按连续日期块抽样，多日共享一个残差块，保留误差相关性。未公布部分按完整路径求和，已知值直接加上；代码和测试覆盖“已知六天 1440 万、剩余一天需超过 210 万”的情况。种子固定，可复现。没有人为将每日独立概率相乘。

这一误差模型为首版近似：并非专门按每个提前期拟合的误差过程；远期与节假日分布需要实证校准后才能信任。节假日样本很少时不得解释为可靠优势。近期水平不是任意长预测区间的保证。

允许修订的合约需要修订不确定性。`contract_distribution` 支持共享修订冲击参数；**paper 当前没有经过验证的修订幅度估计，因此拒绝这类合约**。首次发布结算也必须有可核实的公布版本；历史页面首次抓到的数据不算首次发布值。这是有意保留的安全边界。

`backtest` 默认按已观察的信息集逐周推进，输出 1/3/7 天提前期、节假日/普通日、train/validation/test 分组的 MAE、Brier、log loss、校准表，以及与简单星期基线的配对改善。阈值由当时星期基线取整到 10 万决定，是预测检验事件，不冒充真实合约。最后 20% 时间为测试集，中间 20% 为验证集，没有使用测试集调阈值。按起点周（事件族）聚类重抽样估计改善不确定性，少于 10 族不报区间。

`--revised-history` 明确为修订后历史重分析，假设统计日期后两天可得。它不能恢复真实首次发布时间/修订信息集，不能作为严格历史实盘回测。批量抓到历史页后，严格模式对过去会自然得到零样本。真实的同期市场预测比较需要同规则、同时间的预测及市场参考概率；首版没有匹配数据时报告 null 和原因，不借用网页概率。

## 执行与 paper

以 asks 从低到高按目标数量计算 VWAP，逐档计算 `shares × current_fee_rate × p × (1-p)`，费用保守向上取到 0.00001。YES 正常预期收益为 p−VWAP−fee/share，NO 使用 1−p。VWAP 已含深度冲击，不重复扣；额外价格压力仅表示执行延迟假设。

信号要求：已审核规则、新鲜元数据、新鲜成功抓取且统计日期未过期的来源、真实新鲜盘口、足量、费用可知；固定概率折减与延迟价格压力后优势仍超过安全余量。默认 8 个百分点概率折减是**配置压力假设，不是统计置信区间**。模型一致性未用于置信度。

`paper` 每次运行推进旧订单，然后估值并登记新意向；执行延迟后必须取得新的盘口快照才允许成交。无后续盘口会超时取消，不用旧盘口假设成交。支持限价后深度不足、撤单、部分入场、支付双边费用的提前全部退出（Python `Ledger.exit`；部分退出拒绝），以及人工核实结算后的资金延迟释放。

事件族和统计日期重叠共同限制敞口；不同分档不能绕开风险限制。按最坏每份 1 美元预留 pending 资金；持仓使用实际占款。重复市场/规则/方向意向去重，状态持久化；CLI paper 用文件锁。并行外部写入/多进程采集尚未作为生产运行方式支持。

纸面结算只允许完整人工证据、截止后、0/1 支付：

```json
{"key":"ACTUAL_ORDER_KEY","payout":1,"evidence":"实际结算记录和来源"}
```

```bash
tsa settle settlement.json
```

账本回撤目前按已结算/退出的已实现收益计算，未对未平仓持仓逐时盯市，输出 `drawdown_basis` 明确标注；不能将它当作完整组合净值回撤。自动结算事件抓取、部分退出、真实队列位置、精确逐笔撤单轨迹尚未实现。`replay` 只使用实际记录的历史盘口按时间重放，输出收益、回撤、成交率、资金峰值和持有时间，提供基础/30秒延迟/3美分价格压力/15百分点概率折减场景。没有盘口时这些收益保持空值。重放不会把人工结算输入自动转换成已知未来结算，完整收益回放还需要补充历史结算事件。

## 测试及面板

`PYTHONPATH=src python -m pytest -q` 覆盖可用时间与修订、夏令时、闰日、区间边界、累计预测、连续误差块、费率/VWAP、深度、重复信号、相关敞口、延迟成交、取消、结算占款、分页、退避和无盘口保护。DuckDB/Parquet 集成测试在依赖存在时运行，否则明确 skip。

Streamlit 提供数据状态、原始规则、分布、接受/拒绝原因、持仓收益及分组校准图。当前没有实际数据时只显示状态，不制造示例预测或资金曲线。建议先恢复依赖和数据访问，再长期定时采集；目前不应将这个研究原型用于真钱交易。
