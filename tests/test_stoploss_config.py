"""只验证配置生成及Freqtrade原生覆盖，不执行下载、撮合或绩效回测。"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from freqtrade.resolvers import StrategyResolver

ROOT = Path(__file__).resolve().parents[1]


class StoplossConfigTests(unittest.TestCase):
    def test_native_override_and_preserved_strategy_default(self):
        runs = ROOT / "user_data/ui-runs"
        runs.mkdir(parents=True, exist_ok=True)
        # S03覆盖其原5%默认、S09覆盖10%默认；未设置CLI选项时保留源码默认。
        for strategy, name, percent, expected in [
            ("S03", "S03BollingerReversion", "7.5", -0.075),
            ("S09", "S09BtcTrendEth", "2.5", -0.025),
            ("S03", "S03BollingerReversion", None, -0.05),
        ]:
            with self.subTest(strategy=strategy, percent=percent), tempfile.TemporaryDirectory(dir=runs) as directory:
                argv = [sys.executable, str(ROOT / "scripts/run_backtest.py"), "--strategies", strategy,
                        "--prepare-only", "--output-dir", directory]
                if strategy == "S09":
                    argv += ["--pairs", "ETH/USDT", "--timeframe", "1h"]
                if percent is not None:
                    argv += ["--stoploss-percent", percent]
                subprocess.run(argv, cwd=ROOT, check=True, capture_output=True)
                runtime = Path(directory) / "user_data"
                config = json.loads((runtime / "config.backtest.json").read_text())
                record = json.loads((Path(directory) / "latest-run.json").read_text())
                self.assertEqual(record["arguments"]["stoploss_percent"],float(percent) if percent else None)
                config.update(strategy=name, user_data_dir=runtime)
                loaded = StrategyResolver.load_strategy(config)
                self.assertAlmostEqual(loaded.stoploss,expected)
                self.assertAlmostEqual(config["stoploss"],expected)

    def test_cli_rejects_zero_negative_and_nonfinite_stoploss(self):
        for value in ["0", "-10", "100", "nan", "inf"]:
            result = subprocess.run([sys.executable, str(ROOT / "scripts/run_backtest.py"),
                "--prepare-only", "--stoploss-percent", value], cwd=ROOT, capture_output=True, text=True)
            self.assertEqual(result.returncode,2)
            self.assertIn("止损百分比",result.stderr)
