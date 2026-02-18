"""
🧀 CheeseDog - 技術分析指標計算模組
計算 RSI、MACD、VWAP、EMA 交叉、Heikin Ashi 蠟燭線等指標。
"""

from typing import List, Optional, Tuple
from app import config


def _ema_series(values: List[float], period: int) -> List[Optional[float]]:
    """
    計算 EMA (Exponential Moving Average) 序列

    Args:
        values: 數值序列
        period: EMA 週期

    Returns:
        EMA 值序列（前 period-1 個為 None）
    """
    if len(values) < period:
        return [None] * len(values)

    multiplier = 2.0 / (period + 1)
    result = [None] * (period - 1)
    result.append(sum(values[:period]) / period)

    for v in values[period:]:
        result.append(v * multiplier + result[-1] * (1 - multiplier))

    return result


def rsi(klines: List[dict], period: int = config.RSI_PERIOD) -> Optional[float]:
    """
    計算相對強弱指標 (RSI)

    RSI = 100 - (100 / (1 + RS))
    RS = 平均漲幅 / 平均跌幅

    RSI > 70: 超買（可能回調）
    RSI < 30: 超賣（可能反彈）

    Args:
        klines: K 線數據列表
        period: RSI 週期

    Returns:
        RSI 值 [0, 100] 或 None
    """
    closes = [k["c"] for k in klines]
    if len(closes) < period + 1:
        return None

    changes = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
    avg_gain = sum(max(c, 0) for c in changes[:period]) / period
    avg_loss = sum(max(-c, 0) for c in changes[:period]) / period

    for c in changes[period:]:
        avg_gain = (avg_gain * (period - 1) + max(c, 0)) / period
        avg_loss = (avg_loss * (period - 1) + max(-c, 0)) / period

    if avg_loss == 0:
        return 100.0

    return 100.0 - 100.0 / (1 + avg_gain / avg_loss)


def macd(
    klines: List[dict],
    fast: int = config.MACD_FAST,
    slow: int = config.MACD_SLOW,
    signal: int = config.MACD_SIGNAL,
) -> Tuple[Optional[float], Optional[float], Optional[float]]:
    """
    計算 MACD (Moving Average Convergence Divergence)

    MACD Line = EMA(fast) - EMA(slow)
    Signal Line = EMA(MACD Line, signal)
    Histogram = MACD Line - Signal Line

    Histogram > 0: 看漲動能
    Histogram < 0: 看跌動能

    Returns:
        (MACD 線, Signal 線, Histogram) 或 (None, None, None)
    """
    closes = [k["c"] for k in klines]
    if len(closes) < slow:
        return None, None, None

    ema_fast = _ema_series(closes, fast)
    ema_slow = _ema_series(closes, slow)

    macd_line = [
        ema_fast[i] - ema_slow[i]
        for i in range(len(closes))
        if ema_fast[i] is not None and ema_slow[i] is not None
    ]

    if not macd_line:
        return None, None, None

    signal_line = _ema_series(macd_line, signal)
    m = macd_line[-1]
    s = signal_line[-1]
    h = (m - s) if s is not None else None

    return m, s, h


def vwap(klines: List[dict]) -> float:
    """
    計算成交量加權平均價格 (VWAP)

    VWAP = Σ(典型價格 × 成交量) / Σ(成交量)
    典型價格 = (最高價 + 最低價 + 收盤價) / 3

    價格 > VWAP: 相對強勢（看漲）
    價格 < VWAP: 相對弱勢（看跌）

    Returns:
        VWAP 值
    """
    tp_vol = sum(
        (k["h"] + k["l"] + k["c"]) / 3 * k["v"]
        for k in klines
    )
    total_vol = sum(k["v"] for k in klines)
    return tp_vol / total_vol if total_vol > 0 else 0.0


