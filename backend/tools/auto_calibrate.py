"""
🧀 乳酪のBTC預測室 — 自動校準排程工具
=====================================================

設計給 VPS 上的 Agent / crontab 使用。
每日自動執行以下流程:
    1. 從 Binance 下載最新 16 小時真實 K 線
    2. 使用校準引擎搜索最佳權重
    3. 與現有權重比較
    4. 若新權重顯著優於舊權重 → 自動更新 config.py
    5. 記錄校準歷史，供 AI 分析趨勢

VPS 定時任務設定:
    # 每日凌晨 4:00 自動校準（UTC+8）
    0 4 * * * cd /path/to/backend && python tools/auto_calibrate.py >> logs/calibrate.log 2>&1

    # 或每 8 小時校準一次（更積極的自適應）
    0 */8 * * * cd /path/to/backend && python tools/auto_calibrate.py >> logs/calibrate.log 2>&1

使用方式:
    python tools/auto_calibrate.py                   # 預設自動校準
    python tools/auto_calibrate.py --dry-run          # 只測試，不寫入
    python tools/auto_calibrate.py --threshold 0.15   # 改善 15% 才更新
    python tools/auto_calibrate.py --notify            # 校準後發送通知
"""

import sys
import os
import json
import time
import logging
import math
from datetime import datetime
from pathlib import Path

# ── 加入專案路徑 ────────────────────────────────────────────────
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import config

