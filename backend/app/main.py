"""
🧀 CheeseDog Polymarket 智慧交易輔助系統
FastAPI 主應用程式 - 系統核心控制模組

Phase 2 變更：
- 整合 MessageBus 事件匯流排
- signal_loop 改為事件驅動（收到 binance.kline / binance.orderbook 立即計算）
- Dashboard 推播加入元件健康度資訊
"""

import asyncio
import json
import time
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, List, Set, Optional
from pydantic import BaseModel

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.core.event_bus import bus, Event
from app.data_feeds.binance_feed import BinanceFeed
from app.data_feeds.polymarket_feed import PolymarketFeed
from app.data_feeds.chainlink_feed import ChainlinkFeed
from app.strategy.signal_generator import SignalGenerator
from app.trading.engine import TradingEngine, EngineType
from app.trading.simulator import SimulationEngine
from app.trading.live_trader import LiveTradingEngine
from app.security.password_manager import password_manager
from app.database import db
from app.performance.tracker import PerformanceTracker
from app.performance.backtester import run_backtest, run_mode_comparison
from app.llm.prompt_builder import prompt_builder
from app.llm.advisor import llm_advisor
from app.llm.engine import ai_engine
from app.trading.risk_manager import risk_manager
from app.supervisor.authorization import auth_manager
from app.supervisor.proposal_queue import proposal_queue
from app.notifications.telegram_bot import telegram_bot


# ═══════════════════════════════════════════════════════════════
# 日誌設定
# ═══════════════════════════════════════════════════════════════
# 日誌設定
# ═══════════════════════════════════════════════════════════════
_log_level_str = config.LOG_LEVEL.upper() if hasattr(config, "LOG_LEVEL") else "INFO"
_log_level = getattr(logging, _log_level_str, None)
if not isinstance(_log_level, int):
    _log_level = logging.INFO  # fallback: 20

