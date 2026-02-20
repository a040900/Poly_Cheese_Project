"""
🧪 Phase 4 Supervisor 模組整合測試
驗證 Proposal Queue + Authorization Manager 的基本功能
"""
import sys
sys.path.insert(0, ".")

from app.supervisor.proposal_queue import proposal_queue, Proposal, ProposalStatus
from app.supervisor.authorization import auth_manager
from app import config

print("=" * 60)
print("🧪 Phase 4 Supervisor Module Integration Test")
print("=" * 60)

# ── Test 1: Config 設定確認 ──────────────────────────────────
print("\n📋 T1: Config 設定確認")
assert hasattr(config, "AI_NAVIGATOR"), "缺少 AI_NAVIGATOR"
assert hasattr(config, "AUTHORIZATION_MODE"), "缺少 AUTHORIZATION_MODE"
assert hasattr(config, "PROPOSAL_QUEUE_CONFIG"), "缺少 PROPOSAL_QUEUE_CONFIG"
print(f"  AI_NAVIGATOR: {config.AI_NAVIGATOR}")
print(f"  AUTHORIZATION_MODE: {config.AUTHORIZATION_MODE}")
print(f"  PROPOSAL_QUEUE_CONFIG: {config.PROPOSAL_QUEUE_CONFIG}")
print("  ✅ 全部通過")

# ── Test 2: ProposalQueue 基本操作 ───────────────────────────
print("\n📋 T2: ProposalQueue 基本操作")

# 建立提案
p = proposal_queue.create(
    advice_data={
        "action": "SWITCH_MODE",
        "recommended_mode": "conservative",
        "confidence": 75,
        "risk_level": "MEDIUM",
        "reasoning": "Market is choppy, recommend conservative mode.",
    },
    source="internal",
)
assert p.status == ProposalStatus.PENDING, f"應為 PENDING，實際: {p.status}"
assert p.priority.value == "normal", f"應為 normal，實際: {p.priority.value}"
assert p.action == "SWITCH_MODE"
assert p.confidence == 75
print(f"  建立提案: ID={p.id}, Status={p.status.value}, Priority={p.priority.value}")
print(f"  Pending count: {len(proposal_queue.get_pending())}")
print("  ✅ 建立提案通過")

# 核准提案
result = proposal_queue.approve(p.id, note="Test approve")
assert result["success"], f"核准失敗: {result}"
assert p.status == ProposalStatus.APPROVED
print(f"  核准結果: success={result['success']}")
print(f"  Pending after approve: {len(proposal_queue.get_pending())}")
print(f"  History count: {len(proposal_queue.get_history())}")
print("  ✅ 核准提案通過")

# ── Test 3: 拒絕提案 ────────────────────────────────────────
print("\n📋 T3: 拒絕提案")
p2 = proposal_queue.create(
    advice_data={
        "action": "SWITCH_MODE",
        "recommended_mode": "aggressive",
        "confidence": 50,
        "risk_level": "LOW",
        "reasoning": "Test reject",
    },
    source="api",
)
result = proposal_queue.reject(p2.id, note="不同意切換到積極模式")
assert result["success"]
assert p2.status == ProposalStatus.REJECTED
print(f"  拒絕結果: success={result['success']}")
print("  ✅ 拒絕提案通過")

# ── Test 4: 緊急安全閥 ──────────────────────────────────────
print("\n📋 T4: 緊急安全閥測試")
p3 = proposal_queue.create(
    advice_data={
        "action": "PAUSE_TRADING",
        "recommended_mode": "defensive",
        "confidence": 98,
        "risk_level": "CRITICAL",
        "reasoning": "Emergency: crash detected",
    },
    source="internal",
)
assert p3.status == ProposalStatus.AUTO_APPROVED, f"應被自動放行，實際: {p3.status}"
print(f"  緊急提案: ID={p3.id}, Status={p3.status.value}")
print("  ✅ 緊急安全閥觸發正確")

# ── Test 5: 非緊急不觸發安全閥 ──────────────────────────────
print("\n📋 T5: 非緊急提案不觸發安全閥")
p4 = proposal_queue.create(
    advice_data={
        "action": "SWITCH_MODE",
        "recommended_mode": "aggressive",
        "confidence": 98,
        "risk_level": "LOW",
        "reasoning": "高信心但非緊急操作",
    },
    source="internal",
)
assert p4.status == ProposalStatus.PENDING, f"不應被自動放行，實際: {p4.status}"
print(f"  普通高信心提案: ID={p4.id}, Status={p4.status.value}")
print("  ✅ 非緊急正確保持 PENDING")
proposal_queue.reject(p4.id)  # 清理

