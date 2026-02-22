""" 
🧀 CheeseDog - 回測引擎 (步驟 12b)
利用歷史市場快照重播策略邏輯，驗證信號生成和交易模擬的有效性。

設計理念 (借鏡 NautilusTrader):
- 回測使用與實時相同的 SignalGenerator + SimulationEngine
- 從 DB 讀取歷史 market_snapshots 作為數據源
- 產出 PerformanceTracker 報告

回測流程:
1. 從 DB 載入歷史 market_snapshots (含 btc_price, indicators_json)
2. 逐筆還原 K 線和訂單簿狀態 (簡化版)
3. 送入 SignalGenerator.generate_signal()
4. 根據信號進行模擬交易
5. 15 分鐘後自動結算
6. 輸出 PerformanceTracker 報告
"""

import time
import json
import logging
from typing import Optional, List, Dict
from dataclasses import dataclass

from app import config
from app.database import db
from app.strategy.signal_generator import SignalGenerator
from app.strategy.fees import fee_model
from app.performance.tracker import PerformanceTracker

logger = logging.getLogger("cheesedog.performance.backtester")


@dataclass
class BacktestConfig:
    """回測配置"""
    initial_balance: float = 1000.0
    trading_mode: str = "balanced"
    max_open_trades: int = 1  # 同時最多持倉數
    settlement_seconds: float = 900.0  # 結算時間 (15 分鐘)
    use_fees: bool = True  # 是否計算手續費
    use_profit_filter: bool = True  # 是否啟用利潤過濾器
    use_saved_signals: bool = True  # 是否使用快照中保存的信號分數（校準時設為 False）
    disable_cooldown: bool = False  # 是否禁用信號冷卻期（校準時設為 True）


@dataclass
class BacktestTrade:
    """回測中的虛擬交易"""
    trade_id: int
    direction: str
    entry_price: float  # 進場時 BTC 中價
    quantity: float
    entry_fee: float
    entry_time: float
    trading_mode: str
    signal_score: float
    contract_price: float = 0.5  # Polymarket 合約價格


