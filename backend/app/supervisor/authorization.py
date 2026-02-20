"""
🧀 CheeseDog - 授權管理器 (Authorization Manager) — Phase 4

「守門員」角色：攔截所有 AI 建議，根據 Navigator 和 Authorization Mode
決定該建議應該被直接執行、進入提案佇列、還是僅記錄。

架構定位:
    AIEngine / 外部 API
        ↓ (AI 建議)
    AuthorizationManager  ← ★ 本模組
        ├─ AUTO 模式     → 直接交給 LLMAdvisor.apply_advice()
        ├─ HITL 模式     → 封裝成 Proposal 進入佇列
        └─ MONITOR 模式  → 僅記錄日誌，不執行任何操作

    注意：讀取類 API（/api/cro/stats, /api/llm/context）
    不經過此管理器，它們屬於「資料平面」，永遠開放。

設計原則:
    - 單一職責 (SRP): 只負責「判斷是否放行」，不執行交易邏輯。
    - 開閉原則 (OCP): 新增 Navigator 來源只需加 elif，不需改核心流程。
    - 與 LLMAdvisor 銜接: 透過回調傳遞 signal_generator，讓 Proposal
      在核准後能正確調用 apply_advice()。
"""

import time
import logging
from typing import Optional, Dict, Any

from app import config
from app.core.event_bus import bus
from app.llm.advisor import llm_advisor
from app.supervisor.proposal_queue import proposal_queue, Proposal

logger = logging.getLogger("cheesedog.supervisor.auth")


