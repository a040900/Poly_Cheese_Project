"""
🧀 CheeseDog - LLM 建議處理器 (步驟 13)
接收宿主 AI 代理的分析建議，驗證格式後應用到系統。

功能:
- 驗證 AI 建議的 JSON 格式
- 應用交易模式切換建議
- 應用指標權重調整建議
- 記錄所有建議到資料庫
- 透過 MessageBus 發佈建議事件
"""

import time
import json
import logging
from typing import Optional, Dict, Any

from app import config
from app.database import db
from app.core.event_bus import bus

logger = logging.getLogger("cheesedog.llm.advisor")


class LLMAdvisor:
    """
    LLM 建議處理器

    宿主 AI 代理分析完資料後，會呼叫 /api/llm/advice
    將建議送入此處理器，系統驗證格式後執行。
    """

    VALID_MODES = {"aggressive", "balanced", "conservative"}
    VALID_ACTIONS = {"HOLD", "SWITCH_MODE", "PAUSE_TRADING", "CONTINUE"}
    VALID_RISK_LEVELS = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}

    def __init__(self):
        self._advice_history: list[dict] = []
        self._last_advice: Optional[dict] = None
        self._applied_count = 0
        self._rejected_count = 0

    def process_advice(
        self,
        advice_data: dict,
        signal_generator=None,
        auto_apply: bool = False,
    ) -> dict:
        """
        處理 AI 建議

        Args:
            advice_data: AI 代理回傳的 JSON 建議
            signal_generator: SignalGenerator 實例 (若要自動切換模式)
            auto_apply: 是否自動應用建議

        Expected advice_data format:
            {
                "analysis": str,
                "recommended_mode": "aggressive"|"balanced"|"conservative",
                "confidence": 0-100,
                "risk_level": "LOW"|"MEDIUM"|"HIGH",
                "action": "HOLD"|"SWITCH_MODE"|"PAUSE_TRADING"|"CONTINUE",
                "param_adjustments": {
                    "signal_threshold": int | null,
                    "indicator_weights": dict
                },
                "reasoning": str
            }

        Returns:
            處理結果
        """
        # 驗證
        validation = self._validate_advice(advice_data)
        if not validation["valid"]:
            self._rejected_count += 1
            logger.warning(f"⚠️ AI 建議格式無效: {validation['errors']}")
            return {
                "status": "rejected",
                "errors": validation["errors"],
            }

        # 記錄建議
        advice_record = {
            "timestamp": time.time(),
            "advice_type": advice_data.get("action", "HOLD"),
            "recommended_mode": advice_data.get("recommended_mode", "balanced"),
            "reasoning": advice_data.get("reasoning", ""),
            "market_context": {
                "analysis": advice_data.get("analysis", ""),
                "confidence": advice_data.get("confidence", 0),
                "risk_level": advice_data.get("risk_level", "MEDIUM"),
                "param_adjustments": advice_data.get("param_adjustments", {}),
            },
            "applied": False,
        }

        self._last_advice = advice_record
        self._advice_history.append(advice_record)

        # 存入資料庫
        try:
            db.save_llm_advice(advice_record)
        except Exception as e:
            logger.error(f"儲存建議到 DB 失敗: {e}")

        # 發佈事件
        bus.publish("llm.advice_received", advice_record, source="llm_advisor")

        # 自動應用
        result = {
            "status": "received",
            "advice": advice_record,
            "applied": False,
            "changes": [],
        }

        if auto_apply and signal_generator:
            apply_result = self.apply_advice(advice_data, signal_generator)
            result.update(apply_result)

        self._applied_count += 1
        logger.info(
            f"📬 收到 AI 建議 | 行動: {advice_data.get('action')} | "
            f"推薦模式: {advice_data.get('recommended_mode')} | "
            f"信心度: {advice_data.get('confidence')}%"
        )

        return result

    def apply_advice(
        self,
        advice_data: dict,
        signal_generator,
    ) -> dict:
        """
        應用 AI 建議到系統

        Args:
            advice_data: 已驗證的建議
            signal_generator: SignalGenerator 實例

        Returns:
            應用結果
        """
        changes = []
        action = advice_data.get("action", "HOLD")

        # 1. 模式切換
        if action == "SWITCH_MODE":
            recommended = advice_data.get("recommended_mode")
            if recommended and recommended in self.VALID_MODES:
                old_mode = signal_generator.current_mode
                if old_mode != recommended:
                    signal_generator.set_mode(recommended)
                    changes.append({
                        "type": "mode_switch",
                        "from": old_mode,
                        "to": recommended,
                    })
                    bus.publish(
                        "llm.mode_switched",
                        {"from": old_mode, "to": recommended},
                        source="llm_advisor",
                    )

        # 2. 指標權重調整
        param_adj = advice_data.get("param_adjustments", {})
        if param_adj:
            new_weights = param_adj.get("indicator_weights", {})
            if new_weights and isinstance(new_weights, dict):
                weight_changes = self._apply_weight_adjustments(new_weights)
                if weight_changes:
                    changes.extend(weight_changes)

        # 更新最後建議的 applied 狀態
        if self._last_advice:
            self._last_advice["applied"] = bool(changes)

        return {
            "applied": bool(changes),
            "changes": changes,
        }

    def _apply_weight_adjustments(self, new_weights: dict) -> list:
        """
        應用指標權重調整

        只允許合理範圍 (1-20) 的權重值，
        防止 AI hallucination 產生極端值。
        """
        changes = []
        for key, value in new_weights.items():
            if key not in config.BIAS_WEIGHTS:
                continue

            # 驗證值的合理性
            if not isinstance(value, (int, float)):
                continue
            value = max(1, min(20, int(value)))

            old_value = config.BIAS_WEIGHTS[key]
            if old_value != value:
                config.BIAS_WEIGHTS[key] = value
                changes.append({
                    "type": "weight_adjustment",
                    "indicator": key,
                    "from": old_value,
                    "to": value,
                })

        if changes:
            logger.info(f"⚙️ 已套用 {len(changes)} 項指標權重調整")
            bus.publish(
                "llm.weights_adjusted",
                {"changes": changes},
                source="llm_advisor",
            )

        return changes

    def _validate_advice(self, data: dict) -> dict:
        """驗證建議格式"""
        errors = []

        if not isinstance(data, dict):
            return {"valid": False, "errors": ["建議數據必須是字典格式"]}

        # 必要欄位
        if "recommended_mode" not in data:
            errors.append("缺少 recommended_mode 欄位")
        elif data["recommended_mode"] not in self.VALID_MODES:
            errors.append(f"recommended_mode 無效: {data['recommended_mode']}，有效值: {self.VALID_MODES}")

        if "action" in data and data["action"] not in self.VALID_ACTIONS:
            errors.append(f"action 無效: {data['action']}，有效值: {self.VALID_ACTIONS}")

        if "confidence" in data:
            conf = data["confidence"]
            if not isinstance(conf, (int, float)) or conf < 0 or conf > 100:
                errors.append(f"confidence 必須在 0-100 之間，目前: {conf}")

        if "risk_level" in data and data["risk_level"] not in self.VALID_RISK_LEVELS:
            errors.append(f"risk_level 無效: {data['risk_level']}")

        # 參數調整驗證
        param_adj = data.get("param_adjustments", {})
        if param_adj and isinstance(param_adj, dict):
            weights = param_adj.get("indicator_weights", {})
            if weights and isinstance(weights, dict):
                for key, val in weights.items():
                    if key not in config.BIAS_WEIGHTS:
                        errors.append(f"指標權重 '{key}' 不存在")
                    elif isinstance(val, (int, float)) and (val < 0 or val > 50):
                        errors.append(f"指標權重 '{key}' 值 {val} 超出合理範圍 (0-50)")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
        }

    # ── 查詢方法 ──────────────────────────────────────────────

    def get_last_advice(self) -> Optional[dict]:
        """取得最近一次建議"""
        return self._last_advice

    def get_advice_history(self, limit: int = 20) -> list:
        """取得建議歷史"""
        return self._advice_history[-limit:]

    def get_stats(self) -> dict:
        """取得建議處理統計"""
        return {
            "total_received": self._applied_count + self._rejected_count,
            "applied": self._applied_count,
            "rejected": self._rejected_count,
            "last_advice": self._last_advice,
        }


# 全域實例
llm_advisor = LLMAdvisor()
