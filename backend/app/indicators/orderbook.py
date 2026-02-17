"""
🧀 CheeseDog - 訂單簿指標計算模組
計算訂單簿失衡 (OBI)、買賣掛單牆、流動性深度等指標。
"""

from typing import List, Tuple, Dict
from app import config


def order_book_imbalance(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    mid: float,
    band_pct: float = config.OBI_BAND_PCT,
) -> float:
    """
    計算訂單簿失衡 (Order Book Imbalance, OBI)

    OBI = (買方量 - 賣方量) / (買方量 + 賣方量)
    範圍: [-1, +1]
    正值 = 買壓較強（看漲），負值 = 賣壓較強（看跌）

    Args:
        bids: 買盤列表 [(價格, 數量), ...]
        asks: 賣盤列表 [(價格, 數量), ...]
        mid: 中間價
        band_pct: 中價兩側帶寬百分比

    Returns:
        OBI 值 [-1.0, +1.0]
    """
    if not mid or mid == 0:
        return 0.0

    band = mid * band_pct / 100
    bid_vol = sum(q for p, q in bids if p >= mid - band)
    ask_vol = sum(q for p, q in asks if p <= mid + band)
    total = bid_vol + ask_vol

    return (bid_vol - ask_vol) / total if total > 0 else 0.0


def detect_walls(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    multiplier: float = config.WALL_MULT,
) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """
    檢測買牆和賣牆

    掛單量超過平均值 N 倍的價位被視為「牆」。

    Args:
        bids: 買盤列表
        asks: 賣盤列表
        multiplier: 牆判定倍數

    Returns:
        (買牆列表, 賣牆列表)
    """
    all_vols = [q for _, q in bids] + [q for _, q in asks]
    if not all_vols:
        return [], []

    avg_vol = sum(all_vols) / len(all_vols)
    threshold = avg_vol * multiplier

    bid_walls = [(p, q) for p, q in bids if q >= threshold]
    ask_walls = [(p, q) for p, q in asks if q >= threshold]

    return bid_walls, ask_walls


def liquidity_depth(
    bids: List[Tuple[float, float]],
    asks: List[Tuple[float, float]],
    mid: float,
    bands: List[float] = config.DEPTH_BANDS,
) -> Dict[float, float]:
    """
    計算不同距離的流動性深度（USD 金額）

    Args:
        bids: 買盤列表
        asks: 賣盤列表
        mid: 中間價
        bands: 距離中價的百分比帶寬

    Returns:
        {百分比: USD 深度金額}
    """
    if not mid or mid == 0:
        return {b: 0.0 for b in bands}

    result = {}
    for pct in bands:
        band = mid * pct / 100
        bid_depth = sum(p * q for p, q in bids if p >= mid - band)
        ask_depth = sum(p * q for p, q in asks if p <= mid + band)
        result[pct] = bid_depth + ask_depth

    return result
