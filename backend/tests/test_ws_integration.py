
import asyncio
import json
import websockets
import sys

async def test_ws():
    uri = "ws://localhost:8888/ws"
    print(f"🔗 連接 WebSocket: {uri}")
    try:
        async with websockets.connect(uri) as websocket:
            print("✅ 成功連線！等待初始數據...")
            message = await websocket.recv()
            data = json.loads(message)
            
            print("📦 收到初始數據 payload")
            
            # 驗證 Spread 欄位
            market = data.get("market", {})
            up_spread = market.get("pm_up_spread")
            down_spread = market.get("pm_down_spread")
            
            print(f"🔍 檢查 Spread 數據: UP={up_spread}, DOWN={down_spread}")
            
            if "pm_up_spread" in market and "pm_down_spread" in market:
                print("✅ PASS: Spread 欄位存在")
            else:
                print("❌ FAIL: Spread 欄位缺失")
                
            # 驗證 Market Title
            title = market.get("pm_market_title")
            print(f"🔍 檢查 Market Title: {title}")
            
            if "pm_market_title" in market:
                print("✅ PASS: Market Title 欄位存在")
            else:
                 print("❌ FAIL: Market Title 欄位缺失")

    except Exception as e:
        print(f"❌ WebSocket 連線失敗: {e}")

if __name__ == "__main__":
    # 需要先安裝 websockets: pip install websockets
    # 如果環境沒有，改用簡單的 socket 測試 HTTP
    try:
        asyncio.run(test_ws())
    except ImportError:
        print("⚠️ 未安裝 websockets 套件，跳過 WS 測試")
