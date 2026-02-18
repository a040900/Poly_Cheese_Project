
import sys
import os
import time
import logging

# 強制重新導向 stdout
sys.stdout.reconfigure(encoding='utf-8')

# 加入專案路徑
backend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app import config
from app.trading.simulator import SimulationEngine

# 設定 Log
logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger("test_profit_filter")

class MockPolymarketState:
    def __init__(self):
        self.up_price = 0.5
        self.down_price = 0.5
        self.up_bid = 0.49
        self.down_bid = 0.49
        self.up_spread = 0.02
        self.down_spread = 0.02
        self.market_title = "Test Market - BTC 15m"

def run_test():
    try:
        print("🚀 開始測試 Phase 2.1 利潤過濾器邏輯")
        print("="*60)

        sim = SimulationEngine(initial_balance=1000.0)
        sim.start()
        pm_state = MockPolymarketState()
        
        signal = {"direction": "BUY_UP", "score": 80, "confidence": 100, "mode": "balanced"}
        config.PROFIT_FILTER_ENABLED = True
        config.PROFIT_FILTER_MAX_SPREAD_PCT = 0.02
        
        # [測試 1] Spread 過大
        pm_state.up_price = 0.55
        pm_state.up_bid = 0.5225
        pm_state.up_spread = 0.05
        pm_state.market_title = "High Spread Market"
        
        trade1 = sim.execute_trade(signal, pm_state=pm_state)
        if trade1 is None:
            print("✅ [PASS 1] Spread 過大 (5%) -> 正確拒絕")
        else:
            print(f"❌ [FAIL 1] Spread 過大 -> 未被拒絕")

        # [測試 2] 利潤太薄
        pm_state.up_price = 0.98
        pm_state.up_bid = 0.97
        pm_state.up_spread = 0.01 
        pm_state.market_title = "Low Profit Market"

        trade2 = sim.execute_trade(signal, pm_state=pm_state)
        if trade2 is None:
            print("✅ [PASS 2] 利潤太薄 (價格 0.98) -> 正確拒絕")
        else:
            print(f"❌ [FAIL 2] 利潤太薄 -> 未被拒絕")

        # [測試 3] 正常交易 + 資料流驗證
        pm_state.up_price = 0.40
        pm_state.up_bid = 0.398
        pm_state.up_spread = 0.005 
        pm_state.market_title = "Good Market - BTC 15m"

        trade3 = sim.execute_trade(signal, pm_state=pm_state)
        if trade3:
            print(f"✅ [PASS 3] 正常交易 (價格 0.40) -> 成功開倉 ID:{trade3.trade_id}")
            
            # 驗證 Market Title (Backend Fix #2)
            if trade3.market_title == "Good Market - BTC 15m":
                print("✅ [PASS 3a] Market Title 正確抓取 (execute_trade)")
            else:
                print(f"❌ [FAIL 3a] Market Title 錯誤: {trade3.market_title}")
                
            # 驗證 Contract Price
            if trade3.contract_price == 0.40:
                print("✅ [PASS 3b] 合約價格正確")
            else:
                print(f"❌ [FAIL 3b] 合約價格錯誤")

            # 結算測試 (Backend Fix #1)
            sim.settle_trade(trade3, "UP", settlement_price=1.0)
            last_record = sim.trade_history[-1]
            
            if last_record.get("market_title") == "Good Market - BTC 15m":
                print("✅ [PASS 4] 結算歷史記錄保留 Market Title")
            else:
                print(f"❌ [FAIL 4] 結算歷史丟失 Market Title")
                
            # 驗證動態回報率PnL
            # 0.40 進場, 1000 * 0.1(mode=10%) = 100u, 手續費約 0.5u+1.5u=2u, 獲利約 150u, 淨利約 148u
            print(f"   PnL: ${last_record['pnl']:.2f}")

        else:
            print("❌ [FAIL 3] 正常交易 -> 意外被拒絕")

        print("="*60)
        print("🏁 全部測試完成")
        
    except Exception as e:
        print(f"❌ 測試發生未預期錯誤: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    run_test()