# ── 日誌設定 ────────────────────────────────────────────────────
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(LOG_DIR / "auto_calibrate.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("auto_calibrate")

# ── 校準歷史記錄路徑 ────────────────────────────────────────────
HISTORY_DIR = Path(__file__).parent.parent / "data" / "calibration_history"
HISTORY_DIR.mkdir(parents=True, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# 市場狀態偵測
# ═══════════════════════════════════════════════════════════════

def detect_market_regime(klines: list) -> dict:
    """
    基於最近的 K 線數據偵測市場狀態

    Returns:
        {
            "regime": "strong_trend" | "mild_trend" | "ranging" | "choppy" | "crash",
            "volatility_pct": float,
            "trend_strength": float,
            "recommended_mode": str,
            "details": str,
        }
    """
    if len(klines) < 30:
        return {
            "regime": "ranging",
            "volatility_pct": 0,
            "trend_strength": 0,
            "recommended_mode": "balanced",
            "details": "數據不足，使用預設模式",
        }

    regime_cfg = config.MARKET_REGIME_CONFIG

    # ── 計算波動率 (ATR-like) ────────────────────────────────
    # 使用最近 30 根 K 線的 (high-low)/close 百分比
    recent = klines[-30:]
    tr_list = []
    for i, k in enumerate(recent):
        high = k.get("h", k.get("c", 0))
        low = k.get("l", k.get("c", 0))
        close = k.get("c", 1)
        tr = (high - low) / close * 100 if close > 0 else 0
        tr_list.append(tr)

    avg_tr = sum(tr_list) / len(tr_list) if tr_list else 0

    # ── 計算趨勢強度 (類 ADX) ────────────────────────────────
    # 使用價格方向變化的一致性來模擬 ADX
    closes = [k.get("c", 0) for k in recent]
    directions = []
    for i in range(1, len(closes)):
        if closes[i] > closes[i-1]:
            directions.append(1)
        elif closes[i] < closes[i-1]:
            directions.append(-1)
        else:
            directions.append(0)

    if directions:
        # 方向一致性 = |平均方向| * 100
        avg_dir = sum(directions) / len(directions)
        trend_strength = abs(avg_dir) * 50  # 0~50 的範圍

        # 加上整體價格變動幅度
        total_change_pct = abs(closes[-1] - closes[0]) / closes[0] * 100 if closes[0] > 0 else 0
        trend_strength += total_change_pct * 5  # 放大趨勢效果
    else:
        trend_strength = 0

    # ── 判定市場狀態 ──────────────────────────────────────────
    regime = "ranging"
    details = ""

    if avg_tr > regime_cfg["volatility_high"]:
        # 高波動
        if trend_strength > regime_cfg["trend_strong"]:
            regime = "strong_trend"
            details = f"高波動+強趨勢（volatility={avg_tr:.2f}%, trend={trend_strength:.1f}）"
        else:
            regime = "choppy"
            details = f"高波動+無趨勢（volatility={avg_tr:.2f}%, trend={trend_strength:.1f}）"
    elif avg_tr > regime_cfg["volatility_low"]:
        # 中波動
        if trend_strength > regime_cfg["trend_mild"]:
            regime = "mild_trend"
            details = f"中波動+溫和趨勢（volatility={avg_tr:.2f}%, trend={trend_strength:.1f}）"
        else:
            regime = "ranging"
            details = f"中波動+盤整（volatility={avg_tr:.2f}%, trend={trend_strength:.1f}）"
    else:
        # 低波動
        regime = "ranging"
        details = f"低波動+盤整（volatility={avg_tr:.2f}%, trend={trend_strength:.1f}）"

    # 檢查是否崩盤（最近 30 分鐘跌幅 > 2%）
    if len(closes) >= 30:
        last_30_change = (closes[-1] - closes[-30]) / closes[-30] * 100 if closes[-30] > 0 else 0
        if last_30_change < -2.0:
            regime = "crash"
            details = f"⚠️ 崩盤偵測！30 分鐘跌幅 {last_30_change:.2f}%"

    recommended_mode = regime_cfg["regime_mode_map"].get(regime, "balanced")

    return {
        "regime": regime,
        "volatility_pct": round(avg_tr, 4),
        "trend_strength": round(trend_strength, 2),
        "recommended_mode": recommended_mode,
        "details": details,
    }


# ═══════════════════════════════════════════════════════════════
# 自動校準主流程
# ═══════════════════════════════════════════════════════════════

def run_auto_calibration(
    dry_run: bool = False,
    improvement_threshold: float = 0.10,
    random_iterations: int = 150,
    hill_iterations: int = 80,
    notify: bool = False,
):
    """
    自動校準完整流程

    Args:
        dry_run: 只測試，不寫入 config.py
        improvement_threshold: 新權重需比舊權重改善 N% 才更新
        random_iterations: Random Search 迭代次數
        hill_iterations: Hill Climbing 迭代次數
        notify: 校準完成後是否發送通知
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("=" * 60)
    logger.info(f"🧀 自動校準開始 @ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    # ── Step 1: 下載真實數據 ──────────────────────────────────
    logger.info("\n📥 Step 1: 下載最新市場數據...")
    from tools.fetch_historical_data import (
        fetch_binance_klines,
        clear_snapshots,
        generate_snapshots_from_real_data,
    )

    # 先下載 K 線（用於市場狀態偵測）
    raw_klines = fetch_binance_klines(limit=1000)
    if not raw_klines:
        logger.error("❌ 無法獲取 Binance 數據，校準中止。")
        return False

    logger.info(f"   獲取 {len(raw_klines)} 根 K 線")
    logger.info(f"   價格範圍: ${min(k['l'] for k in raw_klines):,.2f} - ${max(k['h'] for k in raw_klines):,.2f}")

    # ── Step 2: 偵測市場狀態 ──────────────────────────────────
    logger.info("\n🔍 Step 2: 偵測市場狀態...")
    regime = detect_market_regime(raw_klines)
    logger.info(f"   狀態: {regime['regime']}")
    logger.info(f"   波動率: {regime['volatility_pct']:.4f}%")
    logger.info(f"   趨勢強度: {regime['trend_strength']:.2f}")
    logger.info(f"   推薦模式: {regime['recommended_mode']}")
    logger.info(f"   詳情: {regime['details']}")

    calibration_mode = regime["recommended_mode"]

    # ── Step 3: 清空舊快照，寫入新數據 ────────────────────────
    logger.info("\n🗑️  Step 3: 更新快照數據...")
    clear_snapshots()
    generate_snapshots_from_real_data(hours=16)

    # ── Step 4: 執行校準 ──────────────────────────────────────
    logger.info(f"\n⚙️  Step 4: 執行權重校準（模式: {calibration_mode}）...")
    from tools.calibrate_weights import WeightCalibrator, save_results_json

    calibrator = WeightCalibrator(
        trading_mode=calibration_mode,
        initial_balance=1000.0,
        snapshot_limit=5000,
        use_fees=True,
    )

    best = calibrator.run_calibration(
        random_iterations=random_iterations,
        hill_climb_iterations=hill_iterations,
        top_k=5,
    )

    # ── Step 5: 交叉驗證 ──────────────────────────────────────
    logger.info("\n📊 Step 5: 交叉驗證...")
    cv_result = calibrator.cross_validate(best.weights, n_folds=3)

    # ── Step 6: 比較新舊權重 ──────────────────────────────────
    logger.info("\n📈 Step 6: 比較新舊權重...")

    # 找到 baseline 結果
    baseline = next(
        (r for r in calibrator.results if r.source == "baseline"), None
    )

    improvement = 0.0
    if baseline and baseline.composite_score > 0:
        improvement = (best.composite_score - baseline.composite_score) / baseline.composite_score
    elif best.composite_score > 0:
        improvement = 1.0  # baseline 為 0，任何改善都是 100%

    logger.info(f"   Baseline Composite: {baseline.composite_score:.4f}" if baseline else "   Baseline: N/A")
    logger.info(f"   最佳 Composite: {best.composite_score:.4f}")
    logger.info(f"   改善幅度: {improvement:+.1%}")
    logger.info(f"   交叉驗證穩定性: {cv_result['stability_score']:.4f}")

    # ── Step 7: 決定是否更新 ──────────────────────────────────
    should_update = (
        improvement >= improvement_threshold
        and cv_result["stability_score"] > 0.3  # 穩定性至少 30%
        and best.total_trades >= 5              # 至少 5 筆交易
    )

    logger.info("")
    if should_update:
        logger.info(f"✅ 新權重通過更新條件:")
        logger.info(f"   ✓ 改善 {improvement:+.1%} ≥ 門檻 {improvement_threshold:+.1%}")
        logger.info(f"   ✓ 穩定性 {cv_result['stability_score']:.4f} > 0.3")
        logger.info(f"   ✓ 交易數 {best.total_trades} ≥ 5")
    else:
        reasons = []
        if improvement < improvement_threshold:
            reasons.append(f"改善不足 ({improvement:+.1%} < {improvement_threshold:+.1%})")
        if cv_result["stability_score"] <= 0.3:
            reasons.append(f"穩定性不足 ({cv_result['stability_score']:.4f} ≤ 0.3)")
        if best.total_trades < 5:
            reasons.append(f"交易次數不足 ({best.total_trades} < 5)")
        logger.info(f"⏭️  不更新權重: {'; '.join(reasons)}")

    # ── Step 8: 寫入或跳過 ────────────────────────────────────
    if should_update and not dry_run:
        from tools.calibrate_weights import apply_weights_to_config
        apply_weights_to_config(best.weights)
        logger.info("📝 最佳權重已自動寫入 config.py")
        updated = True
    elif should_update and dry_run:
        logger.info("🔬 [DRY RUN] 不實際寫入 config.py")
        updated = False
    else:
        updated = False

    # ── Step 9: 保存校準歷史 ──────────────────────────────────
    history_record = {
        "timestamp": datetime.now().isoformat(),
        "market_regime": regime,
        "calibration_mode": calibration_mode,
        "old_weights": dict(config.BIAS_WEIGHTS) if not updated else (
            baseline.weights if baseline else {}
        ),
        "new_weights": best.weights,
        "metrics": {
            "baseline_composite": baseline.composite_score if baseline else 0,
            "best_composite": best.composite_score,
            "improvement_pct": round(improvement * 100, 2),
            "sharpe_ratio": best.sharpe_ratio,
            "win_rate": best.win_rate,
            "profit_factor": best.profit_factor,
            "total_trades": best.total_trades,
        },
        "cross_validation": cv_result,
        "updated": updated,
        "dry_run": dry_run,
        "total_iterations": len(calibrator.results),
    }

    history_file = HISTORY_DIR / f"calibration_{timestamp}.json"
    with open(history_file, "w", encoding="utf-8") as f:
        json.dump(history_record, f, indent=2, ensure_ascii=False, default=str)

    logger.info(f"📁 校準歷史已儲存: {history_file}")

    # 同時保存完整結果
    full_result_file = HISTORY_DIR / f"full_results_{timestamp}.json"
    save_results_json(calibrator, str(full_result_file))

    # ── Step 10: 通知 (可選) ──────────────────────────────────
    if notify:
        _send_notification(history_record)

    # ── 摘要 ──────────────────────────────────────────────────
    logger.info("")
    logger.info("=" * 60)
    logger.info("📋 自動校準摘要")
    logger.info("=" * 60)
    logger.info(f"   市場狀態: {regime['regime']} → 使用模式: {calibration_mode}")
    logger.info(f"   迭代次數: {len(calibrator.results)}")
    logger.info(f"   最佳 Sharpe: {best.sharpe_ratio:.2f}")
    logger.info(f"   最佳勝率: {best.win_rate:.1f}%")
    logger.info(f"   改善幅度: {improvement:+.1%}")
    logger.info(f"   是否更新: {'✅ 已更新' if updated else '❌ 未更新'}")
    logger.info("=" * 60)

    return updated


def _send_notification(record: dict):
    """
    發送校準結果通知
    
    目前支援:
    - 寫入 JSON 檔案（供 CRO Dashboard 讀取）
    - 未來可擴展: Discord Webhook, Telegram, Email
    """
    try:
        # 寫入至 /data/latest_calibration.json 供 Dashboard 讀取
        latest_file = Path(__file__).parent.parent / "data" / "latest_calibration.json"
        with open(latest_file, "w", encoding="utf-8") as f:
            json.dump({
                "timestamp": record["timestamp"],
                "regime": record["market_regime"]["regime"],
                "mode": record["calibration_mode"],
                "improvement_pct": record["metrics"]["improvement_pct"],
                "sharpe": record["metrics"]["sharpe_ratio"],
                "win_rate": record["metrics"]["win_rate"],
                "updated": record["updated"],
            }, f, indent=2, ensure_ascii=False)
        logger.info("🔔 通知已發送至 latest_calibration.json")
    except Exception as e:
        logger.warning(f"⚠️ 通知發送失敗: {e}")


# ═══════════════════════════════════════════════════════════════
# 校準歷史分析
# ═══════════════════════════════════════════════════════════════

def analyze_calibration_history():
    """
    分析校準歷史，找出最穩定的權重趨勢

    供 AI Agent 使用，可以辨認出:
    - 哪些指標的最佳權重是穩定的（每次校準都差不多）
    - 哪些指標的最佳權重變動大（與市場狀態相關）
    """
    history_files = sorted(HISTORY_DIR.glob("calibration_*.json"))

    if not history_files:
        logger.info("📭 無校準歷史記錄")
        return None

    records = []
    for f in history_files:
        with open(f, "r", encoding="utf-8") as fp:
            records.append(json.load(fp))

    # 統計每個指標的最佳權重分佈
    weight_stats = {}
    for key in config.BIAS_WEIGHTS.keys():
        values = [r["new_weights"].get(key, 0) for r in records]
        avg = sum(values) / len(values) if values else 0
        std = math.sqrt(
            sum((v - avg) ** 2 for v in values) / len(values)
        ) if len(values) > 1 else 0

        weight_stats[key] = {
            "avg": round(avg, 2),
            "std": round(std, 2),
            "min": min(values),
            "max": max(values),
            "cv": round(std / avg, 3) if avg > 0 else float("inf"),
            "stable": std < 2.0,  # 標準差 < 2 視為穩定
        }

    # 按穩定性排序
    stable_keys = [k for k, v in weight_stats.items() if v["stable"]]
    volatile_keys = [k for k, v in weight_stats.items() if not v["stable"]]

    analysis = {
        "total_records": len(records),
        "date_range": {
            "first": records[0]["timestamp"],
            "last": records[-1]["timestamp"],
        },
        "weight_stats": weight_stats,
        "stable_indicators": stable_keys,
        "volatile_indicators": volatile_keys,
        "regime_distribution": {},
        "update_rate": sum(1 for r in records if r.get("updated")) / len(records),
    }

    # 統計市場狀態分佈
    for r in records:
        regime = r.get("market_regime", {}).get("regime", "unknown")
        analysis["regime_distribution"][regime] = (
            analysis["regime_distribution"].get(regime, 0) + 1
        )

    logger.info("\n📊 校準歷史分析:")
    logger.info(f"   記錄數: {len(records)}")
    logger.info(f"   更新率: {analysis['update_rate']:.1%}")
    logger.info(f"   穩定指標: {', '.join(stable_keys) or '無'}")
    logger.info(f"   變動指標: {', '.join(volatile_keys) or '無'}")
    logger.info(f"   市場狀態分佈: {analysis['regime_distribution']}")

    return analysis


# ═══════════════════════════════════════════════════════════════
# CLI 入口
# ═══════════════════════════════════════════════════════════════

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="🧀 乳酪のBTC預測室 — 自動校準排程工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例:
  python tools/auto_calibrate.py                    # 自動校準（符合條件自動更新）
  python tools/auto_calibrate.py --dry-run           # 只測試，不寫入
  python tools/auto_calibrate.py --threshold 0.15    # 改善 15% 才更新
  python tools/auto_calibrate.py --history           # 分析校準歷史

VPS crontab 設定:
  0 4 * * * cd /path/to/backend && python tools/auto_calibrate.py >> logs/calibrate.log 2>&1
        """,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只測試，不寫入 config.py",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.10,
        help="改善門檻百分比 (預設: 0.10 = 10%%)",
    )
    parser.add_argument(
        "-n", "--iterations",
        type=int,
        default=150,
        help="Random Search 迭代次數 (預設: 150)",
    )
    parser.add_argument(
        "--hill",
        type=int,
        default=80,
        help="Hill Climbing 迭代次數 (預設: 80)",
    )
    parser.add_argument(
        "--notify",
        action="store_true",
        help="校準完成後發送通知",
    )
    parser.add_argument(
        "--history",
        action="store_true",
        help="分析校準歷史（不執行新的校準）",
    )

    args = parser.parse_args()

    if args.history:
        analyze_calibration_history()
        return

    run_auto_calibration(
        dry_run=args.dry_run,
        improvement_threshold=args.threshold,
        random_iterations=args.iterations,
        hill_iterations=args.hill,
        notify=args.notify,
    )


if __name__ == "__main__":
    main()
