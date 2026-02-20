"""
🧀 CheeseDog - 提案佇列 (Proposal Queue) — Phase 4: Hybrid Intelligence

在 HITL (Human-in-the-Loop) 模式下，AI 的操作建議不會直接執行，
而是被封裝成「提案 (Proposal)」進入此佇列等待人類審核。

提案生命週期 (State Machine):
    PENDING  → APPROVED  (人類核准)
    PENDING  → REJECTED  (人類拒絕)
    PENDING  → EXPIRED   (超時未處理)
    PENDING  → AUTO_APPROVED (緊急安全閥自動放行)

設計原則:
    - 與 LLMAdvisor 完全解耦：佇列只管提案的生命週期，不碰交易邏輯。
    - 透過 MessageBus 發佈事件：其他模組可訂閱 supervisor.* 事件做二次處理。
    - 安全閥 (Emergency Override): 在極端行情下，即使是 HITL 模式，
      高信心度的 PAUSE_TRADING 指令仍能自動放行，避免人類不在場時的損失。
"""

import time
import uuid
import logging
import threading
from enum import Enum
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Any, Callable

from app import config
from app.core.event_bus import bus

logger = logging.getLogger("cheesedog.supervisor.proposal")


# ═══════════════════════════════════════════════════════════════
# 提案狀態列舉
# ═══════════════════════════════════════════════════════════════
class ProposalStatus(str, Enum):
    """提案狀態"""
    PENDING = "pending"             # 等待審核
    APPROVED = "approved"           # 已核准
    REJECTED = "rejected"           # 已拒絕
    EXPIRED = "expired"             # 已過期
    AUTO_APPROVED = "auto_approved" # 緊急安全閥自動放行


class ProposalPriority(str, Enum):
    """提案優先級"""
    LOW = "low"           # 一般調參、觀察建議
    NORMAL = "normal"     # 模式切換、權重調整
    HIGH = "high"         # 風險警示、強烈建議
    CRITICAL = "critical" # 緊急停損、崩盤防護


# ═══════════════════════════════════════════════════════════════
# 提案資料結構
# ═══════════════════════════════════════════════════════════════
@dataclass
class Proposal:
    """
    提案物件

    封裝一筆來自 AI 的操作建議，包含完整的上下文metadata，
    以便人類審核者做出知情的決策。
    """
    # ── 識別 ──────────────────────────────────────────────────
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    status: ProposalStatus = ProposalStatus.PENDING

    # ── 來源 ──────────────────────────────────────────────────
    source: str = ""               # "internal" | "openclaw" | "unknown"
    navigator: str = ""            # AI_NAVIGATOR 值

    # ── 內容 (原始 AI 建議) ───────────────────────────────────
    advice_data: Dict[str, Any] = field(default_factory=dict)
    action: str = ""               # HOLD | SWITCH_MODE | PAUSE_TRADING | CONTINUE
    recommended_mode: str = ""
    confidence: float = 0.0
    risk_level: str = "MEDIUM"     # LOW | MEDIUM | HIGH | CRITICAL
    reasoning: str = ""
    analysis: str = ""

    # ── 優先級 ────────────────────────────────────────────────
    priority: ProposalPriority = ProposalPriority.NORMAL

    # ── 時間戳 ────────────────────────────────────────────────
    created_at: float = field(default_factory=time.time)
    resolved_at: Optional[float] = None
    expires_at: float = 0.0        # 建構時計算

    # ── 審核結果 ──────────────────────────────────────────────
    resolved_by: str = ""          # "human" | "system" | "emergency"
    resolution_note: str = ""      # 審核者的備註

    def __post_init__(self):
        """建構後自動計算過期時間與優先級"""
        if self.expires_at == 0.0:
            expiry = config.PROPOSAL_QUEUE_CONFIG.get("expiry_seconds", 600)
            self.expires_at = self.created_at + expiry

        # 根據 advice_data 自動填充欄位
        if self.advice_data and not self.action:
            self.action = self.advice_data.get("action", "HOLD")
            self.recommended_mode = self.advice_data.get("recommended_mode", "")
            self.confidence = self.advice_data.get("confidence", 0.0)
            self.risk_level = self.advice_data.get("risk_level", "MEDIUM")
            self.reasoning = self.advice_data.get("reasoning", "")
            self.analysis = self.advice_data.get("analysis", "")

        # 自動推算優先級
        self.priority = self._infer_priority()

    def _infer_priority(self) -> ProposalPriority:
        """根據建議內容推算優先級"""
        if self.risk_level == "CRITICAL" or self.action == "PAUSE_TRADING":
            return ProposalPriority.CRITICAL
        if self.risk_level == "HIGH" or self.confidence >= 85:
            return ProposalPriority.HIGH
        if self.action in ("SWITCH_MODE",) or self.confidence >= 60:
            return ProposalPriority.NORMAL
        return ProposalPriority.LOW

    @property
    def is_expired(self) -> bool:
        """是否已過期"""
        return time.time() > self.expires_at

    @property
    def is_pending(self) -> bool:
        """是否在等待審核"""
        return self.status == ProposalStatus.PENDING

    @property
    def remaining_seconds(self) -> float:
        """距離過期還剩多少秒"""
        return max(0.0, self.expires_at - time.time())

    def to_dict(self) -> dict:
        """轉為可序列化的字典"""
        d = asdict(self)
        d["status"] = self.status.value
        d["priority"] = self.priority.value
        d["is_expired"] = self.is_expired
        d["remaining_seconds"] = round(self.remaining_seconds, 1)
        return d


