# Freqtrade 数字货币策略研究

统一使用 **Freqtrade + uv**。所有策略源码放在根目录 **repo/**，由根目录Git
管理；Freqtrade本体作为依赖装在.venv，源码与框架互不混放。运行前只复制
选中策略到user_data/strategies/，更新框架不会修改repo中的策略源码。
项目约定见[AGENTS.md](AGENTS.md)，策略介绍见[选择说明](docs/策略选择说明.md)。

## 目录

| 路径 | 用途 | Git |
| --- | --- | --- |
| repo/ | 7个IStrategy源码，完整中文注释 | 管理 |
| config/backtest.json | 无密钥的现货回测模板 | 管理 |
| scripts/ | 复制策略、调用Freqtrade、整理原生结果 | 管理 |
| ui/ | Next.js策略选择、参数表单、任务接口与结果查看 | 管理（node_modules/.next除外） |
| reports/ | 参数页面模板、实际参数和统计摘要 | 管理（日志除外） |
| pyproject.toml、uv.lock | 框架版本和依赖锁定 | 管理 |
| user_data/strategies/ | 运行时拷贝和原生参数JSON | 忽略 |
| user_data/postgres/ | PostgreSQL 私有集群，只保存5m OHLCV | 忽略 |
| user_data/market_data/、user_data/backtest_results/ | 临时聚合行情、Freqtrade原始结果 | 忽略 |
| user_data/data/ | 旧5m行情导入来源（保留原文件） | 忽略 |
| user_data/ui-runs/ | UI独立任务、运行副本、日志、回测结果 | 忽略 |
| .venv/、.cache/ | 依赖与缓存 | 忽略 |

## 使用uv

```sh
cd /Users/alex/quant
uv sync --locked
uv run freqtrade --version
uv run python scripts/run_backtest.py --prepare-only
uv run freqtrade list-strategies
uv run python -m unittest discover -s tests -v
```

Freqtrade当前锁定2026.9，Python支持3.12/3.13。修改策略只编辑repo中的源码，
不要编辑user_data运行副本。默认目录无需重复传--strategy-path，否则会重复扫描。
脚本仅调用Freqtrade，不实现独立回测、撮合或收益计算器。

## 页面选择策略、运行并查看结果

使用本地Next.js界面，不需要复制回测命令：

```sh
uv sync --locked
npm --prefix ui ci
npm --prefix ui run build
npm --prefix ui run start
```

打开 **http://127.0.0.1:3000/**，勾选策略、设置币种/区间/周期/资金/费用，
然后点击“运行回测”。S01/S02可调整窗口，其余三个使用源码默认参数。
页面会显示运行日志，完成后自动展示收益、回撤、胜率和交易数；记录保留，
刷新页面也能查看。已有的一年回测作为首条历史记录导入。

UI后端调用 `uv run --no-sync python scripts/run_backtest.py`，再由脚本调用
Freqtrade。实际回测仍由Freqtrade执行，不存在第二套回测引擎。
源码在repo，每个任务复制选定策略到独立运行目录；共用 PostgreSQL 5m 行情仓库，
仅允许一个UI任务；数据库按交易对加锁避免CLI重复下载。任务文件不入Git。
页面仅监听本机127.0.0.1；需要先完成uv同步，并确保启动服务器时PATH中有uv。
本地开发可用 `npm --prefix ui run dev`，源码及package-lock.json纳入根目录Git。

```sh
npm --prefix ui test
uv run python -m unittest discover -s tests -v
```

## S01 / S02 一年回测

旧双均线页面未找到，用户已授权新建参数页面和测试配置。新的默认口径：
Binance现货、BTC/USDT、1d、2025-10-12至2026-10-12（UTC终点不含）、
单边手续费0.1%、初始资金10000USDT、单笔1000USDT、最多一笔持仓。
S01为20/60均线，S02为20/10通道，固定10%止损，不设置ROI独立止盈。
这些是新测试假设，不声称复现旧报告。

```sh
uv run python scripts/run_backtest.py \
  --strategies S01 S02 \
  --exchange binance --pairs BTC/USDT \
  --timeframe 1d --start 2025-10-12 --end 2026-10-12 \
  --fee 0.001 --wallet 10000 --stake 1000 \
  --fast 20 --slow 60 --entry 20 --exit 10
```

命令行仍可用于自动化，会自动复制源码、写Freqtrade原生参数文件、下载额外
预热行情、分别回测并生成[旧静态报告](reports/index.html)及
[统计说明](reports/回测结果.md)。日常操作优先使用上述Next.js界面，
修改参数后点击“运行回测”生成新结果。原有静态报告仅保留作为历史记录。
下载失败或没有新Freqtrade结果时明确记录failed，不展示虚构结果。

首次使用无需密钥。模板dry_run=true，通知和API关闭，脚本只调用
 download-data/backtesting，不启动实盘。行情自动查库复用、仅补下载缺口。

## 更新Freqtrade

修改pyproject.toml中的Freqtrade版本，然后：

```sh
uv lock
uv sync --locked
uv run python scripts/run_backtest.py --prepare-only
uv run freqtrade list-strategies
uv run python -m unittest discover -s tests -v
```

策略文件不与框架源码混存；升级后仍须检查接口兼容性、lookahead-analysis、
recursive-analysis及回测差异。S06轮动和S07配对目前只有研究说明，未实现。

## MACD（S08）与回测UI

打开 http://127.0.0.1:3000/，选择S08。默认中线(12,26,9)，可选择短线
(6,12,9)、长线(19,39,9)，或分别修改快线、慢线和信号线。
信号周期默认1d，成交细化周期默认5m，使用Freqtrade原生timeframe-detail；
指标在日线收盘后产生信号，5分钟行情用于盘中撮合和止损，不重新计算日线信号。
默认区间2026-01-01至2026-10-12（UTC终点不含），只用已结束日K线。
Binance现货BTC/USDT，单边0.1%费用，10000USDT初始、1000USDT单笔。
固定10%止损为项目额外风控。实现来源中的基础金叉/死叉，不含未定义的背离过滤。

```sh
cd /Users/alex/quant/ui
npm ci
npm run build
npm run start -- --port 3000
```

命令行等价运行（项目根目录）：

```sh
UV_CACHE_DIR=/Users/alex/quant/.cache/uv uv run python scripts/run_backtest.py \
  --strategies S08 --start 2026-01-01 --end 2026-10-12 \
  --timeframe 1d --timeframe-detail 5m \
  --macd-fast 12 --macd-slow 26 --macd-signal 9
```

UI每次回测独立保存在user_data/ui-runs，不覆盖S01/S02基线记录。
自动检查区间与预热覆盖，仅补下载缺失5m行情；不完整时明确失败。
修改区间、周期或参数后自动重新检查覆盖，无需手动选择是否复用。
本次MACD结果快照见[报告](reports/macd/回测结果.md)及[验证](reports/MACD验证记录.md)。

## Ant Design 回测工作台

UI使用Ant Design 6及Next.js样式注册，入口仍为 http://127.0.0.1:3000/。

- **运行回测**（`#run`）：下拉框单选策略，设置市场、区间和策略参数，
  资金/费用可展开调整。点击运行后显示本次进度和真实结果，任务自动保存。
- **历史回测**（`#history`）：按策略、交易对或日期搜索，按状态筛选；
  点击名称/箭头打开历史详情，查看结果、实际参数与日志。
- 详情地址保留记录ID，刷新和浏览器后退可恢复。
  “使用此参数”将历史配置带回运行表单，不自动执行回测；旧多策略记录使用首个策略。
- 运行页通过当前会话恢复本次任务；打开历史详情不会把旧结果展示为本次新测试。
- 响应式菜单与表单适配窄屏，原有数据与Freqtrade运行脚本继续复用。

UI验证记录见[验证记录](reports/验证记录.md)。

测试结果包含逐笔交易记录：UTC入场/退出时间、成交价格、收益和退出原因；
支持排序、分页，展开可查看投入、成交数量、持仓时长、信号标记和费率。
现有成功回测已从原始Freqtrade ZIP补齐明细，无需重跑。

## MACD可选增强

S08运行表单提供四个独立开关，默认全部关闭；启用后展开对应参数。
同一次入场需要短周期金叉和所有启用过滤器同时满足，退出仍为短周期死叉或10%止损。
被过滤的金叉不会在条件后来满足时补买，需等下一次金叉。

| 选项 | 默认参数 | 确切规则 |
| --- | --- | --- |
| 多时间框架 | 长1d、长MACD12/26/9、DIF>DEA；启用时日线入场改为1h | 长K线收盘后判断方向，短周期MACD金叉入场；长趋势可选DIF>0或两个条件同时满足 |
| RSI区间过滤 | 14、30~70 | 入场信号周期RSI处于包含边界的区间；下限0可只排除超买 |
| 均线趋势过滤 | EMA200 | 入场收盘价严格高于EMA/SMA，窗口可调 |
| 成交量确认 | 前20根均量、1.2倍 | 当前已结束K线量≥此前均量×倍数，均量排除当前K线 |

长周期支持1d/4h且必须严格大于入场周期，5m成交细化仍只负责撮合。
长/短MACD窗口独立；RSI、均线、均量窗口以入场信号周期K线数计。
开启或关闭多周期后应核对入场周期，关闭开关不自动恢复日线。
运行脚本为每个行情周期分别下载、预热并检查覆盖，复用行情不足时直接失败。
框架对主周期和informative数据共用startup_candle_count，预热取所有开启指标需求的最大值。
EMA200需要1000根预热；多周期同时开启时长周期也下载该数量，可能需要较长历史。
每次实际开关和参数写入原生参数JSON、job配置和审计报告，旧记录不受新默认值影响。
这些过滤规则是本库对资料建议的具体量化实现，不保证改善胜率或收益。

命令行举例（仅说明参数，增强版本尚未做真实绩效回测）：

```sh
UV_CACHE_DIR=/Users/alex/quant/.cache/uv uv run python scripts/run_backtest.py \
  --strategies S08 --start 2026-01-01 --end 2026-10-12 \
  --timeframe 1h --timeframe-detail 5m \
  --macd-mtf --macd-trend-timeframe 1d --macd-trend-mode dif_dea \
  --macd-trend-fast 12 --macd-trend-slow 26 --macd-trend-signal 9 \
  --macd-rsi --macd-rsi-period 14 --macd-rsi-min 30 --macd-rsi-max 70 \
  --macd-ma --macd-ma-type ema --macd-ma-period 200 \
  --macd-volume --macd-volume-window 20 --macd-volume-multiplier 1.2
```

## S09：BTC信号交易ETH

在回测UI选择S09，唯一交易对象是ETH/USDT，唯一方向信号来源是BTC/USDT。
BTC不下单，ETH不计算MACD或其他方向信号。

- BTC MACD金叉买ETH，BTC MACD死叉卖ETH，默认日线(12,26,9)。
- BTC信号周期可选1h/4h/1d，快线、慢线和信号线参数可调。
- ETH执行周期不得长于BTC信号周期，默认1h；5m细化ETH的成交/止损。
- 只在BTC K线结束并首次可见时触发一次，止损后等待下一次BTC金叉。
- 固定10% ETH止损仍有效，可先于BTC死叉退出；没有ETH死叉或ROI退出。
- 脚本分别下载并检查BTC信号行情与ETH成交行情，不按BTC价格撮合ETH。

```sh
UV_CACHE_DIR=/Users/alex/quant/.cache/uv uv run python scripts/run_backtest.py \
  --strategies S09 --pairs ETH/USDT --timeframe 1h --timeframe-detail 5m \
  --start 2026-01-01 --end 2026-10-12 \
  --btc-timeframe 1d --btc-fast 12 --btc-slow 26 --btc-signal 9
```

旧版S09（BTC趋势过滤+ETH金叉）历史记录保留原规则，不作为此版的回测结果。
使用旧记录参数重跑S09时会采用当前BTC独立信号规则，ETH MACD旧参数不参与判断。
当前S09默认参数已完成2026-01-01至2026-10-12真实行情回测，见[报告](reports/s09/回测结果.md)。
BTC/ETH可能解耦，BTC信号并不保证适合ETH；选择参数后再测试并做原生未来数据/递归分析。

## 公开行情代理

Freqtrade的同步及异步CCXT HTTPS请求显式使用`http://127.0.0.1:7890`代理。
配置位于config/backtest.json的ccxt_config/ccxt_async_config.httpsProxy；
运行脚本复制到每次任务配置，切换交易所时也保留代理。代理服务需已启动。
只影响项目公开行情请求，不修改系统网络设置，不连接交易密钥。

## 可复用策略参数与BTC策略选择

S09增加“BTC信号策略”单选下拉框，目前仅提供已实现的MACD与双SMA均线。
默认仍为MACD，不改变此前MACD回测的规则；历史缺btc_strategy字段时按MACD读取。

- MACD快捷组合：短线6/12/9、中线12/26/9、长线19/39/9，支持自定义。
  相同组件用于S08主周期、S08长周期过滤及S09的BTC MACD。
- 双均线快捷组合：短线5/20、中线20/60、长线50/200，支持自定义。
  相同组件用于S01与S09的BTC双均线。快捷参数仅用于研究，不代表已经比较过收益。
- S09双SMA规则沿用S01：BTC短SMA>长SMA时买ETH，<=时退出；
  每根已结束BTC K线判断一次，止损后下一根BTC仍多头时可重新入场。
  这不同于MACD等待下一次金叉，不把两者都描述为相同交叉策略。
- S02通道参数也已独立成组件。UI组件在ui/components/strategy-parameters.js，
  快捷参数定义在ui/lib/parameter-presets.mjs。每个实例有独立id与值，不互相覆盖。
- BTC策略类型与对应窗口写入任务配置、原生参数JSON与报告，历史还原对应参数。

选择S09双均线的命令行示例：

```sh
UV_CACHE_DIR=/Users/alex/quant/.cache/uv uv run python scripts/run_backtest.py \
  --strategies S09 --pairs ETH/USDT --timeframe 1h --timeframe-detail 5m \
  --start 2026-01-01 --end 2026-10-12 \
  --btc-strategy sma --btc-timeframe 1d --btc-ma-fast 20 --btc-ma-slow 60
```

双SMA模式本次只完成代码与原生加载检查，没有运行真实收益回测；此前S09报告均为MACD模式。

## PostgreSQL 5m 行情仓库

页面已移除“复用已下载行情”选项。数据库仅保存现货5m OHLCV，主键为交易所、
交易对和UTC开盘时间；同一BTC/ETH数据可供不同策略、区间和周期复用。
运行时先导入已有 `user_data/data/<exchange>/*-5m.feather`（内容未变则跳过），
逐根检测区间内缺口，包括策略预热；只用 Freqtrade `download-data --timeframes 5m`
补下载缺口，继续沿用7890代理。下载失败或仍有缺口就停止，不静默填补。

PostgreSQL 14及以上支持本项目使用的 `date_bin`。默认使用本项目的私有本地
PostgreSQL 17集群，不需要TimescaleDB扩展；通过SQL生成1h/4h/1d的首开、最高、
最低、末收与成交量和。UTC对齐、只导出完整桶，当前未收盘5m不入库。
派生Feather只是单次任务的Freqtrade输入，不作为永久行情库；收益与撮合仍由
Freqtrade原生引擎完成，回测记录含查库/补下载范围及最终输入文件SHA256。

macOS首次安装和启动：

```sh
brew install postgresql@17
uv sync --locked
uv run python scripts/postgres_service.py start
uv run python scripts/postgres_service.py status
# 无回测运行时可停止，下次任务自动启动
uv run python scripts/postgres_service.py stop
```

默认集群在 `user_data/postgres/`，socket在 `.cache/postgres-socket/`（权限700），
只接受私有Unix socket，不监听TCP，不修改系统服务。首次任务可自动初始化/启动。
其他安装路径用 `QUANT_PG_BIN` 指定含initdb/pg_ctl的目录。
已有数据库可设置 `QUANT_DATABASE_URL` 后启动UI，例如
`postgresql://quant:密码@127.0.0.1:5432/quant`；此时不创建或启动本地集群。
目标库需预先创建、PostgreSQL>=14，并授权创建表/索引及读写权限。连接串不要提交Git，
也不会写入回测审计。停用外部数据库时请自行管理其服务。

只准备用户指定策略所需行情，不运行性能回测：

```sh
uv run python scripts/run_backtest.py --strategies S08 --timeframe 1d \
  --timeframe-detail 5m --start 2026-01-01 --end 2026-10-12 --prepare-data-only
QUANT_TEST_POSTGRES=1 uv run python -m unittest discover -s tests -p test_market_store.py -v
```

首次缺少历史5m时下载量会大于直接下载日线，但后续只补缺失区间。
旧高周期文件不能反推5m，因此不会用旧日线伪造更细粒度行情。

## 可调固定止损

回测表单的“风控参数”支持设置止损百分比，输入正数，例如5表示5%。
范围0.01%至99.99%，普通策略默认10%，S03保留5%默认；切换策略时恢复其默认，
可在运行前修改。S09的止损应用于实际交易的ETH，BTC仍独立决定方向信号。
运行摘要、结果和历史参数会记录所选值，“使用此参数”可恢复设置；旧记录缺少
该字段时按原策略默认显示，历史结果不改写。

脚本支持 `--stoploss-percent 5`，将其转换为Freqtrade原生配置 `stoploss=-0.05`；
由框架覆盖策略类的默认止损并执行。CLI省略该选项时沿用各策略源码默认值。
止损不是亏损封顶承诺，实际损失还受手续费及跳空影响；本功能不改变买卖信号。

## S09 可选 ATR 偏离控制

S09的MACD及双均线模式都支持“ATR偏离控制”，默认关闭，旧记录恢复为关闭。
开启后按BTC信号周期计算 `(BTC收盘价-EMA)/ATR`，超过阈值时仍按BTC买入信号交易ETH，
但初始投入缩小为计划金额的指定比例。默认EMA20、ATR14、阈值2、过热投入30%；
阈值相等时正常投入。EMA/ATR尚未就绪或ATR为0时不入场。

退出与用户配置的固定止损保持原规则；没有ATR止损、等待回落或自动加仓。
减仓标签随已结束BTC信号K线生成，由Freqtrade原生custom_stake_amount执行；
若缩小后的金额低于交易所最小下单额则跳过，不自动放大试探仓位。
此控制不识别未来顶部，也不判断ETH自身是否过热；未验证收益改善。

命令行选项：`--btc-atr-enabled --btc-atr-period 14 --btc-atr-ema-period 20
--btc-atr-threshold 2 --btc-atr-stake-percent 30`。ATR周期2~100、EMA周期2~400、
阈值0.1~20、仓位比例1~100%，仅适用于S09；未传开关时完全沿用原始仓位/信号。
预热自动覆盖EMA与ATR递归初始化，行情继续通过PostgreSQL复用和缺口补齐。
参数保存到任务/运行审计，结果标签显示ATR设置；交易详情的入场信号带
`_atr_reduced`表示本次按比例减仓，实际投入金额可展开交易明细查看。

每次UI回测的Run ID显示在进度/结果顶部，可复制完整ID；历史列表显示短ID，
复制时仍复制完整ID，也支持用完整或部分ID搜索。交易表直接显示Freqtrade实际投入
USDT和ATR减仓标记，入场/退出时间统一显示UTC日期及小时分钟。
日线执行的入场可能全部为00:00，这是回测实际成交时间，5m细化不产生新的方向信号。

## S09历史行情缺口：明确跳过交易

用户已授权遇到缺口跳过不交易。S09开启5m细化时，下载后仍缺的5m区间
不会让整个任务失败；缺口写入运行审计，结果显示警示，可展开“行情覆盖与缺口记录”。
BTC方向指标只用完整的高周期真实K线，原生加载器的零成交量占位不参与BTC EMA/ATR/MACD。
ETH执行高周期可聚合仍存在的真实子K线（单独统计不完整桶），逐笔撮合仍使用5m行情。
数据库不保存占位K线；原生加载器为时间对齐生成的缺失5m占位不得成交，
策略通过confirm_trade_entry/confirm_trade_exit禁止这些实际缺口时刻的买卖。

缺口前已有持仓不会凭空消失；缺口内被阻止的卖出/止损请求由custom_exit在恢复后
交回Freqtrade按可用行情执行，标签gap_resume_exit。缺口内无法验证止损封顶，
结果不可当作无缺口行情回测。回测终点本身缺ETH行情时仍失败，避免用占位价结算。
未启用5m细化或其他策略仍采用严格完整性检查，不能沿用未保护的缺口处理。
旧失败记录保留原状态，但页面现在直接显示审计中的具体错误，不只显示退出码。