class Backtester:
    """
    歷史回測引擎
    從資料庫載入歷史市場快照，模擬策略運行，
    輸出完整績效報告。
    """

    def __init__(self, bt_config: Optional[BacktestConfig] = None):
        self.config = bt_config or BacktestConfig()
        self._signal_gen = SignalGenerator()
        self._tracker = PerformanceTracker(self.config.initial_balance)
        self._balance = self.config.initial_balance
        self._open_trades: List[BacktestTrade] = []
        self._trade_counter = 0
        self._result: Optional[dict] = None

    def run(
        self,
        snapshots: Optional[List[dict]] = None,
        limit: int = 5000,
    ) -> dict:
        """
        執行回測

        Args:
            snapshots: 歷史快照列表 (None 則從 DB 載入)
            limit: 從 DB 載入的最大快照數量

        Returns:
            績效報告字典
        """
        start_time = time.time()

        # 載入歷史數據
        if snapshots is None:
            snapshots = self._load_snapshots(limit)

        if not snapshots:
            logger.warning("⚠️ 無歷史快照可供回測")
            return {"error": "無歷史數據", "snapshots_count": 0}

        # 依時間排序（舊 → 新）
        snapshots.sort(key=lambda s: s.get("timestamp", 0))

        logger.info(
            f"🔄 開始回測 | 快照: {len(snapshots)} 筆 | "
            f"模式: {self.config.trading_mode} | "
            f"初始資金: ${self.config.initial_balance:.2f}"
        )

        # 設定交易模式
        self._signal_gen.set_mode(self.config.trading_mode)
        self._balance = self.config.initial_balance
        self._open_trades = []
        self._trade_counter = 0
        self._tracker.reset(self.config.initial_balance)

        # 建構模擬用的 K 線窗口
        kline_window: List[dict] = []
        prev_btc_price = 0.0

        for snap in snapshots:
            ts = snap.get("timestamp", 0)
            btc_price = snap.get("btc_price", 0)

            if not btc_price or btc_price <= 0:
                continue

            # ── 結算到期交易 ──────────────────────────────────
            self._settle_expired(ts, prev_btc_price, btc_price)

            # ── 建構模擬 K 線 ────────────────────────────────
            # 使用相鄰快照價差來建構更合理的 OHLCV
            if prev_btc_price > 0:
                price_change = abs(btc_price - prev_btc_price)
                volatility = max(price_change * 1.5, btc_price * 0.0005)
            else:
                volatility = btc_price * 0.0005

            simulated_kline = {
                "t": ts,
                "o": prev_btc_price if prev_btc_price > 0 else btc_price,
                "h": max(btc_price, prev_btc_price if prev_btc_price > 0 else btc_price) + volatility * 0.5,
                "l": min(btc_price, prev_btc_price if prev_btc_price > 0 else btc_price) - volatility * 0.5,
                "c": btc_price,
                "v": 100.0 + price_change * 10 if prev_btc_price > 0 else 100.0,
            }
            kline_window.append(simulated_kline)
            kline_window = kline_window[-config.KLINE_MAX:]

            # 必須有足夠 K 線才能計算指標
            if len(kline_window) < 30:
                prev_btc_price = btc_price
                continue

            # ── 嘗試使用快照中的指標 ──────────────────────────
            indicators_json = snap.get("indicators_json", "{}")
            try:
                saved_indicators = json.loads(indicators_json) if isinstance(indicators_json, str) else indicators_json
            except (json.JSONDecodeError, TypeError):
                saved_indicators = {}

            # ── 生成信號 ──────────────────────────────────────
            # 使用空 bids/asks 和 trades（回測中無訂單簿數據）
            # 校準模式下禁用冷卻期，讓信號更頻繁
            if self.config.disable_cooldown:
                self._signal_gen._last_buy_time = 0.0
                self._signal_gen._last_sell_time = 0.0

            signal = self._signal_gen.generate_signal(
                bids=[],
                asks=[],
                mid=btc_price,
                trades=[],
                klines=kline_window,
            )

            # 如果快照有保存的指標分數，可以優先使用
            # （校準模式下禁用此功能，以測試不同權重的效果）
            if self.config.use_saved_signals:
                saved_score = snap.get("bias_score")
                if saved_score is not None:
                    signal["score"] = saved_score
                    # 重新根據當前模式的門檻判定方向，而不是直接使用快照中的方向
                    # 這樣不同模式（門檻不同）才會產生不同的回測結果
                    threshold = self._signal_gen.get_mode_config()["signal_threshold"]
                    if saved_score >= threshold:
                        signal["direction"] = "BUY_UP"
                    elif saved_score <= -threshold:
                        signal["direction"] = "SELL_DOWN"
                    else:
                        signal["direction"] = "NEUTRAL"

            # ── 交易邏輯 ──────────────────────────────────────
            if signal["direction"] != "NEUTRAL" and len(self._open_trades) < self.config.max_open_trades:
                # 檢查是否已有同方向持倉
                has_same = any(t.direction == signal["direction"] for t in self._open_trades)
                if not has_same:
                    # 從快照中取得 Polymarket 合約價格
                    pm_up = snap.get("pm_up_price")
                    pm_down = snap.get("pm_down_price")
                    self._open_trade(signal, btc_price, ts, pm_up, pm_down)

            prev_btc_price = btc_price

        # ── 強制結算所有剩餘持倉 ──────────────────────────────
        if self._open_trades and prev_btc_price > 0:
            for trade in list(self._open_trades):
                self._close_trade(trade, prev_btc_price, snapshots[-1].get("timestamp", time.time()))

        # ── 生成報告 ──────────────────────────────────────────
        elapsed = time.time() - start_time
        report = self._tracker.get_report()
        report["backtest_info"] = {
            "snapshots_total": len(snapshots),
            "snapshots_used": len([s for s in snapshots if s.get("btc_price", 0) > 0]),
            "trading_mode": self.config.trading_mode,
            "initial_balance": self.config.initial_balance,
            "use_fees": self.config.use_fees,
            "settlement_seconds": self.config.settlement_seconds,
            "elapsed_seconds": round(elapsed, 2),
            "time_range": {
                "start": snapshots[0].get("timestamp"),
                "end": snapshots[-1].get("timestamp"),
            },
        }
        self._result = report

        logger.info(
            f"✅ 回測完成 | 交易: {report['summary']['total_trades']} 筆 | "
            f"PnL: ${report['summary']['total_pnl']:+.2f} | "
            f"勝率: {report['summary']['win_rate']}% | "
            f"夏普: {report['summary']['sharpe_ratio']} | "
            f"耗時: {elapsed:.1f}s"
        )
        return report

    # ── 內部方法 ──────────────────────────────────────────────

    def _load_snapshots(self, limit: int) -> List[dict]:
        """從 DB 載入歷史市場快照"""
        try:
            rows = db.get_recent_snapshots(limit)
            logger.info(f"📂 從 DB 載入 {len(rows)} 筆歷史快照")
            return rows
        except Exception as e:
            logger.error(f"❌ 載入歷史快照失敗: {e}")
            return []

    def _open_trade(self, signal: dict, btc_price: float, ts: float, pm_up: float = None, pm_down: float = None):
        """開倉（Phase 2.1: 含利潤過濾器）"""
        mode_config = config.TRADING_MODES.get(
            self.config.trading_mode,
            config.TRADING_MODES["balanced"],
        )

        confidence = signal.get("confidence", 50)
        amount = self._balance * mode_config["max_position_pct"] * (confidence / 100)

        if amount <= 0 or amount > self._balance:
            return

        # 確定合約價格
        direction = signal["direction"]
        contract_price = 0.5  # 預設
        if direction == "BUY_UP" and pm_up and pm_up > 0:
            contract_price = pm_up
        elif direction == "SELL_DOWN" and pm_down and pm_down > 0:
            contract_price = pm_down

        # 🔧 修復：過濾極端合約價格 (0.05 ~ 0.95)
        # 超出此範圍代表市場極端偏差，可能導致不合理的回報率
        if contract_price < 0.05 or contract_price > 0.95:
            logger.debug(f"跳過極端價格交易 | 方向: {direction} | 價格: {contract_price:.4f}")
            return

        # 利潤過濾器
        if self.config.use_profit_filter and config.PROFIT_FILTER_ENABLED:
            if 0 < contract_price < 1:
                expected_return_rate = (1.0 / contract_price) - 1.0
                expected_gross_profit = expected_return_rate * amount
                round_trip = fee_model.estimate_round_trip_cost(
                    amount, buy_price=contract_price, sell_price=contract_price
                )
                total_fee = round_trip["total_fee"]
                min_required = total_fee * config.PROFIT_FILTER_MIN_PROFIT_RATIO
                if expected_gross_profit < min_required:
                    return  # 利潤不足，放棄交易

        # 手續費
        entry_fee = 0.0
        if self.config.use_fees:
            fee_result = fee_model.calculate_buy_fee(amount, contract_price)
            entry_fee = fee_result.fee_amount

        self._balance -= (amount + entry_fee)
        self._trade_counter += 1

        trade = BacktestTrade(
            trade_id=self._trade_counter,
            direction=direction,
            entry_price=btc_price,
            quantity=amount,
            entry_fee=entry_fee,
            entry_time=ts,
            trading_mode=self.config.trading_mode,
            signal_score=signal.get("score", 0),
            contract_price=contract_price,
        )
        self._open_trades.append(trade)

    def _settle_expired(self, current_ts: float, prev_price: float, cur_price: float):
        """結算到期交易"""
        for trade in list(self._open_trades):
            elapsed = current_ts - trade.entry_time
            if elapsed >= self.config.settlement_seconds:
                self._close_trade(trade, cur_price, current_ts)

    def _close_trade(self, trade: BacktestTrade, exit_price: float, ts: float):
        """平倉結算"""
        # 判斷勝負：BTC 價格漲了 = UP 贏，跌了 = DOWN 贏
        price_went_up = exit_price > trade.entry_price
        if trade.direction == "BUY_UP":
            won = price_went_up
        else:  # SELL_DOWN
            won = not price_went_up

        # 計算 PnL（Phase 2.1: 使用實際合約價格計算回報率）
        exit_fee = 0.0
        cp = trade.contract_price if trade.contract_price > 0 else 0.5

        # 🔧 修復：確保合約價格在合理範圍內 (0.05 ~ 0.95)
        # 超出此範圍的價格代表市場極端偏差，數據可能異常
        if cp < 0.05 or cp > 0.95:
            logger.warning(f"⚠️ 合約價格極端: {cp:.4f}，跳過交易 #{trade.trade_id}")
            self._open_trades = [t for t in self._open_trades if t.trade_id != trade.trade_id]
            return

        if won:
            return_rate = (1.0 / cp) - 1.0
            gross_profit = trade.quantity * return_rate
            if self.config.use_fees:
                sell_fee_result = fee_model.calculate_sell_fee(
                    trade.quantity + gross_profit, cp
                )
                exit_fee = sell_fee_result.fee_amount
            pnl = gross_profit - exit_fee
            self._balance += trade.quantity + pnl
        else:
            pnl = -trade.quantity
        total_fee = trade.entry_fee + exit_fee

        # 記錄到 PerformanceTracker
        self._tracker.record_trade({
            "trade_id": trade.trade_id,
            "direction": trade.direction,
            "quantity": trade.quantity,
            "pnl": pnl,
            "fee": total_fee,
            "trading_mode": trade.trading_mode,
            "entry_time": trade.entry_time,
            "exit_time": ts,
            "won": won,
            "entry_price": trade.entry_price,
            "exit_price": exit_price,
            "signal_score": trade.signal_score,
        })

        # 從持倉移除
        self._open_trades = [t for t in self._open_trades if t.trade_id != trade.trade_id]

    def get_last_result(self) -> Optional[dict]:
        """取得最近一次回測結果"""
        return self._result


