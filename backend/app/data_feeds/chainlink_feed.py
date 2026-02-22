"""
🧀 CheeseDog - Chainlink 鏈上價格獲取模組
透過 Polygon RPC 從 Chainlink 預言機獲取 BTC/USD 實時價格。

Phase 2 變更：
- 繼承 Component 基類，具備 ComponentState 生命週期
- 透過 MessageBus 發佈 chainlink.price 事件
"""

import asyncio
import logging
import time
from typing import Optional, Callable

import aiohttp

from app import config
from app.core.state import Component, ComponentState
from app.core.event_bus import bus

logger = logging.getLogger("cheesedog.feeds.chainlink")


class ChainlinkState:
    """Chainlink 數據狀態容器"""

    def __init__(self):
        self.btc_price: Optional[float] = None
        self.round_id: Optional[int] = None
        self.updated_at: Optional[float] = None
        self.decimals: int = 8  # BTC/USD 預設精度

        # 連線狀態
        self.connected: bool = False
        self.last_update: float = 0.0
        self.error: Optional[str] = None


# 已廢棄備用 Polygon RPC URL 列表（公共免費節點），改用私有節點
# 從 config 中直接取得用戶專屬的高效能 RPC URL

class ChainlinkFeed(Component):
    """Chainlink 鏈上價格訂閱管理器"""

    def __init__(self):
        super().__init__("feeds.chainlink")
        self.state = ChainlinkState()
        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._on_update: Optional[Callable] = None
        self._rpc_index = 0  # 當前使用的 RPC URL 索引
        self._consecutive_failures = 0

    def set_update_callback(self, callback: Callable):
        """設定數據更新回調函數（向後相容）"""
        self._on_update = callback

    async def start(self):
        """啟動 Chainlink 價格輪詢"""
        if self._running:
            return
        self._running = True
        self.set_ready()

        logger.info("🟢 啟動 Chainlink BTC/USD 價格訂閱")

        # 先獲取精度
        await self._fetch_decimals()

        # 啟動輪詢
        self._tasks = [
            asyncio.create_task(self._price_poller()),
        ]
        self.set_running()

    async def stop(self):
        """停止價格輪詢"""
        self._running = False
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()
        self.state.connected = False
        self.set_stopped()
        logger.info("🔴 Chainlink 價格訂閱已停止")

    def _current_rpc_url(self) -> str:
        """取得當前使用的 RPC URL"""
        return config.POLYGON_RPC_URL

    def _rotate_rpc(self):
        """（已停用）私有 RPC 不再輪換"""
        logger.warning("⚠️ Chainlink RPC 發生連續失敗，但由於使用專屬私有節點，將不進行輪換。")
    async def _eth_call(self, data: str) -> Optional[str]:
        """執行以太坊 RPC 呼叫（含備用 RPC 輪換）"""
        payload = {
            "jsonrpc": "2.0",
            "method": "eth_call",
            "params": [
                {
                    "to": config.CHAINLINK_BTC_USD_AGGREGATOR,
                    "data": data,
                },
                "latest",
            ],
            "id": 1,
        }

        rpc_url = self._current_rpc_url()
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    rpc_url,
                    json=payload,
                    timeout=aiohttp.ClientTimeout(total=15),
                ) as resp:
                    result = await resp.json()
                    if "error" in result:
                        logger.error(f"RPC 錯誤 ({rpc_url}): {result['error']}")
                        self._consecutive_failures += 1
                        if self._consecutive_failures >= 3:
                            self._rotate_rpc()
                            self._consecutive_failures = 0
                        return None
                    self._consecutive_failures = 0
                    return result.get("result")
        except Exception as e:
            self._consecutive_failures += 1
            logger.warning(f"⚠️ RPC 呼叫失敗 ({rpc_url}): {repr(e)}")
            if self._consecutive_failures >= 3:
                self._rotate_rpc()
                self._consecutive_failures = 0
            return None

    async def _fetch_decimals(self):
        """獲取 Chainlink 價格精度"""
        # decimals() 函數選擇器: 0x313ce567
        result = await self._eth_call("0x313ce567")
        if result:
            try:
                self.state.decimals = int(result, 16)
                logger.info(f"📊 Chainlink BTC/USD 精度: {self.state.decimals}")
            except (ValueError, TypeError):
                logger.warning("無法解析精度，使用預設值 8")

    async def _fetch_latest_price(self):
        """獲取 Chainlink 最新價格"""
        # latestRoundData() 函數選擇器: 0xfeaf968c
        result = await self._eth_call("0xfeaf968c")
        if not result or result == "0x":
            return

        try:
            # 解析返回數據（5 個 uint256/int256 值）
            # roundId, answer, startedAt, updatedAt, answeredInRound
            hex_data = result[2:]  # 移除 0x
            if len(hex_data) < 320:  # 5 * 64 hex chars
                return

            # answer 在第 2 個 slot（offset 64-128）
            answer_hex = hex_data[64:128]
            # updatedAt 在第 4 個 slot（offset 192-256）
            updated_hex = hex_data[192:256]

            # 處理有符號整數
            answer = int(answer_hex, 16)
            if answer > 2**255:
                answer -= 2**256

            updated_at = int(updated_hex, 16)

            price = answer / (10 ** self.state.decimals)

            self.state.btc_price = price
            self.state.updated_at = updated_at
            self.state.connected = True
            self.state.last_update = time.time()
            self.state.error = None

            logger.debug(f"📈 Chainlink BTC/USD: ${price:,.2f}")

            # 🚌 發佈事件到 MessageBus
            bus.publish(
                "chainlink.price",
                {"btc_price": price, "updated_at": updated_at},
                source=self._name,
            )

            # 向後相容：舊回調
            if self._on_update:
                self._on_update("chainlink", "price_update")

        except Exception as e:
            logger.error(f"價格解析錯誤: {e}")
            self.state.error = str(e)

    async def fetch_current_price(self) -> Optional[float]:
        """
        即時獲取 Chainlink 最新價格（用於結算等關鍵時刻）
        
        Returns:
            當前 BTC/USD 價格，如果獲取失敗則返回 None
        """
        await self._fetch_latest_price()
        return self.state.btc_price

    async def _price_poller(self):
        """定期輪詢 Chainlink 價格"""
        while self._running:
            try:
                await self._fetch_latest_price()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.state.error = str(e)
                logger.debug(f"Chainlink 輪詢錯誤: {e}")

            await asyncio.sleep(config.CHAINLINK_POLL_INTERVAL)

    def get_snapshot(self) -> dict:
        """取得當前 Chainlink 數據快照"""
        return {
            "connected": self.state.connected,
            "last_update": self.state.last_update,
            "error": self.state.error,
            "btc_price": self.state.btc_price,
            "updated_at": self.state.updated_at,
            "decimals": self.state.decimals,
            # Phase 2: 加入元件狀態
            "component_state": self._component_state.value,
        }
