"""
🧀 CheeseDog Polymarket 智慧交易輔助系統
FastAPI 主應用程式 - 系統核心控制模組
"""

import asyncio
import json
import time
import logging
import sys
from pathlib import Path
from contextlib import asynccontextmanager
from typing import Dict, List, Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app import config
from app.data_feeds.binance_feed import BinanceFeed
from app.data_feeds.polymarket_feed import PolymarketFeed
from app.data_feeds.chainlink_feed import ChainlinkFeed
from app.strategy.signal_generator import SignalGenerator
from app.trading.simulator import SimulationEngine
from app.security.password_manager import password_manager
from app.database import db

# ═══════════════════════════════════════════════════════════════
# 日誌設定
# ═══════════════════════════════════════════════════════════════
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL, logging.INFO),
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
sim_engine = SimulationEngine()

# WebSocket 連線管理
ws_clients: Set[WebSocket] = set()


# ═══════════════════════════════════════════════════════════════
# 數據更新回調
# ═══════════════════════════════════════════════════════════════
def on_data_update(source: str, event: str):
    """數據源更新時觸發"""
    pass  # WebSocket 推播由定時器處理


binance_feed.set_update_callback(on_data_update)
polymarket_feed.set_update_callback(on_data_update)
chainlink_feed.set_update_callback(on_data_update)


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


async def signal_loop():
    """定期生成交易信號"""
    while True:
        try:
            bs = binance_feed.state
            if bs.mid > 0 and bs.klines:
                # 合併當前 K 線
                all_klines = list(bs.klines)
                if bs.cur_kline:
                    all_klines.append(bs.cur_kline)

                signal = signal_generator.generate_signal(
                    bs.bids, bs.asks, bs.mid, bs.trades, all_klines
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

                # 如果模擬交易啟動且有明確信號，嘗試自動交易
                if sim_engine.is_running() and signal["direction"] != "NEUTRAL":
                    # 檢查是否已有同方向的未平倉交易
                    has_open = any(
                        t.direction == signal["direction"]
                        for t in sim_engine.open_trades
                    )
                    if not has_open:
                        sim_engine.execute_trade(signal)

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
            logger.error(f"信號生成循環錯誤: {e}")

        await asyncio.sleep(10)  # 每 10 秒更新信號


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
            },
            "polymarket": {
                "connected": ps.connected,
                "last_update": ps.last_update,
                "error": ps.error,
            },
            "chainlink": {
                "connected": cs.connected,
                "last_update": cs.last_update,
                "error": cs.error,
            },
        },
        "market": {
            "btc_price": bs.mid,
            "pm_up_price": ps.up_price,
            "pm_down_price": ps.down_price,
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
            "confidence": signal.get("confidence", 0),
            "threshold": signal.get("threshold", 40),
            "timestamp": signal.get("timestamp", 0),
        },
        "indicators": indicators,
        "trading": {
            "mode": signal_generator.current_mode,
            "mode_name": config.TRADING_MODES.get(
                signal_generator.current_mode, {}
            ).get("name", ""),
            "simulation": sim_engine.get_stats(),
            "pnl_curve": sim_engine.get_pnl_curve(),
        },
        "security": password_manager.get_status(),
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

    # 啟動數據訂閱
    await binance_feed.start()
    await polymarket_feed.start()
    await chainlink_feed.start()

    # 啟動模擬交易
    sim_engine.start()

    # 啟動背景任務
    broadcast_task = asyncio.create_task(broadcast_loop())
    signal_task = asyncio.create_task(signal_loop())

    logger.info("✅ 所有模組已啟動，系統就緒！")

    yield

    # 關閉
    logger.info("🔴 正在關閉系統...")
    broadcast_task.cancel()
    signal_task.cancel()
    sim_engine.stop()
    await binance_feed.stop()
    await polymarket_feed.stop()
    await chainlink_feed.stop()
    logger.info("👋 系統已安全關閉")


# ═══════════════════════════════════════════════════════════════
# FastAPI 應用程式
# ═══════════════════════════════════════════════════════════════
app = FastAPI(
    title=config.APP_NAME,
    version=config.VERSION,
    lifespan=lifespan,
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

@app.get("/")
async def serve_frontend():
    """提供前端頁面"""
    index_path = frontend_dir / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return JSONResponse({"message": f"🧀 {config.APP_NAME} API is running"})


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


# ═══════════════════════════════════════════════════════════════
# 入口點
# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=config.BACKEND_HOST,
        port=config.BACKEND_PORT,
        reload=False,
        log_level="info",
    )
