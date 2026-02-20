
"""
🧀 CheeseDog - 內建 AI 引擎 (Internal AI Engine)
直接由後端呼叫 OpenAI API (或兼容介面) 進行系統分析，替代外部 Agent。
"""
import asyncio
import logging
import json
import time
from typing import Optional

import aiohttp

from app import config
from app.core.state import Component
from app.core.event_bus import bus
from app.llm.prompt_builder import prompt_builder
from app.llm.advisor import llm_advisor

logger = logging.getLogger("cheesedog.llm.engine")

class AIEngine(Component):
    """
    內建 AI 引擎
    定期收集系統狀態 -> 構建 Prompt -> 呼叫 LLM API -> 執行建議
    """
    
    def __init__(self):
        super().__init__("llm.engine")
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._last_run_time = 0.0
        self._next_run_time = 0.0
    
    async def start(self):
        """啟動 AI 監控循環"""
        if not config.AI_MONITOR_ENABLED:
            logger.info("⚪ AI 監控已停用 (config.AI_MONITOR_ENABLED=False)")
            return

        if self._running:
            return

        # 檢查 API Key
        if not config.OPENAI_API_KEY:
            logger.warning("⚠️ AI 監控已啟用但缺少 OPENAI_API_KEY，無法啟動")
            return

        self._running = True
        self._task = asyncio.create_task(self._monitor_loop())
        self.set_running()
        logger.info(f"🟢 AI 監控引擎已啟動 (間隔: {config.AI_MONITOR_INTERVAL}s)")

    async def stop(self):
        """停止 AI 監控"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        self.set_stopped()
        logger.info("🔴 AI 監控引擎已停止")

    async def _monitor_loop(self):
        """監控迴圈"""
        while self._running:
            try:
                now = time.time()
                self._last_run_time = now
                self._next_run_time = now + config.AI_MONITOR_INTERVAL
                
                await self._perform_analysis()
                
                # 計算剩餘等待時間
                wait_time = max(1.0, self._next_run_time - time.time())
                logger.debug(f"AI 引擎進入休眠 {wait_time:.1f} 秒")
                await asyncio.sleep(wait_time)
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"AI 監控迴圈錯誤: {e}", exc_info=True)
                await asyncio.sleep(60) # 出錯後等待 1 分鐘重試

    async def _perform_analysis(self):
        """執行一次完整的分析流程"""
        logger.info("🧠 AI 引擎開始分析系統狀態...")
        
        # 1. 收集 Context
        # 這邊需要取得各組件的實例。
        # 為了避免循環引用，我們從 main app 或是全域變數取得?
        # 更好的方式是 prompt_builder 提供方法來組合資料。
        # 目前 prompt_builder.build_context_snapshot 需要傳入資料。
        
        # 由於我們在 Component 內部，不容易直接存取 main.py 裡的 binance_feed 等實例。
        # 我們可以使用 Event Bus 的 'snapshot' request?
        # 或者直接依賴全域變數 (Python 模組單例特性)。
        # 為了簡單起見，我們在 main.py 裡把 AIEngine 初始化並傳入依賴，或者在此 import main (會有循環引用)。
        
        # 解法：我們在 app.main 裡將資料 feed 注入到一個全域可訪問的地方，或者直接在這裡 import app.main (在函數內 import 避開循環)。
        try:
            from app.main import (
                binance_feed, polymarket_feed, chainlink_feed,
                signal_generator, trading_engine, perf_tracker
            )
        except ImportError:
            logger.error("無法匯入系統組件，跳過分析")
            return

        market_data = {
            "binance": binance_feed.get_snapshot(),
            "polymarket": polymarket_feed.get_snapshot(),
            "chainlink": chainlink_feed.get_snapshot(),
        }
        
        signal_data = signal_generator.get_snapshot()
        indicators = signal_generator.indicators.get_snapshot() if hasattr(signal_generator, "indicators") else {}
        performance = perf_tracker.get_snapshot()
        sim_stats = trading_engine.get_snapshot()
        
        connections = {
            "binance": binance_feed.state.connected,
            "polymarket": polymarket_feed.state.connected,
            "chainlink": chainlink_feed.state.connected,
        }

        context = prompt_builder.build_context_snapshot(
            market_data, signal_data, indicators, performance, connections, sim_stats
        )
        
        # 2. 建構 Prompt (專注於 Mode Switch 和 Risk)
        prompt = prompt_builder.build_analysis_prompt(context, focus="general")
        
        # 3. 呼叫 LLM
        logger.info(f"📤 發送 Prompt 至 {config.OPENAI_MODEL} ({len(prompt)} chars)...")
        response_json = await self._call_openai(prompt)
        
        if not response_json:
            logger.warning("⚠️ LLM 未回傳有效回應")
            return

        # 4. 處理建議 (Phase 4: 經過 AuthorizationManager 路由)
        try:
            from app.supervisor.authorization import auth_manager
            result = auth_manager.process_advice(
                advice_data=response_json,
                source="internal",  # 來自內建 AI 引擎
            )
        except ImportError:
            # Fallback: 若 Supervisor 模組不可用，直接走舊流程
            result = llm_advisor.process_advice(
                response_json, 
                signal_generator=signal_generator,
                auto_apply=True,
            )
        
        logger.info(f"✅ 分析完成: {result.get('status')} - {result.get('advice', {}).get('action', 'N/A')}")


    async def _call_openai(self, prompt: str) -> Optional[dict]:
        """呼叫 OpenAI Compatible API"""
        headers = {
            "Authorization": f"Bearer {config.OPENAI_API_KEY}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": config.OPENAI_MODEL,
            "messages": [
                {"role": "system", "content": self._get_system_prompt()},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7,
            "response_format": {"type": "json_object"} # 強制 JSON
        }
        
        url = f"{config.OPENAI_BASE_URL.rstrip('/')}/chat/completions"
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers, timeout=60) as resp:
                    if resp.status != 200:
                        text = await resp.text()
                        logger.error(f"OpenAI API Error ({resp.status}): {text}")
                        return None
                    
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    
                    # 清理可能的 Markdown code block
                    if "```json" in content:
                        content = content.replace("```json", "").replace("```", "")
                    
                    return json.loads(content)
                    
        except Exception as e:
            logger.error(f"OpenAI Call Failed: {e}")
            return None

    def _get_system_prompt(self) -> str:
        """內建 System Prompt (簡化版)"""
        return """
