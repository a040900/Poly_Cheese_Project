"""
🧀 CheeseDog - 元件狀態機 (步驟 10)
借鏡 NautilusTrader ComponentState 設計，為每個元件提供統一的生命週期管理。

狀態流轉:
    INITIALIZING → READY → RUNNING → STOPPED
                            ↓
                        DEGRADED (可自動恢復)
                            ↓
                        FAULTED  (需手動介入)
"""

from enum import Enum
import time
import logging
from typing import Optional

logger = logging.getLogger("cheesedog.core.state")


class ComponentState(Enum):
    """元件生命週期狀態"""
    INITIALIZING = "INITIALIZING"   # 初始化中（載入設定、建立連線）
    READY = "READY"                 # 就緒，等待啟動
    RUNNING = "RUNNING"             # 正常運行中
    STOPPED = "STOPPED"             # 已停止
    DEGRADED = "DEGRADED"           # 降級（延遲過高、部分數據缺失）
    FAULTED = "FAULTED"             # 故障（連線中斷、致命錯誤）

    def __str__(self):
        return self.value


# 合法狀態轉換表
_VALID_TRANSITIONS = {
    ComponentState.INITIALIZING: {ComponentState.READY, ComponentState.FAULTED},
    ComponentState.READY:        {ComponentState.RUNNING, ComponentState.STOPPED, ComponentState.FAULTED},
    ComponentState.RUNNING:      {ComponentState.STOPPED, ComponentState.DEGRADED, ComponentState.FAULTED},
    ComponentState.DEGRADED:     {ComponentState.RUNNING, ComponentState.STOPPED, ComponentState.FAULTED},
    ComponentState.FAULTED:      {ComponentState.STOPPED, ComponentState.INITIALIZING},
    ComponentState.STOPPED:      {ComponentState.INITIALIZING},
}


class Component:
    """
    帶狀態機的元件基類

    所有 DataFeed、策略引擎、模擬器等模組均繼承此類，
    獲得統一的狀態追蹤能力。
    """

    def __init__(self, name: str):
        self._name = name
        self._state = ComponentState.INITIALIZING
        self._state_changed_at = time.time()
        self._error_message: Optional[str] = None
        self._logger = logging.getLogger(f"cheesedog.{name}")

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> ComponentState:
        return self._state

    @property
    def state_info(self) -> dict:
        """取得元件狀態摘要（供 Dashboard 顯示）"""
        return {
            "name": self._name,
            "state": self._state.value,
            "since": self._state_changed_at,
            "error": self._error_message,
        }

    def _transition_to(self, new_state: ComponentState, reason: str = ""):
        """執行狀態轉換（附合法性檢查）"""
        valid = _VALID_TRANSITIONS.get(self._state, set())
        if new_state not in valid:
            self._logger.warning(
                f"⚠️ 非法狀態轉換: {self._state} → {new_state} (reason: {reason})"
            )
            return

        old = self._state
        self._state = new_state
        self._state_changed_at = time.time()

        if new_state == ComponentState.FAULTED:
            self._error_message = reason or "Unknown fault"
        elif new_state == ComponentState.RUNNING:
            self._error_message = None

        self._logger.info(f"🔄 [{self._name}] {old} → {new_state}"
                          + (f" ({reason})" if reason else ""))

    def set_ready(self):
        self._transition_to(ComponentState.READY, "初始化完成")

    def set_running(self):
        self._transition_to(ComponentState.RUNNING, "開始運行")

    def set_stopped(self):
        self._transition_to(ComponentState.STOPPED, "已停止")

    def set_degraded(self, reason: str = "效能降級"):
        self._transition_to(ComponentState.DEGRADED, reason)

    def set_faulted(self, reason: str = "元件故障"):
        self._error_message = reason
        self._transition_to(ComponentState.FAULTED, reason)

    def is_healthy(self) -> bool:
        """判斷元件是否健康（RUNNING 或 DEGRADED 視為可用）"""
        return self._state in (ComponentState.RUNNING, ComponentState.DEGRADED)