# ── Test 6: Navigator 阻擋測試 ──────────────────────────────
print("\n📋 T6: Navigator 阻擋測試 (Navigator=internal, Source=openclaw)")
original_mode = config.AUTHORIZATION_MODE
config.AUTHORIZATION_MODE = "auto"  # 先設為 auto 避免進入佇列

blocked = auth_manager.process_advice(
    advice_data={
        "action": "SWITCH_MODE",
        "recommended_mode": "aggressive",
        "confidence": 80,
        "risk_level": "LOW",
        "reasoning": "test from openclaw",
    },
    source="openclaw",
)
assert blocked["status"] == "blocked", f"應被阻擋，實際: {blocked['status']}"
print(f"  Result status: {blocked['status']}")
print(f"  Reason: {blocked['reason']}")
print("  ✅ Navigator 阻擋正確")

config.AUTHORIZATION_MODE = original_mode  # 還原

# ── Test 7: None Navigator 全部阻擋 ─────────────────────────
print("\n📋 T7: None Navigator 全部阻擋")
config.AI_NAVIGATOR = "none"
blocked2 = auth_manager.process_advice(
    advice_data={
        "action": "HOLD",
        "recommended_mode": "balanced",
        "confidence": 90,
        "risk_level": "LOW",
        "reasoning": "test",
    },
    source="internal",
)
assert blocked2["status"] == "blocked"
print(f"  Result status: {blocked2['status']}")
print("  ✅ None Navigator 正確阻擋所有 AI")
config.AI_NAVIGATOR = "internal"  # 還原

# ── Test 8: HITL 模式 → 進入佇列 ────────────────────────────
print("\n📋 T8: HITL 模式 → 提案進入佇列")
config.AUTHORIZATION_MODE = "hitl"
hitl_result = auth_manager.process_advice(
    advice_data={
        "action": "SWITCH_MODE",
        "recommended_mode": "conservative",
        "confidence": 70,
        "risk_level": "MEDIUM",
        "reasoning": "test HITL mode",
    },
    source="internal",
)
assert hitl_result["status"] == "queued", f"應進入佇列，實際: {hitl_result['status']}"
print(f"  Result status: {hitl_result['status']}")
print(f"  Proposal ID: {hitl_result['proposal_id']}")
print(f"  Priority: {hitl_result['priority']}")
print("  ✅ HITL 模式正確建立提案")
proposal_queue.reject(hitl_result["proposal_id"])  # 清理

# ── Test 9: MONITOR 模式 → 僅記錄 ───────────────────────────
print("\n📋 T9: MONITOR 模式 → 僅記錄")
config.AUTHORIZATION_MODE = "monitor"
monitor_result = auth_manager.process_advice(
    advice_data={
        "action": "SWITCH_MODE",
        "recommended_mode": "aggressive",
        "confidence": 85,
        "risk_level": "LOW",
        "reasoning": "test monitor mode",
    },
    source="internal",
)
assert monitor_result["status"] == "monitored"
print(f"  Result status: {monitor_result['status']}")
print(f"  Note: {monitor_result['note']}")
print("  ✅ MONITOR 模式正確僅記錄")
config.AUTHORIZATION_MODE = "hitl"  # 還原

# ── Test 10: 動態設定更新 ────────────────────────────────────
print("\n📋 T10: 動態設定更新")
update_result = auth_manager.update_settings(
    navigator="openclaw",
    auth_mode="auto",
)
assert update_result["success"]
assert config.AI_NAVIGATOR == "openclaw"
assert config.AUTHORIZATION_MODE == "auto"
print(f"  Changes: {update_result['changes']}")

# 無效設定
bad_result = auth_manager.update_settings(navigator="yolo_ai")
assert not bad_result["success"]
print(f"  Invalid test: {bad_result['error']}")

# 還原
config.AI_NAVIGATOR = "internal"
config.AUTHORIZATION_MODE = "hitl"
print("  ✅ 動態設定更新通過")

# ── Test 11: ProposalQueue 統計 ──────────────────────────────
print("\n📋 T11: 統計資訊")
stats = proposal_queue.get_stats()
print(f"  {stats}")
auth_status = auth_manager.get_status()
print(f"  Auth stats: {auth_status['stats']}")
print("  ✅ 統計正確")

# ── 總結 ─────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("🎉 全部 11 項測試通過！Phase 4 Supervisor 模組功能正常！")
print("=" * 60)