logging.basicConfig(
    level=_log_level,
    format="%(asctime)s | %(name)-30s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(
            config.LOG_DIR / "cheesedog.log",
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger("cheesedog.main")


# ═══════════════════════════════════════════════════════════════
# 全域元件實例
# ═══════════════════════════════════════════════════════════════
binance_feed = BinanceFeed()
polymarket_feed = PolymarketFeed()
chainlink_feed = ChainlinkFeed()
signal_generator = SignalGenerator()

# Step 15+16: 統一交易引擎介面
# 根據 PM_LIVE_ENABLED 環境變數自動選擇引擎
if config.PM_LIVE_ENABLED:
    logger.warning("🔴 實盤模式已啟用！所有交易將使用真實資金！")
    trading_engine: TradingEngine = LiveTradingEngine()
    trading_engine.set_trade_limits(
        max_single=config.PM_LIVE_MAX_SINGLE_TRADE,
        max_total=config.PM_LIVE_MAX_TOTAL_TRADED,
    )
else:
    trading_engine: TradingEngine = SimulationEngine()
sim_engine = trading_engine  # 向下相容別名
perf_tracker = PerformanceTracker(config.SIM_INITIAL_BALANCE)

# WebSocket 連線管理
ws_clients: Set[WebSocket] = set()

# 信號生成節流：避免極短時間內重複計算
_last_signal_time = 0.0
_SIGNAL_MIN_INTERVAL = 2.0  # 最少間隔 2 秒


# ═══════════════════════════════════════════════════════════════
# 數據更新回調（向後相容，Phase 2 主要靠 MessageBus）
# ═══════════════════════════════════════════════════════════════
def on_data_update(source: str, event: str):
    """數據源更新時觸發"""
    pass  # 已由 MessageBus 接管


binance_feed.set_update_callback(on_data_update)
polymarket_feed.set_update_callback(on_data_update)
chainlink_feed.set_update_callback(on_data_update)


# ═══════════════════════════════════════════════════════════════
# 事件驅動信號生成（Phase 2 步驟 11 核心）
# ═══════════════════════════════════════════════════════════════
async def on_market_data_event(event: Event):
    """
    當收到市場數據事件時，立即觸發信號計算。

    訂閱的事件:
    - binance.kline      (K 線更新)
    - binance.orderbook  (訂單簿更新)
    """
    global _last_signal_time

    # 節流：防止 binance.trade 高頻事件導致過度計算
    now = time.time()
    if now - _last_signal_time < _SIGNAL_MIN_INTERVAL:
        return

    _last_signal_time = now

    try:
        bs = binance_feed.state
        if bs.mid <= 0 or not bs.klines:
            return

        # 合併當前 K 線
        all_klines = list(bs.klines)
        if bs.cur_kline:
            all_klines.append(bs.cur_kline)

        signal = signal_generator.generate_signal(
            bs.bids, bs.asks, bs.mid, bs.trades, all_klines,
            pm_state=polymarket_feed.state,
        )

        # 儲存信號到資料庫
        db.save_signal({
            "direction": signal["direction"],
            "score": signal["score"],
            "confidence": signal["confidence"],
            "trading_mode": signal["mode"],
            "indicators": signal["indicators"],
            "acted_on": False,
        })

        # 🚌 發佈信號事件
        signal["btc_price"] = bs.mid
        signal["binance_last_update"] = bs.last_update
        bus.publish("signal.generated", signal, source="signal_generator")

        # 如果模擬交易啟動且有明確信號，嘗試自動交易
        if sim_engine.is_running() and signal["direction"] != "NEUTRAL":
            # 檢查是否已有同方向的未平倉交易
            has_open = any(
                t.direction == signal["direction"]
                for t in sim_engine.open_trades
            )
            if not has_open:
                sim_engine.execute_trade(signal, pm_state=polymarket_feed.state)

        # 保存市場快照
        pm = polymarket_feed.state
        cl = chainlink_feed.state
        db.save_market_snapshot({
            "btc_price": bs.mid,
            "pm_up_price": pm.up_price,
            "pm_down_price": pm.down_price,
            "chainlink_price": cl.btc_price,
            "bias_score": signal["score"],
            "signal": signal["direction"],
            "trading_mode": signal["mode"],
            "indicators": signal["indicators"],
        })

    except Exception as e:
        logger.error(f"事件驅動信號生成錯誤: {e}")


# ═══════════════════════════════════════════════════════════════
# 定時推播任務
# ═══════════════════════════════════════════════════════════════
async def broadcast_loop():
    """定期向所有 WebSocket 客戶端推播系統數據"""
    while True:
        try:
            if ws_clients:
                data = build_dashboard_data()
                message = json.dumps(data, default=str)
                disconnected = set()
                for ws in ws_clients:
                    try:
                        await ws.send_text(message)
                    except Exception:
                        disconnected.add(ws)
                ws_clients.difference_update(disconnected)
        except Exception as e:
            logger.debug(f"推播錯誤: {e}")
        await asyncio.sleep(config.REFRESH_INTERVAL)


async def settle_loop():
    """
    定期檢查並結算到期交易（保留定時器，因為結算依賴時間而非事件）
    """
    while True:
        try:
            bs = binance_feed.state
            cs = chainlink_feed.state
            # BUG FIX: 使用 Chainlink 價格進行結算 (與 Polymarket 官方一致)
            settle_price = cs.btc_price if cs.btc_price > 0 else bs.mid
            if settle_price > 0 and sim_engine.is_running():
                sim_engine.auto_settle_expired(settle_price)  # BUG FIX: 只傳入當前價格，開始價格從交易記錄讀取
        except Exception as e:
            logger.debug(f"結算循環錯誤: {e}")
        await asyncio.sleep(30)  # 每 30 秒檢查一次


# ═══════════════════════════════════════════════════════════════
# Dashboard 數據建構
# ═══════════════════════════════════════════════════════════════
def build_dashboard_data() -> dict:
    """建構完整的 Dashboard 數據"""
    bs = binance_feed.state
    ps = polymarket_feed.state
    cs = chainlink_feed.state

    # 計算指標
    all_klines = list(bs.klines)
    if bs.cur_kline:
        all_klines.append(bs.cur_kline)

    # 當前信號
    signal = signal_generator.last_signal or {}
    indicators = signal_generator.last_indicators or {}

    return {
        "timestamp": time.time(),
        "system": {
            "name": config.APP_NAME,
            "version": config.VERSION,
            "uptime": time.time(),
        },
        "connections": {
            "binance": {
                "connected": bs.connected,
                "last_update": bs.last_update,
                "error": bs.error,
                # Phase 2: 元件健康度
                "component_state": binance_feed.state_info["state"],
            },
            "polymarket": {
                "connected": ps.connected,
                "last_update": ps.last_update,
                "error": ps.error,
                "component_state": polymarket_feed.state_info["state"],
            },
            "chainlink": {
                "connected": cs.connected,
                "last_update": cs.last_update,
                "error": cs.error,
                "component_state": chainlink_feed.state_info["state"],
            },
        },
        "market": {
            "btc_price": bs.mid,
            "pm_up_price": ps.up_price,
            "pm_down_price": ps.down_price,
            "pm_up_bid": ps.up_bid,
            "pm_down_bid": ps.down_bid,
            "pm_up_spread": ps.up_spread,
            "pm_down_spread": ps.down_spread,
            "chainlink_price": cs.btc_price,
            "pm_market_title": ps.market_title,
            "pm_liquidity": ps.liquidity,
            "pm_volume": ps.volume,
            "orderbook": {
                "top_bids": bs.bids[:5],
                "top_asks": bs.asks[:5],
            },
            "trade_count": len(bs.trades),
            "kline_count": len(all_klines),
        },
        "signal": {
            "direction": signal.get("direction", "NEUTRAL"),
            "score": signal.get("score", 0),
            "raw_score": signal.get("raw_score", 0),
            "confidence": signal.get("confidence", 0),
            "threshold": signal.get("threshold", 40),
            "timestamp": signal.get("timestamp", 0),
        },
        "sentiment": signal.get("sentiment", {}),
        "sentiment_adjustment": signal.get("sentiment_adjustment", {}),
        "indicators": indicators,
        "trading": {
            "mode": signal_generator.current_mode,
            "mode_name": config.TRADING_MODES.get(
                signal_generator.current_mode, {}
            ).get("name", ""),
            "sentiment_sensitivity": config.TRADING_MODES.get(
                signal_generator.current_mode, {}
            ).get("sentiment_sensitivity", 0),
            "simulation": sim_engine.get_stats(pm_state=polymarket_feed.state),
            "recent_trades": sim_engine.get_recent_trades(),
            "pnl_curve": sim_engine.get_pnl_curve(),
        },
        "security": password_manager.get_status(),
        # Phase 2: MessageBus 統計
        "event_bus": bus.get_stats(),
        # Phase 2: 最新 AI 建議（推播到主畫面底部欄位）
        "latest_advice": llm_advisor.get_last_advice(),
    }


# ═══════════════════════════════════════════════════════════════
# 應用程式生命週期
# ═══════════════════════════════════════════════════════════════
@asynccontextmanager
async def lifespan(app: FastAPI):
    """應用程式啟動/關閉生命週期"""
    logger.info("=" * 60)
    logger.info(f"🧀 {config.APP_NAME} v{config.VERSION}")
    logger.info(f"   啟動中...")
    logger.info("=" * 60)

    # Phase 2: 啟動 MessageBus
    await bus.start()

    # 註冊事件訂閱（信號生成改為事件驅動）
    bus.subscribe("binance.kline", on_market_data_event)
    bus.subscribe("binance.orderbook", on_market_data_event)
    logger.info("📬 已註冊事件驅動信號生成 (binance.kline + binance.orderbook)")

    # 啟動數據訂閱
    await binance_feed.start()
    await polymarket_feed.start()
    await chainlink_feed.start()

    # 啟動模擬交易
    sim_engine.start()

    # Phase 4: 注入 SignalGenerator 到 AuthorizationManager
    auth_manager.inject_signal_generator(signal_generator)
    logger.info("🛡️ Phase 4 Supervisor 模組已就緒")

    # 啟動內建 AI 引擎 (Phase 3 P1)
    await ai_engine.start()

    # Phase 4: 啟動 Telegram Bot
    await telegram_bot.start()

    # 啟動背景任務（推播 + 結算，信號已改為事件驅動）
    broadcast_task = asyncio.create_task(broadcast_loop())
    settle_task = asyncio.create_task(settle_loop())

    logger.info("✅ 所有模組已啟動，系統就緒！")
    logger.info(
        f"🚌 信號引擎已切換至事件驅動模式 "
        f"(取代舊版 10 秒輪詢)"
    )

    yield

    # 關閉
    logger.info("🔴 正在關閉系統...")
    broadcast_task.cancel()
    settle_task.cancel()
    sim_engine.stop()
    await ai_engine.stop()
    await telegram_bot.stop()
    await binance_feed.stop()
    await polymarket_feed.stop()
    await chainlink_feed.stop()
    await bus.stop()
    logger.info("👋 系統已安全關閉")


# ═══════════════════════════════════════════════════════════════
# FastAPI 應用程式
# ═══════════════════════════════════════════════════════════════
app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    lifespan=lifespan,
    root_path=config.ROOT_PATH,
)

