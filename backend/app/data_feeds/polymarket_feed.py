"""
🧀 CheeseDog - Polymarket 數據獲取模組
透過 Gamma REST API 和 WebSocket 獲取 BTC 15 分鐘市場的數據。

Phase 2 變更：
- 繼承 Component 基類，具備 ComponentState 生命週期
- 透過 MessageBus 發佈 polymarket.price 事件
"""

import asyncio
import json
import time
import logging
from typing import Optional, Callable
from datetime import datetime, timezone, timedelta

import aiohttp

from app import config
from app.core.state import Component, ComponentState
from app.core.event_bus import bus

logger = logging.getLogger("cheesedog.feeds.polymarket")

# ── 月份名稱映射 ─────────────────────────────────────────────
_MONTHS = [
    "", "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december"
]


class PolymarketState:
    """Polymarket 數據狀態容器"""

    def __init__(self):
        # 市場基本資訊
        self.market_slug: Optional[str] = None
        self.market_title: Optional[str] = None
        self.market_end_time: Optional[float] = None

        # Token IDs
        self.up_token_id: Optional[str] = None
        self.down_token_id: Optional[str] = None

        # 合約價格 (best_ask = 買入價，best_bid = 賣出價)
        self.up_price: Optional[float] = None       # UP 合約 best_ask
        self.down_price: Optional[float] = None     # DOWN 合約 best_ask
        self.up_bid: Optional[float] = None         # UP 合約 best_bid
        self.down_bid: Optional[float] = None       # DOWN 合約 best_bid
        self.up_spread: Optional[float] = None      # UP 合約 spread 比例
        self.down_spread: Optional[float] = None    # DOWN 合約 spread 比例

        # 市場流動性
        self.liquidity: Optional[float] = None
        self.volume: Optional[float] = None

        # 連線狀態
        self.connected: bool = False
        self.last_update: float = 0.0
        self.error: Optional[str] = None