你是一個專業的加密貨幣與預測市場交易分析師 AI。
你的任務是根據提供的「乳酪のBTC預測室」系統狀態，分析市場趨勢並提供操作建議。

請嚴格遵守以下 JSON 回應格式：
{
    "analysis": "簡短分析市場狀態、趨勢強弱與風險...",
    "recommended_mode": "aggressive" | "balanced" | "conservative",
    "confidence": 0-100,
    "risk_level": "LOW" | "MEDIUM" | "HIGH",
    "action": "HOLD" | "SWITCH_MODE" | "PAUSE_TRADING",
    "param_adjustments": {
        "indicator_weights": {
            "rsi": 5, "macd": 10, "ema": 5 
            // 僅在有強烈理由時建議調整 (範圍 1-20)
        }
    },
    "reasoning": "為什麼做出這個建議..."
}

分析重點：
1. 觀察 btc_price 趨勢 與 polymarket 價格價差 (spread)。
2. 參考 technical_indicators (RSI, MACD, EMA)。
3. 當趨勢不明確時，建議 conservative 或 balanced。
4. 當趨勢強烈且指標一致時，建議 aggressive。
5. 若發現極端風險或數據延遲，建議 PAUSE_TRADING。
"""

# Global Instance
ai_engine = AIEngine()