# CORS 中間件
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 靜態文件（前端）
frontend_dir = Path(__file__).parent.parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/static", StaticFiles(directory=str(frontend_dir)), name="static")


# ── 前端頁面 ─────────────────────────────────────────────────

from fastapi.responses import HTMLResponse


# ── AI 設定與狀態 API ──────────────────────────────────────────

class AISettingsModel(BaseModel):
    enabled: bool
    api_key: Optional[str] = None
    base_url: Optional[str] = None
    model: Optional[str] = None
    interval: Optional[int] = None

@app.get("/api/settings/ai")
async def get_ai_settings():
    """取得目前 AI 監控設定"""
    masked_key = ""
    if config.OPENAI_API_KEY and len(config.OPENAI_API_KEY) > 4:
        masked_key = "***" + config.OPENAI_API_KEY[-4:]
    
    return {
        "enabled": config.AI_MONITOR_ENABLED,
        "api_key": masked_key,
        "base_url": config.OPENAI_BASE_URL,
        "model": config.OPENAI_MODEL,
        "interval": config.AI_MONITOR_INTERVAL,
        "status": ai_engine.state.value if hasattr(ai_engine, "state") else "unknown"
    }

@app.post("/api/settings/ai")
async def update_ai_settings(settings: AISettingsModel):
    """更新 AI 監控設定並重啟引擎"""
    config.AI_MONITOR_ENABLED = settings.enabled
    
    # Only update if provided (allow partial updates for key security)
    if settings.api_key and settings.api_key.strip():
        if "***" not in settings.api_key:
             config.OPENAI_API_KEY = settings.api_key

    if settings.base_url:
        config.OPENAI_BASE_URL = settings.base_url
    if settings.model:
        config.OPENAI_MODEL = settings.model
    if settings.interval:
        config.AI_MONITOR_INTERVAL = settings.interval
        
    logger.info(f"🔧 AI 設定已更新: Enabled={settings.enabled}, Model={config.OPENAI_MODEL}")
    
    # Restart Engine to apply changes
    await ai_engine.stop()
    # Give a small pause? No need.
    
    if config.AI_MONITOR_ENABLED:
        await ai_engine.start()
        
    return {"status": "updated", "monitor_enabled": config.AI_MONITOR_ENABLED}


@app.get("/")
async def serve_frontend():
    """
    提供前端頁面。
    透過動態注入 <base> 標籤，確保在反向代理子路徑下
    CSS/JS 等相對路徑資源也能正確載入。
    """
    index_path = frontend_dir / "index.html"
    if not index_path.exists():
        return JSONResponse({"message": f"🧀 {config.APP_NAME} API is running"})

    html = index_path.read_text(encoding="utf-8")

    # 計算 <base> href: root_path + "/"
    base_href = (config.ROOT_PATH or "") + "/"
    base_tag = f'<base href="{base_href}">'

    # 注入到 <head> 之後（在 <meta charset> 之前最佳）
    html = html.replace("<head>", f"<head>\n    {base_tag}", 1)

    return HTMLResponse(content=html, media_type="text/html")