# ═══════════════════════════════════════════════════════════════
# 提案佇列管理器
# ═══════════════════════════════════════════════════════════════
class ProposalQueue:
    """
    提案佇列管理器

    負責提案的完整生命週期管理：
    1. 建立提案 (create)
    2. 核准/拒絕提案 (approve / reject)
    3. 自動過期檢查 (expire_stale)
    4. 緊急安全閥 (emergency override)
    5. 歷史查詢 (get_history)

    所有狀態變更都會透過 MessageBus 發佈事件。
    """

    def __init__(self):
        self._pending: Dict[str, Proposal] = {}   # id → Proposal
        self._history: List[Proposal] = []         # 已處理的提案
        self._lock = threading.Lock()

        # 統計
        self._stats = {
            "total_created": 0,
            "total_approved": 0,
            "total_rejected": 0,
            "total_expired": 0,
            "total_auto_approved": 0,
        }

        # 可註冊的回調：核准後自動執行
        self._on_approve_callback: Optional[Callable] = None

        logger.info("📋 ProposalQueue 已初始化")

    # ── 回調註冊 ──────────────────────────────────────────────

    def set_approve_callback(self, callback: Callable):
        """
        註冊「核准後」的回調函數。

        此回調將在提案被核准 (APPROVED / AUTO_APPROVED) 後觸發，
        用於將提案內容傳遞給 LLMAdvisor 執行。

        Args:
            callback: fn(proposal: Proposal) -> dict
        """
        self._on_approve_callback = callback
        logger.info(f"📋 已註冊核准回調: {getattr(callback, '__name__', repr(callback))}")

    # ── 建立提案 ──────────────────────────────────────────────

    def create(
        self,
        advice_data: dict,
        source: str = "unknown",
        navigator: str = "",
    ) -> Proposal:
        """
        建立新的提案

        Args:
            advice_data: 原始 AI 建議 (經過 LLMAdvisor 驗證後的)
            source: 來源標識  ("internal" | "openclaw" | "api")
            navigator: 當前 Navigator 設定值

        Returns:
            新建立的 Proposal 物件
        """
        proposal = Proposal(
            advice_data=advice_data,
            source=source,
            navigator=navigator or config.AI_NAVIGATOR,
        )

        with self._lock:
            # 容量檢查：如果佇列已滿，先清理最舊的
            max_size = config.PROPOSAL_QUEUE_CONFIG.get("max_queue_size", 50)
            if len(self._pending) >= max_size:
                self._evict_oldest()

            self._pending[proposal.id] = proposal
            self._stats["total_created"] += 1

        # 發佈事件
        bus.publish(
            "supervisor.proposal_created",
            proposal.to_dict(),
            source="proposal_queue",
        )

        logger.info(
            f"📋 新提案建立 | ID={proposal.id} | "
            f"Action={proposal.action} | "
            f"Priority={proposal.priority.value} | "
            f"Confidence={proposal.confidence}% | "
            f"Expires in {proposal.remaining_seconds:.0f}s"
        )

        # ── 緊急安全閥判斷 ────────────────────────────────────
        if self._should_emergency_approve(proposal):
            logger.warning(
                f"🚨 緊急安全閥觸發！提案 {proposal.id} 自動放行 | "
                f"Action={proposal.action} | Confidence={proposal.confidence}%"
            )
            self._resolve(
                proposal,
                ProposalStatus.AUTO_APPROVED,
                resolved_by="emergency",
                note="緊急安全閥: 高信心度保護性操作自動放行",
            )

        return proposal

    # ── 核准提案 ──────────────────────────────────────────────

    def approve(self, proposal_id: str, note: str = "") -> dict:
        """
        人類核准提案

        Args:
            proposal_id: 提案 ID
            note: 審核備註

        Returns:
            處理結果
        """
        with self._lock:
            proposal = self._pending.get(proposal_id)
            if not proposal:
                return {"success": False, "error": f"提案 {proposal_id} 不存在或已處理"}

            if proposal.is_expired:
                self._resolve(
                    proposal,
                    ProposalStatus.EXPIRED,
                    resolved_by="system",
                    note="嘗試核准時已過期",
                )
                return {"success": False, "error": f"提案 {proposal_id} 已過期"}

        result = self._resolve(
            proposal,
            ProposalStatus.APPROVED,
            resolved_by="human",
            note=note or "人類審核核准",
        )

        return {"success": True, "proposal": proposal.to_dict(), "apply_result": result}

    # ── 拒絕提案 ──────────────────────────────────────────────

    def reject(self, proposal_id: str, note: str = "") -> dict:
        """
        人類拒絕提案

        Args:
            proposal_id: 提案 ID
            note: 拒絕原因

        Returns:
            處理結果
        """
        with self._lock:
            proposal = self._pending.get(proposal_id)
            if not proposal:
                return {"success": False, "error": f"提案 {proposal_id} 不存在或已處理"}

        self._resolve(
            proposal,
            ProposalStatus.REJECTED,
            resolved_by="human",
            note=note or "人類審核拒絕",
        )

        return {"success": True, "proposal": proposal.to_dict()}

    # ── 過期清理 ──────────────────────────────────────────────

    def expire_stale(self) -> int:
        """
        清理過期的提案

        Returns:
            清理的提案數量
        """
        expired_count = 0
        with self._lock:
            expired_ids = [
                pid for pid, p in self._pending.items()
                if p.is_expired
            ]

        for pid in expired_ids:
            proposal = self._pending.get(pid)
            if proposal:
                self._resolve(
                    proposal,
                    ProposalStatus.EXPIRED,
                    resolved_by="system",
                    note="超時未審核自動過期",
                )
                expired_count += 1

        if expired_count > 0:
            logger.info(f"🕐 清理 {expired_count} 筆過期提案")

        return expired_count

    # ── 查詢方法 ──────────────────────────────────────────────

    def get_pending(self) -> List[dict]:
        """
        取得所有待審核的提案

        Returns:
            提案列表 (按優先級排序: CRITICAL > HIGH > NORMAL > LOW)
        """
        # 先清理過期的
        self.expire_stale()

        priority_order = {
            ProposalPriority.CRITICAL: 0,
            ProposalPriority.HIGH: 1,
            ProposalPriority.NORMAL: 2,
            ProposalPriority.LOW: 3,
        }

        with self._lock:
            pending_list = [
                p.to_dict() for p in self._pending.values()
                if p.is_pending
            ]

        # 按優先級排序
        pending_list.sort(
            key=lambda x: (
                priority_order.get(ProposalPriority(x["priority"]), 99),
                x["created_at"],
            )
        )

        return pending_list

    def get_proposal(self, proposal_id: str) -> Optional[dict]:
        """取得單一提案的詳情"""
        # 先查 pending
        proposal = self._pending.get(proposal_id)
        if proposal:
            return proposal.to_dict()

        # 再查 history
        for p in reversed(self._history):
            if p.id == proposal_id:
                return p.to_dict()

        return None

    def get_history(self, limit: int = 50) -> List[dict]:
        """取得已處理的提案歷史"""
        return [p.to_dict() for p in reversed(self._history[-limit:])]

    def get_stats(self) -> dict:
        """取得佇列統計"""
        return {
            "pending_count": len(self._pending),
            "history_count": len(self._history),
            **self._stats,
        }

    # ── 內部方法 ──────────────────────────────────────────────

    def _resolve(
        self,
        proposal: Proposal,
        status: ProposalStatus,
        resolved_by: str = "",
        note: str = "",
    ) -> Optional[dict]:
        """
        解決一筆提案 (核准 / 拒絕 / 過期)

        Args:
            proposal: 提案物件
            status: 目標狀態
            resolved_by: 解決者 ("human" | "system" | "emergency")
            note: 備註

        Returns:
            如果是核准/自動核准並有回調，回傳回調結果
        """
        proposal.status = status
        proposal.resolved_at = time.time()
        proposal.resolved_by = resolved_by
        proposal.resolution_note = note

        # 從 pending 移到 history
        with self._lock:
            self._pending.pop(proposal.id, None)
            self._history.append(proposal)

            # 清理過多的歷史
            max_history = config.PROPOSAL_QUEUE_CONFIG.get("history_retention", 200)
            if len(self._history) > max_history:
                self._history = self._history[-max_history:]

        # 更新統計
        stat_key = f"total_{status.value}"
        if stat_key in self._stats:
            self._stats[stat_key] += 1

        # 發佈事件
        bus.publish(
            "supervisor.proposal_resolved",
            {
                "proposal": proposal.to_dict(),
                "status": status.value,
                "resolved_by": resolved_by,
            },
            source="proposal_queue",
        )

        logger.info(
            f"📋 提案解決 | ID={proposal.id} | "
            f"Status={status.value} | "
            f"ResolvedBy={resolved_by} | "
            f"Note={note}"
        )

        # 如果是核准/自動核准，觸發回調去執行建議
        apply_result = None
        if status in (ProposalStatus.APPROVED, ProposalStatus.AUTO_APPROVED):
            if self._on_approve_callback:
                try:
                    apply_result = self._on_approve_callback(proposal)
                    logger.info(
                        f"✅ 核准回調執行完畢 | ID={proposal.id} | "
                        f"Result={apply_result}"
                    )
                except Exception as e:
                    logger.error(f"❌ 核准回調執行失敗 | ID={proposal.id} | Error={repr(e)}")
                    apply_result = {"error": str(e)}

        return apply_result

    def _should_emergency_approve(self, proposal: Proposal) -> bool:
        """
        判斷是否觸發緊急安全閥

        條件 (全部滿足):
        1. 信心度 >= emergency_auto_approve_confidence (預設 95)
        2. action 在 emergency_actions 白名單中
           或 risk_level == "CRITICAL"
        """
        pq_cfg = config.PROPOSAL_QUEUE_CONFIG
        min_confidence = pq_cfg.get("emergency_auto_approve_confidence", 95)
        emergency_actions = pq_cfg.get("emergency_actions", ["PAUSE_TRADING"])

        if proposal.confidence < min_confidence:
            return False

        if proposal.action in emergency_actions:
            return True

        if proposal.risk_level == "CRITICAL":
            return True

        return False

    def _evict_oldest(self):
        """驅逐最舊的待處理提案 (FIFO)"""
        if not self._pending:
            return

        # 找到建立時間最早的
        oldest_id = min(self._pending, key=lambda pid: self._pending[pid].created_at)
        oldest = self._pending[oldest_id]

        logger.warning(f"⚠️ 佇列已滿，驅逐最舊提案 | ID={oldest_id}")
        self._resolve(
            oldest,
            ProposalStatus.EXPIRED,
            resolved_by="system",
            note="佇列容量已滿，自動清除最舊的未處理提案",
        )


# ═══════════════════════════════════════════════════════════════
# 全域單例
# ═══════════════════════════════════════════════════════════════
proposal_queue = ProposalQueue()
