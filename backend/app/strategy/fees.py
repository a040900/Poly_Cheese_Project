"""
🧀 CheeseDog - 手續費計算模組 (Phase 2)
借鏡 NautilusTrader Polymarket 整合文件：
  - 15 分鐘加密貨幣市場有特殊手續費結構
  - Buy 端手續費: 0.2% - 1.6%（從 Token 扣除）
  - Sell 端手續費: 0.8% - 3.7%（從 USDC 扣除）
  - 手續費四捨五入至 4 位小數（最低 0.0001 USDC）
"""

import logging
from dataclasses import dataclass
from typing import Literal

from app import config

logger = logging.getLogger("cheesedog.strategy.fees")


@dataclass
class FeeResult:
    """手續費計算結果"""
    gross_amount: float       # 原始金額
    fee_amount: float         # 手續費金額
    net_amount: float         # 扣除手續費後的淨額
    fee_rate: float           # 實際費率
    fee_deducted_in: str      # 手續費從哪裡扣（"token" 或 "usdc"）
    side: str                 # "buy" 或 "sell"


class PolymarketFeeModel:
    """
    Polymarket 15 分鐘市場手續費模型

    根據 NautilusTrader 文件：
    - 大部分 Polymarket 市場免手續費
    - 15 分鐘加密貨幣市場例外
    - Buy: 0.2% - 1.6%（從 Token 扣除）
    - Sell: 0.8% - 3.7%（從 USDC 扣除）
    - 實際費率通常與合約價格相關
    """

    def __init__(self):
        self.buy_range = config.PM_FEE_BUY_RANGE
        self.sell_range = config.PM_FEE_SELL_RANGE
        self.buy_default = config.PM_FEE_BUY_DEFAULT
        self.sell_default = config.PM_FEE_SELL_DEFAULT
        self.min_fee = 0.0001  # 最低手續費 0.0001 USDC

    def calculate_buy_fee(
        self,
        amount: float,
        contract_price: float = 0.5,
    ) -> FeeResult:
        """
        計算 Buy 端手續費

        Buy 端手續費從 Token 扣除，費率隨合約價格變動：
        - 合約價格越低（風險越高）→ 手續費越高
        - 價格 ≈ 0.50 → 約 0.5%
        - 價格 ≈ 0.90 → 約 0.2%
        - 價格 ≈ 0.10 → 約 1.6%

        Args:
            amount: 購買金額 (USDC)
            contract_price: 合約當前價格 (0~1)

        Returns:
            FeeResult 手續費計算結果
        """
        fee_rate = self._estimate_fee_rate(
            contract_price,
            self.buy_range[0],
            self.buy_range[1],
            self.buy_default,
        )

        fee_amount = max(round(amount * fee_rate, 4), self.min_fee)
        net_amount = amount - fee_amount

        return FeeResult(
            gross_amount=amount,
            fee_amount=fee_amount,
            net_amount=net_amount,
            fee_rate=fee_rate,
            fee_deducted_in="token",
            side="buy",
        )

    def calculate_sell_fee(
        self,
        amount: float,
        contract_price: float = 0.5,
    ) -> FeeResult:
        """
        計算 Sell 端手續費

        Sell 端手續費從 USDC 扣除，費率通常高於 Buy 端：
        - 價格 ≈ 0.50 → 約 1.5%
        - 價格 ≈ 0.90 → 約 0.8%
        - 價格 ≈ 0.10 → 約 3.7%

        Args:
            amount: 賣出金額 (USDC 等值)
            contract_price: 合約當前價格 (0~1)

        Returns:
            FeeResult 手續費計算結果
        """
        fee_rate = self._estimate_fee_rate(
            contract_price,
            self.sell_range[0],
            self.sell_range[1],
            self.sell_default,
        )

        fee_amount = max(round(amount * fee_rate, 4), self.min_fee)
        net_amount = amount - fee_amount

        return FeeResult(
            gross_amount=amount,
            fee_amount=fee_amount,
            net_amount=net_amount,
            fee_rate=fee_rate,
            fee_deducted_in="usdc",
            side="sell",
        )

    def calculate_fee(
        self,
        side: Literal["buy", "sell"],
        amount: float,
        contract_price: float = 0.5,
    ) -> FeeResult:
        """統一入口：根據方向計算手續費"""
        if side == "buy":
            return self.calculate_buy_fee(amount, contract_price)
        return self.calculate_sell_fee(amount, contract_price)

    def estimate_round_trip_cost(
        self,
        amount: float,
        buy_price: float = 0.5,
        sell_price: float = 0.5,
    ) -> dict:
        """
        估算一次完整交易（買入 → 賣出）的總手續費成本

        Args:
            amount: 交易金額
            buy_price: 買入時合約價格
            sell_price: 賣出時合約價格

        Returns:
            包含總成本、各端手續費的字典
        """
        buy_fee = self.calculate_buy_fee(amount, buy_price)
        sell_fee = self.calculate_sell_fee(amount, sell_price)

        total_fee = buy_fee.fee_amount + sell_fee.fee_amount
        total_rate = total_fee / amount if amount > 0 else 0

        return {
            "amount": amount,
            "buy_fee": buy_fee.fee_amount,
            "buy_rate": buy_fee.fee_rate,
            "sell_fee": sell_fee.fee_amount,
            "sell_rate": sell_fee.fee_rate,
            "total_fee": round(total_fee, 4),
            "total_rate": round(total_rate, 4),
            "break_even_pct": round(total_rate * 100, 2),
        }

    @staticmethod
    def _estimate_fee_rate(
        price: float,
        min_rate: float,
        max_rate: float,
        default_rate: float,
    ) -> float:
        """
        根據合約價格估算手續費率

        模型假設：合約價格越極端（接近 0 或 1），手續費越高
        這是因為極端價格的合約流動性較差

        使用二次函數在 min_rate 和 max_rate 之間映射：
        price = 0.5 → 最低費率（最具流動性的價格點）
        price → 0 或 1 → 最高費率
        """
        price = max(0.01, min(0.99, price))

        # 距離 0.5 的偏差度（0~0.5）
        deviation = abs(price - 0.5) * 2  # 正規化至 0~1

        # 二次映射: deviation^1.5 讓曲線更自然
        factor = deviation ** 1.5

        # 從 min_rate 到 max_rate 的插值
        fee_rate = min_rate + factor * (max_rate - min_rate)

        return round(fee_rate, 6)


# 全域手續費模型實例
fee_model = PolymarketFeeModel()
