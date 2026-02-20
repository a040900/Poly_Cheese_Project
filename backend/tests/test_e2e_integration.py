import asyncio
import httpx
import time
import json
import os

API_BASE = "http://localhost:8000/api"

async def test_full_system_flow():
    print("🚀 啟動完整測試流程...")
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        # 1. 檢查系統健康狀態
        print("1️⃣ 檢查系統健康狀態...")
        r = await client.get(f"{API_BASE}/components")
        assert r.status_code == 200
        health = r.json()
        print(f"✅ 系統運行中，元件數量: {len(health.get('components', []))}")
        
        # 2. 取得目前的 Supervisor 狀態
        print("2️⃣ 取得 Supervisor 狀態...")
        r = await client.get(f"{API_BASE}/supervisor/status")
        assert r.status_code == 200
        sv_status = r.json()
        print(f"✅ Supervisor Mode: {sv_status['auth_mode']}, Navigator: {sv_status['navigator']}")
        
        # 3. 更新 Supervisor 設定為測試模式
        print("3️⃣ 更新 Supervisor 設定為 HITL + Internal...")
        r = await client.post(f"{API_BASE}/supervisor/settings", json={
            "navigator": "internal",
            "auth_mode": "hitl"
        })
        assert r.status_code == 200
        
        # 4. 模擬 AI 傳送建議 (HITL 模式，應該會進入佇列)
        print("4️⃣ 模擬 AI 建議 (預期進入 Pending Queue)...")
        r = await client.post(f"{API_BASE}/llm/advice", json={
            "action": "SWITCH_MODE",
            "recommended_mode": "conservative",
            "reasoning": "Test automated flow",
            "confidence": 80,
            "source": "api"
        })
        assert r.status_code == 200
        advice_res = r.json()
        assert advice_res.get("status") == "queued"
        proposal_id = advice_res.get("proposal_id")
        print(f"✅ 提案成功進入佇列，ID: {proposal_id}")
        
        # 5. 核准提案
        print("5️⃣ 自動核准提案...")
        r = await client.post(f"{API_BASE}/supervisor/proposals/{proposal_id}/approve", json={
            "note": "Auto approved by test"
        })
        if r.status_code != 200:
            print(f"Error at step 5: {r.status_code} - {r.text}")
        assert r.status_code == 200
        assert r.json().get("success") == True
        print("✅ 提案核准成功")
        
        # 6. 確認交易模式被切換 (因為核准了 SWITCH_MODE)
        print("6️⃣ 驗證交易模式是否切換為 conservative...")
        r = await client.get(f"{API_BASE}/cro/stats")
        if r.status_code != 200:
            print(f"Error: {r.status_code} - {r.text}")
        assert r.status_code == 200
        assert r.json()["performance"]["current_mode"] == "conservative"
        print("✅ 交易模式驗證成功")
        
        # 7. 測試緊急安全閥 (預期直接放行 Auto Approved)
        print("7️⃣ 模擬緊急告警 (預期直接放行)...")
        r = await client.post(f"{API_BASE}/llm/advice", json={
            "action": "PAUSE_TRADING",
            "recommended_mode": "conservative",
            "reasoning": "Flash crash detected using test",
            "risk_level": "CRITICAL",
            "confidence": 99,
            "source": "api"
        })
        assert r.status_code == 200
        emergency_res = r.json()
        if emergency_res.get("status") != "emergency_auto_approved":
            print(f"Error, unexpected status: {emergency_res}")
        assert emergency_res.get("status") == "emergency_auto_approved"
        print("✅ 緊急防護機制驗證成功")
        
        # 8. 測試 Telegram 狀態
        print("8️⃣ 測試 Telegram Bot API...")
        r = await client.get(f"{API_BASE}/telegram/status")
        assert r.status_code == 200
        tg_status = r.json()
        print(f"✅ Telegram 狀態: Enabled={tg_status['enabled']}, Running={tg_status['running']}")
        
        print("\n🎉 完整端到端測試通過！系統各模組運作正常。")

if __name__ == "__main__":
    import sys
    # 強制設定輸出編碼
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(test_full_system_flow())
