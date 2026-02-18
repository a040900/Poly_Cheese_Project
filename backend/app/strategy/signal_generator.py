"""
🧀 CheeseDog - 信號生成引擎（Phase 3: Signal Quality Enhancement）
基於多指標加權計算綜合趨勢分數，生成交易信號。

Phase 3 變更：
- B1: EMA 交叉 → 連續函數（反映偏離幅度，非二元判定）
- B2: MACD Histogram → 幅度化正規化（反映動能強弱）
- B3: RSI → 極端區域加強（<20 / >80 權重放大）
- B4: 新增 Bollinger Band 指標（填補波動率維度）
- B5: 信號冷卻期（防止同方向信號短時間內重複觸發）
- CRO: 新增績效追蹤統計供 AI Agent 使用
"""

import time
import logging
import math
from typing import Dict, Optional, Tuple
from collections import deque

from app import config
from app.indicators import orderbook, volume, technical

logger = logging.getLogger("cheesedog.strategy.signal")


class SignalGenerator:
    """交易信號生成器（Phase 3 Enhanced）"""

    def __init__(self):
        self.current_mode: str = "balanced"  # 預設平衡模式
        self.last_signal: Optional[dict] = None
        self.last_score: float = 0.0
        self.last_indicators: Dict = {}

        # Phase 3 (B5): 信號冷卻期追蹤
        self._last_buy_time: float = 0.0
        self._last_sell_time: float = 0.0

        # Phase 3 (CRO): 績效追蹤（供 AI Agent 使用）
        self._signal_history: deque = deque(maxlen=200)  # 最近 200 筆信號
        self._trade_results: deque = deque(maxlen=100)   # 最近 100 筆交易結果

    def set_mode(self, mode: str):
        """設定交易模式"""
        if mode in config.TRADING_MODES:
            old_mode = self.current_mode
            self.current_mode = mode
            logger.info(
                f"🔄 交易模式已切換為: {config.TRADING_MODES[mode]['name']} "
                f"(從 {old_mode})"
            )
        else:
            logger.warning(f"⚠️ 無效的交易模式: {mode}")

    def get_mode_config(self) -> dict:
        """取得當前交易模式配置"""
        return config.TRADING_MODES.get(
            self.current_mode, config.TRADING_MODES["balanced"]
        )

    # ═══════════════════════════════════════════════════════════════
    # Phase 3 (CRO): 績效追蹤方法
    # ═══════════════════════════════════════════════════════════════

    def record_trade_result(self, won: bool, pnl: float):
        """紀錄交易結果（供 CRO 統計使用）"""
        self._trade_results.append({
            "won": won,
            "pnl": pnl,
            "timestamp": time.time(),
        })

    def get_cro_stats(self) -> dict:
        """
        取得 CRO (Chief Risk Officer) 層級的聚合統計數據，
        供 VPS 上的 AI Agent (OpenClaw) 使用。

        Returns:
            {
                "win_rate_6h": float,      # 近 6 小時勝率
                "win_rate_24h": float,     # 近 24 小時勝率
                "profit_factor": float,    # 獲利因子
                "consecutive_losses": int, # 當前連續虧損次數
                "max_drawdown_pct": float, # 最大回撤
                "signals_per_hour": float, # 每小時信號數
                "avg_confidence": float,   # 平均信心度
                "current_mode": str,       # 目前模式
            }
        """
        now = time.time()
        cutoff_6h = now - 6 * 3600
        cutoff_24h = now - 24 * 3600

        # 勝率計算
        results_6h = [r for r in self._trade_results if r["timestamp"] >= cutoff_6h]
        results_24h = [r for r in self._trade_results if r["timestamp"] >= cutoff_24h]

        wins_6h = sum(1 for r in results_6h if r["won"])
        wins_24h = sum(1 for r in results_24h if r["won"])

        win_rate_6h = (wins_6h / len(results_6h) * 100) if results_6h else 0
        win_rate_24h = (wins_24h / len(results_24h) * 100) if results_24h else 0

        # 獲利因子 (Profit Factor)
        gross_profit = sum(r["pnl"] for r in results_24h if r["pnl"] > 0)
        gross_loss = abs(sum(r["pnl"] for r in results_24h if r["pnl"] < 0))
        profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else 999.0

        # 連續虧損
        consecutive_losses = 0
        for r in reversed(list(self._trade_results)):
            if not r["won"]:
                consecutive_losses += 1
            else:
                break

        # 每小時信號數
        signals_1h = [
            s for s in self._signal_history
            if s.get("timestamp", 0) >= now - 3600
        ]
        signals_per_hour = len(signals_1h)

        # 平均信心度
        recent_confidences = [
            s.get("confidence", 0) for s in self._signal_history
            if s.get("timestamp", 0) >= cutoff_6h
            and s.get("direction") != "NEUTRAL"
        ]
        avg_confidence = (
            sum(recent_confidences) / len(recent_confidences)
            if recent_confidences
            else 0
        )

        return {
            "win_rate_6h": round(win_rate_6h, 1),
            "win_rate_24h": round(win_rate_24h, 1),
            "profit_factor": round(min(profit_factor, 999.0), 2),
            "consecutive_losses": consecutive_losses,
            "total_trades_24h": len(results_24h),
            "signals_per_hour": signals_per_hour,
            "avg_confidence": round(avg_confidence, 1),
            "current_mode": self.current_mode,
            "mode_name": self.get_mode_config()["name"],
        }

    # ═══════════════════════════════════════════════════════════════
    # 偏差分數計算（Phase 3 Enhanced）
    # ═══════════════════════════════════════════════════════════════

    def calculate_bias_score(
        self,
        bids: list,
        asks: list,
        mid: float,
        trades: list,
        klines: list,
    ) -> Tuple[float, Dict]:
        """
        計算綜合趨勢偏差分數（Phase 3 Enhanced）

        Phase 3 改進：
        - EMA: 連續函數（反映偏離幅度）
        - MACD: Histogram 正規化幅度
        - RSI: 極端區域加強
        - BB: 新增波動率維度
        - 所有指標使用更精細的連續函數，而非二元判定

        Returns:
            (偏差分數 [-100, +100], 各指標詳細數值)
        """
        mode_config = self.get_mode_config()
        weights = config.BIAS_WEIGHTS
        multipliers = mode_config["indicator_weights_multiplier"]

        total = 0.0
        indicator_details = {}

        # ── 1. EMA 交叉（Phase 3 B1: 連續函數）─────────────────
        # 舊: ema_s > ema_l → +w (二元)
        # 新: 根據 (ema_s - ema_l) / ema_l 的比例連續計算
        ema_s, ema_l = technical.ema_cross(klines)
        if ema_s is not None and ema_l is not None and ema_l != 0:
            w = weights["ema"] * multipliers.get("ema", 1.0)
            # 偏離比例：(短期 - 長期) / 長期，正值=看漲
            deviation_pct = (ema_s - ema_l) / ema_l * 100
            # 使用 tanh 壓縮到 [-1, +1]，scaling = 0.5% 對應飽和
            normalized = math.tanh(deviation_pct / 0.5)
            contribution = w * normalized
            total += contribution
            indicator_details["ema"] = {
                "short": round(ema_s, 2),
                "long": round(ema_l, 2),
                "deviation_pct": round(deviation_pct, 4),
                "signal": "BULLISH" if deviation_pct > 0 else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 2. 訂單簿失衡 (OBI) ────────────────────────────────
        # (保持原有的連續函數，已經做得不錯)
        if mid:
            obi_val = orderbook.order_book_imbalance(bids, asks, mid)
            w = weights["obi"] * multipliers.get("obi", 1.0)
            contribution = obi_val * w
            total += contribution
            indicator_details["obi"] = {
                "value": round(obi_val, 4),
                "signal": (
                    "BULLISH" if obi_val > 0
                    else "BEARISH" if obi_val < 0
                    else "NEUTRAL"
                ),
                "contribution": round(contribution, 2),
            }

        # ── 3. MACD 直方圖（Phase 3 B2: 幅度化）────────────────
        # 舊: macd_h > 0 → +w (二元)
        # 新: 根據 histogram 的幅度連續計算
        macd_m, macd_s, macd_h = technical.macd(klines)
        if macd_h is not None:
            w = weights["macd"] * multipliers.get("macd", 1.0)
            # 正規化 histogram：用 mid price 的比例來表達 histogram 大小
            # MACD histogram 典型值在 BTC 上可能是 ±50~200
            # 用 mid price * 0.1% 作為參考基準
            ref = mid * 0.001 if mid > 0 else 100.0
            normalized = math.tanh(macd_h / ref)
            contribution = w * normalized
            total += contribution
            indicator_details["macd"] = {
                "macd_line": round(macd_m, 2) if macd_m else None,
                "signal_line": round(macd_s, 2) if macd_s else None,
                "histogram": round(macd_h, 2),
                "normalized": round(normalized, 4),
                "signal": "BULLISH" if macd_h > 0 else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 4. CVD 5 分鐘 ──────────────────────────────────────
        # (保持原有二元判定 — CVD 方向比幅度更重要)
        cvd_5m = volume.cumulative_volume_delta(trades, 300)
        if cvd_5m != 0:
            w = weights["cvd"] * multipliers.get("cvd", 1.0)
            contribution = w if cvd_5m > 0 else -w
            total += contribution
            indicator_details["cvd"] = {
                "cvd_1m": round(volume.cumulative_volume_delta(trades, 60), 2),
                "cvd_3m": round(volume.cumulative_volume_delta(trades, 180), 2),
                "cvd_5m": round(cvd_5m, 2),
                "signal": "BULLISH" if cvd_5m > 0 else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 5. Heikin Ashi 連續方向 ────────────────────────────
        streak = technical.ha_streak(klines)
        if streak != 0:
            w = weights["ha"] * multipliers.get("ha", 1.0)
            contribution = max(-w, min(w, streak * (w / 3)))
            total += contribution
            indicator_details["heikin_ashi"] = {
                "streak": streak,
                "signal": "BULLISH" if streak > 0 else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 6. 價格 vs VWAP ───────────────────────────────────
        vwap_val = technical.vwap(klines)
        if vwap_val and mid:
            w = weights["vwap"] * multipliers.get("vwap", 1.0)
            contribution = w if mid > vwap_val else -w
            total += contribution
            indicator_details["vwap"] = {
                "value": round(vwap_val, 2),
                "price_above": mid > vwap_val,
                "signal": "BULLISH" if mid > vwap_val else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 7. RSI（Phase 3 B3: 極端區域加強）──────────────────
        # 舊: RSI <30 → +w, >70 → -w, 中間線性
        # 新: 極端區域 (<20, >80) 給予 1.5x 加權
        #     並使用 S 曲線 (sigmoid) 代替線性
        rsi_val = technical.rsi(klines)
        if rsi_val is not None:
            w = weights["rsi"] * multipliers.get("rsi", 1.0)
            if rsi_val <= 20:
                # 極度超賣 → 強烈看漲反轉
                contribution = w * 1.5
            elif rsi_val >= 80:
                # 極度超買 → 強烈看跌反轉
                contribution = -w * 1.5
            elif rsi_val <= config.RSI_OVERSOLD:
                # 超賣區 (20-30) → 漸進看漲
                intensity = (config.RSI_OVERSOLD - rsi_val) / 10  # 0~1
                contribution = w * (1.0 + 0.5 * intensity)
            elif rsi_val >= config.RSI_OVERBOUGHT:
                # 超買區 (70-80) → 漸進看跌
                intensity = (rsi_val - config.RSI_OVERBOUGHT) / 10
                contribution = -w * (1.0 + 0.5 * intensity)
            else:
                # 中間區域 (30-70): 使用 sigmoid 取代線性
                # 將 RSI 映射到 [-1, +1]：RSI=30→+1, RSI=50→0, RSI=70→-1
                x = (50 - rsi_val) / 20  # 30→1, 50→0, 70→-1
                contribution = w * math.tanh(x * 1.5)

            total += contribution
            indicator_details["rsi"] = {
                "value": round(rsi_val, 2),
                "signal": (
                    "EXTREME_OVERSOLD" if rsi_val <= 20
                    else "OVERSOLD" if rsi_val <= 30
                    else "EXTREME_OVERBOUGHT" if rsi_val >= 80
                    else "OVERBOUGHT" if rsi_val >= 70
                    else "NEUTRAL"
                ),
                "contribution": round(contribution, 2),
            }

        # ── 8. Bollinger Band %B（Phase 3 B4: 新增）────────────
        # %B > 1: 突破上軌（可能超買或強勢突破）
        # %B < 0: 跌破下軌（可能超賣或弱勢崩盤）
        # %B ≈ 0.5: 在中軌，中性
        bb = technical.bollinger_bands(klines)
        if bb is not None:
            w = weights["bb"] * multipliers.get("bb", 1.0)
            pct_b = bb["pct_b"]

            # 反轉邏輯：%B 極端時視為反轉信號
            # %B = 0.5 → 中性 (contribution = 0)
            # %B = 0.0 → 超賣 → 看漲 (contribution ≈ +w)
            # %B = 1.0 → 超買 → 看跌 (contribution ≈ -w)
            # 使用 sigmoid: (0.5 - pct_b) 映射
            x = (0.5 - pct_b) * 4  # 放大映射
            contribution = w * math.tanh(x)
            total += contribution

            indicator_details["bollinger"] = {
                "upper": bb["upper"],
                "middle": bb["middle"],
                "lower": bb["lower"],
                "pct_b": bb["pct_b"],
                "bandwidth": bb["bandwidth"],
                "signal": (
                    "OVERSOLD" if pct_b < 0.0
                    else "OVERBOUGHT" if pct_b > 1.0
                    else "BULLISH" if pct_b < 0.3
                    else "BEARISH" if pct_b > 0.7
                    else "NEUTRAL"
                ),
                "contribution": round(contribution, 2),
            }

        # ── 9. 價格 vs POC ─────────────────────────────────────
        poc, _ = volume.volume_profile(klines)
        if poc and mid:
            w = weights["poc"] * multipliers.get("poc", 1.0)
            contribution = w if mid > poc else -w
            total += contribution
            indicator_details["poc"] = {
                "value": round(poc, 2),
                "price_above": mid > poc,
                "signal": "BULLISH" if mid > poc else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 10. 買牆 vs 賣牆 ──────────────────────────────────
        bid_walls, ask_walls = orderbook.detect_walls(bids, asks)
        w = weights["walls"] * multipliers.get("walls", 1.0)
        wall_pts = (min(len(bid_walls), 2) - min(len(ask_walls), 2)) * 2
        contribution = max(-w, min(w, wall_pts))
        total += contribution
        indicator_details["walls"] = {
            "bid_walls": len(bid_walls),
            "ask_walls": len(ask_walls),
            "signal": (
                "BULLISH" if wall_pts > 0
                else "BEARISH" if wall_pts < 0
                else "NEUTRAL"
            ),
            "contribution": round(contribution, 2),
        }

        # ── 計算最終偏差分數 ───────────────────────────────────
        max_possible = sum(
            w * multipliers.get(k, 1.0)
            for k, w in weights.items()
        )
        raw_score = (total / max_possible) * 100 if max_possible > 0 else 0
        bias_score = max(-100.0, min(100.0, raw_score))

        self.last_score = bias_score
        self.last_indicators = indicator_details

        return bias_score, indicator_details

    # ═══════════════════════════════════════════════════════════════
    # 信號生成（Phase 3: 含冷卻期）
    # ═══════════════════════════════════════════════════════════════

    def generate_signal(
        self,
        bids: list,
        asks: list,
        mid: float,
        trades: list,
        klines: list,
    ) -> dict:
        """
        生成交易信號（Phase 3 Enhanced）

        Phase 3 新增：
        - B5: 冷卻期檢查（同方向信號 N 秒內不重複觸發）
        - CRO: 信號歷史紀錄

        Returns:
            {
                "direction": "BUY_UP" | "SELL_DOWN" | "NEUTRAL",
                "score": float,
                "confidence": float,
                "mode": str,
                "threshold": float,
                "indicators": dict,
                "timestamp": float,
                "cooldown_blocked": bool,  # Phase 3: 是否被冷卻期擋住
            }
        """
        score, indicators = self.calculate_bias_score(
            bids, asks, mid, trades, klines
        )

        mode_config = self.get_mode_config()
        threshold = mode_config["signal_threshold"]
        now = time.time()

        # 決定方向（原始）
        if score >= threshold:
            raw_direction = "BUY_UP"
        elif score <= -threshold:
            raw_direction = "SELL_DOWN"
        else:
            raw_direction = "NEUTRAL"

        # Phase 3 (B5): 冷卻期檢查
        cooldown = config.SIGNAL_COOLDOWN_SECONDS
        cooldown_blocked = False

        if raw_direction == "BUY_UP":
            if now - self._last_buy_time < cooldown:
                raw_direction = "NEUTRAL"
                cooldown_blocked = True
                logger.debug(
                    f"⏳ BUY_UP 信號被冷卻期阻擋 "
                    f"(剩餘 {cooldown - (now - self._last_buy_time):.0f}s)"
                )
        elif raw_direction == "SELL_DOWN":
            if now - self._last_sell_time < cooldown:
                raw_direction = "NEUTRAL"
                cooldown_blocked = True
                logger.debug(
                    f"⏳ SELL_DOWN 信號被冷卻期阻擋 "
                    f"(剩餘 {cooldown - (now - self._last_sell_time):.0f}s)"
                )

        # 更新冷卻期時間戳
        if raw_direction == "BUY_UP":
            self._last_buy_time = now
        elif raw_direction == "SELL_DOWN":
            self._last_sell_time = now

        # 計算信心度 (0-100)
        confidence = (
            min(100, abs(score) / threshold * 100)
            if threshold > 0
            else 0
        )

        signal = {
            "direction": raw_direction,
            "score": round(score, 2),
            "confidence": round(confidence, 2),
            "mode": self.current_mode,
            "mode_name": mode_config["name"],
            "threshold": threshold,
            "indicators": indicators,
            "timestamp": now,
            "cooldown_blocked": cooldown_blocked,
        }

        self.last_signal = signal

        # Phase 3 (CRO): 記錄信號歷史
        self._signal_history.append(signal)

        return signal

    def get_risk_assessment(self, signal: dict, balance: float) -> dict:
        """
        基於信號和當前餘額進行風險評估

        Returns:
            {
                "risk_level": "LOW" | "MEDIUM" | "HIGH",
                "suggested_amount": float,
                "max_amount": float,
                "stop_loss": float,
                "take_profit": float,
            }
        """
        mode_config = self.get_mode_config()
        confidence = signal.get("confidence", 0)

        # 風險等級
        if confidence >= 80:
            risk_level = "LOW"
        elif confidence >= 50:
            risk_level = "MEDIUM"
        else:
            risk_level = "HIGH"

        # 建議金額（基於信心度和模式）
        max_amount = balance * mode_config["max_position_pct"]
        suggested_amount = max_amount * (confidence / 100)

        return {
            "risk_level": risk_level,
            "suggested_amount": round(suggested_amount, 2),
            "max_amount": round(max_amount, 2),
            "stop_loss_pct": mode_config["stop_loss_pct"],
            "take_profit_pct": mode_config["take_profit_pct"],
            "confidence": confidence,
        }