# ── WebSocket 端點 ───────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket 實時數據推播"""
    await websocket.accept()
    ws_clients.add(websocket)
    logger.info(f"🔗 WebSocket 客戶端已連線 (總計: {len(ws_clients)})")

    try:
        # 立即發送初始數據
        data = build_dashboard_data()
        await websocket.send_text(json.dumps(data, default=str))

        # 保持連線，處理客戶端訊息
        while True:
            msg = await websocket.receive_text()
            try:
                cmd = json.loads(msg)
                await handle_ws_command(websocket, cmd)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        ws_clients.discard(websocket)
        logger.info(f"🔌 WebSocket 客戶端已斷線 (剩餘: {len(ws_clients)})")


async def handle_ws_command(ws: WebSocket, cmd: dict):
    """處理 WebSocket 客戶端指令"""
    action = cmd.get("action")

    if action == "set_mode":
        mode = cmd.get("mode", "balanced")
        signal_generator.set_mode(mode)
        await ws.send_text(json.dumps({
            "type": "mode_changed",
            "mode": mode,
            "mode_name": config.TRADING_MODES.get(mode, {}).get("name", ""),
        }))

    elif action == "toggle_simulation":
        if sim_engine.is_running():
            sim_engine.stop()
        else:
            sim_engine.start()
        await ws.send_text(json.dumps({
            "type": "simulation_toggled",
            "running": sim_engine.is_running(),
        }))

    elif action == "reset_simulation":
        balance = cmd.get("balance", config.SIM_INITIAL_BALANCE)
        sim_engine.reset(balance)
        await ws.send_text(json.dumps({
            "type": "simulation_reset",
            "balance": balance,
        }))

    elif action == "request_password":
        result = password_manager.request_password()
        await ws.send_text(json.dumps({
            "type": "password_requested",
            **result,
        }))

    elif action == "verify_password":
        password = cmd.get("password", "")
        result = password_manager.verify_password(password)
        await ws.send_text(json.dumps({
            "type": "password_verified",
            **result,
        }))


# ── REST API 端點 ────────────────────────────────────────────

@app.get("/api/status")
async def get_system_status():
    """取得系統狀態"""
    return build_dashboard_data()


@app.get("/api/signal")
async def get_current_signal():
    """取得當前交易信號"""
    return signal_generator.last_signal or {"direction": "NEUTRAL", "score": 0}


@app.get("/api/signals/history")
async def get_signal_history(limit: int = 50):
    """取得歷史信號"""
    return db.get_recent_signals(limit)


@app.get("/api/trades")
async def get_trades(trade_type: str = "simulation", limit: int = 50):
    """取得交易記錄"""
    return db.get_trades(trade_type, limit)


@app.get("/api/trades/stats")
async def get_trade_stats(trade_type: str = "simulation"):
    """取得交易統計"""
    return db.get_trade_stats(trade_type)


@app.get("/api/simulation/stats")
async def get_simulation_stats():
    """取得模擬交易統計"""
    return sim_engine.get_stats()


@app.get("/api/simulation/pnl")
async def get_pnl_curve():
    """取得 PnL 曲線"""
    return sim_engine.get_pnl_curve()


@app.post("/api/mode/{mode}")
async def set_trading_mode(mode: str):
    """設定交易模式"""
    if mode not in config.TRADING_MODES:
        return JSONResponse(
            status_code=400,
            content={"error": f"無效的模式: {mode}"}
        )
    signal_generator.set_mode(mode)
    return {
        "mode": mode,
        "name": config.TRADING_MODES[mode]["name"],
        "description": config.TRADING_MODES[mode]["description"],
    }


@app.get("/api/modes")
async def get_available_modes():
    """取得所有可用交易模式"""
    return {
        "current": signal_generator.current_mode,
        "modes": {
            k: {"name": v["name"], "description": v["description"]}
            for k, v in config.TRADING_MODES.items()
        },
    }


@app.post("/api/security/request-password")
async def request_security_password():
    """觸發安全密碼請求"""
    return password_manager.request_password()


@app.post("/api/security/verify")
async def verify_security_password(data: dict):
    """驗證安全密碼"""
    return password_manager.verify_password(data.get("password", ""))


@app.get("/api/security/status")
async def get_security_status():
    """取得安全模組狀態"""
    return password_manager.get_status()


# Phase 2 步驟 12: 績效追蹤 + 回測 API
@app.get("/api/performance")
async def get_performance():
    """取得即時績效報告"""
    return perf_tracker.get_report()


@app.post("/api/backtest")
async def api_backtest(data: dict = None):
    """
    執行歷史回測

    Body (可選):
        {
            "mode": "balanced",
            "initial_balance": 1000,
            "limit": 5000,
            "use_fees": true
        }
    """
    data = data or {}
    try:
        result = run_backtest(
            mode=data.get("mode", "balanced"),
            initial_balance=data.get("initial_balance", 1000.0),
            limit=data.get("limit", 5000),
            use_fees=data.get("use_fees", True),
        )
        return result
    except Exception as e:
        logger.error(f"回測執行失敗: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/api/backtest/compare")
