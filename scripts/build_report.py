"""把Freqtrade导出的现成统计整理为HTML/Markdown，不重算交易收益。"""

import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--empty", action="store_true", help="仅生成等待回测的参数页面")
    parser.add_argument("--output-dir", default=str(ROOT / "reports"))
    args = parser.parse_args()
    output_dir = Path(args.output_dir).resolve()
    if output_dir != ROOT / "reports" and not output_dir.is_relative_to((ROOT / "user_data/ui-runs").resolve()):
        raise ValueError("报告目录必须在reports或user_data/ui-runs内")
    record = json.loads((output_dir / "latest-run.json").read_text())
    stats = {}
    if not args.empty:
        if record.get("status") != "completed":
            raise ValueError("运行未完成，不能展示为成功回测")
        with zipfile.ZipFile(ROOT / record["result_file"]) as archive:
            for name in archive.namelist():
                if not name.endswith(".json"):
                    continue
                value = json.loads(archive.read(name))
                if "strategy" in value:
                    stats = value["strategy"]
                    break
        if not stats:
            raise ValueError("Freqtrade结果中没有strategy统计")
    fields = ["total_trades", "profit_total", "profit_total_abs", "winrate",
              "max_drawdown_account", "starting_balance", "final_balance", "backtest_start", "backtest_end"]
    trade_fields = ["pair", "open_date", "close_date", "open_timestamp", "close_timestamp",
                    "open_rate", "close_rate", "stake_amount", "amount", "trade_duration",
                    "profit_ratio", "profit_abs", "exit_reason", "enter_tag", "fee_open",
                    "fee_close", "is_open", "is_short"]
    report = {"run": record, "strategies": {name: {
              **{key: data.get(key) for key in fields},
              "trades": [{key: trade.get(key) for key in trade_fields}
                         for trade in data.get("trades", [])]}
              for name, data in stats.items()}}
    # 逐笔交易直接复制框架导出字段，不按价格差重新计算收益或手续费。
    (output_dir / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    content = (ROOT / "reports/template.html").read_text()
    payload = json.dumps(report, ensure_ascii=False).replace("<", "\\u003c")
    (output_dir / "index.html").write_text(content.replace("__REPORT_DATA__", payload), encoding="utf-8")
    lines = ["# 策略回测结果", "", "数据与统计由Freqtrade生成。", "",
             "```json", json.dumps(record["arguments"], ensure_ascii=False, indent=2), "```", "",
             "| 策略 | 交易数 | 收益率（总资金） | 收益USDT | 胜率 | 最大回撤 |",
             "| --- | ---: | ---: | ---: | ---: | ---: |"]
    for name, data in report["strategies"].items():
        lines.append(f"| {name} | {data['total_trades']} | {data['profit_total']:.2%} | "
                     f"{data['profit_total_abs']:.2f} | {data['winrate']:.2%} | {data['max_drawdown_account']:.2%} |")
    if not stats:
        lines.append("\n尚未生成真实回测结果。")
    lines.extend(["", "单笔投入与总资金不同，收益率以Freqtrade总资金口径为准；"
                  "手续费为单边费用，撮合遵循Freqtrade假设，未另行加入独立滑点模型。",
                  "止损默认为10%；止损/信号与实盘成交可能有差异。"])
    (output_dir / "回测结果.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"报告已生成：{output_dir / 'index.html'}")


if __name__ == "__main__":
    main()
