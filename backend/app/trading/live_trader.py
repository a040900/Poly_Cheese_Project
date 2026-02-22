"""
🧀 乳酪のBTC預測室 — 實盤交易引擎 (Step 16)
=================================================

實作 TradingEngine 介面，串接 Polymarket CLOB API。

⚠️ 重要注意事項（借鏡 NautilusTrader 文件）：
    - Market BUY = Quote Quantity (USDC 面值)
    - Market SELL = Base Quantity (Token 數量)
    - Python 訂單簽名約需 1 秒延遲
    - 15m 市場是 Polymarket 少數收費的市場類型

認證流程：
    1. 使用 Private Key 初始化 ClobClient (L1 Auth)
    2. 衍生 API Credentials (L2 Auth)
    3. 所有交易請求使用 L2 HMAC-SHA256 簽名
"""

import time
import logging
import asyncio
from typing import Optional, Dict, List, Any

from app import config
from app.database import db
from app.strategy.fees import fee_model
from app.trading.engine import TradingEngine, EngineType, Trade, TradeStatus
from app.trading.risk_manager import risk_manager

logger = logging.getLogger("cheesedog.trading.live")

# ═══════════════════════════════════════════════════════════════
# Polymarket CLOB 常數
# ═══════════════════════════════════════════════════════════════
CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon Mainnet


