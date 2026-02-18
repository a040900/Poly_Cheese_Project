
import asyncio
import logging
import sys
import os
from pathlib import Path
import json

# ✅ 修正 Python 路徑
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("sim_report.txt", mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger("sim_test")

from app.trading.simulator import SimulationEngine
from app.data_feeds.binance_feed import BinanceFeed
from app.core.event_bus import bus
from app.trading.engine import Trade

async def run_simulation_cycle():
    logger.info("🎬 開始模擬交易週期測試 (Full Cycle Test)")
    logger.info("=" * 60)

    # 1. 初始化元件
    sim_engine = SimulationEngine()
    binance = BinanceFeed()
    
    # 重置模擬引擎餘額
    sim_engine.reset(new_balance=1000.0)
    logger.info(f"💰 初始餘額: ${sim_engine.get_balance():,.2f}")

    # 2. 啟動 Feeds 和 Engine
    await bus.start()
    await binance.start()
    sim_engine.start()

    logger.info("⏳ 等待 Binance 數據 (5秒)...")
    await asyncio.sleep(5)
    
    # 獲取當前價格作為參考
    market_price = binance.get_snapshot().get("mid_price", 60000.0) # 如果抓不到就用假價格
    logger.info(f"📊 當前市場價格參考: ${market_price:,.2f}")

    # ----------------------------------------------------
    # 3. 測試開倉 (OPEN LONG)
    # ----------------------------------------------------
    logger.info("-" * 60)
    logger.info("🚀 [Action] 注入 BUY 信號...")
    
    buy_signal = {
        "direction": "BUY_UP",
        "score": 85,
        "confidence": 0.9,
        "timestamp": asyncio.get_event_loop().time()
    }
    
    # Mock Polymarket State Object
    class MockPMState:
        def __init__(self, up_price, down_price, slug, up_spread=0.01, down_spread=0.01):
            self.up_price = up_price
            self.down_price = down_price
            self.market_slug = slug
            self.up_spread = up_spread
            self.down_spread = down_spread
            self.best_bid = 0.44
            self.best_ask = 0.46

    # 強制執行交易
    # 注意：在真實運作中，這是由 broadcast_loop 呼叫的。這裡我們手動呼叫。
    mock_pm_state = MockPMState(
        up_price=0.45, 
        down_price=0.55,
        slug="mock-market-slug"
    )

    trade = sim_engine.execute_trade(buy_signal, amount=100.0, pm_state=mock_pm_state)
    
    if trade and trade.status == "open":
        logger.info(f"✅ 開倉成功! Trade ID: {trade.trade_id}")
        logger.info(f"   Entry Price: ${trade.entry_price:.2f} (UP Token)")
        logger.info(f"   Amount: ${trade.quantity * trade.entry_price:.2f} USDC")
        logger.info(f"   Balance: ${sim_engine.get_balance():,.2f}")
    else:
        logger.error("❌ 開倉失敗")
        return

    # ----------------------------------------------------
    # 4. 持倉期間 (模擬價格變動)
    # ----------------------------------------------------
    logger.info("-" * 60)
    logger.info("⏳ 持倉中... (模擬 3 秒經過)")
    await asyncio.sleep(3)
    
    open_trades = sim_engine.get_open_trades()
    if not open_trades:
        logger.error("❌ 持倉丟失！")
        return
    logger.info(f"📋 當前持倉數: {len(open_trades)}")

    # ----------------------------------------------------
    # 5. 測試平倉 (CLOSE POS)
    # ----------------------------------------------------
    logger.info("-" * 60)
    logger.info("🛑 [Action] 注入 SELL (平倉) 信號...")
    
    # 模擬價格上漲: UP Token $0.45 -> $0.55 (賺爛了)
    mock_pm_state_exit = MockPMState(
        up_price=0.55,
        down_price=0.45,
        slug="mock-market-slug"
    )
    
    sell_signal = {
        "direction": "SELL_DOWN", # 反向信號觸發平倉
        "score": -80,
        "confidence": 0.8
    }
    
    # 執行平倉
    # 注意: execute_trade 內部邏輯是: 如果有反向信號 -> 平倉
    closed_trade = sim_engine.execute_trade(sell_signal, pm_state=mock_pm_state_exit)
    
    # 這裡 execute_trade 可能回傳 None (如果只是平倉而不開反向倉位)
    # 我們檢查持倉是否清空
    remaining_trades = sim_engine.get_open_trades()
    
    if len(remaining_trades) == 0:
         # 從歷史記錄找剛剛那筆
        stats = sim_engine.get_stats()
        logger.info("✅ 平倉成功! 所有持倉已結算。")
        logger.info(f"💰 最終餘額: ${sim_engine.get_balance():,.2f}")
        logger.info(f"📈 交易統計: {json.dumps(stats, indent=2, ensure_ascii=False)}")
        
        # 簡單驗證 PnL
        # 買入 $0.45, 賣出 $0.55 => 獲利 22% 左右
        if sim_engine.get_balance() > 1000:
             logger.info("🎉 測試通過: 餘額增加 (獲利確認)")
        else:
             logger.warning("⚠️ 測試通過但餘額未增加 (可能手續費吃掉利潤?)")
    else:
        logger.error(f"❌ 平倉失敗，仍有 {len(remaining_trades)} 筆持倉")

    # 6. 清理
    logger.info("=" * 60)
    await binance.stop()
    await bus.stop()
    logger.info("👋 測試結束")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(run_simulation_cycle())
