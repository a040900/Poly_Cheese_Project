"""
🧀 CheeseDog - Binance 數據獲取模組
透過 WebSocket 和 REST API 獲取 BTCUSDT 的實時與歷史數據。
"""

import asyncio
import json
import time
import logging
from typing import Optional, Callable

import aiohttp

from app import config

logger = logging.getLogger("cheesedog.feeds.binance")


class BinanceState:
    """Binance 數據狀態容器"""

    def __init__(self):
        # 訂單簿
        self.bids: list[tuple[float, float]] = []
        self.asks: list[tuple[float, float]] = []
        self.mid: float = 0.0

        # 實時交易
        self.trades: list[dict] = []

        # K 線
        self.klines: list[dict] = []
        self.cur_kline: Optional[dict] = None

        # 連線狀態
        self.connected: bool = False
        self.last_update: float = 0.0
        self.error: Optional[str] = None


class BinanceFeed:
    """Binance 數據訂閱管理器"""

    def __init__(self, symbol: str = config.BINANCE_SYMBOL):
        self.symbol = symbol
        self.state = BinanceState()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._on_update: Optional[Callable] = None

    def set_update_callback(self, callback: Callable):
        """設定數據更新回調函數"""
        self._on_update = callback

    async def start(self):
        """啟動所有數據訂閱"""
        if self._running:
            return
        self._running = True

        logger.info(f"🟢 啟動 Binance 數據訂閱 [{self.symbol}]")

        # 先載入歷史 K 線
        await self._bootstrap_klines()

        # 啟動併行任務
        self._tasks = [
            asyncio.create_task(self._ws_feed()),
            asyncio.create_task(self._ob_poller()),
        ]

    async def stop(self):
        """停止所有數據訂閱"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self.state.connected = False
        logger.info("🔴 Binance 數據訂閱已停止")

    async def _bootstrap_klines(self):
        """啟動時載入歷史 K 線數據"""
        url = f"{config.BINANCE_REST}/klines"
        params = {
            "symbol": self.symbol,
            "interval": config.KLINE_INTERVAL,
            "limit": config.KLINE_BOOT,
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    data = await resp.json()
                    self.state.klines = [
                        {
                            "t": r[0] / 1e3,
                            "o": float(r[1]),
                            "h": float(r[2]),
                            "l": float(r[3]),
                            "c": float(r[4]),
                            "v": float(r[5]),
                        }
                        for r in data
                    ]
                    logger.info(f"📊 已載入 {len(self.state.klines)} 根歷史 K 線")
        except Exception as e:
            logger.error(f"❌ 載入歷史 K 線失敗: {e}")
            self.state.error = str(e)

    async def _ws_feed(self):
        """WebSocket 數據流（交易 + K 線）"""
        sym = self.symbol.lower()
        streams = "/".join([
            f"{sym}@trade",
            f"{sym}@kline_{config.KLINE_INTERVAL}",
        ])
        url = f"{config.BINANCE_WS}?streams={streams}"

        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        url,
                        heartbeat=20,
                        timeout=aiohttp.ClientTimeout(total=None),
                    ) as ws:
                        self.state.connected = True
                        self.state.error = None
                        logger.info(f"🔗 Binance WebSocket 已連線 [{self.symbol}]")

                        async for msg in ws:
                            if not self._running:
                                break
                            if msg.type == aiohttp.WSMsgType.TEXT:
                                self._process_ws_message(json.loads(msg.data))
                            elif msg.type == aiohttp.WSMsgType.ERROR:
                                logger.error(f"WebSocket 錯誤: {ws.exception()}")
                                break

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.state.connected = False
                self.state.error = str(e)
                logger.warning(f"⚠️ Binance WebSocket 斷線: {e}，5秒後重連...")
                await asyncio.sleep(5)

    def _process_ws_message(self, data: dict):
        """處理 WebSocket 訊息"""
        stream = data.get("stream", "")
        pay = data.get("data", {})

        if "@trade" in stream:
            self._handle_trade(pay)
        elif "@kline" in stream:
            self._handle_kline(pay)

        self.state.last_update = time.time()

        # 觸發更新回調
        if self._on_update:
            self._on_update("binance", stream)

    def _handle_trade(self, pay: dict):
        """處理交易數據"""
        self.state.trades.append({
            "t": pay["T"] / 1000.0,
            "price": float(pay["p"]),
            "qty": float(pay["q"]),
            "is_buy": not pay["m"],
        })

        # 清理過期交易數據
        if len(self.state.trades) > config.TRADE_MAX_BUFFER:
            cut = time.time() - config.TRADE_TTL
            self.state.trades = [
                t for t in self.state.trades if t["t"] >= cut
            ]

    def _handle_kline(self, pay: dict):
        """處理 K 線數據"""
        k = pay["k"]
        candle = {
            "t": k["t"] / 1000.0,
            "o": float(k["o"]),
            "h": float(k["h"]),
            "l": float(k["l"]),
            "c": float(k["c"]),
            "v": float(k["v"]),
        }
        self.state.cur_kline = candle

        # K 線收盤時新增到數組
        if k["x"]:
            self.state.klines.append(candle)
            self.state.klines = self.state.klines[-config.KLINE_MAX:]

    async def _ob_poller(self):
        """訂單簿輪詢器（REST API）"""
        url = f"{config.BINANCE_REST}/depth"
        logger.info(f"📖 啟動訂單簿輪詢 [{self.symbol}] 每 {config.OB_POLL_INTERVAL} 秒")

        while self._running:
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params={"symbol": self.symbol, "limit": config.OB_LEVELS},
                        timeout=aiohttp.ClientTimeout(total=5),
                    ) as resp:
                        data = await resp.json()
                        self.state.bids = [
                            (float(p), float(q)) for p, q in data["bids"]
                        ]
                        self.state.asks = [
                            (float(p), float(q)) for p, q in data["asks"]
                        ]
                        if self.state.bids and self.state.asks:
                            self.state.mid = (
                                self.state.bids[0][0] + self.state.asks[0][0]
                            ) / 2
                        self.state.last_update = time.time()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"訂單簿輪詢錯誤: {e}")

            await asyncio.sleep(config.OB_POLL_INTERVAL)

    def get_snapshot(self) -> dict:
        """取得當前 Binance 數據快照"""
        all_klines = list(self.state.klines)
        if self.state.cur_kline:
            all_klines = all_klines + [self.state.cur_kline]

        return {
            "connected": self.state.connected,
            "last_update": self.state.last_update,
            "error": self.state.error,
            "symbol": self.symbol,
            "mid_price": self.state.mid,
            "bids": self.state.bids[:5],  # 前 5 檔買盤
            "asks": self.state.asks[:5],  # 前 5 檔賣盤
            "trade_count": len(self.state.trades),
            "kline_count": len(all_klines),
            "current_kline": self.state.cur_kline,
        }