def run_backtest(
    mode: str = "balanced",
    initial_balance: float = 1000.0,
    limit: int = 5000,
    use_fees: bool = True,
) -> dict:
    """
    快捷函數：執行一次回測

    Args:
        mode: 交易模式 ("aggressive" / "balanced" / "conservative")
        initial_balance: 初始資金
        limit: 歷史快照數量上限
        use_fees: 是否計算手續費

    Returns:
        績效報告字典
    """
    bt_config = BacktestConfig(
        initial_balance=initial_balance,
        trading_mode=mode,
        use_fees=use_fees,
    )
    backtester = Backtester(bt_config)
    return backtester.run(limit=limit)


def run_mode_comparison(
    initial_balance: float = 1000.0,
    limit: int = 5000,
) -> dict:
    """
    比較所有交易模式的回測績效

    Returns:
        {
            "aggressive": { ...績效報告... },
            "balanced": { ...績效報告... },
            "conservative": { ...績效報告... },
            "comparison": { ...比較摘要... },
        }
    """
    results = {}

    for mode in config.TRADING_MODES:
        logger.info(f"── 回測模式: {mode} ─────────────────")
        results[mode] = run_backtest(mode=mode, initial_balance=initial_balance, limit=limit)

    # 生成比較摘要
    comparison = {}
    for mode, report in results.items():
        if "error" in report:
            comparison[mode] = {"error": report["error"]}
        else:
            s = report["summary"]
            comparison[mode] = {
                "total_pnl": s["total_pnl"],
                "total_return_pct": s["total_return_pct"],
                "win_rate": s["win_rate"],
                "sharpe_ratio": s["sharpe_ratio"],
                "total_fees": s["total_fees"],
                "total_trades": s["total_trades"],
                "mode_name": config.TRADING_MODES.get(mode, {}).get("name", mode),
            }

    # 找出最佳模式
    best_mode = max(
        (m for m in comparison if "error" not in comparison[m]),
        key=lambda m: comparison[m]["total_pnl"],
        default=None,
    )

    results["comparison"] = comparison
    results["best_mode"] = best_mode

    logger.info(f"🏆 最佳模式: {best_mode}" if best_mode else "⚠️ 無有效回測結果")
    return results
