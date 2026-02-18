"""
🧀 乳酪のBTC預測室 — Phase 3 P1: 指標權重校準工具
=====================================================

使用回測引擎進行大規模權重搜索，找出最佳的 BIAS_WEIGHTS 組合。

搜索策略：
    1. Phase 1 — Random Search（隨機搜索）：
       在整個權重空間中均勻採樣 N 組候選權重，快速建立全局分佈。
    2. Phase 2 — Hill Climbing（爬山法）：
       以 Phase 1 的 Top-K 結果為起點，對每個指標進行微調，
       逐步逼近局部最優。
    3. Phase 3 — Cross Validation：
       將數據集切分為多個時段，驗證最佳權重的穩定性，避免 overfitting。

目標函數（Objective）：
    composite_score = sharpe_ratio * 0.5
                    + win_rate * 0.2
                    + profit_factor * 0.2
                    - max_drawdown_pct * 0.1
    
    主要以 Sharpe Ratio 為導向，同時兼顧勝率與獲利因子。

使用方式：
    cd backend
    python tools/calibrate_weights.py                    # 預設搜索
    python tools/calibrate_weights.py --iterations 500   # 更多迭代
    python tools/calibrate_weights.py --apply             # 搜索完成後寫回 config
    python tools/calibrate_weights.py --hours 72          # 先生成 72 小時合成數據
"""

import sys
import os
import math
import time
import json
import copy
import random
import logging
import argparse
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field, asdict

# ── 加入專案路徑 ────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import config
from app.performance.backtester import Backtester, BacktestConfig

# ── 日誌設定 ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("calibrator")
logger.setLevel(logging.INFO)

# 壓制回測引擎的 INFO 日誌（避免輸出過多）
logging.getLogger("cheesedog.performance.backtester").setLevel(logging.WARNING)
logging.getLogger("cheesedog.strategy.signal").setLevel(logging.WARNING)
logging.getLogger("cheesedog.performance.tracker").setLevel(logging.WARNING)


# ═══════════════════════════════════════════════════════════════
# 資料結構
# ═══════════════════════════════════════════════════════════════

# 指標名稱列表（與 config.BIAS_WEIGHTS 鍵對應）
INDICATOR_KEYS = list(config.BIAS_WEIGHTS.keys())

# 每個指標的搜索範圍
WEIGHT_RANGE = {
    "ema":   (0, 20),
    "obi":   (0, 15),
    "macd":  (0, 15),
    "cvd":   (0, 12),
    "ha":    (0, 12),
    "vwap":  (0, 10),
    "rsi":   (0, 10),
    "bb":    (0, 10),
    "poc":   (0, 8),
    "walls": (0, 8),
}

# Hill Climbing 步長
HILL_CLIMB_STEP = 1


@dataclass
class CalibrationResult:
    """單次校準結果"""
    weights: Dict[str, int]
    sharpe_ratio: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    total_pnl: float = 0.0
    total_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    total_trades: int = 0
    total_fees: float = 0.0
    composite_score: float = 0.0
    source: str = "random"  # random / hill_climb / baseline

    def calculate_composite(self):
        """計算綜合評分"""
        # 正規化各指標到 [0, 1] 範圍
        # Sharpe: 好的策略通常在 0~5 之間，我們用 3 作為滿分基準
        norm_sharpe = max(0, min(1, self.sharpe_ratio / 3.0))
        # 勝率: 50~70% 為目標
        norm_wr = max(0, min(1, (self.win_rate - 40) / 30))
        # 獲利因子: 1.0~3.0 為目標;  > 1 才有正期望
        norm_pf = max(0, min(1, (self.profit_factor - 1.0) / 2.0))
        # 最大回撤: 越小越好，10% 以下為佳
        norm_dd = max(0, min(1, self.max_drawdown_pct / 50))

        self.composite_score = (
            norm_sharpe * 0.40
            + norm_wr * 0.25
            + norm_pf * 0.25
            - norm_dd * 0.10
        )

        # 懲罰交易次數太少的情況（< 10 筆交易不具統計意義）
        if self.total_trades < 10:
            self.composite_score *= (self.total_trades / 10)

        return self.composite_score


