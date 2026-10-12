"""复制根目录repo策略并调用Freqtrade；不实现撮合、收益计算或回测引擎。

参数页面生成本脚本的命令。运行参数会写入运行配置与审计记录，
S01/S02/S08窗口用Freqtrade原生参数文件加载，策略源码始终留在repo。
"""

import argparse
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import shutil
import subprocess
import pandas as pd
from freqtrade import __version__


ROOT = Path(__file__).resolve().parents[1]
NAMES = {"S01": "S01SmaTrend", "S02": "S02DonchianBreakout",
         "S03": "S03BollingerReversion", "S04": "S04RsiPullback",
         "S05": "S05TimeSeriesMomentum", "S08": "S08MacdCross", "S09": "S09BtcTrendEth"}


def write_json(path, value):
    """运行记录/参数以UTF-8写入，页面和报告可复用同一口径。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strategies", nargs="+", choices=NAMES, default=["S01", "S02"])
    parser.add_argument("--exchange", default="binance")
    parser.add_argument("--pairs", nargs="+", default=["BTC/USDT"])
    parser.add_argument("--timeframe", choices=["1d", "4h", "1h"], default="1d")
    parser.add_argument("--timeframe-detail", choices=["5m"], help="使用5分钟K线细化撮合，指标仍按信号周期计算")
    parser.add_argument("--start", default="2025-10-12")
    parser.add_argument("--end", default="2026-10-12")
    parser.add_argument("--fee", type=float, default=0.001, help="单边比例，0.001=0.1%%")
    parser.add_argument("--wallet", type=float, default=10000)
    parser.add_argument("--stake", type=float, default=1000)
    parser.add_argument("--fast", type=int, default=20)
    parser.add_argument("--slow", type=int, default=60)
    parser.add_argument("--entry", type=int, default=20)
    parser.add_argument("--exit", type=int, default=10)
    parser.add_argument("--macd-fast", type=int, default=12)
    parser.add_argument("--macd-slow", type=int, default=26)
    parser.add_argument("--macd-signal", type=int, default=9)
    parser.add_argument("--macd-mtf", action="store_true")
    parser.add_argument("--macd-trend-timeframe", choices=["4h", "1d"], default="1d")
    parser.add_argument("--macd-trend-mode", choices=["dif_dea", "zero", "both"], default="dif_dea")
    parser.add_argument("--macd-trend-fast", type=int, default=12)
    parser.add_argument("--macd-trend-slow", type=int, default=26)
    parser.add_argument("--macd-trend-signal", type=int, default=9)
    parser.add_argument("--macd-rsi", action="store_true")
    parser.add_argument("--macd-rsi-period", type=int, default=14)
    parser.add_argument("--macd-rsi-min", type=int, default=30)
    parser.add_argument("--macd-rsi-max", type=int, default=70)
    parser.add_argument("--macd-ma", action="store_true")
    parser.add_argument("--macd-ma-type", choices=["ema", "sma"], default="ema")
    parser.add_argument("--macd-ma-period", type=int, default=200)
    parser.add_argument("--macd-volume", action="store_true")
    parser.add_argument("--macd-volume-window", type=int, default=20)
    parser.add_argument("--macd-volume-multiplier", type=float, default=1.2)
    parser.add_argument("--btc-timeframe", choices=["1h", "4h", "1d"], default="1d")
    parser.add_argument("--btc-mode", choices=["cross"], default="cross")
    parser.add_argument("--btc-fast", type=int, default=12)
    parser.add_argument("--btc-slow", type=int, default=26)
    parser.add_argument("--btc-signal", type=int, default=9)
    parser.add_argument("--btc-exit", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--prepare-only", action="store_true", help="只复制策略、生成配置，不联网回测")
    parser.add_argument("--skip-download", action="store_true", help="复用已下载行情")
    parser.add_argument("--output-dir", help="UI任务独立输出目录（项目user_data/ui-runs内）")
    args = parser.parse_args()
    output_dir = ROOT / "reports"
    runtime_dir = ROOT / "user_data"
    if args.output_dir:
        output_dir = Path(args.output_dir).resolve()
        if not output_dir.is_relative_to((ROOT / "user_data/ui-runs").resolve()):
            parser.error("UI输出目录必须位于user_data/ui-runs内")
        runtime_dir = output_dir / "user_data"
    output_dir.mkdir(parents=True, exist_ok=True)
    start, end = date.fromisoformat(args.start), date.fromisoformat(args.end)
    if start >= end or not 0 <= args.fee < 0.1 or not 0 < args.stake <= args.wallet * 0.99:
        parser.error("检查日期、费用和资金：起点<终点，0<=fee<0.1，stake<=wallet*0.99")
    if not 2 <= args.fast < args.slow <= 400 or not 1 <= args.exit <= args.entry <= 400 or args.entry < 2:
        parser.error("窗口需2<=fast<slow<=400，1<=exit<=entry<=400，entry>=2")
    if any(not pair.endswith("/USDT") or ":" in pair for pair in args.pairs):
        parser.error("当前模板只接受USDT计价现货，例如BTC/USDT，不接受永续符号")
    if not 2 <= args.macd_fast < args.macd_slow <= 400 or not 2 <= args.macd_signal <= 100:
        parser.error("MACD需2<=fast<slow<=400，2<=signal<=100")
    if "S05" in args.strategies and args.timeframe != "1d":
        parser.error("S05的UTC月末条件仅支持1d")

    minutes_by_tf = {"1d": 1440, "4h": 240, "1h": 60, "5m": 5}
    enhancements = args.macd_mtf or args.macd_rsi or args.macd_ma or args.macd_volume
    if enhancements and "S08" not in args.strategies:
        parser.error("MACD增强选项只适用于S08")
    if args.macd_mtf and minutes_by_tf[args.macd_trend_timeframe] <= minutes_by_tf[args.timeframe]:
        parser.error("趋势周期必须长于入场信号周期，例如日线趋势+小时线入场")
    if not 2 <= args.macd_trend_fast < args.macd_trend_slow <= 400 or not 2 <= args.macd_trend_signal <= 100:
        parser.error("长周期MACD窗口无效")
    if not 2 <= args.macd_rsi_period <= 100 or not 0 <= args.macd_rsi_min < args.macd_rsi_max <= 100:
        parser.error("RSI周期需2~100，下限<上限，阈值需0~100")
    if not 2 <= args.macd_ma_period <= 400 or not 2 <= args.macd_volume_window <= 400 or not 0.1 <= args.macd_volume_multiplier <= 10:
        parser.error("均线/均量窗口需2~400，成交量倍数需0.1~10")
    if "S09" in args.strategies:
        if not args.btc_exit:
            parser.error("S09以BTC死叉退出，不支持关闭BTC退出信号")
        if args.pairs != ["ETH/USDT"]:
            parser.error("S09只交易ETH/USDT；BTC/USDT仅作为参考行情")
        if minutes_by_tf[args.btc_timeframe] < minutes_by_tf[args.timeframe]:
            parser.error("BTC趋势周期不能短于ETH入场周期")
    if not 2 <= args.btc_fast < args.btc_slow <= 400 or not 2 <= args.btc_signal <= 100:
        parser.error("BTC MACD窗口无效")
    # 主周期和长周期使用框架统一startup_candle_count；下载与审计都按这一数量预热。
    macd_warmup = max(5 * (args.macd_slow + args.macd_signal),
                      5 * (args.macd_trend_slow + args.macd_trend_signal) if args.macd_mtf else 0,
                      5 * args.macd_rsi_period + 1 if args.macd_rsi else 0,
                      args.macd_ma_period * (5 if args.macd_ma_type == "ema" else 1) if args.macd_ma else 0,
                      args.macd_volume_window + 1 if args.macd_volume else 0)
    config = json.loads((ROOT / "config/backtest.json").read_text())
    config.update(timeframe=args.timeframe, fee=args.fee, dry_run_wallet=args.wallet,
                  stake_amount=args.stake)
    config["exchange"].update(name=args.exchange, pair_whitelist=args.pairs)
    if args.exchange != "binance":
        # Binance只读域名和市场加载选项不能套用到其他交易所。
        for key in ("ccxt_config", "ccxt_async_config"):
            proxy = config["exchange"][key].get("httpsProxy")
            config["exchange"][key] = {"enableRateLimit": True}
            if proxy:
                config["exchange"][key]["httpsProxy"] = proxy
    warmup = max([args.slow if "S01" in args.strategies else 0,
                  args.entry + 1 if "S02" in args.strategies else 0,
                  20 if "S03" in args.strategies else 0,
                  macd_warmup if "S08" in args.strategies else 0,
                  5 * (args.btc_slow + args.btc_signal) if "S09" in args.strategies else 0,
                  400 if {"S04", "S05"}.intersection(args.strategies) else 0])
    # 对所选策略统一预热长度，避免比较时评估起点不同。
    config["startup_candle_count"] = warmup
    destination = runtime_dir / "strategies"
    destination.mkdir(parents=True, exist_ok=True)
    params = {"S01": {"buy": {"fast_window": args.fast, "slow_window": args.slow}},
              "S02": {"buy": {"entry_window": args.entry}, "sell": {"exit_window": args.exit}},
              "S08": {"buy": {"macd_fast": args.macd_fast, "macd_slow": args.macd_slow,
                               "macd_signal": args.macd_signal,
                               "mtf_enabled": args.macd_mtf, "trend_timeframe": args.macd_trend_timeframe,
                               "trend_mode": args.macd_trend_mode, "trend_fast": args.macd_trend_fast,
                               "trend_slow": args.macd_trend_slow, "trend_signal": args.macd_trend_signal,
                               "rsi_enabled": args.macd_rsi, "rsi_period": args.macd_rsi_period,
                               "rsi_min": args.macd_rsi_min, "rsi_max": args.macd_rsi_max,
                               "ma_enabled": args.macd_ma, "ma_type": args.macd_ma_type,
                               "ma_period": args.macd_ma_period, "volume_enabled": args.macd_volume,
                               "volume_window": args.macd_volume_window,
                               "volume_multiplier": args.macd_volume_multiplier}},
              "S09": {"buy": {"btc_timeframe": args.btc_timeframe, "btc_fast": args.btc_fast,
                               "btc_slow": args.btc_slow, "btc_signal": args.btc_signal}}}
    copied = {}
    for strategy_id in args.strategies:
        name = NAMES[strategy_id]
        source = ROOT / "repo" / f"{name}.py"
        shutil.copy2(source, destination / source.name)
        copied[source.name] = hashlib.sha256(source.read_bytes()).hexdigest()
        param_path = destination / f"{name}.json"
        if strategy_id in params:
            write_json(param_path, {"strategy_name": name, "params": params[strategy_id],
                                   "ft_stratparam_v": 1,
                                   "export_time": datetime.now(timezone.utc).isoformat()})
        elif param_path.exists():
            # 移除本脚本此前为运行副本生成的参数，防止误用旧配置。
            param_path.unlink()
    path = runtime_dir / "config.backtest.json"
    write_json(path, config)
    # metadata仅用于审计；所有收益/交易/风险指标均由Freqtrade输出。
    # 为入场、成交细化、长周期分别规划行情，使用各自K线长度，避免只下载短周期。
    data_warmups = {args.timeframe: warmup}
    if args.timeframe_detail:
        data_warmups[args.timeframe_detail] = 0
    if args.macd_mtf:
        data_warmups[args.macd_trend_timeframe] = warmup
    data_plan = {(pair, tf): count for pair in args.pairs for tf, count in data_warmups.items()}
    if "S09" in args.strategies:
        data_plan[("BTC/USDT", args.btc_timeframe)] = warmup
    record = {"arguments": vars(args), "source_sha256": copied,
              "freqtrade_version": __version__,
              "startup_candle_count": warmup, "status": "prepared",
              "data_requirements": [{"pair": pair, "timeframe": tf, "warmup_candles": count}
                                    for (pair, tf), count in data_plan.items()],
              "created_at": datetime.now(timezone.utc).isoformat()}
    record_path = output_dir / "latest-run.json"
    write_json(record_path, record)
    if args.prepare_only:
        print(f"已复制策略并生成配置：{path}")
        return
    base = ["uv", "run", "--no-sync", "freqtrade"]
    common = ["--config", str(path), "--userdir", str(runtime_dir),
              "--datadir", str(ROOT / "user_data/data" / args.exchange)]
    results_dir = runtime_dir / "backtest_results"
    before = set(results_dir.glob("*.zip"))
    try:
        if not args.skip_download:
            for (pair, tf), count in data_plan.items():
                download_start = datetime.combine(start, datetime.min.time()) - timedelta(
                    minutes=(count + 10 if count else 0) * minutes_by_tf[tf])
                # Freqtrade默认只追加；先补历史再追加近期数据，不能因预热不足推迟起点。
                for prepend in (True, False):
                    subprocess.run(base + ["download-data"] + common + ["--pairs", pair, "--timeframes", tf,
                                   "--timerange", f"{download_start:%Y%m%d}-{end:%Y%m%d}"] +
                                   (["--prepend"] if prepend else []), cwd=ROOT, check=True)
        # 行情完整性审计，不计算收益或撮合。缺失行情/预热应失败，不能悄悄缩短区间。
        coverage = {}
        for (pair, tf), count in data_plan.items():
            data_path = ROOT / "user_data/data" / args.exchange / f"{pair.replace('/', '_')}-{tf}.feather"
            candles = pd.read_feather(data_path)
            times = pd.DatetimeIndex(pd.to_datetime(candles["date"], utc=True))
            delta = pd.Timedelta(minutes=minutes_by_tf[tf])
            first = pd.Timestamp(start, tz="UTC") - count * delta
            expected = pd.date_range(first, pd.Timestamp(end, tz="UTC"), freq=delta, inclusive="left")
            if times.has_duplicates or len(expected.difference(times)):
                raise ValueError(f"{pair} {tf}缺少行情/预热或有重复K线，请关闭复用行情后重新下载")
            coverage[f"{pair} {tf}"] = {"required_start": first.isoformat(), "end_exclusive": args.end,
                                         "verified_candles": len(expected), "missing": 0}
        record["data_coverage"] = coverage
        write_json(record_path, record)
        subprocess.run(base + ["backtesting"] + common + ["--strategy-list"] +
                       [NAMES[s] for s in args.strategies] + ["--timerange", f"{start:%Y%m%d}-{end:%Y%m%d}",
                       "--export", "trades", "--cache", "none", "--breakdown", "month"] +
                       (["--timeframe-detail", args.timeframe_detail] if args.timeframe_detail else []), cwd=ROOT, check=True)
    except (subprocess.CalledProcessError, ValueError, OSError) as error:
        record.update(status="failed", error=str(error), exit_code=getattr(error, "returncode", None))
        write_json(record_path, record)
        raise
    fresh = set(results_dir.glob("*.zip")) - before
    if not fresh:
        record.update(status="failed", error="Freqtrade未生成新的回测结果，请检查日志")
        write_json(record_path, record)
        raise RuntimeError(record["error"])
    record.update(status="completed", result_file=str(max(fresh, key=lambda p: p.stat().st_mtime).relative_to(ROOT)))
    data_dir = ROOT / "user_data/data" / args.exchange
    record["data_sha256"] = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                              for pair, tf in data_plan
                              for p in [data_dir / f"{pair.replace('/', '_')}-{tf}.feather"]}
    write_json(record_path, record)
    subprocess.run(["uv", "run", "--no-sync", "python", "scripts/build_report.py",
                    "--output-dir", str(output_dir)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
