"""
🧀 CheeseDog - 事件匯流排 MessageBus (步驟 11)
借鏡 NautilusTrader MessageBus Pub/Sub 模式，實現事件驅動架構。

事件主題 (Topics):
    binance.trade       — 每筆 Binance 成交
    binance.kline       — K 線更新/收盤
    binance.orderbook   — 訂單簿更新
    polymarket.price    — Polymarket 合約價格更新
    chainlink.price     — Chainlink 鏈上價格更新
    signal.generated    — 新交易信號產生
    trade.opened        — 模擬交易開倉
    trade.settled       — 模擬交易結算
"""

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable, Optional

logger = logging.getLogger("cheesedog.core.bus")


# ═══════════════════════════════════════════════════════════════
# 事件資料結構
# ═══════════════════════════════════════════════════════════════
@dataclass
class Event:
    """事件物件"""
    topic: str          # 事件主題，如 "binance.trade"
    data: Any           # 事件資料
    timestamp: float = field(default_factory=time.time)
    source: str = ""    # 事件來源元件名稱


# 事件處理器型別：接受 Event，回傳 None（可以是 sync 或 async）
EventHandler = Callable[[Event], Any]


# ═══════════════════════════════════════════════════════════════
# 事件匯流排
# ═══════════════════════════════════════════════════════════════
class MessageBus:
    """
    輕量級非同步事件匯流排 (Pub/Sub)

    特點：
    - 支援 sync / async handler
    - Fire-and-forget publish (不阻塞發佈者)
    - 內建事件佇列，逐一分發，保證處理順序
    - 可統計事件吞吐量
    """

    def __init__(self, max_queue_size: int = 10000):
        self._subscribers: dict[str, list[EventHandler]] = defaultdict(list)
        self._queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=max_queue_size)
        self._running = False
        self._worker: Optional[asyncio.Task] = None

        # 統計
        self._published_count = 0
        self._processed_count = 0
        self._error_count = 0

    # ── 生命週期 ──────────────────────────────────────────────

    async def start(self):
        """啟動事件處理迴圈"""
        if self._running:
            return
        self._running = True
        self._worker = asyncio.create_task(self._dispatch_loop())
        logger.info("🚌 MessageBus 已啟動")

    async def stop(self):
        """停止事件處理迴圈"""
        self._running = False
        if self._worker:
            self._worker.cancel()
            try:
                await self._worker
            except asyncio.CancelledError:
                pass
            self._worker = None
        logger.info(
            f"🛑 MessageBus 已停止 "
            f"(發佈: {self._published_count}, "
            f"處理: {self._processed_count}, "
            f"錯誤: {self._error_count})"
        )

    # ── 訂閱 / 發佈 ──────────────────────────────────────────

    def subscribe(self, topic: str, handler: EventHandler):
        """訂閱事件主題"""
        if handler not in self._subscribers[topic]:
            self._subscribers[topic].append(handler)
            handler_name = getattr(handler, "__name__", repr(handler))
            logger.debug(f"📬 訂閱: {topic} → {handler_name}")

    def unsubscribe(self, topic: str, handler: EventHandler):
        """取消訂閱"""
        try:
            self._subscribers[topic].remove(handler)
        except ValueError:
            pass

    def publish(self, topic: str, data: Any = None, source: str = ""):
        """
        發佈事件（非阻塞）

        如果 MessageBus 未啟動或佇列已滿，事件將被丟棄。
        """
        if not self._running:
            return

        event = Event(topic=topic, data=data, source=source)
        try:
            self._queue.put_nowait(event)
            self._published_count += 1
        except asyncio.QueueFull:
            logger.warning(f"⚠️ 事件佇列已滿！丟棄事件: {topic}")

    # ── 內部分發迴圈 ──────────────────────────────────────────

    async def _dispatch_loop(self):
        """主事件分發迴圈"""
        while self._running:
            try:
                event = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            handlers = self._subscribers.get(event.topic, [])
            if not handlers:
                self._queue.task_done()
                continue

            for handler in handlers:
                try:
                    result = handler(event)
                    # 如果 handler 回傳 coroutine，await 它
                    if asyncio.iscoroutine(result):
                        await result
                except Exception as e:
                    self._error_count += 1
                    handler_name = getattr(handler, "__name__", repr(handler))
                    logger.error(
                        f"❌ 事件處理錯誤: {event.topic} → {handler_name}: {e}"
                    )

            self._processed_count += 1
            self._queue.task_done()

    # ── 統計 / 偵錯 ───────────────────────────────────────────

    def get_stats(self) -> dict:
        """取得 MessageBus 統計資訊"""
        return {
            "running": self._running,
            "published": self._published_count,
            "processed": self._processed_count,
            "errors": self._error_count,
            "queue_size": self._queue.qsize(),
            "subscriber_count": {
                topic: len(handlers)
                for topic, handlers in self._subscribers.items()
                if handlers
            },
        }


# ═══════════════════════════════════════════════════════════════
# 全域單例 — 整個系統共用一條 MessageBus
# ═══════════════════════════════════════════════════════════════
bus = MessageBus()
