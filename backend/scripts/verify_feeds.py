
import asyncio
import logging
import sys
import os
from pathlib import Path
from datetime import datetime

# ✅ 修正 Python 路徑：指向 `backend` 資料夾
backend_dir = Path(__file__).resolve().parent.parent
sys.path.append(str(backend_dir))

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-7s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("feed_report.txt", mode='w', encoding='utf-8')
    ]
)
logger = logging.getLogger("feed_test")

try:
    from app.data_feeds.binance_feed import BinanceFeed
    from app.data_feeds.polymarket_feed import PolymarketFeed
    from app.data_feeds.chainlink_feed import ChainlinkFeed
    from app.core.event_bus import bus
except ImportError as e:
    logger.error(f"Import 錯誤: {e}")
    sys.exit(1)

async def test_feeds():
    logger.info("🚀 開始全功能數據源測試 (Binance, Polymarket, Chainlink)...")
    logger.info("=" * 60)

    # 1. 初始化 Feeds
    binance = BinanceFeed()
    polymarket = PolymarketFeed()
    chainlink = ChainlinkFeed()

    # 啟動並等待數據
    await bus.start() # 啟動事件匯流排以接收事件
    await binance.start()
    await polymarket.start()
    await chainlink.start()

    logger.info("⏳ 等待數據暖機 (15秒)...")
    await asyncio.sleep(15)

    # 2. 驗證 Binance 數據
    logger.info("-" * 60)
    logger.info("🔍 檢查 Binance Feed...")
    b_snap = binance.get_snapshot()
    if b_snap.get("connected") and b_snap.get("price", 0) > 0:
        logger.info(f"✅ Binance OK | Price: ${b_snap.get('price', 0):,.2f}")
    else:
        logger.error(f"❌ Binance 異常 | State: {b_snap}")

    # 3. 驗證 Polymarket 數據
    logger.info("-" * 60)
    logger.info("🔍 檢查 Polymarket Feed...")
    p_snap = polymarket.get_snapshot()
    if p_snap.get("market_slug"):
        logger.info(f"✅ Polymarket OK | Market: {p_snap.get('market_title')}")
        logger.info(f"   UP Price: {p_snap.get('up_price')} | DOWN Price: {p_snap.get('down_price')}")
        logger.info(f"   Liquidity: ${p_snap.get('liquidity', 0):,.2f}")
    else:
        logger.error(f"❌ Polymarket 異常 | State: {p_snap}")

    # 4. 驗證 Chainlink 數據
    logger.info("-" * 60)
    logger.info("🔍 檢查 Chainlink Feed...")
    c_snap = chainlink.get_snapshot()
    if c_snap.get("btc_price") and c_snap.get("btc_price") > 0:
        logger.info(f"✅ Chainlink OK | Price: ${c_snap.get('btc_price', 0):,.2f}")
        logger.info(f"   RPC Updated: {datetime.fromtimestamp(c_snap.get('updated_at', 0))}")
    else:
        logger.error(f"❌ Chainlink 異常 (可能是 RPC 限制) | State: {c_snap}")

    logger.info("=" * 60)
    
    # 5. 清理資源
    await binance.stop()
    await polymarket.stop()
    await chainlink.stop()
    await bus.stop()
    logger.info("👋 測試完成")

if __name__ == "__main__":
    try:
        if sys.platform == 'win32':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(test_feeds())
    except KeyboardInterrupt:
        pass
