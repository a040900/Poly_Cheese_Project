"""
🧀 CheeseDog - 信號生成引擎
基於多指標加權計算綜合趨勢分數，生成交易信號。
"""

import time
import logging
from typing import Dict, Optional, Tuple

from app import config
from app.indicators import orderbook, volume, technical

logger = logging.getLogger("cheesedog.strategy.signal")


class SignalGenerator:
    """交易信號生成器"""

    def __init__(self):
        self.current_mode: str = "balanced"  # 預設平衡模式
        self.last_signal: Optional[dict] = None
        self.last_score: float = 0.0
        self.last_indicators: Dict = {}

    def set_mode(self, mode: str):
        """設定交易模式"""
        if mode in config.TRADING_MODES:
            self.current_mode = mode
            logger.info(f"🔄 交易模式已切換為: {config.TRADING_MODES[mode]['name']}")
        else:
            logger.warning(f"⚠️ 無效的交易模式: {mode}")

    def get_mode_config(self) -> dict:
        """取得當前交易模式配置"""
        return config.TRADING_MODES.get(self.current_mode, config.TRADING_MODES["balanced"])

    def calculate_bias_score(
        self,
        bids: list,
        asks: list,
        mid: float,
        trades: list,
        klines: list,
    ) -> Tuple[float, Dict]:
        """
        計算綜合趨勢偏差分數

        使用加權合成所有指標，產生 [-100, +100] 範圍的趨勢分數。
        正值 = 看漲傾向，負值 = 看跌傾向。

        Returns:
            (偏差分數, 各指標詳細數值)
        """
        mode_config = self.get_mode_config()
        weights = config.BIAS_WEIGHTS
        multipliers = mode_config["indicator_weights_multiplier"]

        total = 0.0
        indicator_details = {}

        # ── 1. EMA 交叉 ────────────────────────────────────────
        ema_s, ema_l = technical.ema_cross(klines)
        if ema_s is not None and ema_l is not None:
            w = weights["ema"] * multipliers.get("ema", 1.0)
            contribution = w if ema_s > ema_l else -w
            total += contribution
            indicator_details["ema"] = {
                "short": round(ema_s, 2),
                "long": round(ema_l, 2),
                "signal": "BULLISH" if ema_s > ema_l else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 2. 訂單簿失衡 (OBI) ────────────────────────────────
        if mid:
            obi_val = orderbook.order_book_imbalance(bids, asks, mid)
            w = weights["obi"] * multipliers.get("obi", 1.0)
            contribution = obi_val * w
            total += contribution
            indicator_details["obi"] = {
                "value": round(obi_val, 4),
                "signal": "BULLISH" if obi_val > 0 else "BEARISH" if obi_val < 0 else "NEUTRAL",
                "contribution": round(contribution, 2),
            }

        # ── 3. MACD 直方圖 ─────────────────────────────────────
        macd_m, macd_s, macd_h = technical.macd(klines)
        if macd_h is not None:
            w = weights["macd"] * multipliers.get("macd", 1.0)
            contribution = w if macd_h > 0 else -w
            total += contribution
            indicator_details["macd"] = {
                "macd_line": round(macd_m, 2) if macd_m else None,
                "signal_line": round(macd_s, 2) if macd_s else None,
                "histogram": round(macd_h, 2),
                "signal": "BULLISH" if macd_h > 0 else "BEARISH",
                "contribution": round(contribution, 2),
            }

        # ── 4. CVD 5 分鐘 ──────────────────────────────────────
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

        # ── 7. RSI ─────────────────────────────────────────────
        rsi_val = technical.rsi(klines)
        if rsi_val is not None:
            w = weights["rsi"] * multipliers.get("rsi", 1.0)
            if rsi_val <= config.RSI_OVERSOLD:
                contribution = w
            elif rsi_val >= config.RSI_OVERBOUGHT:
                contribution = -w
            elif rsi_val < 50:
                contribution = w * (50 - rsi_val) / 20
            else:
                contribution = -w * (rsi_val - 50) / 20
            total += contribution
            indicator_details["rsi"] = {
                "value": round(rsi_val, 2),
                "signal": (
                    "OVERSOLD" if rsi_val <= 30
                    else "OVERBOUGHT" if rsi_val >= 70
                    else "NEUTRAL"
                ),
                "contribution": round(contribution, 2),
            }

        # ── 8. 價格 vs POC ─────────────────────────────────────
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

        # ── 9. 買牆 vs 賣牆 ───────────────────────────────────
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

    def generate_signal(
        self,
        bids: list,
        asks: list,
        mid: float,
        trades: list,
        klines: list,
    ) -> dict:
        """
        生成交易信號

        Returns:
            {
                "direction": "BUY_UP" | "SELL_DOWN" | "NEUTRAL",
                "score": float,
                "confidence": float,
                "mode": str,
                "threshold": float,
                "indicators": dict,
                "timestamp": float,
            }
        """
        score, indicators = self.calculate_bias_score(
            bids, asks, mid, trades, klines
        )

        mode_config = self.get_mode_config()
        threshold = mode_config["signal_threshold"]

        # 決定方向
        if score >= threshold:
            direction = "BUY_UP"
        elif score <= -threshold:
            direction = "SELL_DOWN"
        else:
            direction = "NEUTRAL"

        # 計算信心度 (0-100)
        confidence = min(100, abs(score) / threshold * 100) if threshold > 0 else 0

        signal = {
            "direction": direction,
            "score": round(score, 2),
            "confidence": round(confidence, 2),
            "mode": self.current_mode,
            "mode_name": mode_config["name"],
            "threshold": threshold,
            "indicators": indicators,
            "timestamp": time.time(),
        }

        self.last_signal = signal
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