# ═══════════════════════════════════════════════════════════════
# 核心校準引擎
# ═══════════════════════════════════════════════════════════════

class WeightCalibrator:
    """
    權重校準引擎
    
    透過大規模回測搜索最佳 BIAS_WEIGHTS 組合。
    """

    def __init__(
        self,
        trading_mode: str = "balanced",
        initial_balance: float = 1000.0,
        snapshot_limit: int = 5000,
        use_fees: bool = True,
    ):
        self.trading_mode = trading_mode
        self.initial_balance = initial_balance
        self.snapshot_limit = snapshot_limit
        self.use_fees = use_fees

        self.results: List[CalibrationResult] = []
        self.best_result: Optional[CalibrationResult] = None
        self._snapshots: Optional[list] = None

    def _load_snapshots(self):
        """預載入快照數據（避免每次回測都重新載入）"""
        if self._snapshots is not None:
            return

        logger.info("📂 預載入歷史快照數據...")
        from app.database import db

        self._snapshots = db.get_recent_snapshots(self.snapshot_limit)
        if not self._snapshots:
            raise RuntimeError(
                "❌ 資料庫中無歷史快照！\n"
                "   請先執行: python tests/generate_synthetic_data.py --hours 48\n"
                "   來生成合成測試數據。"
            )
        # 依時間排序
        self._snapshots.sort(key=lambda s: s.get("timestamp", 0))
        logger.info(f"✅ 已載入 {len(self._snapshots)} 筆快照")

    def _run_backtest_with_weights(self, weights: Dict[str, int]) -> dict:
        """使用指定權重執行一次回測"""
        # 臨時替換全域權重
        original_weights = config.BIAS_WEIGHTS.copy()
        config.BIAS_WEIGHTS = weights

        try:
            bt_config = BacktestConfig(
                initial_balance=self.initial_balance,
                trading_mode=self.trading_mode,
                use_fees=self.use_fees,
                use_saved_signals=False,  # 校準時必須使用信號引擎計算
                disable_cooldown=True,    # 校準時禁用冷卻期
            )
            backtester = Backtester(bt_config)
            report = backtester.run(
                snapshots=copy.deepcopy(self._snapshots),
            )
            return report
        finally:
            # 還原全域權重
            config.BIAS_WEIGHTS = original_weights

    def _extract_result(
        self, weights: Dict[str, int], report: dict, source: str = "random"
    ) -> CalibrationResult:
        """從回測報告提取校準結果"""
        if "error" in report:
            return CalibrationResult(weights=weights, source=source)

        summary = report.get("summary", {})
        dd = report.get("drawdown", {})

        result = CalibrationResult(
            weights=weights,
            sharpe_ratio=summary.get("sharpe_ratio", 0.0),
            win_rate=summary.get("win_rate", 0.0),
            profit_factor=summary.get("profit_factor", 0.0),
            total_pnl=summary.get("total_pnl", 0.0),
            total_return_pct=summary.get("total_return_pct", 0.0),
            max_drawdown_pct=dd.get("max_dd_pct", 0.0),
            total_trades=summary.get("total_trades", 0),
            total_fees=summary.get("total_fees", 0.0),
            source=source,
        )
        result.calculate_composite()
        return result

    def _generate_random_weights(self) -> Dict[str, int]:
        """生成一組隨機權重"""
        return {
            key: random.randint(lo, hi)
            for key, (lo, hi) in WEIGHT_RANGE.items()
        }

    def _mutate_weights(
        self, base_weights: Dict[str, int], num_mutations: int = 2
    ) -> Dict[str, int]:
        """在基礎權重上進行小幅突變"""
        new_weights = base_weights.copy()
        keys = random.sample(INDICATOR_KEYS, min(num_mutations, len(INDICATOR_KEYS)))

        for key in keys:
            lo, hi = WEIGHT_RANGE[key]
            delta = random.choice([-HILL_CLIMB_STEP, HILL_CLIMB_STEP])
            new_weights[key] = max(lo, min(hi, new_weights[key] + delta))

        return new_weights

    # ── 主要搜索流程 ──────────────────────────────────────────

    def run_calibration(
        self,
        random_iterations: int = 200,
        hill_climb_iterations: int = 100,
        top_k: int = 5,
    ) -> CalibrationResult:
        """
        執行完整校準流程

        Args:
            random_iterations: 隨機搜索迭代次數
            hill_climb_iterations: 爬山法迭代次數
            top_k: 從隨機搜索中取前 K 名進行爬山

        Returns:
            最佳校準結果
        """
        self._load_snapshots()
        total_start = time.time()

        # ── Phase 0: Baseline（使用現有權重）────────────────────
        logger.info("=" * 60)
        logger.info("📊 Phase 0: Baseline（使用現有權重）")
        logger.info("=" * 60)
        baseline_weights = {k: v for k, v in config.BIAS_WEIGHTS.items()}
        baseline_report = self._run_backtest_with_weights(baseline_weights)
        baseline_result = self._extract_result(baseline_weights, baseline_report, "baseline")
        self.results.append(baseline_result)

        logger.info(
            f"   基線結果 | Sharpe: {baseline_result.sharpe_ratio:.2f} | "
            f"勝率: {baseline_result.win_rate:.1f}% | "
            f"PnL: ${baseline_result.total_pnl:+.2f} | "
            f"交易: {baseline_result.total_trades} 筆 | "
            f"綜合: {baseline_result.composite_score:.4f}"
        )

        # ── Phase 1: Random Search ────────────────────────────
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"🎲 Phase 1: Random Search（{random_iterations} 次迭代）")
        logger.info("=" * 60)

        phase1_start = time.time()
        for i in range(random_iterations):
            weights = self._generate_random_weights()
            report = self._run_backtest_with_weights(weights)
            result = self._extract_result(weights, report, "random")
            self.results.append(result)

            # 進度報告
            if (i + 1) % 20 == 0 or i == 0:
                best_so_far = max(self.results, key=lambda r: r.composite_score)
                elapsed = time.time() - phase1_start
                eta = elapsed / (i + 1) * (random_iterations - i - 1)
                logger.info(
                    f"   [{i+1:4d}/{random_iterations}] "
                    f"本次: {result.composite_score:.4f} | "
                    f"最佳: {best_so_far.composite_score:.4f} "
                    f"(Sharpe={best_so_far.sharpe_ratio:.2f}) | "
                    f"ETA: {eta:.0f}s"
                )

        phase1_elapsed = time.time() - phase1_start
        logger.info(f"   Phase 1 完成，耗時 {phase1_elapsed:.1f}s")

        # ── Phase 2: Hill Climbing ───────────────────────────
        logger.info("")
        logger.info("=" * 60)
        logger.info(f"⛰️  Phase 2: Hill Climbing（Top-{top_k} 起點 × {hill_climb_iterations} 次微調）")
        logger.info("=" * 60)

        # 取 Phase 1 前 K 名
        sorted_results = sorted(self.results, key=lambda r: r.composite_score, reverse=True)
        top_candidates = sorted_results[:top_k]

        phase2_start = time.time()
        for rank, candidate in enumerate(top_candidates, 1):
            logger.info(
                f"\n   🏔️  起點 #{rank}: "
                f"composite={candidate.composite_score:.4f} | "
                f"Sharpe={candidate.sharpe_ratio:.2f}"
            )

            current_best = candidate
            stagnant_count = 0
            max_stagnant = 15  # 連續 N 次未改善則停止

            for j in range(hill_climb_iterations):
                # 根據進度調整突變幅度
                mutations = 2 if j < hill_climb_iterations // 2 else 1
                mutated_weights = self._mutate_weights(
                    current_best.weights, num_mutations=mutations
                )
                report = self._run_backtest_with_weights(mutated_weights)
                result = self._extract_result(mutated_weights, report, "hill_climb")
                self.results.append(result)

                if result.composite_score > current_best.composite_score:
                    improvement = result.composite_score - current_best.composite_score
                    current_best = result
                    stagnant_count = 0
                    logger.info(
                        f"   ↑ [{j+1:3d}] 改善: +{improvement:.4f} → "
                        f"{current_best.composite_score:.4f} | "
                        f"Sharpe={current_best.sharpe_ratio:.2f}"
                    )
                else:
                    stagnant_count += 1

                if stagnant_count >= max_stagnant:
                    logger.info(
                        f"   ✋ 連續 {max_stagnant} 次未改善，提前停止"
                    )
                    break

        phase2_elapsed = time.time() - phase2_start
        logger.info(f"\n   Phase 2 完成，耗時 {phase2_elapsed:.1f}s")

        # ── 找出全局最佳 ──────────────────────────────────────
        self.best_result = max(self.results, key=lambda r: r.composite_score)
        total_elapsed = time.time() - total_start

        logger.info("")
        logger.info("=" * 60)
        logger.info("🏆 校準完成！")
        logger.info("=" * 60)
        logger.info(f"   總迭代: {len(self.results)} 次 | 總耗時: {total_elapsed:.1f}s")

        return self.best_result

    # ── 多時段交叉驗證 ────────────────────────────────────────

    def cross_validate(
        self, weights: Dict[str, int], n_folds: int = 3
    ) -> Dict:
        """
        將歷史數據切分為 N 段，驗證權重的穩定性

        Returns:
            {
                "folds": [{"sharpe": ..., "win_rate": ..., ...}, ...],
                "avg_sharpe": float,
                "std_sharpe": float,
                "stability_score": float,  # 0~1, 越高越穩定
            }
        """
        self._load_snapshots()

        total = len(self._snapshots)
        fold_size = total // n_folds
        fold_results = []

        logger.info(f"\n📊 交叉驗證（{n_folds} 折，每折 {fold_size} 筆快照）")

        for fold_idx in range(n_folds):
            start = fold_idx * fold_size
            end = start + fold_size if fold_idx < n_folds - 1 else total
            fold_snapshots = self._snapshots[start:end]

            # 臨時替換全域權重
            original_weights = config.BIAS_WEIGHTS.copy()
            config.BIAS_WEIGHTS = weights

            try:
                bt_config = BacktestConfig(
                    initial_balance=self.initial_balance,
                    trading_mode=self.trading_mode,
                    use_fees=self.use_fees,
                    use_saved_signals=False,  # 校準驗證同樣使用信號引擎計算
                    disable_cooldown=True,    # 校準時禁用冷卻期
                )
                backtester = Backtester(bt_config)
                report = backtester.run(snapshots=copy.deepcopy(fold_snapshots))
            finally:
                config.BIAS_WEIGHTS = original_weights

            summary = report.get("summary", {})
            dd = report.get("drawdown", {})
            fold_results.append({
                "fold": fold_idx + 1,
                "snapshots": len(fold_snapshots),
                "sharpe": summary.get("sharpe_ratio", 0.0),
                "win_rate": summary.get("win_rate", 0.0),
                "pnl": summary.get("total_pnl", 0.0),
                "trades": summary.get("total_trades", 0),
                "max_dd": dd.get("max_dd_pct", 0.0),
            })

            logger.info(
                f"   Fold {fold_idx+1}: Sharpe={fold_results[-1]['sharpe']:.2f} | "
                f"勝率={fold_results[-1]['win_rate']:.1f}% | "
                f"PnL=${fold_results[-1]['pnl']:+.2f} | "
                f"交易={fold_results[-1]['trades']} 筆"
            )

        # 計算穩定性指標
        sharpes = [f["sharpe"] for f in fold_results]
        avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0
        std_sharpe = math.sqrt(
            sum((s - avg_sharpe) ** 2 for s in sharpes) / len(sharpes)
        ) if len(sharpes) > 1 else 0

        # 穩定性分數：Sharpe 平均值正且標準差小 → 高穩定性
        stability = 0.0
        if avg_sharpe > 0 and std_sharpe >= 0:
            cv = std_sharpe / avg_sharpe if avg_sharpe != 0 else float('inf')
            stability = max(0, min(1, 1.0 - cv))

        return {
            "folds": fold_results,
            "avg_sharpe": round(avg_sharpe, 2),
            "std_sharpe": round(std_sharpe, 2),
            "stability_score": round(stability, 4),
        }


