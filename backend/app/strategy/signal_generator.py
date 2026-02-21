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

        # Phase 5: 情緒因子追蹤
        self.last_sentiment: Optional[dict] = None

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
    # Phase 5: 情緒因子計算 (Polymarket 乖離率)
    # ═══════════════════════════════════════════════════════════════

    def _calculate_market_sentiment(
        self,
        mid: float,
        pm_up_price: Optional[float],
        pm_down_price: Optional[float],
        market_title: Optional[str] = None,
    ) -> dict:
        """
        計算 Polymarket 情緒溢價分數

        核心概念：
            1. 從合約標題解析出目標結算價 (strike_price)
            2. 根據 BTC 當前價 vs 目標價的距離，用 Sigmoid
               估算一個「技術面合理的」隱含機率 (fair_prob)
            3. 將 fair_prob 與 Polymarket 實際定價 (market_prob) 比較
            4. 兩者的乖離就是情緒分數
               正值 = 市場比技術面更看漲 (貪婪/FOMO)
               負值 = 市場比技術面更看跌 (恐懼/Panic)

        Args:
            mid: Binance BTC 中間價
            pm_up_price: Polymarket UP 合約價格 (0~1)
            pm_down_price: Polymarket DOWN 合約價格 (0~1)
            market_title: 合約標題 (用於解析目標價)

        Returns:
            {
                "score": float,        # -100 ~ +100
                "fair_prob": float,    # 技術面合理機率 (0~1)
                "market_prob": float,  # Polymarket 實際定價 (0~1)
                "premium_pct": float,  # 溢價百分比
                "label": str,          # 情緒標籤
            }
        """
        result = {
            "score": 0.0,
            "fair_prob": 0.5,
            "market_prob": 0.5,
            "premium_pct": 0.0,
            "label": "NEUTRAL",
        }

        if not mid or mid <= 0 or not pm_up_price:
            return result

        # ── Step 1: 解析目標結算價 ────────────────────────────
        strike_price = self._parse_strike_price(market_title, mid)

        # ── Step 2: 計算技術面合理機率 ────────────────────────
        # 使用 Sigmoid 函數：距離越近 → 機率越高
        # distance_pct = (mid - strike) / strike * 100
        # 正值 = 已經超過目標（應該看漲）
        # 負值 = 還沒到目標（需要上漲才贏）
        distance_pct = (mid - strike_price) / strike_price * 100
        steepness = config.SENTIMENT_CONFIG["fair_prob_steepness"]

        # Sigmoid: 1 / (1 + e^(-k * x))
        # distance_pct = +0.5% → fair_prob ≈ 0.98 (已突破目標)
        # distance_pct = 0%    → fair_prob = 0.50 (剛好在目標上)
        # distance_pct = -0.5% → fair_prob ≈ 0.02 (遠低於目標)
        exp_val = min(max(-steepness * distance_pct, -500), 500)
        fair_prob = 1.0 / (1.0 + math.exp(exp_val))

        # ── Step 3: 取得市場實際定價 ──────────────────────────
        market_prob = pm_up_price  # UP 合約價格 = 市場認為上漲的機率

        # ── Step 4: 計算情緒乖離 ──────────────────────────────
        # premium = 市場定價 - 合理機率
        # 正值 = 市場比技術面更樂觀（貪婪）
        # 負值 = 市場比技術面更悲觀（恐懼）
        premium = market_prob - fair_prob
        premium_pct = premium * 100

        # 將溢價映射到 -100 ~ +100 的情緒分數
        # 用 tanh 壓縮，±30% 溢價對應飽和
        sentiment_score = math.tanh(premium_pct / 30.0) * 100

        # ── Step 5: 分類標籤 ──────────────────────────────────
        if sentiment_score > 60:
            label = "EXTREME_GREED"
        elif sentiment_score > 30:
            label = "GREED"
        elif sentiment_score > -30:
            label = "NEUTRAL"
        elif sentiment_score > -60:
            label = "FEAR"
        else:
            label = "EXTREME_FEAR"

        result = {
            "score": round(sentiment_score, 2),
            "fair_prob": round(fair_prob, 4),
            "market_prob": round(market_prob, 4),
            "premium_pct": round(premium_pct, 2),
            "label": label,
            "strike_price": round(strike_price, 2),
            "distance_pct": round(distance_pct, 4),
        }

        self.last_sentiment = result
        return result

    @staticmethod
    def _parse_strike_price(
        market_title: Optional[str], fallback_mid: float
    ) -> float:
        """
        從 Polymarket 合約標題解析目標結算價

        合約標題格式範例:
            "Will Bitcoin be above $67,500 at 2026-02-20 15:00 UTC?"
            "btc-updown-15m-1771563600"

        若解析失敗，使用 BTC 中間價四捨五入到最近的 $100 作為估算。
        """
        import re
        if market_title:
            # 嘗試匹配 $XX,XXX 或 $XXXXX 格式
            match = re.search(r'\$([\d,]+)', market_title)
            if match:
                try:
                    return float(match.group(1).replace(',', ''))
                except ValueError:
                    pass

        # Fallback: 四捨五入到最近的 $100
        return round(fallback_mid / 100) * 100

    def _apply_sentiment_adjustment(
        self,
        base_score: float,
        sentiment: dict,
        mode_config: dict,
    ) -> tuple:
        """
        根據情緒分數與交易模式的敏感度，調整技術指標分數

        核心邏輯:
            - 若「看多信號 + 市場貪婪」→ 衰減（避免追高）
            - 若「看多信號 + 市場恐懼」→ 放大（逢低布局）
            - 若「看空信號 + 市場恐懼」→ 衰減（避免追低）
            - 若「看空信號 + 市場貪婪」→ 放大（高位放空）
            - 簡化公式: 「信號方向與情緒同向 → 衰減，逆向 → 放大」

        Args:
            base_score: 技術指標算出的原始分數 (-100~+100)
            sentiment: _calculate_market_sentiment 的輸出
            mode_config: 當前交易模式配置

        Returns:
            (adjusted_score, adjustment_details)
        """
        sensitivity = mode_config.get("sentiment_sensitivity", 0.0)
        sentiment_score = sentiment.get("score", 0.0)
        sent_cfg = config.SENTIMENT_CONFIG
        threshold = sent_cfg["extreme_threshold"]

        # 如果敏感度為 0 或情緒不極端，不調整
        if sensitivity <= 0 or abs(sentiment_score) < threshold:
            return base_score, {
                "applied": False,
                "reason": "sensitivity=0" if sensitivity <= 0
                          else f"|sentiment|={abs(sentiment_score):.0f} < threshold={threshold}",
                "multiplier": 1.0,
            }

        # ── 判斷「同向」或「逆向」─────────────────────────────
        # 信號正 + 情緒正 = 同向（追高風險）→ 衰減
        # 信號正 + 情緒負 = 逆向（恐慌中做多）→ 放大
        same_direction = (base_score > 0 and sentiment_score > 0) or \
                         (base_score < 0 and sentiment_score < 0)

        # ── 計算情緒強度 (0~1，超過 threshold 的部分) ──────────
        intensity = (abs(sentiment_score) - threshold) / (100 - threshold)
        intensity = max(0.0, min(1.0, intensity))

        if same_direction:
            # 同向 → 衰減：越貪婪/恐慌、敏感度越高 → 扣越多
            max_decay = sent_cfg["max_decay_pct"]
            # multiplier 從 1.0 → max_decay（例如 0.1）
            multiplier = 1.0 - (1.0 - max_decay) * intensity * sensitivity
            reason = "同向衰減（避免追高/追低）"
        else:
            # 逆向 → 放大：恐慌中做多 / FOMO 中做空
            max_boost = sent_cfg["max_boost_multiplier"]
            multiplier = 1.0 + (max_boost - 1.0) * intensity * sensitivity
            reason = "逆向放大（逢低布局/高位放空）"

        adjusted_score = base_score * multiplier
        # 夾緊在 ±100
        adjusted_score = max(-100.0, min(100.0, adjusted_score))

        logger.info(
            f"🎭 情緒調整 | sentiment={sentiment_score:+.0f} ({sentiment.get('label')}) | "
            f"sensitivity={sensitivity} | {'同向衰減' if same_direction else '逆向放大'} | "
            f"multiplier={multiplier:.3f} | "
            f"score {base_score:+.1f} → {adjusted_score:+.1f}"
        )

        return adjusted_score, {
            "applied": True,
            "reason": reason,
            "multiplier": round(multiplier, 4),
            "same_direction": same_direction,
            "intensity": round(intensity, 4),
            "sensitivity": sensitivity,
            "original_score": round(base_score, 2),
        }

    # ═══════════════════════════════════════════════════════════════
    # 信號生成（Phase 5: 含情緒調整 + 冷卻期）
    # ═══════════════════════════════════════════════════════════════

    def generate_signal(
        self,
        bids: list,
        asks: list,
        mid: float,
        trades: list,
        klines: list,
        pm_state=None,
    ) -> dict:
        """
        生成交易信號（Phase 5: Hybrid Decision Engine）

        Phase 5 新增：
        - 情緒因子計算（Polymarket 乖離率）
        - 根據交易模式的 sentiment_sensitivity 調整分數

        Args:
            pm_state: Polymarket 狀態物件（含 up_price, down_price, market_title）

        Returns:
            {
                "direction": "BUY_UP" | "SELL_DOWN" | "NEUTRAL",
                "score": float,
                "raw_score": float,       # Phase 5: 調整前的原始分數
                "confidence": float,
                "mode": str,
                "threshold": float,
                "indicators": dict,
                "sentiment": dict,         # Phase 5: 情緒因子
                "sentiment_adjustment": dict,  # Phase 5: 調整詳情
                "timestamp": float,
                "cooldown_blocked": bool,
            }
        """
        raw_score, indicators = self.calculate_bias_score(
            bids, asks, mid, trades, klines
        )

        mode_config = self.get_mode_config()
        threshold = mode_config["signal_threshold"]
        now = time.time()

        # ── Phase 5: 計算情緒因子 ─────────────────────────────
        sentiment = {"score": 0.0, "label": "N/A"}
        sentiment_adj = {"applied": False, "multiplier": 1.0}
        score = raw_score

        if pm_state is not None:
            pm_up = getattr(pm_state, 'up_price', None)
            pm_down = getattr(pm_state, 'down_price', None)
            pm_title = getattr(pm_state, 'market_title', None)

            sentiment = self._calculate_market_sentiment(
                mid, pm_up, pm_down, pm_title
            )
            score, sentiment_adj = self._apply_sentiment_adjustment(
                raw_score, sentiment, mode_config
            )

        # ── Step 2: Anti-FOMO 防追高/追空過濾器 (Override Rule) ───────────────────────
        # 若是強勢看多，但 RSI 已進入超買區 (>75)，極大懲罰分數，避免追高
        # 若是強勢看空，且 RSI 進入超賣區 (<25)，亦懲罰分數，避免追空
        # 這替未來的「動態公式引擎」預留了擴展點
        rsi_data = indicators.get("rsi", {})
        rsi_val = rsi_data.get("value", 50) if isinstance(rsi_data, dict) else 50
        anti_fomo_applied = False
        
        if score > 0 and rsi_val > 75:
            score *= 0.2
            anti_fomo_applied = True
            logger.warning(f"🛡️ Anti-FOMO 觸發: 偵測到 RSI={rsi_val:.1f} 進入超買區，大幅調降作多分數以避免追高陷阱。")
        elif score < 0 and rsi_val < 25:
            score *= 0.2
            anti_fomo_applied = True
            logger.warning(f"🛡️ Anti-FOMO 觸發: 偵測到 RSI={rsi_val:.1f} 進入超賣區，大幅調降作空分數以避免追低陷阱。")

        # 決定方向（使用調整後的分數）
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
            "raw_score": round(raw_score, 2),
            "confidence": round(confidence, 2),
            "mode": self.current_mode,
            "mode_name": mode_config["name"],
            "threshold": threshold,
            "indicators": indicators,
            "sentiment": sentiment,
            "sentiment_adjustment": sentiment_adj,
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
