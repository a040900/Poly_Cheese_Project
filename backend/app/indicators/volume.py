"""
🧀 CheeseDog - 成交量指標計算模組
計算 CVD (累積交易量差)、Delta、成交量分佈 (Volume Profile) 等指標。
"""

import time
from typing import List, Dict, Tuple
from app import config


def cumulative_volume_delta(
    trades: List[dict],
    window_secs: int,
) -> float:
    """
    計算累積交易量差 (Cumulative Volume Delta, CVD)

    CVD = Σ(買方成交量 * 價格) - Σ(賣方成交量 * 價格)
    正值 = 買方主導（看漲），負值 = 賣方主導（看跌）

    Args:
        trades: 交易記錄列表 [{"t": 時間, "price": 價格, "qty": 數量, "is_buy": bool}]
        window_secs: 時間窗口（秒）

    Returns:
        CVD 值
    """
    cutoff = time.time() - window_secs
    return sum(
        t["qty"] * t["price"] * (1 if t["is_buy"] else -1)
        for t in trades
        if t["t"] >= cutoff
    )


def cvd_all_windows(trades: List[dict]) -> Dict[int, float]:
    """
    計算所有預設時間窗口的 CVD

    Returns:
        {窗口秒數: CVD 值} 例如 {60: 1234.5, 180: 5678.9, 300: 9012.3}
    """
    return {
        w: cumulative_volume_delta(trades, w)
        for w in config.CVD_WINDOWS
    }


def delta(trades: List[dict], window_secs: int = config.DELTA_WINDOW) -> float:
    """
    計算短線 Delta（純成交量差，不乘以價格）

    Delta > 0: 買方量佔優
    Delta < 0: 賣方量佔優

    Args:
        trades: 交易記錄列表
        window_secs: 時間窗口（秒）

    Returns:
        Delta 值
    """
    cutoff = time.time() - window_secs
    return sum(
        t["qty"] * (1 if t["is_buy"] else -1)
        for t in trades
        if t["t"] >= cutoff
    )


def volume_profile(
    klines: List[dict],
    n_bins: int = config.VP_BINS,
) -> Tuple[float, List[Tuple[float, float]]]:
    """
    計算成交量分佈 (Volume Profile) 與 POC (Point of Control)

    POC = 成交量最集中的價格水平

    Args:
        klines: K 線數據列表
        n_bins: 價格分桶數

    Returns:
        (POC 價格, [(桶中心價格, 成交量), ...])
    """
    if not klines:
        return 0.0, []

    lo = min(k["l"] for k in klines)
    hi = max(k["h"] for k in klines)

    if hi == lo:
        total_vol = sum(k["v"] for k in klines)
        return lo, [(lo, total_vol)]

    bin_size = (hi - lo) / n_bins
    bins = [0.0] * n_bins

    for k in klines:
        b_lo = max(0, int((k["l"] - lo) / bin_size))
        b_hi = min(n_bins - 1, int((k["h"] - lo) / bin_size))
        share = k["v"] / max(1, b_hi - b_lo + 1)
        for b in range(b_lo, b_hi + 1):
            bins[b] += share

    poc_idx = bins.index(max(bins))
    poc = lo + (poc_idx + 0.5) * bin_size

    data = [(lo + (i + 0.5) * bin_size, bins[i]) for i in range(n_bins)]

    return poc, data
