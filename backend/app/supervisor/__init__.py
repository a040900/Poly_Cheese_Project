"""
🧀 CheeseDog - Supervisor Module (Phase 4)
監督者模組：提案佇列 (Proposal Queue) + 授權管理員 (Authorization Manager)

本模組實現「控制平面」的權限管控，確保 AI 建議在適當的審核流程下執行。
「資料平面」(讀取 API) 不受影響，永遠開放。
"""

__module_name__ = "supervisor"
__version__ = "1.0.0"