class LiveTradingEngine(TradingEngine):
    """
    實盤交易引擎（實作 TradingEngine 介面）

    串接 Polymarket CLOB API 進行真實交易。
    使用 py-clob-client 官方 SDK。
    """

    @property
    def engine_type(self) -> EngineType:
        return EngineType.LIVE

    def __init__(self):
        self._running = False
        self._balance: float = 0.0
        self._open_trades: List[Trade] = []
        self._trade_history: List[dict] = []
        self._trade_counter: int = 0
        self._client = None  # ClobClient 實例
        self._api_creds_set = False

        # 安全鎖：一旦觸發緊急停止，需要手動重置
        self._emergency_locked = False
        self._emergency_reason = ""

        # 交易上限保護（首次實盤強制小額）
        self._max_single_trade_usdc = 10.0  # 🔒 硬上限：單筆最多 $10
        self._total_traded_usdc = 0.0
        self._max_total_traded_usdc = 100.0  # 🔒 硬上限：累計最多 $100

        logger.info("🔴 實盤交易引擎已初始化")

    # ── 生命週期 ──────────────────────────────────────────────

    def start(self) -> None:
        """
        啟動實盤引擎

        流程：
        1. 讀取環境變數中的 Private Key
        2. 初始化 ClobClient
        3. 衍生 API Credentials
        4. 驗證連線
        """
        if self._emergency_locked:
            logger.error(
                f"🚨 引擎已被緊急鎖定！原因: {self._emergency_reason} | "
                "請呼叫 reset() 後重新啟動"
            )
            return

        private_key = config.__dict__.get("PM_PRIVATE_KEY") or \
                      __import__("os").environ.get("WALLET_PRIVATE_KEY", "")

        if not private_key:
            logger.error(
                "❌ 無法啟動實盤引擎：缺少 WALLET_PRIVATE_KEY 環境變數\n"
                "   請在 .env 檔案中設定 WALLET_PRIVATE_KEY=<your-private-key>"
            )
            return

        try:
            from py_clob_client.client import ClobClient

            # 讀取可選的 funder 地址和簽名類型
            funder = __import__("os").environ.get("PM_FUNDER_ADDRESS", "")
            sig_type = int(__import__("os").environ.get("PM_SIGNATURE_TYPE", "0"))

            client_kwargs = {
                "host": CLOB_HOST,
                "key": private_key,
                "chain_id": CHAIN_ID,
            }
            if funder:
                client_kwargs["funder"] = funder
                client_kwargs["signature_type"] = sig_type

            self._client = ClobClient(**client_kwargs)

            # 衍生 L2 API Credentials
            self._client.set_api_creds(self._client.create_or_derive_api_creds())
            self._api_creds_set = True

            # 驗證連線
            ok = self._client.get_ok()
            server_time = self._client.get_server_time()
            logger.info(
                f"✅ Polymarket CLOB API 連線成功\n"
                f"   Server OK: {ok}\n"
                f"   Server Time: {server_time}\n"
                f"   Chain ID: {CHAIN_ID}\n"
                f"   安全上限: 單筆 ${self._max_single_trade_usdc} | "
                f"累計 ${self._max_total_traded_usdc}"
            )

            self._running = True
            logger.info("🟢 實盤交易引擎已啟動")

        except ImportError:
            logger.error(
                "❌ 缺少 py-clob-client 套件\n"
                "   請執行: pip install py-clob-client"
            )
        except Exception as e:
            logger.error(f"❌ 實盤引擎啟動失敗: {repr(e)}")

    def stop(self) -> None:
        """停止實盤引擎"""
        self._running = False
        logger.info("🔴 實盤交易引擎已停止")

    def is_running(self) -> bool:
        return self._running and not self._emergency_locked

    def reset(self, new_balance: Optional[float] = None) -> None:
        """
        重置引擎
        - 清空內部追蹤（不影響鏈上狀態）
        - 解除緊急鎖定
        """
        self._open_trades.clear()
        self._trade_history.clear()
        self._trade_counter = 0
        self._total_traded_usdc = 0.0
        self._emergency_locked = False
        self._emergency_reason = ""
        logger.info("🔄 實盤引擎已重置（含解除緊急鎖定）")

    # ── 交易執行 ──────────────────────────────────────────────

    def get_snapshot(self) -> dict:
        \"\"\"取得當前引擎狀態快照（供 AI Engine 使用）\"\"\"
        return {
            \"balance\": round(self.get_balance(), 2),
            \"total_pnl\": round(self.total_pnl, 2),
            \"open_trades\": len(self.open_trades),
            \"total_trades\": self.total_trades,
            \"is_running\": self._running,
            \"engine_type\": \"live\"
        }

    def execute_trade(
        self,
        signal: dict,
        amount: Optional[float] = None,
        pm_state: Optional[Any] = None,
    ) -> Optional[Trade]:
        """
        執行實盤交易

        流程：
        1. 安全檢查（引擎狀態、金額上限、熔斷器）
        2. 取得 Token ID 與合約價格
        3. 利潤過濾器
        4. RiskManager 倉位計算
        5. 建立 Market Order (FOK)
        6. 簽名並提交
        7. 記錄交易
        """
        # ── 前置檢查 ──────────────────────────────────────────
        if not self._running:
            logger.warning("實盤交易引擎未啟動")
            return None

        if self._emergency_locked:
            logger.warning(f"🚨 引擎已鎖定: {self._emergency_reason}")
            return None

        if not self._client or not self._api_creds_set:
            logger.error("❌ CLOB API 未初始化")
            return None

        direction = signal.get("direction")
        if direction == "NEUTRAL":
            return None

        # ── 取得 Token ID 與合約價格 ──────────────────────────
        if pm_state is None:
            logger.warning("❌ 缺少 Polymarket 狀態，無法下單")
            return None

        if direction == "BUY_UP":
            token_id = pm_state.up_token_id
            contract_price = pm_state.up_price
            spread = pm_state.up_spread
        elif direction == "SELL_DOWN":
            token_id = pm_state.down_token_id
            contract_price = pm_state.down_price
            spread = pm_state.down_spread
        else:
            logger.warning(f"未知信號方向: {direction}")
            return None

        if not token_id:
            logger.error(f"❌ {direction} 的 Token ID 不可用")
            return None

        if not contract_price or contract_price <= 0:
            logger.error(f"❌ 合約價格無效: {contract_price}")
            return None

        # ── 倉位計算 (RiskManager) ────────────────────────────
        if amount is None:
            confidence = signal.get("confidence", 50)
            sizing = risk_manager.calculate_position_size(
                balance=self._balance if self._balance > 0 else 100.0,
                signal_confidence=confidence,
                trading_mode=signal.get("mode", "balanced"),
                contract_price=contract_price,
            )
            if sizing.circuit_breaker_active:
                logger.warning(
                    f"🔴 熔斷攔截！| 原因: {sizing.circuit_breaker_reason}"
                )
                return None
            amount = sizing.recommended_amount

        # ── 🔒 安全上限檢查 ───────────────────────────────────
        if amount > self._max_single_trade_usdc:
            logger.warning(
                f"🔒 金額超過單筆上限！${amount:.2f} > "
                f"${self._max_single_trade_usdc:.2f} | 已截斷"
            )
            amount = self._max_single_trade_usdc

        if self._total_traded_usdc + amount > self._max_total_traded_usdc:
            remaining = self._max_total_traded_usdc - self._total_traded_usdc
            if remaining <= 0:
                logger.warning(
                    f"🔒 累計交易已達上限 ${self._max_total_traded_usdc:.2f} | "
                    "請增加上限或重置引擎"
                )
                return None
            logger.warning(
                f"🔒 累計金額接近上限！剩餘額度: ${remaining:.2f} | 已截斷"
            )
            amount = remaining

        if amount < config.PROFIT_FILTER_MIN_TRADE_AMOUNT:
            logger.debug(f"交易金額太小: ${amount:.2f}")
            return None

        # ── 利潤過濾器 ────────────────────────────────────────
        if config.PROFIT_FILTER_ENABLED:
            if spread is not None and spread > config.PROFIT_FILTER_MAX_SPREAD_PCT:
                logger.info(
                    f"⛔ 利潤過濾器攔截 [SPREAD] | {direction} | "
                    f"Spread: {spread*100:.2f}% > {config.PROFIT_FILTER_MAX_SPREAD_PCT*100:.1f}%"
                )
                return None

            if 0 < contract_price < 1:
                expected_return = (1.0 / contract_price) - 1.0
                expected_profit = expected_return * amount
                round_trip = fee_model.estimate_round_trip_cost(
                    amount, buy_price=contract_price, sell_price=contract_price,
                )
                total_fee = round_trip["total_fee"]
                min_required = total_fee * config.PROFIT_FILTER_MIN_PROFIT_RATIO
                if expected_profit < min_required:
                    logger.info(
                        f"⛔ 利潤過濾器攔截 [FEE] | {direction} | "
                        f"毛利 ${expected_profit:.4f} < 最低 ${min_required:.4f}"
                    )
                    return None

        # ── 🚀 提交訂單到 Polymarket ─────────────────────────
        try:
            from py_clob_client.clob_types import (
                MarketOrderArgs,
                OrderType,
            )
            from py_clob_client.order_builder.constants import BUY

            logger.info(
                f"📤 提交實盤訂單 | {direction} | "
                f"Token: {token_id[:16]}... | "
                f"金額: ${amount:.2f} USDC | "
                f"合約價: {contract_price:.4f}"
            )

            # ⚠️ Market BUY = Quote Quantity (USDC 面值)
            # FOK (Fill or Kill) 確保完全成交或取消
            market_order = MarketOrderArgs(
                token_id=token_id,
                amount=round(amount, 2),  # USDC 金額 (Quote Qty)
                side=BUY,
                order_type=OrderType.FOK,
            )

            # 建立簽名訂單（約 1 秒延遲）
            t_start = time.time()
            signed_order = self._client.create_market_order(market_order)
            sign_time = time.time() - t_start

            # 提交訂單
            t_start = time.time()
            response = self._client.post_order(signed_order, OrderType.FOK)
            post_time = time.time() - t_start

            logger.info(
                f"📨 訂單回應 | 簽名耗時: {sign_time:.2f}s | "
                f"提交耗時: {post_time:.2f}s | "
                f"回應: {response}"
            )

            # 解析回應
            order_id = None
            if isinstance(response, dict):
                order_id = response.get("orderID") or response.get("order_id")
                # 檢查是否成功
                status = response.get("status", "")
                if status in ("FAILED", "REJECTED"):
                    logger.error(f"❌ 訂單被拒絕: {response}")
                    return None

        except Exception as e:
            logger.error(f"❌ 訂單提交失敗: {repr(e)}")
            return None

        # ── 記錄交易 ──────────────────────────────────────────
        self._trade_counter += 1
        fee_result = fee_model.calculate_buy_fee(amount, contract_price=contract_price)

        # 市場標題
        market_title = "BTC 15m UP/DOWN"
        if pm_state and hasattr(pm_state, "market_title") and pm_state.market_title:
            market_title = pm_state.market_title

        # 存入 DB
        trade_data = {
            "trade_type": "live",  # ← 區分實盤
            "direction": direction,
            "entry_time": time.time(),
            "entry_price": contract_price,
            "quantity": amount,
            "fee": fee_result.fee_amount,
            "fee_rate": fee_result.fee_rate,
            "signal_score": signal.get("score", 0),
            "trading_mode": signal.get("mode", "balanced"),
            "status": "open",
            "metadata": {
                "engine": "live",
                "order_id": order_id,
                "token_id": token_id,
                "sign_time_ms": round(sign_time * 1000),
                "post_time_ms": round(post_time * 1000),
                "market_title": market_title,
                "contract_price": contract_price,
                "spread": spread,
                "api_response": str(response)[:200],
            },
        }
        db_trade_id = db.save_trade(trade_data)

        # 建立追蹤物件
        trade = Trade(
            trade_id=db_trade_id,
            direction=direction,
            entry_price=contract_price,
            quantity=amount,
            signal_score=signal.get("score", 0),
            trading_mode=signal.get("mode", "balanced"),
            market_title=market_title,
            contract_price=contract_price,
            order_id=order_id,
        )
        self._open_trades.append(trade)
        self._total_traded_usdc += amount

        # 通知風險管理器
        risk_manager.on_trade_opened(amount, self._balance)

        logger.info(
            f"✅ 實盤交易開倉成功 | #{db_trade_id} | {direction} | "
            f"市場: {market_title} | "
            f"金額: ${amount:.2f} | 訂單ID: {order_id} | "
            f"累計: ${self._total_traded_usdc:.2f}/${self._max_total_traded_usdc:.2f}"
        )

        return trade

    def auto_settle_expired(
        self, btc_price_start: float, btc_price_end: float
    ) -> None:
        """
        自動結算到期交易

        Polymarket 15m 市場會自動結算，此方法用於：
        1. 同步內部狀態
        2. 記錄盈虧到 DB
        3. 通知 RiskManager
        """
        if not self._open_trades:
            return

        market_result = "UP" if btc_price_end > btc_price_start else "DOWN"

        for trade in list(self._open_trades):
            elapsed = time.time() - trade.entry_time
            if elapsed >= 900:  # 15 分鐘
                # 判斷勝負
                if trade.direction == "BUY_UP":
                    won = market_result == "UP"
                else:
                    won = market_result == "DOWN"

                # 計算盈虧
                cp = trade.contract_price if trade.contract_price > 0 else 0.5
                if won:
                    return_rate = (1.0 / cp) - 1.0
                    gross_profit = trade.quantity * return_rate
                    sell_fee = fee_model.calculate_sell_fee(
                        trade.quantity + gross_profit, contract_price=cp
                    )
                    trade.pnl = gross_profit - sell_fee.fee_amount
                else:
                    trade.pnl = -trade.quantity

                trade.status = TradeStatus.CLOSED
                trade.exit_time = time.time()
                trade.exit_price = 1.0 if won else 0.0

                # 更新 DB
                db.update_trade(trade.trade_id, {
                    "exit_time": trade.exit_time,
                    "exit_price": trade.exit_price,
                    "pnl": trade.pnl,
                    "status": "closed",
                })

                # 通知風險管理器
                risk_manager.on_trade_closed(
                    pnl=trade.pnl,
                    balance=self._balance,
                    won=won,
                )

                # 移入歷史
                self._trade_history.append({
                    "trade_id": trade.trade_id,
                    "direction": trade.direction,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl,
                    "won": won,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "contract_price": trade.contract_price,
                    "market_title": trade.market_title,
                    "order_id": trade.order_id,
                })

                # 從未平倉移除
                self._open_trades = [
                    t for t in self._open_trades
                    if t.trade_id != trade.trade_id
                ]

                result_emoji = "✅" if won else "❌"
                logger.info(
                    f"{result_emoji} 實盤交易結算 | #{trade.trade_id} | "
                    f"{trade.direction} | PnL: ${trade.pnl:+.2f}"
                )

    # ── 查詢 ──────────────────────────────────────────────────

    def get_balance(self) -> float:
        """取得當前餘額（嘗試從 API 獲取）"""
        # TODO: 從 Polymarket API 查詢實際 USDC 餘額
        # 目前從內部追蹤推算
        return self._balance

    def get_open_trades(self) -> List[Trade]:
        """取得所有未平倉交易"""
        return self._open_trades

    def get_stats(self) -> dict:
        """取得交易統計摘要"""
        wins = sum(1 for t in self._trade_history if t.get("won"))
        total = len(self._trade_history)
        total_pnl = sum(t.get("pnl", 0) for t in self._trade_history)

        return {
            "balance": round(self._balance, 2),
            "initial_balance": 0,
            "total_pnl": round(total_pnl, 2),
            "total_pnl_pct": 0,
            "total_trades": self._trade_counter,
            "closed_trades": total,
            "open_trades": len(self._open_trades),
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total * 100, 2) if total > 0 else 0,
            "is_running": self._running,
            "engine_type": self.engine_type.value,
            "total_traded_usdc": round(self._total_traded_usdc, 2),
            "max_total_traded_usdc": self._max_total_traded_usdc,
            "emergency_locked": self._emergency_locked,
        }

    def get_recent_trades(self, limit: int = 10) -> List[dict]:
        """取得最近交易記錄"""
        trades = []
        for t in self._open_trades:
            trades.append(t.to_dict())
        for t in reversed(self._trade_history[-limit:]):
            trades.append(t)
        return trades

    def get_pnl_curve(self) -> List[dict]:
        """取得 PnL 曲線數據"""
        curve = []
        cumulative = 0.0
        for t in self._trade_history:
            cumulative += t.get("pnl", 0)
            curve.append({
                "trade_id": t.get("trade_id"),
                "time": t.get("exit_time"),
                "pnl": round(t.get("pnl", 0), 2),
                "cumulative_pnl": round(cumulative, 2),
            })
        return curve

    # ── 緊急控制 ──────────────────────────────────────────────

    def emergency_stop(self, reason: str = "手動觸發") -> dict:
        """
        緊急停止：停止引擎 + 取消所有掛單 + 鎖定引擎
        """
        self._emergency_locked = True
        self._emergency_reason = reason
        self._running = False

        cancelled = 0
        if self._client and self._api_creds_set:
            try:
                self._client.cancel_all()
                cancelled = -1  # 表示已呼叫 cancel_all
                logger.info("🚨 已呼叫 cancel_all() 取消所有掛單")
            except Exception as e:
                logger.error(f"❌ cancel_all() 失敗: {repr(e)}")

        logger.warning(
            f"🚨 緊急停止！原因: {reason} | "
            f"引擎已鎖定，需呼叫 reset() 解鎖"
        )

        return {
            "action": "emergency_stop",
            "engine": self.engine_type.value,
            "reason": reason,
            "cancelled_orders": cancelled,
            "timestamp": time.time(),
            "locked": True,
        }

    # ── 工具方法 ──────────────────────────────────────────────

    def set_trade_limits(
        self,
        max_single: float = 10.0,
        max_total: float = 100.0,
    ) -> None:
        """
        設定交易金額上限

        Args:
            max_single: 單筆最大金額 (USDC)
            max_total: 累計最大金額 (USDC)
        """
        self._max_single_trade_usdc = max_single
        self._max_total_traded_usdc = max_total
        logger.info(
            f"🔒 交易上限已更新 | 單筆: ${max_single} | 累計: ${max_total}"
        )

    def get_api_status(self) -> dict:
        """取得 CLOB API 連線狀態"""
        status = {
            "connected": self._client is not None,
            "api_creds_set": self._api_creds_set,
            "engine_running": self._running,
            "emergency_locked": self._emergency_locked,
        }
        if self._client:
            try:
                ok = self._client.get_ok()
                status["server_ok"] = ok
            except Exception as e:
                status["server_ok"] = False
                status["error"] = repr(e)
        return status