class PolymarketFeed(Component):
    """Polymarket 數據訂閱管理器"""

    def __init__(self):
        super().__init__("feeds.polymarket")
        self.state = PolymarketState()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._on_update: Optional[Callable] = None

    def set_update_callback(self, callback: Callable):
        """設定數據更新回調函數（向後相容）"""
        self._on_update = callback

    async def start(self):
        """啟動 Polymarket 數據訂閱"""
        if self._running:
            return
        self._running = True
        self.set_ready()

        logger.info("🟢 啟動 Polymarket 數據訂閱")

        # 先獲取當前市場資訊
        await self._fetch_market_info()

        # 啟動任務
        self._tasks = [
            asyncio.create_task(self._ws_feed()),
            asyncio.create_task(self._market_poller()),
        ]
        self.set_running()

    async def stop(self):
        """停止數據訂閱"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self.state.connected = False
        self.set_stopped()
        logger.info("🔴 Polymarket 數據訂閱已停止")

    def _build_slug(self) -> Optional[str]:
        """建構 Polymarket 市場 slug（15 分鐘 BTC 市場）"""
        now_utc = datetime.now(timezone.utc)
        now_ts = int(now_utc.timestamp())

        # BTC 15 分鐘市場的 slug 格式
        ts = (now_ts // 900) * 900
        slug = f"btc-updown-15m-{ts}"
        return slug

    async def _fetch_market_info(self):
        """從 Gamma API 獲取市場資訊"""
        try:
            slug = self._build_slug()
            if not slug:
                logger.warning("無法建構市場 slug")
                return

            async with aiohttp.ClientSession() as session:
                # 方法 1：嘗試直接用 slug 查詢
                url = config.PM_GAMMA_API
                params = {"slug": slug, "limit": 1}
                async with session.get(
                    url, params=params,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as resp:
                    data = await resp.json()

                # 如果直接查詢失敗，嘗試搜尋系列
                if not data:
                    params = {
                        "slug": config.PM_SERIES_SLUG,
                        "limit": 5,
                        "closed": "false",
                    }
                    async with session.get(
                        url, params=params,
                        timeout=aiohttp.ClientTimeout(total=10)
                    ) as resp:
                        data = await resp.json()

                if data and len(data) > 0:
                    event = data[0]
                    self.state.market_slug = event.get("ticker", slug)
                    self.state.market_title = event.get("title", "BTC 15m UP/DOWN")

                    # 提取市場資訊
                    markets = event.get("markets", [])
                    if markets:
                        market = markets[0]
                        self.state.liquidity = float(market.get("liquidity", 0))
                        self.state.volume = float(market.get("volume", 0))

                        # 提取 UP/DOWN token IDs
                        try:
                            token_ids = json.loads(market.get("clobTokenIds", "[]"))
                            if len(token_ids) >= 2:
                                self.state.up_token_id = token_ids[0]
                                self.state.down_token_id = token_ids[1]
                                logger.info(
                                    f"📊 Polymarket 市場: {self.state.market_title}\n"
                                    f"   UP Token: {self.state.up_token_id[:16]}...\n"
                                    f"   DN Token: {self.state.down_token_id[:16]}..."
                                )
                        except (json.JSONDecodeError, IndexError) as e:
                            logger.error(f"Token ID 解析失敗: {e}")

                        # 提取初始價格
                        try:
                            outcomes = json.loads(market.get("outcomePrices", "[]"))
                            if len(outcomes) >= 2:
                                self.state.up_price = float(outcomes[0])
                                self.state.down_price = float(outcomes[1])
                        except (json.JSONDecodeError, IndexError):
                            pass

                    self.state.last_update = time.time()
                    logger.info(f"✅ 已獲取 Polymarket 市場資訊: {self.state.market_slug}")
                else:
                    logger.warning(f"⚠️ 未找到活躍的 BTC 15m 市場 (slug: {slug})")
                    self.state.error = "未找到活躍市場"

        except Exception as e:
            logger.error(f"❌ 獲取 Polymarket 市場資訊失敗: {repr(e)}")
            self.state.error = str(e) or repr(e)

    async def _ws_feed(self):
        """WebSocket 數據流（合約價格實時更新）"""
        while self._running:
            # 確保有 Token IDs
            if not self.state.up_token_id:
                logger.info("等待 Token ID 初始化...5秒後重試")
                await asyncio.sleep(5)
                await self._fetch_market_info()
                continue

            assets = [self.state.up_token_id, self.state.down_token_id]

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.ws_connect(
                        config.PM_WS,
                        heartbeat=20,
                        timeout=aiohttp.ClientTimeout(total=None),
                    ) as ws:
                        # 訂閱市場數據
                        await ws.send_json({
                            "assets_ids": assets,
                            "type": "market"
                        })
                        self.state.connected = True
                        self.state.error = None
                        if self._component_state in (ComponentState.DEGRADED, ComponentState.FAULTED):
                            self.set_running()
                        logger.info("🔗 Polymarket WebSocket 已連線")

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
                self.state.error = str(e) or repr(e)
                self.set_degraded(f"WebSocket 斷線: {repr(e)}")
                logger.warning(f"⚠️ Polymarket WebSocket 斷線: {repr(e)}，10秒後重連...")
                await asyncio.sleep(10)

    def _process_ws_message(self, data):
        """處理 WebSocket 訊息"""
        try:
            if isinstance(data, list):
                for entry in data:
                    asset_id = entry.get("asset_id")
                    # 取得 best_ask（買入價）
                    best_ask = None
                    asks = entry.get("asks", [])
                    if asks:
                        best_ask = min(float(a["price"]) for a in asks)
                    # 取得 best_bid（賣出價）
                    best_bid = None
                    bids = entry.get("bids", [])
                    if bids:
                        best_bid = max(float(b["price"]) for b in bids)
                    if best_ask is not None:
                        self._update_price(asset_id, best_ask, best_bid)

            elif isinstance(data, dict):
                event_type = data.get("event_type", "")
                if event_type == "price_change":
                    for ch in data.get("price_changes", []):
                        best_ask = ch.get("best_ask")
                        best_bid = ch.get("best_bid")
                        if best_ask:
                            self._update_price(
                                ch["asset_id"],
                                float(best_ask),
                                float(best_bid) if best_bid else None,
                            )

            self.state.last_update = time.time()

            # 🚌 發佈事件到 MessageBus
            bus.publish(
                "polymarket.price",
                {
                    "up_price": self.state.up_price,
                    "down_price": self.state.down_price,
                    "up_bid": self.state.up_bid,
                    "down_bid": self.state.down_bid,
                    "up_spread": self.state.up_spread,
                    "down_spread": self.state.down_spread,
                },
                source=self._name,
            )

            # 向後相容：舊回調
            if self._on_update:
                self._on_update("polymarket", "price_update")

        except Exception as e:
            logger.debug(f"WebSocket 訊息處理錯誤: {e}")

    def _update_price(self, asset_id: str, ask_price: float, bid_price: Optional[float] = None):
        """
        更新 UP/DOWN 合約價格（含 bid/ask/spread）

        Args:
            asset_id: Token ID
            ask_price: 最佳賣價（= 買入成本）
            bid_price: 最佳買價（= 賣出可得），可能為 None
        """
        if asset_id == self.state.up_token_id:
            self.state.up_price = ask_price
            if bid_price is not None:
                self.state.up_bid = bid_price
                # 計算 spread: (ask - bid) / ask
                self.state.up_spread = round(
                    (ask_price - bid_price) / ask_price, 6
                ) if ask_price > 0 else None
        elif asset_id == self.state.down_token_id:
            self.state.down_price = ask_price
            if bid_price is not None:
                self.state.down_bid = bid_price
                self.state.down_spread = round(
                    (ask_price - bid_price) / ask_price, 6
                ) if ask_price > 0 else None

    async def _market_poller(self):
        """定期輪詢市場資訊（檢查市場更新、切換新市場）"""
        while self._running:
            await asyncio.sleep(config.PM_POLL_INTERVAL * 6)  # 每 30 秒
            try:
                await self._fetch_market_info()
            except Exception as e:
                logger.debug(f"市場輪詢錯誤: {e}")

    def get_snapshot(self) -> dict:
        """取得當前 Polymarket 數據快照"""
        return {
            "connected": self.state.connected,
            "last_update": self.state.last_update,
            "error": self.state.error,
            "market_slug": self.state.market_slug,
            "market_title": self.state.market_title,
            "up_price": self.state.up_price,
            "down_price": self.state.down_price,
            "up_bid": self.state.up_bid,
            "down_bid": self.state.down_bid,
            "up_spread": self.state.up_spread,
            "down_spread": self.state.down_spread,
            "liquidity": self.state.liquidity,
            "volume": self.state.volume,
            "has_tokens": self.state.up_token_id is not None,
            # Phase 2: 加入元件狀態
            "component_state": self._component_state.value,
        }