class AuthorizationManager:
    """
    授權管理器

    根據系統設定 (AI_NAVIGATOR, AUTHORIZATION_MODE)
    攔截 AI 建議並導向正確的處理流程。
    """

    def __init__(self):
        self._signal_generator = None  # 延遲注入，避免循環引用
        self._total_processed = 0
        self._total_auto_executed = 0
        self._total_queued = 0
        self._total_monitor_logged = 0
        self._total_blocked = 0        # Navigator 不符被阻擋

        # 設定 ProposalQueue 的核准回調
        proposal_queue.set_approve_callback(self._on_proposal_approved)

        logger.info(
            f"🛡️ AuthorizationManager 已初始化 | "
            f"Navigator={config.AI_NAVIGATOR} | "
            f"AuthMode={config.AUTHORIZATION_MODE}"
        )

    # ── 依賴注入 ──────────────────────────────────────────────

    def inject_signal_generator(self, signal_generator):
        """
        注入 SignalGenerator 實例 (延遲注入避免循環引用)

        在 main.py 的 lifespan 中調用。
        """
        self._signal_generator = signal_generator
        logger.info("🛡️ SignalGenerator 已注入 AuthorizationManager")

    # ── 核心方法：處理 AI 建議 ────────────────────────────────

    def process_advice(
        self,
        advice_data: dict,
        source: str = "unknown",
        force_auto: bool = False,
    ) -> dict:
        """
        處理 AI 建議的統一入口

        取代原本直接調用 llm_advisor.process_advice() 的流程，
        在 LLMAdvisor 驗證完格式後，根據授權模式決定下一步。

        Args:
            advice_data: AI 代理回傳的 JSON 建議
            source: 建議來源標識 ("internal" | "openclaw" | "api")
            force_auto: 是否強制以 AUTO 模式處理（用於除錯）

        Returns:
            處理結果字典
        """
        self._total_processed += 1
        current_navigator = config.AI_NAVIGATOR
        current_auth_mode = config.AUTHORIZATION_MODE

        action = advice_data.get("action", "HOLD")
        confidence = advice_data.get("confidence", 0)

        logger.info(
            f"🛡️ 收到建議 | Source={source} | Action={action} | "
            f"Confidence={confidence}% | "
            f"Navigator={current_navigator} | AuthMode={current_auth_mode}"
        )

        # ── Step 1: Navigator 檢查 ───────────────────────────
        # 只有來自被選中的 Navigator 的建議才能進入控制平面
        if not self._check_navigator(source, current_navigator):
            self._total_blocked += 1
            logger.warning(
                f"🚫 建議被阻擋 | Source={source} 不符合 "
                f"Navigator={current_navigator}"
            )

            # 即使被阻擋，仍然記錄建議（資料平面不受影響）
            record_result = llm_advisor.process_advice(
                advice_data,
                signal_generator=None,
                auto_apply=False,
            )

            return {
                "status": "blocked",
                "reason": f"Navigator 設定為 '{current_navigator}'，"
                          f"來源 '{source}' 無控制權限",
                "advice_recorded": True,
                "record": record_result,
            }

        # ── Step 2: 先讓 LLMAdvisor 驗證格式 ────────────────
        validation_result = llm_advisor.process_advice(
            advice_data,
            signal_generator=None,
            auto_apply=False,  # 先不自動執行
        )

        if validation_result.get("status") == "rejected":
            return validation_result  # 格式無效，直接回傳拒絕

        # ── Step 3: 根據 Authorization Mode 路由 ────────────
        if force_auto:
            current_auth_mode = "auto"

        if current_auth_mode == "auto":
            return self._handle_auto(advice_data, source, validation_result)
        elif current_auth_mode == "hitl":
            return self._handle_hitl(advice_data, source, validation_result)
        elif current_auth_mode == "monitor":
            return self._handle_monitor(advice_data, source, validation_result)
        else:
            logger.error(f"❌ 未知的授權模式: {current_auth_mode}")
            return {
                "status": "error",
                "reason": f"未知的授權模式: {current_auth_mode}",
            }

    # ── AUTO 模式處理 ─────────────────────────────────────────

    def _handle_auto(
        self, advice_data: dict, source: str, validation_result: dict
    ) -> dict:
        """
        God Mode: 建議直接執行

        適用於高頻交易或夜間無人值守。
        """
        self._total_auto_executed += 1

        if not self._signal_generator:
            logger.warning("⚠️ SignalGenerator 尚未注入，無法執行建議")
            return {
                "status": "error",
                "reason": "SignalGenerator 尚未初始化",
                "advice_recorded": True,
            }

        # 直接執行
        apply_result = llm_advisor.apply_advice(
            advice_data,
            signal_generator=self._signal_generator,
        )

        bus.publish(
            "supervisor.auto_executed",
            {
                "source": source,
                "action": advice_data.get("action"),
                "apply_result": apply_result,
            },
            source="auth_manager",
        )

        logger.info(
            f"⚡ AUTO 模式直接執行 | Action={advice_data.get('action')} | "
            f"Applied={apply_result.get('applied')}"
        )

        return {
            "status": "auto_executed",
            "auth_mode": "auto",
            "advice_recorded": True,
            "record": validation_result,
            "apply_result": apply_result,
        }

    # ── HITL 模式處理 ─────────────────────────────────────────

    def _handle_hitl(
        self, advice_data: dict, source: str, validation_result: dict
    ) -> dict:
        """
        Supervisor Mode: 建議進入提案佇列等待人類審核

        例外：高信心度的保護性操作可能被緊急安全閥自動放行。
        """
        self._total_queued += 1

        # 建立提案（ProposalQueue 內部會處理緊急安全閥）
        proposal = proposal_queue.create(
            advice_data=advice_data,
            source=source,
            navigator=config.AI_NAVIGATOR,
        )

        result = {
            "status": "queued",
            "auth_mode": "hitl",
            "proposal_id": proposal.id,
            "priority": proposal.priority.value,
            "expires_at": proposal.expires_at,
            "remaining_seconds": proposal.remaining_seconds,
            "advice_recorded": True,
            "record": validation_result,
        }

        # 如果被緊急安全閥自動放行，狀態已變為 AUTO_APPROVED
        if proposal.status.value == "auto_approved":
            result["status"] = "emergency_auto_approved"
            result["note"] = "緊急安全閥觸發，已自動放行"

        logger.info(
            f"📋 HITL 提案已建立 | ID={proposal.id} | "
            f"Priority={proposal.priority.value} | "
            f"FinalStatus={proposal.status.value}"
        )

        return result

    # ── MONITOR 模式處理 ──────────────────────────────────────

    def _handle_monitor(
        self, advice_data: dict, source: str, validation_result: dict
    ) -> dict:
        """
        Monitor Only: 僅記錄，不執行任何操作

        建議已在 Step 2 中由 LLMAdvisor 記錄到歷史中，
        此處僅發佈事件並回傳。
        """
        self._total_monitor_logged += 1

        bus.publish(
            "supervisor.monitor_logged",
            {
                "source": source,
                "action": advice_data.get("action"),
                "confidence": advice_data.get("confidence", 0),
            },
            source="auth_manager",
        )

        logger.info(
            f"👁️ MONITOR 模式僅記錄 | Action={advice_data.get('action')} | "
            f"Confidence={advice_data.get('confidence', 0)}%"
        )

        return {
            "status": "monitored",
            "auth_mode": "monitor",
            "advice_recorded": True,
            "record": validation_result,
            "note": "MONITOR 模式：建議已記錄但不會執行",
        }

    # ── Proposal 核准回調 ─────────────────────────────────────

    def _on_proposal_approved(self, proposal: Proposal) -> dict:
        """
        提案被核准後的回調

        從 ProposalQueue 調用，將核准的提案交給 LLMAdvisor 執行。
        """
        if not self._signal_generator:
            logger.warning("⚠️ SignalGenerator 尚未注入，無法執行核准的提案")
            return {"applied": False, "error": "SignalGenerator 未初始化"}

        apply_result = llm_advisor.apply_advice(
            proposal.advice_data,
            signal_generator=self._signal_generator,
        )

        logger.info(
            f"✅ 核准提案已執行 | ID={proposal.id} | "
            f"Applied={apply_result.get('applied')}"
        )

        return apply_result

    # ── Navigator 檢查 ────────────────────────────────────────

    def _check_navigator(self, source: str, navigator: str) -> bool:
        """
        檢查建議來源是否被允許

        Args:
            source: 建議的實際來源 ("internal" | "openclaw" | "api")
            navigator: 系統設定的 Navigator

        Returns:
            True = 允許, False = 阻擋
        """
        if navigator == "none":
            # 純演算法模式，拒絕所有 AI 建議
            return False

        if navigator == "internal":
            # 僅接受來自內建 AI 或本地 API 的建議
            return source in ("internal", "api")

        if navigator == "openclaw":
            # 僅接受來自 OpenClaw 的建議
            return source in ("openclaw", "api")

        # 未知的 Navigator 設定，預設允許（寬鬆）
        logger.warning(f"⚠️ 未知的 Navigator 值: {navigator}，預設允許")
        return True

    # ── 動態配置更新 ──────────────────────────────────────────

    def update_settings(
        self,
        navigator: Optional[str] = None,
        auth_mode: Optional[str] = None,
    ) -> dict:
        """
        動態更新授權設定

        可從 Dashboard 或 API 呼叫來即時變更設定，
        無需重啟後端。

        Args:
            navigator: 新的 Navigator 值
            auth_mode: 新的 AuthorizationMode 值

        Returns:
            更新結果
        """
        changes = []

        if navigator is not None:
            valid_navigators = ("openclaw", "internal", "none")
            if navigator not in valid_navigators:
                return {
                    "success": False,
                    "error": f"無效的 Navigator: {navigator}，有效值: {valid_navigators}",
                }
            old = config.AI_NAVIGATOR
            config.AI_NAVIGATOR = navigator
            changes.append({"field": "AI_NAVIGATOR", "from": old, "to": navigator})

        if auth_mode is not None:
            valid_modes = ("auto", "hitl", "monitor")
            if auth_mode not in valid_modes:
                return {
                    "success": False,
                    "error": f"無效的 AuthMode: {auth_mode}，有效值: {valid_modes}",
                }
            old = config.AUTHORIZATION_MODE
            config.AUTHORIZATION_MODE = auth_mode
            changes.append({"field": "AUTHORIZATION_MODE", "from": old, "to": auth_mode})

        if changes:
            bus.publish(
                "supervisor.settings_changed",
                {"changes": changes},
                source="auth_manager",
            )

            logger.info(f"🛡️ 授權設定已更新: {changes}")

        return {
            "success": True,
            "changes": changes,
            "current": {
                "navigator": config.AI_NAVIGATOR,
                "auth_mode": config.AUTHORIZATION_MODE,
            },
        }

    # ── 狀態查詢 ──────────────────────────────────────────────

    def get_status(self) -> dict:
        """取得 AuthorizationManager 的完整狀態"""
        return {
            "navigator": config.AI_NAVIGATOR,
            "auth_mode": config.AUTHORIZATION_MODE,
            "stats": {
                "total_processed": self._total_processed,
                "total_auto_executed": self._total_auto_executed,
                "total_queued": self._total_queued,
                "total_monitor_logged": self._total_monitor_logged,
                "total_blocked": self._total_blocked,
            },
            "proposal_queue": proposal_queue.get_stats(),
            "signal_generator_injected": self._signal_generator is not None,
        }


# ═══════════════════════════════════════════════════════════════
# 全域單例
# ═══════════════════════════════════════════════════════════════
auth_manager = AuthorizationManager()
