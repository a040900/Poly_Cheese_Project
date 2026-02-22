"""
🧀 乳酪のBTC預測室 — 模擬交易引擎
維護虛擬資金帳戶，模擬在 Polymarket 上的交易行為。

Step 15: 已重構為繼承 TradingEngine 抽象基類，
切換模擬/實盤只需更換引擎實例。
"""

import time
import logging
from typing import Optional, Dict, List, Any

from app import config
from app.database import db
from app.strategy.fees import fee_model
from app.trading.risk_manager import risk_manager
from app.trading.engine import TradingEngine, EngineType, Trade

logger = logging.getLogger("cheesedog.trading.simulator")


class SimulationTrade:
    """單筆模擬交易"""

    def __init__(
        self,
        trade_id: int,
        direction: str,
        entry_price: float,
        quantity: float,
        signal_score: float,
        trading_mode: str,
        market_title: Optional[str] = None,
        contract_price: float = 0.5,
        btc_price_start: Optional[float] = None,  # BUG FIX: 15分鐘週期開始時的 BTC 價格
    ):
        self.trade_id = trade_id
        self.direction = direction       # "BUY_UP" 或 "SELL_DOWN"
        self.entry_price = entry_price
        self.quantity = quantity          # USDC 金額
        self.signal_score = signal_score
        self.trading_mode = trading_mode
        self.market_title = market_title  # Polymarket 市場標題
        self.contract_price = contract_price  # 開倉時合約價格（用於結算回報率計算）
        self.btc_price_start = btc_price_start  # BUG FIX: 記錄開倉時的 BTC 價格
        self.entry_time = time.time()
        self.exit_price: Optional[float] = None
        self.exit_time: Optional[float] = None
        self.pnl: float = 0.0
        self.status: str = "open"


