
import asyncio
import json
import httpx
import websockets
import time

API_URL = "http://localhost:8888"
WS_URL = "ws://localhost:8888/ws"

SAMPLE_ADVICE = {
    "analysis": "BTC 當前在關鍵阻力位受阻，且訂單簿顯示上方賣壓沉重。即使目前均線向上，需提防短線回調。",
    "recommended_mode": "conservative",
    "confidence": 85,
    "risk_level": "HIGH",
    "action": "SWITCH_MODE",
    "param_adjustments": {},
    "reasoning": "觀察到 Polymarket 短線合約價格出現倒掛，且 Binance 現貨量能萎縮，建議保守應對。",
    "auto_apply": False
}

async def send_advice():
    """模擬 AI Agent 發送建議"""
    async with httpx.AsyncClient() as client:
        print(f"📤 發送測試建議至 {API_URL}/api/llm/advice ...")
        resp = await client.post(f"{API_URL}/api/llm/advice", json=SAMPLE_ADVICE)
        if resp.status_code == 200:
            print("✅ 建議發送成功 (HTTP 200)")
            return True
        else:
            print(f"❌ 發送失敗: {resp.status_code} - {resp.text}")
            return False

async def listen_for_advice_update():
    """監聽 WebSocket 是否收到最新的 Advice"""
    timeout = 10  # 10秒超時
    start_time = time.time()
    
    print(f"👂 連線 WebSocket {WS_URL} 等待更新...")
    try:
        async with websockets.connect(WS_URL) as websocket:
            # 觸發發送 (連線後稍等一下再發送，確保已 ready)
            await asyncio.sleep(1) 
            sent = await send_advice()
            if not sent:
                return False

            while True:
                if time.time() - start_time > timeout:
                    print("⏰ 測試超時：未收到預期的建議更新")
                    return False
                
                try:
                    message = await asyncio.wait_for(websocket.recv(), timeout=2.0)
                    data = json.loads(message)
                    
                    # 檢查 payload 中是否有 latest_advice
                    latest = data.get("latest_advice")
                    if latest:
                        # 比對內容是否為我們剛剛發送的
                        # 注意：後端會加上 timestamp 等欄位，我們比對 reasoning
                        if latest.get("reasoning") == SAMPLE_ADVICE["reasoning"]:
                            print("\n✨ 成功收到 AI 建議更新！")
                            print(f"   - Reasoning: {latest.get('reasoning')}")
                            print(f"   - Action: {latest.get('advice_type')}")
                            print(f"   - Mode: {latest.get('recommended_mode')}")
                            return True
                        else:
                            # 可能是舊的建議，繼續等待
                            pass
                    
                except asyncio.TimeoutError:
                    continue
                    
    except Exception as e:
        print(f"❌ WebSocket 連線錯誤: {e}")
        return False

if __name__ == "__main__":
    try:
        if asyncio.run(listen_for_advice_update()):
            print("✅ TEST PASSED: AI Advice flow is working correctly.")
            exit(0)
        else:
            print("❌ TEST FAILED: Verification failed.")
            exit(1)
    except KeyboardInterrupt:
        print("測試中斷")