# ═══════════════════════════════════════════════════════════════
# 報告生成
# ═══════════════════════════════════════════════════════════════

def print_report(
    calibrator: WeightCalibrator,
    cv_result: Optional[dict] = None
):
    """印出詳細校準報告"""
    best = calibrator.best_result
    baseline = next(
        (r for r in calibrator.results if r.source == "baseline"), None
    )

    print()
    print("=" * 72)
    print("  🧀 乳酪のBTC預測室 — Phase 3 P1 權重校準報告")
    print("=" * 72)

    # ── Baseline vs Best 比較 ─────────────────────────────────
    print()
    print("┌─────────────────────────────────────────────────────────────┐")
    print("│                    Baseline vs 最佳權重                      │")
    print("├──────────────┬─────────────────┬──────────────────┬─────────┤")
    print("│    指標      │    Baseline     │    最佳 (New)    │  改善   │")
    print("├──────────────┼─────────────────┼──────────────────┼─────────┤")

    if baseline:
        metrics = [
            ("Sharpe Ratio", baseline.sharpe_ratio, best.sharpe_ratio, ".2f", False),
            ("勝率 (%)",     baseline.win_rate,     best.win_rate,     ".1f", False),
            ("獲利因子",     baseline.profit_factor, best.profit_factor, ".2f", False),
            ("PnL ($)",      baseline.total_pnl,    best.total_pnl,    "+.2f", False),
            ("報酬率 (%)",   baseline.total_return_pct, best.total_return_pct, "+.2f", False),
            ("最大回撤 (%)", baseline.max_drawdown_pct, best.max_drawdown_pct, ".2f", True),
            ("交易次數",     baseline.total_trades, best.total_trades, "d", False),
            ("手續費 ($)",   baseline.total_fees,   best.total_fees,   ".2f", True),
            ("綜合評分",     baseline.composite_score, best.composite_score, ".4f", False),
        ]

        for name, base_val, best_val, fmt, lower_better in metrics:
            diff = best_val - base_val
            if lower_better:
                arrow = "↓ 改善" if diff < 0 else "↑ 惡化" if diff > 0 else "  持平"
            else:
                arrow = "↑ 改善" if diff > 0 else "↓ 惡化" if diff < 0 else "  持平"

            print(
                f"│ {name:<12s} │ {format(base_val, fmt):>15s} │ "
                f"{format(best_val, fmt):>16s} │ {arrow} │"
            )

    print("└──────────────┴─────────────────┴──────────────────┴─────────┘")

    # ── 權重比較 ──────────────────────────────────────────────
    print()
    print("┌───────────────────────────────────────────────────────┐")
    print("│                 指標權重比較                           │")
    print("├──────────┬──────────────┬──────────────┬──────────────┤")
    print("│  指標    │  Baseline    │  最佳 (New)  │  變化        │")
    print("├──────────┼──────────────┼──────────────┼──────────────┤")

    if baseline:
        for key in INDICATOR_KEYS:
            base_w = baseline.weights.get(key, 0)
            best_w = best.weights.get(key, 0)
            diff = best_w - base_w

            if diff > 0:
                change = f"+{diff} ↑"
            elif diff < 0:
                change = f"{diff} ↓"
            else:
                change = "  ─"

            print(
                f"│ {key:<8s} │ {base_w:>12d} │ {best_w:>12d} │ {change:>12s} │"
            )

    total_base = sum(baseline.weights.values()) if baseline else 0
    total_best = sum(best.weights.values())
    print("├──────────┼──────────────┼──────────────┼──────────────┤")
    print(f"│ 總和     │ {total_base:>12d} │ {total_best:>12d} │              │")
    print("└──────────┴──────────────┴──────────────┴──────────────┘")

    # ── 交叉驗證結果 ──────────────────────────────────────────
    if cv_result:
        print()
        print("┌───────────────────────────────────────────────────────┐")
        print("│                  交叉驗證結果                          │")
        print("├──────┬──────────┬──────────┬──────────┬──────────────┤")
        print("│ Fold │  Sharpe  │  勝率 %  │  PnL ($) │  交易次數    │")
        print("├──────┼──────────┼──────────┼──────────┼──────────────┤")

        for f in cv_result["folds"]:
            print(
                f"│  {f['fold']}   │ {f['sharpe']:8.2f} │ {f['win_rate']:8.1f} │ "
                f"{f['pnl']:+8.2f} │ {f['trades']:>12d} │"
            )

        print("├──────┼──────────┼──────────┼──────────┼──────────────┤")
        print(
            f"│ 平均 │ {cv_result['avg_sharpe']:8.2f} │          │          │              │"
        )
        print("├──────┴──────────┴──────────┴──────────┴──────────────┤")
        print(
            f"│ Sharpe 標準差: {cv_result['std_sharpe']:.2f}  |  "
            f"穩定性分數: {cv_result['stability_score']:.4f}          │"
        )
        print("└──────────────────────────────────────────────────────┘")

    # ── 搜索統計 ──────────────────────────────────────────────
    print()
    total_results = len(calibrator.results)
    random_count = sum(1 for r in calibrator.results if r.source == "random")
    hill_count = sum(1 for r in calibrator.results if r.source == "hill_climb")
    scores = [r.composite_score for r in calibrator.results]

    print(f"📊 搜索統計:")
    print(f"   總迭代數: {total_results}")
    print(f"   Random Search: {random_count} 次")
    print(f"   Hill Climbing: {hill_count} 次")
    print(f"   綜合評分範圍: [{min(scores):.4f}, {max(scores):.4f}]")
    print(f"   綜合評分平均: {sum(scores)/len(scores):.4f}")
    print()

    # ── 可複製的最佳權重 ──────────────────────────────────────
    print("📋 最佳權重（可直接複製到 config.py）:")
    print()
    print("BIAS_WEIGHTS = {")
    for key in INDICATOR_KEYS:
        comment = _weight_comment(key)
        print(f'    "{key}": {best.weights[key]:>3d},   # {comment}')
    print("}")
    print()