class SimulationEngine(TradingEngine):
    """模擬交易引擎（實作 TradingEngine 介面）"""

    @property
    def engine_type(self) -> EngineType:
        return EngineType.SIMULATION

    def __init__(self, initial_balance: float = config.SIM_INITIAL_BALANCE):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.open_trades: List[SimulationTrade] = []
        self.trade_history: List[Dict] = []
        self.total_trades = 0
        self.total_pnl = 0.0
        self._running = False

        logger.info(f"💰 模擬交易引擎已初始化 | 初始資金: ${initial_balance:.2f} USDC")

    def start(self):
        """啟動模擬交易"""
        self._running = True
        logger.info("🟢 模擬交易引擎已啟動")

    def stop(self):
        """停止模擬交易"""
        self._running = False
        logger.info("🔴 模擬交易引擎已停止")

    def is_running(self) -> bool:
        return self._running

    def execute_trade(
        self,
        signal: dict,
        amount: Optional[float] = None,
        pm_state: Optional[Any] = None,
    ) -> Optional[SimulationTrade]:
        """
        執行模擬交易（Phase 2.1: 含利潤過濾器）

        Args:
            signal: 交易信號
            amount: 交易金額（None 則使用風險評估建議金額）
            pm_state: Polymarket 狀態物件（含 bid/ask/spread）

        Returns:
            SimulationTrade 物件或 None
        """
        if not self._running:
            logger.warning("模擬交易引擎未啟動")
            return None

        direction = signal.get("direction")
        if direction == "NEUTRAL":
            return None

        # ── Step 1: Anti-FOMO 延遲檢查 (已優化) ──
        # 修正說明：
        # - Polymarket 更新週期為 30 秒，不適合作為延遲檢查依據
        # - 改用 Binance (即時數據) 做延遲檢查
        # - 閾值放寬至 5 秒，保留網路波動緩衝
        if signal.get("binance_last_update"):
            staleness = time.time() - signal["binance_last_update"]
            if staleness > 5.0:
                logger.warning(f"⏳ Binance 數據延遲過高 ({staleness:.1f}s > 5.0s)，為防追高/追空已放棄開倉！")
                return None

        # Phase 3 Enhancement: 檢查並平倉反向持倉 (Close Position Logic)
        opposing_direction = "SELL_DOWN" if direction == "BUY_UP" else "BUY_UP"
        trades_to_close = [t for t in self.open_trades if t.direction == opposing_direction]
        
        if trades_to_close:
            logger.info(f"🔄 收到反向信號 {direction}，正在平倉 {len(trades_to_close)} 筆 {opposing_direction} 交易...")
            total_pnl = 0.0
            
            # 使用當前反向價格作為平倉價
            close_price = 0.5
            if pm_state:
                # 若我要平掉 BUY_UP (賣出)，價格是 up_price (Bid)
                # 若我要平掉 SELL_DOWN (買回)，價格是 down_price (Ask? No, should be Ask but here we simplify)
                # 這裡假設 pm_state.up_price 是 Bid, pm_state.down_price 是 Bid (對於反向來說)
                # 實際上: 
                # 平 Long = Sell UP Token @ Bid Price (pm_state.up_price)
                # 平 Short = Buy UP Token @ Ask Price (pm_state.up_price + spread) -> 但這裡是 SELL_DOWN 代表持有 Down Token?
                # 簡化: 直接用對方價格
                if direction == "SELL_DOWN" and pm_state.up_price: # 用 SELL 信號平 BUY 單
                     close_price = pm_state.up_price
                elif direction == "BUY_UP" and pm_state.down_price: # 用 BUY 信號平 SELL 單
                     close_price = pm_state.down_price

            for trade in trades_to_close:
                trade.exit_time = time.time()
                trade.exit_price = close_price
                trade.status = "closed"
                
                # PnL = (Exit - Entry) * Shares
                # Shares = Quantity / Entry_Price
                shares = trade.quantity / trade.entry_price if trade.entry_price > 0 else 0
                trade.pnl = (trade.exit_price - trade.entry_price) * shares
                
                self.balance += trade.quantity + trade.pnl
                self.total_pnl += trade.pnl
                total_pnl += trade.pnl
                
                # 記錄到歷史
                self.trade_history.append({
                    "trade_id": trade.trade_id,
                    "direction": trade.direction,
                    "quantity": trade.quantity,
                    "pnl": trade.pnl,
                    "won": trade.pnl > 0,
                    "entry_time": trade.entry_time,
                    "exit_time": trade.exit_time,
                    "contract_price": trade.contract_price,
                    "metadata": {"market_title": trade.market_title}
                })

            # 從未平倉移除
            self.open_trades = [t for t in self.open_trades if t.direction != opposing_direction]
            logger.info(f"✅ 反向平倉完成 | 總盈虧: ${total_pnl:.2f}")
            return None # 平倉後不開新倉

        # ── 取得實際合約價格 ──────────────────────────────────
        contract_price = 0.5  # 預設候補值
        spread = None
        if pm_state is not None:
            if direction == "BUY_UP" and pm_state.up_price:
                contract_price = pm_state.up_price
                spread = pm_state.up_spread
            elif direction == "SELL_DOWN" and pm_state.down_price:
                contract_price = pm_state.down_price
                spread = pm_state.down_spread

        # ── 計算未實現損益 (Unrealized PnL) 與總曝險 ──
        total_unrealized_pnl = 0.0
        total_open_exposure = 0.0
        if pm_state:
            for t in self.open_trades:
                current_price = t.entry_price
                if t.direction == "BUY_UP" and getattr(pm_state, "up_price", None):
                    current_price = pm_state.up_price
                elif t.direction == "SELL_DOWN" and getattr(pm_state, "down_price", None):
                    current_price = pm_state.down_price
                
                shares = t.quantity / t.entry_price if t.entry_price > 0 else 0
                t_pnl = (current_price - t.entry_price) * shares
                total_unrealized_pnl += t_pnl
                total_open_exposure += (current_price * shares)

        if amount is None:
            mode_config = config.TRADING_MODES.get(
                signal.get("mode", "balanced"),
                config.TRADING_MODES["balanced"]
            )
            confidence = signal.get("confidence", 50)

            # 使用 RiskManager 計算最優倉位 (Phase 3: 加上未實現資料)
            sizing = risk_manager.calculate_position_size(
                balance=self.balance,
                signal_confidence=confidence,
                trading_mode=signal.get("mode", "balanced"),
                volatility_pct=0.5, # Default since we don't have it directly here
                contract_price=contract_price,
                unrealized_pnl=total_unrealized_pnl,
                open_exposure=total_open_exposure,
            )

            # 熔斷檢查
            if sizing.circuit_breaker_active:
                logger.warning(
                    f"🔴 熔斷攔截！ | 原因: {sizing.circuit_breaker_reason}"
                )
                return None

            amount = sizing.recommended_amount

            # 記錄風險管理決策詳情
            logger.debug(
                f"📐 RiskManager 建議 | Kelly={sizing.kelly_fraction:.3f} | "
                f"倉位={sizing.position_pct:.3f} | 風險={sizing.risk_score:.0f} | "
                f"金額=${amount:.2f}"
            )

        # 檢查餘額
        if amount <= 0 or amount > self.balance:
            logger.warning(f"資金不足: 需要 ${amount:.2f}, 可用 ${self.balance:.2f}")
            return None

        # 檢查最低交易金額
        if amount < config.PROFIT_FILTER_MIN_TRADE_AMOUNT:
            logger.debug(f"交易金額太小: ${amount:.2f} < 最低 ${config.PROFIT_FILTER_MIN_TRADE_AMOUNT:.2f}")
            return None

        # ═══ Phase 2.1: 利潤過濾器 (Profit Filter) ════════════════
        if config.PROFIT_FILTER_ENABLED:

            # ── 1. Spread 檢查：價差太大代表流動性差，進去就是被宰 ──
            if spread is not None and spread > config.PROFIT_FILTER_MAX_SPREAD_PCT:
                logger.info(
                    f"⛔ 利潤過濾器攔截 [SPREAD] | 方向: {direction} | "
                    f"Spread: {spread*100:.2f}% > 上限 {config.PROFIT_FILTER_MAX_SPREAD_PCT*100:.1f}% | "
                    f"原因: 流動性不足，進場即虧損"
                )
                return None

            # ── 2. 預期利潤 vs 手續費檢查 ────────────────────
            # Polymarket 二元選擇權：勝利回報 = (1 / contract_price - 1)
            # 例如 contract_price=0.55，勝利毛利 = 81.8%
            if contract_price > 0 and contract_price < 1:
                expected_return_rate = (1.0 / contract_price) - 1.0
                expected_gross_profit = expected_return_rate * amount

                # 估算來回手續費總成本
                round_trip = fee_model.estimate_round_trip_cost(
                    amount,
                    buy_price=contract_price,
                    sell_price=contract_price,
                )
                total_fee = round_trip["total_fee"]
                min_required = total_fee * config.PROFIT_FILTER_MIN_PROFIT_RATIO

                if expected_gross_profit < min_required:
                    logger.info(
                        f"⛔ 利潤過濾器攔截 [FEE] | 方向: {direction} | "
                        f"合約價: {contract_price:.4f} | "
                        f"預期毛利: ${expected_gross_profit:.4f} < "
                        f"最低要求: ${min_required:.4f} "
                        f"(手續費 ${total_fee:.4f} × {config.PROFIT_FILTER_MIN_PROFIT_RATIO})"
                    )
                    return None

                logger.debug(
                    f"✅ 利潤過濾器通過 | 方向: {direction} | "
                    f"合約價: {contract_price:.4f} | "
                    f"預期回報率: {expected_return_rate*100:.1f}% | "
                    f"預期毛利: ${expected_gross_profit:.4f} vs 手續費: ${total_fee:.4f}"
                )

        # ═══ 計算開倉手續費（使用實際合約價格）══════════════
        fee_result = fee_model.calculate_buy_fee(amount, contract_price=contract_price)
        fee = fee_result.fee_amount

        # 取得 Polymarket 市場標題 (優先從 pm_state 獲取)
        market_title = "BTC 15m UP/DOWN"
        if pm_state and hasattr(pm_state, "market_title") and pm_state.market_title:
            market_title = pm_state.market_title
        elif signal.get("market_title"):
            market_title = signal.get("market_title")

        # 記錄到資料庫
        trade_data = {
            "trade_type": "simulation",
            "direction": direction,
            "entry_time": time.time(),
            "entry_price": contract_price,  # 使用實際合約價格
            "quantity": amount,
            "fee": fee,
            "fee_rate": fee_result.fee_rate,
            "signal_score": signal.get("score", 0),
            "trading_mode": signal.get("mode", "balanced"),
            "status": "open",
            "metadata": {
                "confidence": signal.get("confidence"),
                "indicators": signal.get("indicators", {}),
                "fee_model": "polymarket_15m",
                "fee_side": "buy",
                "fee_deducted_in": fee_result.fee_deducted_in,
                "market_title": market_title,
                "contract_price": contract_price,
                "spread": spread,
                "profit_filter": "passed" if config.PROFIT_FILTER_ENABLED else "disabled",
            },
        }
        trade_id = db.save_trade(trade_data)

        # 建立交易物件
        trade = SimulationTrade(
            trade_id=trade_id,
            direction=direction,
            entry_price=contract_price,
            quantity=amount,
            signal_score=signal.get("score", 0),
            trading_mode=signal.get("mode", "balanced"),
            market_title=market_title,
            contract_price=contract_price,
            btc_price_start=signal.get("btc_price"),  # BUG FIX: 傳入開倉時的 BTC 價格
        )

        # 扣除資金和手續費
        self.balance -= (amount + fee)
        self.open_trades.append(trade)
        self.total_trades += 1

        # Phase 3 P2: 通知風險管理器
        risk_manager.on_trade_opened(amount, self.balance)

        logger.info(
            f"📈 模擬交易開倉 | 方向: {direction} | "
            f"市場: {market_title} | "
            f"合約價: {contract_price:.4f} | "
            f"金額: ${amount:.2f} | 手續費: ${fee:.4f} | "
            f"剩餘: ${self.balance:.2f}"
        )

        return trade

    def settle_trade(
        self,
        trade: SimulationTrade,
        market_result: str,
        settlement_price: float = 1.0,
    ) -> float:
        """
        結算模擬交易

        Args:
            trade: 要結算的交易
            market_result: 市場結果 "UP" 或 "DOWN"
            settlement_price: 結算價格

        Returns:
            盈虧金額
        """
        trade.exit_time = time.time()
        trade.exit_price = settlement_price

        # 判斷勝負
        if trade.direction == "BUY_UP":
            won = market_result == "UP"
        else:  # SELL_DOWN
            won = market_result == "DOWN"

        # 計算盈虧（Phase 2.1: 使用實際合約價格計算回報率）
        # Polymarket 二元選擇權：
        #   勝利 = 獲得 (1 / contract_price - 1) * quantity 的利潤
        #   例如 contract_price = 0.55 → 回報率 = 81.8%
        #   例如 contract_price = 0.40 → 回報率 = 150.0%
        if won:
            cp = trade.contract_price if trade.contract_price > 0 else 0.5
            return_rate = (1.0 / cp) - 1.0
            gross_profit = trade.quantity * return_rate

            # 結算時賣出（或贖回），需扣除 Sell 端手續費
            sell_fee = fee_model.calculate_sell_fee(
                trade.quantity + gross_profit, contract_price=cp
            )
            trade.pnl = gross_profit - sell_fee.fee_amount
            self.balance += trade.quantity + trade.pnl

            logger.debug(
                f"結算計算 | 合約價: {cp:.4f} | "
                f"回報率: {return_rate*100:.1f}% | "
                f"毛利: ${gross_profit:.4f} | "
                f"Sell手續費: ${sell_fee.fee_amount:.4f} | "
                f"淨利: ${trade.pnl:.4f}"
            )
        else:
            trade.pnl = -trade.quantity
            # 資金已扣除，無需額外操作

        trade.status = "closed"
        self.total_pnl += trade.pnl

        # 更新資料庫
        db.update_trade(trade.trade_id, {
            "exit_time": trade.exit_time,
            "exit_price": trade.exit_price,
            "pnl": trade.pnl,
            "status": "closed",
        })

        # Phase 3 P2: 通知風險管理器
        risk_manager.on_trade_closed(
            pnl=trade.pnl,
            balance=self.balance,
            won=won,
        )

        # 從未平倉列表移除
        self.open_trades = [t for t in self.open_trades if t.trade_id != trade.trade_id]

        # 記錄到歷史
        self.trade_history.append({
            "trade_id": trade.trade_id,
            "direction": trade.direction,
            "quantity": trade.quantity,
            "pnl": trade.pnl,
            "won": won,
            "entry_time": trade.entry_time,
            "exit_time": trade.exit_time,
            "contract_price": trade.contract_price,
            "market_title": trade.market_title,  # 確保平倉後保留市場標題
        })

        result_emoji = "✅" if won else "❌"
        logger.info(
            f"{result_emoji} 模擬交易結算 | 方向: {trade.direction} | "
            f"合約價: {trade.contract_price:.4f} | "
            f"金額: ${trade.quantity:.2f} | 盈虧: ${trade.pnl:+.2f} | "
            f"餘額: ${self.balance:.2f}"
        )

        return trade.pnl

    def auto_settle_expired(self, btc_price_current: float):
        """
        自動結算 15 分鐘到期的交易

        BUG FIX (2026-02-21): 
        Polymarket 15 分鐘市場結算規則：
        - 結束價格 >= 開始價格 → UP
        - 結束價格 < 開始價格 → DOWN
        
        每筆交易在開倉時已記錄 btc_price_start，
        結算時用當前價格與該交易的 btc_price_start 比較。

        Args:
            btc_price_current: 當前 BTC 價格（用於比較）
        """
        if not self.open_trades:
            return

        for trade in list(self.open_trades):
            # 檢查是否已超過 15 分鐘
            elapsed = time.time() - trade.entry_time
            if elapsed >= 900:  # 15 分鐘
                # BUG FIX: 使用該交易記錄的開始價格，而非統一的參數
                start_price = trade.btc_price_start if trade.btc_price_start else btc_price_current
                market_result = "UP" if btc_price_current >= start_price else "DOWN"
                self.settle_trade(trade, market_result)

    def reset(self, new_balance: Optional[float] = None):
        """重置模擬帳戶"""
        self.balance = new_balance or self.initial_balance
        self.open_trades.clear()
        self.trade_history.clear()
        self.total_trades = 0
        self.total_pnl = 0.0
        logger.info(f"🔄 模擬帳戶已重置 | 初始資金: ${self.balance:.2f}")

    def get_stats(self, pm_state=None) -> dict:
        """取得模擬交易統計"""
        
        # 計算未實現損益 (Unrealized PnL) 與曝險
        unrealized_pnl = 0.0
        open_exposure = 0.0
        if pm_state and self.open_trades:
            for ot in self.open_trades:
                current_value = 0.0
                if ot.direction == "BUY_UP":
                    current_value = pm_state.up_bid * ot.shares if pm_state.up_bid else 0
                elif ot.direction == "SELL_DOWN":
                    current_value = pm_state.down_bid * ot.shares if pm_state.down_bid else 0
                
                if current_value > 0:
                    unrealized_pnl += (current_value - ot.quantity)
                open_exposure += ot.quantity
        wins = sum(1 for t in self.trade_history if t.get("won"))
        losses = len(self.trade_history) - wins
        total_closed = len(self.trade_history)

        return {
            "balance": round(self.balance, 2),
            "initial_balance": self.initial_balance,
            "total_pnl": round(self.total_pnl, 2),
            "total_pnl_pct": round(
                (self.total_pnl / self.initial_balance * 100)
                if self.initial_balance > 0 else 0, 2
            ),
            "unrealized_pnl": round(unrealized_pnl, 2),
            "open_exposure": round(open_exposure, 2),
            "total_trades": self.total_trades,
            "closed_trades": total_closed,
            "open_trades": len(self.open_trades),
            "wins": wins,
            "losses": losses,
            "win_rate": round(wins / total_closed * 100, 2) if total_closed > 0 else 0,
            "is_running": self._running,
            "engine_type": self.engine_type.value,
        }

    def get_balance(self) -> float:
        """取得當前餘額"""
        return self.balance

    def get_open_trades(self) -> List[SimulationTrade]:
        """取得所有未平倉交易"""
        return self.open_trades

    def get_recent_trades(self, limit: int = 10) -> List[dict]:
        """取得最近的交易記錄（含未平倉）"""
        trades = []

        # 未平倉交易
        for t in self.open_trades:
            elapsed = time.time() - t.entry_time
            trades.append({
                "trade_id": t.trade_id,
                "direction": t.direction,
                "quantity": round(t.quantity, 2),
                "pnl": round(t.pnl, 2),  # 顯示當前未實現 PnL
                "status": "open",
                "entry_time": t.entry_time,
                "elapsed_min": round(elapsed / 60, 1),
                "trading_mode": t.trading_mode,
                "market_title": t.market_title or "BTC 15m UP/DOWN",  # 市場標題
            })

        # 最近已結算交易（倒序，最新的在前）
        for t in reversed(self.trade_history[-limit:]):
            trades.append({
                "trade_id": t["trade_id"],
                "direction": t["direction"],
                "quantity": round(t["quantity"], 2),
                "pnl": round(t.get("pnl", 0), 2),
                "status": "closed",
                "won": t.get("won", False),
                "entry_time": t.get("entry_time", 0),
                "exit_time": t.get("exit_time", 0),
                "market_title": t.get("metadata", {}).get("market_title", "BTC 15m UP/DOWN"),  # 從 metadata 取得市場標題
            })

        return trades

    def get_pnl_curve(self) -> List[dict]:
        """取得 PnL 曲線數據"""
        curve = []
        cumulative_pnl = 0.0
        for trade in self.trade_history:
            cumulative_pnl += trade.get("pnl", 0)
            curve.append({
                "trade_id": trade["trade_id"],
                "time": trade["exit_time"],
                "pnl": round(trade["pnl"], 2),
                "cumulative_pnl": round(cumulative_pnl, 2),
                "balance": round(self.initial_balance + cumulative_pnl, 2),
            })
        return curve