async def api_backtest_compare(data: dict = None):
    """
    比較所有交易模式的回測績效

    Body (可選):
        {
            "initial_balance": 1000,
            "limit": 5000
        }
    """
    data = data or {}
    try:
        result = run_mode_comparison(
            initial_balance=data.get("initial_balance", 1000.0),
            limit=data.get("limit", 5000),
        )
        return result
    except Exception as e:
        logger.error(f"回測比較失敗: {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})


# Phase 2 步驟 13: LLM 智能整合 API
@app.get("/api/llm/context")
async def get_llm_context():
    """
    取得結構化系統上下文

    宿主 AI 代理可透過此端點快速讀取完整的系統狀態。
    """
    bs = binance_feed.state
    ps = polymarket_feed.state
    cs = chainlink_feed.state
    signal = signal_generator.last_signal or {}
    indicators = signal_generator.last_indicators or {}

    context = prompt_builder.build_context_snapshot(
        market_data={
            "btc_price": bs.mid,
            "pm_up_price": ps.up_price,
            "pm_down_price": ps.down_price,
            "chainlink_price": cs.btc_price,
            "pm_market_title": ps.market_title,
            "pm_liquidity": ps.liquidity,
            "pm_volume": ps.volume,
            "trade_count": len(bs.trades),
            "kline_count": len(bs.klines),
        },
        signal_data=signal,
        indicators=indicators,
        performance=perf_tracker.get_report(),
        connections={
            "binance": {"connected": bs.connected, "state": binance_feed.state_info["state"]},
            "polymarket": {"connected": ps.connected, "state": polymarket_feed.state_info["state"]},
            "chainlink": {"connected": cs.connected, "state": chainlink_feed.state_info["state"]},
        },
        sim_stats=sim_engine.get_stats(),
    )
    return context


@app.get("/api/llm/prompt")
async def get_llm_prompt(focus: str = "general"):
    """
    生成分析 prompt

    Query params:
        focus: general | signal | risk | mode_switch
    """
    bs = binance_feed.state
    ps = polymarket_feed.state
    cs = chainlink_feed.state
    signal = signal_generator.last_signal or {}
    indicators = signal_generator.last_indicators or {}

    context = prompt_builder.build_context_snapshot(
        market_data={
            "btc_price": bs.mid,
            "pm_up_price": ps.up_price,
            "pm_down_price": ps.down_price,
            "chainlink_price": cs.btc_price,
            "pm_market_title": ps.market_title,
            "pm_liquidity": ps.liquidity,
            "pm_volume": ps.volume,
            "trade_count": len(bs.trades),
            "kline_count": len(bs.klines),
        },
        signal_data=signal,
        indicators=indicators,
        performance=perf_tracker.get_report(),
        connections={},
        sim_stats=sim_engine.get_stats(),
    )

    prompt_text = prompt_builder.build_analysis_prompt(context, focus=focus)
    return {"prompt": prompt_text, "focus": focus}


@app.post("/api/llm/advice")
async def receive_llm_advice(data: dict):
    """
    接收 AI 代理的分析建議 (Phase 4: 經過 AuthorizationManager 路由)

    Body:
        {
            "analysis": "分析文字",
            "recommended_mode": "balanced",
            "confidence": 85,
            "risk_level": "LOW",
            "action": "SWITCH_MODE",
            "param_adjustments": { ... },
            "reasoning": "理由",
            "source": "api"  (可選: "api" | "internal" | "openclaw")
        }

    回傳結果會根據 AUTHORIZATION_MODE 不同而不同:
        - auto:    {"status": "auto_executed", ...}
        - hitl:    {"status": "queued", "proposal_id": "xxx", ...}
        - monitor: {"status": "monitored", ...}
    """
    source = data.pop("source", "api")
    result = auth_manager.process_advice(
        advice_data=data,
        source=source,
    )
    return result


@app.post("/api/llm/apply")
async def apply_llm_advice(data: dict):
    """
    手動應用 AI 建議

    當 auto_apply=false 時，可以透過此端點手動應用之前收到的建議。
    """
    last_advice = llm_advisor.get_last_advice()
    if not last_advice:
        return JSONResponse(status_code=404, content={"error": "無待應用的建議"})

    # 從最近的建議中提取 advice_data
    advice_data = {
        "recommended_mode": last_advice.get("recommended_mode"),
        "action": last_advice.get("advice_type"),
        "param_adjustments": last_advice.get("market_context", {}).get("param_adjustments", {}),
    }
    result = llm_advisor.apply_advice(advice_data, signal_generator)
    return result


@app.get("/api/llm/stats")
async def get_llm_stats():
    """取得 LLM 建議處理統計"""
    return llm_advisor.get_stats()


@app.get("/api/llm/history")
async def get_llm_history(limit: int = 20):
    """取得 LLM 建議歷史"""
    return llm_advisor.get_advice_history(limit)


# ═══════════════════════════════════════════════════════════════
# Phase 2: 元件健康度 & MessageBus 統計 API
# ═══════════════════════════════════════════════════════════════

@app.get("/api/components")
async def get_components():
    """取得所有元件的健康狀態"""
    components = []
    for comp in [binance_feed, polymarket_feed, chainlink_feed]:
        info = comp.state_info
        info["uptime_seconds"] = round(time.time() - info.get("since", time.time()), 1)
        components.append(info)
    return {"components": components}


@app.get("/api/bus/stats")
async def get_bus_stats():
    """取得 MessageBus 統計"""
    stats = bus.get_stats()
    return {
        "running": stats.get("running", False),
        "total_published": stats.get("published", 0),
        "total_processed": stats.get("processed", 0),
        "total_errors": stats.get("errors", 0),
        "queue_size": stats.get("queue_size", 0),
        "subscriber_count": stats.get("subscriber_count", {}),
    }


# ═══════════════════════════════════════════════════════════════
# Phase 3 P2: 風險管理 API
# ═══════════════════════════════════════════════════════════════

@app.get("/api/risk")
async def get_risk_status():
    """取得風險管理狀態（Kelly Criterion + Circuit Breakers）"""
    return risk_manager.get_status()


# ═══════════════════════════════════════════════════════════════
# Phase 4: Supervisor API（提案佇列 + 授權管理）
# ═══════════════════════════════════════════════════════════════

@app.get("/api/supervisor/status")
async def get_supervisor_status():
    """取得 Supervisor 模組完整狀態（Navigator + AuthMode + 佇列統計）"""
    return auth_manager.get_status()


@app.get("/api/supervisor/proposals")
async def get_pending_proposals():
    """
    取得待審核的提案列表

    回傳按優先級排序的待審核提案（CRITICAL > HIGH > NORMAL > LOW）。
    過期的提案會在此呼叫時自動清理。
    """
    return {
        "proposals": proposal_queue.get_pending(),
        "total_pending": len(proposal_queue.get_pending()),
    }


@app.get("/api/supervisor/proposals/{proposal_id}")
async def get_proposal_detail(proposal_id: str):
    """取得單一提案的詳細資訊"""
    proposal = proposal_queue.get_proposal(proposal_id)
    if not proposal:
        return JSONResponse(
            status_code=404,
            content={"error": f"提案 {proposal_id} 不存在"}
        )
    return proposal


@app.post("/api/supervisor/proposals/{proposal_id}/approve")
async def approve_proposal(proposal_id: str, data: dict = None):
    """
    核准提案

    Body (可選):
        {"note": "核准備註"}
    """
    data = data or {}
    result = proposal_queue.approve(
        proposal_id=proposal_id,
        note=data.get("note", ""),
    )
    if not result["success"]:
        return JSONResponse(status_code=400, content=result)
    return result


@app.post("/api/supervisor/proposals/{proposal_id}/reject")
async def reject_proposal(proposal_id: str, data: dict = None):
    """
    拒絕提案

    Body (可選):
        {"note": "拒絕原因"}
    """
    data = data or {}
    result = proposal_queue.reject(
        proposal_id=proposal_id,
        note=data.get("note", ""),
    )
    if not result["success"]:
        return JSONResponse(status_code=400, content=result)
    return result


@app.get("/api/supervisor/history")
async def get_proposal_history(limit: int = 50):
    """取得已處理的提案歷史"""
    return {
        "history": proposal_queue.get_history(limit),
        "stats": proposal_queue.get_stats(),
    }


class SupervisorSettingsModel(BaseModel):
    navigator: Optional[str] = None   # "openclaw" | "internal" | "none"
    auth_mode: Optional[str] = None   # "auto" | "hitl" | "monitor"


@app.post("/api/supervisor/settings")
async def update_supervisor_settings(settings: SupervisorSettingsModel):
    """
    更新 Supervisor 設定（Navigator + Authorization Mode）

    Body:
        {
            "navigator": "internal",  // 可選
            "auth_mode": "hitl"       // 可選
        }
    """
    result = auth_manager.update_settings(
        navigator=settings.navigator,
        auth_mode=settings.auth_mode,
    )
    if not result["success"]:
        return JSONResponse(status_code=400, content=result)
    return result


# ── Telegram Bot API ─────────────────────────────────────────

@app.get("/api/telegram/status")
async def get_telegram_status():
    """取得 Telegram Bot 狀態"""
    return telegram_bot.get_status()


class TelegramConfigModel(BaseModel):
    bot_token: Optional[str] = None
    chat_id: Optional[str] = None
    enabled: Optional[bool] = None


@app.post("/api/telegram/configure")
async def configure_telegram(settings: TelegramConfigModel):
    """
    動態配置 Telegram Bot（供 AI Agent 使用）

    Body:
        {
            "bot_token": "123456:ABCdefGHI...",  // 可選
            "chat_id": "987654321",               // 可選
            "enabled": true                        // 可選
        }

    設定完成且 enabled=true 後，Bot 會自動啟動。
    """
    result = await telegram_bot.configure(
        bot_token=settings.bot_token,
        chat_id=settings.chat_id,
        enabled=settings.enabled,
    )
    return result


@app.post("/api/telegram/test")
async def test_telegram():
    """發送測試訊息到 Telegram"""
    success = await telegram_bot.send_message(
        "🧪 *測試訊息*\n\n"
        "如果你看到這則訊息，代表 Telegram Bot 配置正確！\n"
        f"⏰ {time.strftime('%Y-%m-%d %H:%M:%S')}"
    )
    return {"success": success}


# ═══════════════════════════════════════════════════════════════
# Phase 3: CRO Dashboard API（供 AI Agent 使用）
# ═══════════════════════════════════════════════════════════════

def _calc_btc_volatility_1h() -> dict:
    """計算 BTC 1 小時波動率（基於 Binance K 線）"""
    klines = list(binance_feed.state.klines)
    if len(klines) < 4:
        return {"value": 0.0, "level": "UNKNOWN"}

    # 取最近 4 根 15m K 線 = 1 小時
    recent = klines[-4:]
    hi = max(k["h"] for k in recent)
    lo = min(k["l"] for k in recent)
    mid = (hi + lo) / 2
    volatility_pct = ((hi - lo) / mid * 100) if mid > 0 else 0.0

    if volatility_pct >= 5.0:
        level = "EXTREME"
    elif volatility_pct >= 3.0:
        level = "HIGH"
    elif volatility_pct >= 1.0:
        level = "MEDIUM"
    else:
        level = "LOW"

    return {"value": round(volatility_pct, 2), "level": level}


def _calc_market_liquidity() -> dict:
    """計算 Polymarket 市場流動性狀態"""
    pm = polymarket_feed.state
    up_spread = pm.up_spread or 0
    down_spread = pm.down_spread or 0
    avg_spread = (up_spread + down_spread) / 2 if (up_spread or down_spread) else 0

    if avg_spread >= 0.05:
        level = "CRITICAL"
    elif avg_spread >= 0.03:
        level = "LOW"
    elif avg_spread >= 0.015:
        level = "MEDIUM"
    else:
        level = "GOOD"

    return {
        "up_spread": round(up_spread * 100, 2) if up_spread else None,
        "down_spread": round(down_spread * 100, 2) if down_spread else None,
        "avg_spread_pct": round(avg_spread * 100, 2),
        "liquidity_usd": pm.liquidity,
        "level": level,
    }


@app.get("/api/cro/compact")
async def get_cro_compact():
    """
    🔋 Token 節約版 CRO API — 供 VPS AI Agent 高頻監控使用

    設計目標：將整個系統狀態壓縮至 ~300 tokens 以內。
    AI Agent 應優先使用此端點，僅在需要深入分析時才呼叫 /api/cro/stats。

    回傳格式：極度精簡的單層 key-value，所有 key 使用縮寫。

    Key 說明:
      btc   = BTC 價格
      sig   = 信號方向 (U=BUY_UP, D=SELL_DOWN, N=NEUTRAL)
      sc    = 信號分數 (-100~+100)
      mode  = 交易模式 (agg/bal/con/def/ultra)
      wr6h  = 近6小時勝率 (%)
      wr24h = 近24小時勝率 (%)
      pnl   = 總 PnL ($)
      bal   = 帳戶餘額 ($)
      open  = 未平倉交易數
      dd    = 最大回撤 (%)
      closs = 連續虧損次數
      vol   = BTC 1h 波動率等級 (L/M/H/X)
      liq   = 流動性等級 (G/M/L/C)
      sprd  = 平均 Spread (%)
      hp    = 系統健康 (1=OK, 0=ERROR)
      adv   = 建議行動 (HOLD/SWITCH/PAUSE/ALERT)
      advTo = 建議切換目標模式 (若有)
    """
    signal_stats = signal_generator.get_cro_stats()
    sim_stats = sim_engine.get_stats()
    volatility = _calc_btc_volatility_1h()
    liquidity = _calc_market_liquidity()

    components_ok = all(
        comp._component_state.value == "running"
        for comp in [binance_feed, polymarket_feed, chainlink_feed]
    )

    # 信號方向縮寫
    sig_dir = signal_generator.last_signal or {}
    dir_map = {"BUY_UP": "U", "SELL_DOWN": "D", "NEUTRAL": "N"}
    sig_short = dir_map.get(sig_dir.get("direction", "NEUTRAL"), "N")

    # 模式縮寫
    mode_map = {
        "ultra_aggressive": "ultra", "aggressive": "agg",
        "balanced": "bal", "conservative": "con", "defensive": "def",
    }
    mode_short = mode_map.get(signal_stats.get("current_mode", "balanced"), "bal")

    # 波動率縮寫
    vol_map = {"LOW": "L", "MEDIUM": "M", "HIGH": "H", "EXTREME": "X"}
    vol_short = vol_map.get(volatility.get("level", "MEDIUM"), "M")

    # 流動性縮寫
    liq_map = {"GOOD": "G", "MEDIUM": "M", "LOW": "L", "CRITICAL": "C"}
    liq_short = liq_map.get(liquidity.get("level", "MEDIUM"), "M")

    # 快速建議判斷（與 /api/cro/stats 同邏輯，但只回傳最高優先級）
    adv = "HOLD"
    adv_to = None
    wr6h = signal_stats.get("win_rate_6h", 50)
    trades_24h = signal_stats.get("total_trades_24h", 0)
    c_losses = signal_stats.get("consecutive_losses", 0)

    if volatility.get("level") == "EXTREME":
        adv, adv_to = "PAUSE", None
    elif liquidity.get("level") == "CRITICAL":
        adv, adv_to = "PAUSE", None
    elif wr6h < 40 and trades_24h >= 5:
        adv, adv_to = "SWITCH", "con"
    elif c_losses >= 4:
        adv, adv_to = "SWITCH", "con"
    elif (wr6h >= 70 and trades_24h >= 5
          and vol_short in ("L", "M") and liq_short in ("G", "M")
          and mode_short != "agg"):
        adv, adv_to = "SWITCH", "agg"

    result = {
        "btc": round(chainlink_feed.state.btc_price or binance_feed.state.mid, 2),
        "sig": sig_short,
        "sc": round(sig_dir.get("score", 0), 1),
        "mode": mode_short,
        "wr6h": round(wr6h, 1),
        "wr24h": round(signal_stats.get("win_rate_24h", 0), 1),
        "pnl": round(sim_stats.get("total_pnl", 0), 2),
        "bal": round(sim_stats.get("balance", 0), 2),
        "open": sim_stats.get("open_trades", 0),
        "dd": round(signal_stats.get("max_drawdown_pct", 0), 1),
        "closs": c_losses,
        "vol": vol_short,
        "liq": liq_short,
        "sprd": round(liquidity.get("avg_spread_pct", 0), 2),
        "hp": 1 if components_ok else 0,
        "adv": adv,
    }
    if adv_to:
        result["advTo"] = adv_to

    return result

@app.get("/api/cro/stats")
async def get_cro_stats():
    """
    CRO Dashboard API — 供 VPS AI Agent (OpenClaw) 使用

    回傳高層次的聚合決策數據，包含：
    - 策略績效健康度 (win_rate, drawdown, profit_factor)
    - 市場狀態 (volatility, liquidity, spread)
    - 當前交易模式
    - 建議行動 (advisory)

    AI Agent 應每 30 分鐘 ~ 1 小時呼叫一次此端點。
    """
    # 策略績效（來自 SignalGenerator CRO 統計）
    signal_stats = signal_generator.get_cro_stats()

    # 模擬交易引擎統計
    sim_stats = sim_engine.get_stats()

    # 市場狀態
    volatility = _calc_btc_volatility_1h()
    liquidity = _calc_market_liquidity()

    # 系統健康度
    components_ok = all(
        comp._component_state.value == "running"
        for comp in [binance_feed, polymarket_feed, chainlink_feed]
    )

    # ── 生成建議 (Advisory) ─────────────────────────────────
    advisories = []

    # 低勝率警告
    if signal_stats["win_rate_6h"] < 40 and signal_stats["total_trades_24h"] >= 5:
        advisories.append({
            "severity": "WARNING",
            "type": "ALPHA_DECAY",
            "message": f"近 6h 勝率僅 {signal_stats['win_rate_6h']}%，建議切換至 conservative 模式",
            "suggested_action": "SWITCH_MODE",
            "suggested_value": "conservative",
        })

    # 高波動警告
    if volatility["level"] in ("HIGH", "EXTREME"):
        advisories.append({
            "severity": "CRITICAL" if volatility["level"] == "EXTREME" else "WARNING",
            "type": "HIGH_VOLATILITY",
            "message": f"BTC 1h 波動率 {volatility['value']}% ({volatility['level']})，建議暫停或降級",
            "suggested_action": "PAUSE_TRADING" if volatility["level"] == "EXTREME" else "SWITCH_MODE",
            "suggested_value": "pause" if volatility["level"] == "EXTREME" else "conservative",
        })

    # 流動性危機
    if liquidity["level"] in ("LOW", "CRITICAL"):
        advisories.append({
            "severity": "CRITICAL" if liquidity["level"] == "CRITICAL" else "WARNING",
            "type": "LOW_LIQUIDITY",
            "message": f"Polymarket 平均 Spread {liquidity['avg_spread_pct']}%，流動性{liquidity['level']}",
            "suggested_action": "PAUSE_TRADING",
            "suggested_value": "pause",
        })

    # 連敗警告
    if signal_stats["consecutive_losses"] >= 4:
        advisories.append({
            "severity": "WARNING",
            "type": "LOSING_STREAK",
            "message": f"連續虧損 {signal_stats['consecutive_losses']} 筆，建議降低倉位或暫停",
            "suggested_action": "SWITCH_MODE",
            "suggested_value": "conservative",
        })

    # 順風期 → 可以考慮激進
    if (signal_stats["win_rate_6h"] >= 70
            and signal_stats["total_trades_24h"] >= 5
            and volatility["level"] in ("LOW", "MEDIUM")
            and liquidity["level"] in ("GOOD", "MEDIUM")
            and signal_stats["current_mode"] != "aggressive"):
        advisories.append({
            "severity": "INFO",
            "type": "HOT_STREAK",
            "message": f"近 6h 勝率 {signal_stats['win_rate_6h']}% 且市場穩定，可考慮升級 aggressive",
            "suggested_action": "SWITCH_MODE",
            "suggested_value": "aggressive",
        })

    return {
        "timestamp": time.time(),
        "performance": signal_stats,
        "simulation": {
            "balance": sim_stats.get("balance", 0),
            "total_pnl": sim_stats.get("total_pnl", 0),
            "open_trades": sim_stats.get("open_trades", 0),
            "is_running": sim_engine.is_running(),
        },
        "market_condition": {
            "btc_volatility": volatility,
            "polymarket_liquidity": liquidity,
            "btc_price": chainlink_feed.state.btc_price,
        },
        "system_health": {
            "all_components_ok": components_ok,
            "event_bus_running": bus.get_stats().get("running", False),
        },
        "advisories": advisories,
        "advisory_count": len(advisories),
    }


# ═══════════════════════════════════════════════════════════════
# 入口點
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=config.BACKEND_HOST,
        port=config.BACKEND_PORT,
        root_path=config.ROOT_PATH,
        reload=False,
        log_level="info",
    )
