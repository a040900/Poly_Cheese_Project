"""快速驗證 Phase 5 情緒因子是否正確整合"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import json
from app.strategy.signal_generator import SignalGenerator
from app import config

print("=== 直接測試 _calculate_market_sentiment ===")
sg = SignalGenerator()

# 情境 1: BTC 在 $67,300，目標 $67,500，UP 合約 $0.72 (市場非常看漲)
result = sg._calculate_market_sentiment(
    mid=67300.0,
    pm_up_price=0.72,
    pm_down_price=0.28,
    market_title="Will Bitcoin be above $67,500 at 2026-02-20 15:00 UTC?"
)
print(f"情境 1: BTC=$67,300 目標=$67,500 UP=$0.72")
print(json.dumps(result, indent=2, ensure_ascii=False))

# 情境 2: BTC 在 $67,600 (已突破)，UP 合約 $0.55 (市場很保守)
result2 = sg._calculate_market_sentiment(
    mid=67600.0,
    pm_up_price=0.55,
    pm_down_price=0.45,
    market_title="Will Bitcoin be above $67,500 at 2026-02-20 15:00 UTC?"
)
print(f"\n情境 2: BTC=$67,600 目標=$67,500 UP=$0.55")
print(json.dumps(result2, indent=2, ensure_ascii=False))

# 情境 3: BTC 在 $67,000 (遠低於目標)，UP 定價 $0.60 (散戶 FOMO)
result3 = sg._calculate_market_sentiment(
    mid=67000.0,
    pm_up_price=0.60,
    pm_down_price=0.40,
    market_title="Will Bitcoin be above $67,500 at 2026-02-20 15:00 UTC?"
)
print(f"\n情境 3: BTC=$67,000 目標=$67,500 UP=$0.60 (FOMO)")
print(json.dumps(result3, indent=2, ensure_ascii=False))

print("\n" + "=" * 60)
print("=== 測試各模式的情緒調整效果 ===")
print("=" * 60)

# 用情境 3 (FOMO) 來測試：技術面看多 +50，但市場已經 FOMO
modes = ["ultra_aggressive", "aggressive", "balanced", "conservative", "defensive"]
for mode_name in modes:
    mode_cfg = config.TRADING_MODES[mode_name]
    sens = mode_cfg.get("sentiment_sensitivity", 0)
    adjusted, details = sg._apply_sentiment_adjustment(+50.0, result3, mode_cfg)
    status = "✅ 不調整" if not details["applied"] else f"🎭 {details['reason']}"
    print(f"  {mode_name:20s} (sens={sens}) | +50 → {adjusted:+.1f} | {status}")

# 測試逆向：技術面看多 +50，但市場極度恐慌
result_fear = sg._calculate_market_sentiment(
    mid=67600.0,
    pm_up_price=0.20,
    pm_down_price=0.80,
    market_title="Will Bitcoin be above $67,500 at 2026-02-20 15:00 UTC?"
)
print(f"\n=== 逆向測試: BTC=$67,600 > 目標 但 UP=$0.20 (Panic) ===")
print(f"Sentiment: {json.dumps(result_fear, indent=2, ensure_ascii=False)}")

for mode_name in modes:
    mode_cfg = config.TRADING_MODES[mode_name]
    sens = mode_cfg.get("sentiment_sensitivity", 0)
    adjusted, details = sg._apply_sentiment_adjustment(+50.0, result_fear, mode_cfg)
    status = "✅ 不調整" if not details["applied"] else f"🎭 {details['reason']}"
    print(f"  {mode_name:20s} (sens={sens}) | +50 → {adjusted:+.1f} | {status}")

print("\n🎉 Phase 5 Hybrid Decision Engine 驗證完成！")
