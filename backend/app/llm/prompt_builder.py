"""
🧀 CheeseDog - LLM 結構化提示生成器 (步驟 13)
將系統即時狀態格式化為結構化 prompt，供宿主 AI 代理快速理解。

設計理念:
- CheeseDog 不直接呼叫 LLM API
- 改由宿主 AI 代理 (Antigravity/OpenClaw) 透過 API 取得上下文
- AI 代理分析後回傳建議，系統執行建議

輸出格式:
    1. context_snapshot  — 即時數據摘要 (供 /api/llm/context)
    2. analysis_prompt   — 完整分析 prompt (可直接貼給 AI)
    3. param_tune_prompt — 參數調優 prompt
"""

import time
import json
import logging
from typing import Optional, Dict, List, Any

from app import config

logger = logging.getLogger("cheesedog.llm.prompt_builder")


class PromptBuilder:
    """
    結構化提示生成器

    收集系統各模組的即時數據，格式化為 AI 可理解的結構。
    """

    def build_context_snapshot(
        self,
        market_data: dict,
        signal_data: dict,
        indicators: dict,
        performance: dict,
        connections: dict,
        sim_stats: dict,
    ) -> dict:
        """
        建構完整的系統上下文快照

        這是 /api/llm/context 的核心輸出。
        AI 代理可以用這份資料快速理解系統狀態，
        不需要人工拼裝資訊。

        Returns:
            結構化的上下文字典
        """
        return {
            "system": {
                "name": config.APP_NAME,
                "version": config.VERSION,
                "timestamp": time.time(),
                "timestamp_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
            },
            "market": self._format_market(market_data),
            "signal": self._format_signal(signal_data),
            "indicators": self._format_indicators(indicators),
            "performance": self._format_performance(performance),
            "connections": connections,
            "simulation": self._format_simulation(sim_stats),
            "config": self._format_config(),
        }

    def build_analysis_prompt(
        self,
        context: dict,
        focus: str = "general",
    ) -> str:
        """
        建構完整的分析 prompt

        Args:
            context: build_context_snapshot() 的輸出
            focus: 分析焦點
                - "general"    : 全面分析
                - "signal"     : 專注信號品質
                - "risk"       : 風險評估
                - "mode_switch": 模式切換建議

        Returns:
            可直接給 AI 的結構化 prompt 文字
        """
        market = context.get("market", {})
        signal = context.get("signal", {})
        perf = context.get("performance", {})
        sim = context.get("simulation", {})
        indicators = context.get("indicators", {})

        lines = [
            "# 🧀 CheeseDog 交易系統分析請求",
            "",
            "## 系統說明",
            "CheeseDog 是 Polymarket BTC 15 分鐘二元選擇權的智能交易輔助系統。",
            "系統使用 9 種技術指標綜合評分 (-100 ~ +100) 產生 BUY_UP / SELL_DOWN / NEUTRAL 信號。",
            "",
        ]

        # 市場數據
        lines.extend([
            "## 即時市場數據",
            f"- **BTC 中間價**: ${market.get('btc_mid', 0):,.2f}",
            f"- **Chainlink BTC/USD**: ${market.get('chainlink_price', 0):,.2f}" if market.get("chainlink_price") else "",
            f"- **PM UP 合約**: {market.get('pm_up_price', 'N/A')}",
            f"- **PM DOWN 合約**: {market.get('pm_down_price', 'N/A')}",
            f"- **PM 流動性**: ${market.get('pm_liquidity', 0):,.0f}" if market.get("pm_liquidity") else "",
            "",
        ])

        # 當前信號
        lines.extend([
            "## 當前交易信號",
            f"- **方向**: {signal.get('direction', 'NEUTRAL')}",
            f"- **趨勢分數**: {signal.get('score', 0):.1f} / 100",
            f"- **信心度**: {signal.get('confidence', 0):.1f}%",
            f"- **交易模式**: {signal.get('mode', 'balanced')} ({signal.get('mode_name', '')})",
            f"- **閾值**: ±{signal.get('threshold', 40)}",
            "",
        ])

        # 指標明細
        if indicators:
            lines.append("## 指標明細")
            for name, detail in indicators.items():
                if isinstance(detail, dict):
                    sig = detail.get("signal", "N/A")
                    contrib = detail.get("contribution", 0)
                    lines.append(f"- **{name}**: {sig} (貢獻 {contrib:+.1f})")
            lines.append("")

        # 績效
        summary = perf.get("summary", {})
        if summary:
            dd = perf.get("drawdown", {})
            lines.extend([
                "## 交易績效",
                f"- **總交易數**: {summary.get('total_trades', 0)}",
                f"- **勝率**: {summary.get('win_rate', 0):.1f}%",
                f"- **總 PnL**: ${summary.get('total_pnl', 0):+.2f}",
                f"- **報酬率**: {summary.get('total_return_pct', 0):+.1f}%",
                f"- **夏普比率**: {summary.get('sharpe_ratio', 0)}",
                f"- **收益因子**: {summary.get('profit_factor', 0)}",
                f"- **最大回撤**: {dd.get('max_dd_pct', 0):.1f}%",
                f"- **總手續費**: ${summary.get('total_fees', 0):.4f}",
                "",
            ])

        # 模擬交易統計
        if sim:
            lines.extend([
                "## 模擬交易統計",
                f"- **餘額**: ${sim.get('balance', 0):,.2f}",
                f"- **未平倉**: {sim.get('open_trades', 0)} 筆",
                f"- **已結算**: {sim.get('closed_trades', 0)} 筆",
                "",
            ])

        # 分析焦點
        lines.append("## 分析請求")
        if focus == "general":
            lines.extend([
                "請針對以下幾個面向提供分析和建議：",
                "1. **市場狀態評估**: 當前 BTC 趨勢是否明確？",
                "2. **信號品質**: 當前信號的可信度如何？哪些指標互相矛盾？",
                "3. **模式建議**: 目前應使用 aggressive / balanced / conservative 哪種模式？",
                "4. **風險提醒**: 有無需要注意的風險因素？",
                "5. **參數調整**: 有無建議的指標權重微調？",
            ])
        elif focus == "signal":
            lines.extend([
                "專注分析當前信號品質：",
                "1. 當前各指標的共識程度如何？",
                "2. 是否有指標發出相反信號需要注意？",
                "3. 信號可信度評估 (高/中/低)，原因？",
                "4. 是否建議執行此信號？",
            ])
        elif focus == "risk":
            lines.extend([
                "專注風險評估：",
                "1. 當前最大回撤是否在可接受範圍？",
                "2. 連續虧損跡象？",
                "3. 手續費對盈利的侵蝕程度？",
                "4. 是否應暫停交易？",
            ])
        elif focus == "mode_switch":
            lines.extend([
                "評估是否需要切換交易模式：",
                "1. 當前模式的績效如何？",
                "2. 市場波動性適合哪種模式？",
                "3. 具體建議切換至哪種模式，以及原因？",
                "4. 切換後的預期影響？",
            ])

        lines.extend([
            "",
            "## 回覆格式",
            "請以下列 JSON 格式回覆：",
            "```json",
            "{",
            '  "analysis": "你的分析文字",',
            '  "recommended_mode": "aggressive|balanced|conservative",',
            '  "confidence": 0-100,',
            '  "risk_level": "LOW|MEDIUM|HIGH",',
            '  "action": "HOLD|SWITCH_MODE|PAUSE_TRADING|CONTINUE",',
            '  "param_adjustments": {',
            '    "signal_threshold": null,',
            '    "indicator_weights": {}',
            '  },',
            '  "reasoning": "建議的理由摘要"',
            "}",
            "```",
        ])

        return "\n".join(lines)

    def build_param_tune_prompt(
        self,
        context: dict,
        backtest_results: Optional[dict] = None,
    ) -> str:
        """
        建構參數調優 prompt

        Args:
            context: 系統上下文快照
            backtest_results: 回測結果 (可選)

        Returns:
            參數調優 prompt
        """
        lines = [
            "# 🧀 CheeseDog 參數調優請求",
            "",
            "## 當前參數配置",
            "",
            "### 指標權重 (BIAS_WEIGHTS)",
            "| 指標 | 權重 | 說明 |",
            "|------|------|------|",
        ]

        weight_descriptions = {
            "ema": "EMA5/EMA20 交叉",
            "obi": "訂單簿失衡",
            "macd": "MACD 直方圖方向",
            "cvd": "CVD 5 分鐘方向",
            "ha": "Heikin-Ashi 連續方向",
            "vwap": "價格 vs VWAP",
            "rsi": "RSI 超買/超賣",
            "poc": "價格 vs POC",
            "walls": "買牆 − 賣牆",
        }
        for key, weight in config.BIAS_WEIGHTS.items():
            desc = weight_descriptions.get(key, "")
            lines.append(f"| {key} | {weight} | {desc} |")

        lines.extend([
            "",
            "### 交易模式閾值",
            f"- 積極模式: signal_threshold = {config.TRADING_MODES['aggressive']['signal_threshold']}",
            f"- 平衡模式: signal_threshold = {config.TRADING_MODES['balanced']['signal_threshold']}",
            f"- 保守模式: signal_threshold = {config.TRADING_MODES['conservative']['signal_threshold']}",
            "",
            "### 手續費結構",
            f"- Buy: {config.PM_FEE_BUY_RANGE[0]*100:.1f}% - {config.PM_FEE_BUY_RANGE[1]*100:.1f}%",
            f"- Sell: {config.PM_FEE_SELL_RANGE[0]*100:.1f}% - {config.PM_FEE_SELL_RANGE[1]*100:.1f}%",
            "",
        ])

        # 加入回測結果
        if backtest_results and "comparison" in backtest_results:
            lines.extend([
                "## 回測結果比較",
                "| 模式 | PnL | 報酬率 | 勝率 | 夏普 | 交易數 |",
                "|------|-----|--------|------|------|--------|",
            ])
            for mode, data in backtest_results["comparison"].items():
                if isinstance(data, dict) and "error" not in data:
                    lines.append(
                        f"| {mode} | ${data.get('total_pnl', 0):+.2f} | "
                        f"{data.get('total_return_pct', 0):+.1f}% | "
                        f"{data.get('win_rate', 0):.1f}% | "
                        f"{data.get('sharpe_ratio', 0)} | "
                        f"{data.get('total_trades', 0)} |"
                    )
            best_mode = backtest_results.get("best_mode")
            if best_mode:
                lines.append(f"\n🏆 回測最佳模式: **{best_mode}**")
            lines.append("")

        lines.extend([
            "## 請求",
            "根據以上數據和回測結果，請建議：",
            "1. **BIAS_WEIGHTS 調整**: 哪些指標權重應增減？",
            "2. **閾值調整**: signal_threshold 是否需要修改？",
            "3. **模式切換**: 推薦使用哪種交易模式？",
            "",
            "## 回覆格式",
            "```json",
            "{",
            '  "recommended_weights": {',
            '    "ema": 10, "obi": 8, "macd": 8, "cvd": 7,',
            '    "ha": 6, "vwap": 5, "rsi": 5, "poc": 3, "walls": 4',
            '  },',
            '  "recommended_thresholds": {',
            '    "aggressive": 25,',
            '    "balanced": 40,',
            '    "conservative": 60',
            '  },',
            '  "recommended_mode": "balanced",',
            '  "reasoning": "調整理由摘要"',
            "}",
            "```",
        ])

        return "\n".join(lines)

    # ── 格式化方法 ────────────────────────────────────────────

    @staticmethod
    def _format_market(data: dict) -> dict:
        return {
            "btc_mid": data.get("btc_price", 0),
            "pm_up_price": data.get("pm_up_price"),
            "pm_down_price": data.get("pm_down_price"),
            "chainlink_price": data.get("chainlink_price"),
            "pm_market_title": data.get("pm_market_title"),
            "pm_liquidity": data.get("pm_liquidity"),
            "pm_volume": data.get("pm_volume"),
            "trade_count": data.get("trade_count", 0),
            "kline_count": data.get("kline_count", 0),
        }

    @staticmethod
    def _format_signal(data: dict) -> dict:
        return {
            "direction": data.get("direction", "NEUTRAL"),
            "score": data.get("score", 0),
            "confidence": data.get("confidence", 0),
            "mode": data.get("mode", "balanced"),
            "mode_name": data.get("mode_name", ""),
            "threshold": data.get("threshold", 40),
            "timestamp": data.get("timestamp", 0),
        }

    @staticmethod
    def _format_indicators(data: dict) -> dict:
        """簡化指標數據到重點欄位"""
        simplified = {}
        for name, detail in data.items():
            if isinstance(detail, dict):
                simplified[name] = {
                    "signal": detail.get("signal", "N/A"),
                    "contribution": detail.get("contribution", 0),
                }
                # 保留關鍵數值
                for key in ("value", "streak", "histogram", "cvd_5m"):
                    if key in detail:
                        simplified[name][key] = detail[key]
        return simplified

    @staticmethod
    def _format_performance(data: dict) -> dict:
        if not data:
            return {"summary": {}, "drawdown": {}}
        return {
            "summary": data.get("summary", {}),
            "drawdown": data.get("drawdown", {}),
            "by_mode": data.get("by_mode", {}),
        }

    @staticmethod
    def _format_simulation(data: dict) -> dict:
        return {
            "balance": data.get("balance", 0),
            "open_trades": data.get("open_trades", 0),
            "closed_trades": data.get("closed_trades", 0),
            "running": data.get("running", False),
        }

    @staticmethod
    def _format_config() -> dict:
        """輸出關鍵設定供 AI 參考"""
        return {
            "bias_weights": dict(config.BIAS_WEIGHTS),
            "trading_modes": {
                k: {
                    "name": v["name"],
                    "signal_threshold": v["signal_threshold"],
                    "max_position_pct": v["max_position_pct"],
                }
                for k, v in config.TRADING_MODES.items()
            },
            "fee_structure": {
                "buy_range_pct": [r * 100 for r in config.PM_FEE_BUY_RANGE],
                "sell_range_pct": [r * 100 for r in config.PM_FEE_SELL_RANGE],
            },
        }


# 全域實例
prompt_builder = PromptBuilder()