def _weight_comment(key: str) -> str:
    """產生權重行的中文註解"""
    comments = {
        "ema": "EMA 交叉（連續函數）",
        "obi": "訂單簿失衡",
        "macd": "MACD Histogram（幅度化）",
        "cvd": "CVD 5 分鐘方向",
        "ha": "Heikin-Ashi 連續方向",
        "vwap": "價格 vs VWAP",
        "rsi": "RSI 超買/超賣（極端加強）",
        "bb": "Bollinger Band %B（波動率維度）",
        "poc": "價格 vs POC（成交量集中點）",
        "walls": "買牆 − 賣牆",
    }
    return comments.get(key, key)


# ═══════════════════════════════════════════════════════════════
# Config 寫回功能
# ═══════════════════════════════════════════════════════════════

def apply_weights_to_config(weights: Dict[str, int]):
    """將最佳權重寫回 config.py"""
    config_path = os.path.join(
        os.path.dirname(__file__), '..', 'app', 'config.py'
    )
    config_path = os.path.abspath(config_path)

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 找到 BIAS_WEIGHTS 區塊並替換
    # 使用簡單的字串匹配
    start_marker = "BIAS_WEIGHTS = {"
    end_marker = "}"
    
    start_idx = content.find(start_marker)
    if start_idx == -1:
        logger.error("❌ 在 config.py 中找不到 BIAS_WEIGHTS 定義")
        return False

    # 找到對應的結束 }
    brace_count = 0
    end_idx = start_idx
    for i in range(start_idx, len(content)):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break

    # 生成新的 BIAS_WEIGHTS 區塊
    new_block_lines = ["BIAS_WEIGHTS = {"]
    for key in INDICATOR_KEYS:
        comment = _weight_comment(key)
        new_block_lines.append(f'    "{key}": {weights[key]:>3d},   # {comment}')
    new_block_lines.append("}")
    new_block = "\n".join(new_block_lines)

    # 替換
    new_content = content[:start_idx] + new_block + content[end_idx:]

    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(new_content)

    logger.info(f"✅ 已將最佳權重寫回 {config_path}")
    return True