def ema_cross(
    klines: List[dict],
    short_period: int = config.EMA_SHORT,
    long_period: int = config.EMA_LONG,
) -> Tuple[Optional[float], Optional[float]]:
    """
    計算 EMA 交叉信號

    EMA 短期 > EMA 長期: 黃金交叉（看漲）
    EMA 短期 < EMA 長期: 死亡交叉（看跌）

    Returns:
        (EMA 短期值, EMA 長期值) 或 (None, None)
    """
    closes = [k["c"] for k in klines]
    short_emas = _ema_series(closes, short_period)
    long_emas = _ema_series(closes, long_period)

    short_val = short_emas[-1] if short_emas and short_emas[-1] is not None else None
    long_val = long_emas[-1] if long_emas and long_emas[-1] is not None else None

    return short_val, long_val


def heikin_ashi(klines: List[dict]) -> List[dict]:
    """
    計算 Heikin Ashi 蠟燭線

    Heikin Ashi 平滑化價格波動，更容易辨識趨勢方向。
    連續綠色蠟燭 = 上升趨勢
    連續紅色蠟燭 = 下降趨勢

    Returns:
        Heikin Ashi 蠟燭線列表
    """
    ha = []
    for i, k in enumerate(klines):
        ha_close = (k["o"] + k["h"] + k["l"] + k["c"]) / 4
        if i == 0:
            ha_open = (k["o"] + k["c"]) / 2
        else:
            ha_open = (ha[i - 1]["o"] + ha[i - 1]["c"]) / 2

        ha.append({
            "t": k.get("t"),
            "o": ha_open,
            "h": max(k["h"], ha_open, ha_close),
            "l": min(k["l"], ha_open, ha_close),
            "c": ha_close,
            "green": ha_close >= ha_open,
        })

    return ha


def ha_streak(klines: List[dict], max_candles: int = 3) -> int:
    """
    計算 Heikin Ashi 連續方向蠟燭數

    Returns:
        正數 = 連續看漲蠟燭數，負數 = 連續看跌蠟燭數
    """
    ha = heikin_ashi(klines)
    if not ha:
        return 0

    streak = 0
    for candle in reversed(ha[-max_candles:]):
        if candle["green"]:
            if streak >= 0:
                streak += 1
            else:
                break
        else:
            if streak <= 0:
                streak -= 1
            else:
                break

    return streak


def bollinger_bands(
    klines: List[dict],
    period: int = 20,
    num_std: float = 2.0,
) -> Optional[dict]:
    """
    計算布林通道 (Bollinger Bands)

    布林通道 = SMA ± N 倍標準差
    %B = (價格 - 下軌) / (上軌 - 下軌)

    %B > 1.0: 價格突破上軌（超買 / 強勢突破）
    %B < 0.0: 價格跌破下軌（超賣 / 弱勢突破）
    %B ≈ 0.5: 價格在中軌附近

    帶寬 (Bandwidth) = (上軌 - 下軌) / 中軌
    帶寬越窄 = 波動率越低 → 可能即將爆發（Squeeze）

    Args:
        klines: K 線數據列表
        period: 移動平均週期
        num_std: 標準差倍數

    Returns:
        {
            "upper": float,   # 上軌
            "middle": float,  # 中軌 (SMA)
            "lower": float,   # 下軌
            "pct_b": float,   # %B 值
            "bandwidth": float, # 帶寬
        }
        或 None
    """
    closes = [k["c"] for k in klines]
    if len(closes) < period:
        return None

    # SMA
    sma = sum(closes[-period:]) / period

    # 標準差
    variance = sum((c - sma) ** 2 for c in closes[-period:]) / period
    std_dev = variance ** 0.5

    upper = sma + num_std * std_dev
    lower = sma - num_std * std_dev

    # %B: 價格在通道中的相對位置
    band_width = upper - lower
    price = closes[-1]
    pct_b = (price - lower) / band_width if band_width > 0 else 0.5

    # 帶寬 (正規化)
    bandwidth = band_width / sma if sma > 0 else 0.0

    return {
        "upper": round(upper, 2),
        "middle": round(sma, 2),
        "lower": round(lower, 2),
        "pct_b": round(pct_b, 4),
        "bandwidth": round(bandwidth, 6),
    }