# ═══════════════════════════════════════════════════════════════
# 結果匯出
# ═══════════════════════════════════════════════════════════════

def save_results_json(calibrator: WeightCalibrator, filepath: str):
    """將所有校準結果匯出為 JSON"""
    # 按 composite_score 排序
    sorted_results = sorted(
        calibrator.results,
        key=lambda r: r.composite_score,
        reverse=True,
    )

    output = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "config": {
            "trading_mode": calibrator.trading_mode,
            "initial_balance": calibrator.initial_balance,
            "snapshot_limit": calibrator.snapshot_limit,
            "use_fees": calibrator.use_fees,
            "total_snapshots": len(calibrator._snapshots) if calibrator._snapshots else 0,
        },
        "best_weights": calibrator.best_result.weights if calibrator.best_result else {},
        "best_metrics": {
            "composite_score": calibrator.best_result.composite_score,
            "sharpe_ratio": calibrator.best_result.sharpe_ratio,
            "win_rate": calibrator.best_result.win_rate,
            "profit_factor": calibrator.best_result.profit_factor,
            "total_pnl": calibrator.best_result.total_pnl,
        } if calibrator.best_result else {},
        "top_10": [
            {
                "rank": i + 1,
                "weights": r.weights,
                "composite": r.composite_score,
                "sharpe": r.sharpe_ratio,
                "win_rate": r.win_rate,
                "pnl": r.total_pnl,
                "trades": r.total_trades,
                "source": r.source,
            }
            for i, r in enumerate(sorted_results[:10])
        ],
        "total_iterations": len(calibrator.results),
    }

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    logger.info(f"📁 結果已匯出至 {filepath}")


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="🧀 乳酪のBTC預測室 — Phase 3 P1 指標權重校準工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python tools/calibrate_weights.py                        # 預設搜索 (200 random + 100 hill)
  python tools/calibrate_weights.py -n 500 --hill 200      # 加大搜索量
  python tools/calibrate_weights.py --mode conservative     # 校準保守模式
  python tools/calibrate_weights.py --apply                 # 搜索完成後寫回 config
  python tools/calibrate_weights.py --hours 72              # 先生成合成數據
  python tools/calibrate_weights.py --cv 5                  # 5 折交叉驗證
        """,
    )

    parser.add_argument(
        "-n", "--iterations",
        type=int, default=200,
        help="Random Search 迭代次數 (預設: 200)",
    )
    parser.add_argument(
        "--hill", "--hill-climb",
        type=int, default=100,
        dest="hill_iterations",
        help="Hill Climbing 每個起點的迭代次數 (預設: 100)",
    )
    parser.add_argument(
        "--top-k",
        type=int, default=5,
        help="從 Random Search 取前 K 名做 Hill Climbing (預設: 5)",
    )
    parser.add_argument(
        "--mode",
        type=str, default="balanced",
        choices=["aggressive", "balanced", "conservative"],
        help="要校準的交易模式 (預設: balanced)",
    )
    parser.add_argument(
        "--balance",
        type=float, default=1000.0,
        help="初始資金 (預設: 1000)",
    )
    parser.add_argument(
        "--limit",
        type=int, default=5000,
        help="快照數量上限 (預設: 5000)",
    )
    parser.add_argument(
        "--no-fees",
        action="store_true",
        help="不計算手續費",
    )
    parser.add_argument(
        "--cv",
        type=int, default=0,
        help="交叉驗證折數 (0=不執行, 預設: 0)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="將最佳權重寫回 config.py",
    )
    parser.add_argument(
        "--output",
        type=str, default=None,
        help="結果匯出 JSON 路徑",
    )
    parser.add_argument(
        "--hours",
        type=int, default=0,
        help="先生成 N 小時合成數據 (0=不生成)",
    )
    parser.add_argument(
        "--seed",
        type=int, default=None,
        help="隨機種子 (用於可重現結果)",
    )

    args = parser.parse_args()

    # ── 設定隨機種子 ──────────────────────────────────────────
    if args.seed is not None:
        random.seed(args.seed)
        logger.info(f"🎯 隨機種子: {args.seed}")

    # ── 生成合成數據（可選）─────────────────────────────────────
    if args.hours > 0:
        logger.info(f"🧪 生成 {args.hours} 小時合成市場數據...")
        from tests.generate_synthetic_data import generate_synthetic_data
        generate_synthetic_data(hours=args.hours)
        logger.info("")

    # ── 開始校準 ──────────────────────────────────────────────
    print()
    print("🧀 乳酪のBTC預測室 — Phase 3 P1 指標權重校準工具")
    print("=" * 60)
    print(f"   交易模式: {args.mode}")
    print(f"   Random Search: {args.iterations} 次")
    print(f"   Hill Climbing: Top-{args.top_k} × {args.hill_iterations} 次")
    print(f"   手續費: {'是' if not args.no_fees else '否'}")
    print(f"   快照上限: {args.limit}")
    print("=" * 60)
    print()

    calibrator = WeightCalibrator(
        trading_mode=args.mode,
        initial_balance=args.balance,
        snapshot_limit=args.limit,
        use_fees=not args.no_fees,
    )

    best = calibrator.run_calibration(
        random_iterations=args.iterations,
        hill_climb_iterations=args.hill_iterations,
        top_k=args.top_k,
    )

    # ── 交叉驗證（可選）─────────────────────────────────────
    cv_result = None
    if args.cv > 0:
        cv_result = calibrator.cross_validate(best.weights, n_folds=args.cv)

    # ── 印出報告 ──────────────────────────────────────────────
    print_report(calibrator, cv_result)

    # ── 匯出結果（可選）─────────────────────────────────────
    if args.output:
        save_results_json(calibrator, args.output)
    else:
        # 預設匯出到 data/ 目錄
        default_output = os.path.join(
            os.path.dirname(__file__), '..', 'data',
            f'calibration_{args.mode}_{time.strftime("%Y%m%d_%H%M%S")}.json'
        )
        os.makedirs(os.path.dirname(default_output), exist_ok=True)
        save_results_json(calibrator, default_output)

    # ── 寫回 config（可選）────────────────────────────────────
    if args.apply:
        print()
        print("⚠️  即將把最佳權重寫回 config.py！")
        confirm = input("確認? (y/N): ").strip().lower()
        if confirm == 'y':
            apply_weights_to_config(best.weights)
            print("✅ 權重已更新！請重啟後端以套用新權重。")
        else:
            print("❌ 取消寫回。")

    return best


if __name__ == "__main__":
    main()
