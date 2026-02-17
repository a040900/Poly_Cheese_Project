"""
🧀 CheeseDog - 隨機密碼驗證管理模組
用於高風險操作（如模擬倉轉實盤）的安全驗證機制。
"""

import time
import hashlib
import secrets
import logging
from typing import Optional, Tuple

from app import config
from app.database import db

logger = logging.getLogger("cheesedog.security")


class PasswordManager:
    """隨機密碼管理器"""

    def __init__(self):
        self._pending_password: Optional[str] = None
        self._pending_hash: Optional[str] = None
        self._expires_at: float = 0.0
        self._awaiting: bool = False

    def request_password(self) -> dict:
        """
        觸發密碼請求（前端呼叫此方法）

        Returns:
            {
                "awaiting": True,
                "message": "請口頭向 AI 說出「給我密碼」來獲取驗證密碼",
                "expires_in": 300
            }
        """
        self._awaiting = True
        logger.info("🔐 安全驗證已觸發，等待使用者口頭請求密碼")

        return {
            "awaiting": True,
            "message": "請口頭向 AI 說出「給我密碼」來獲取驗證密碼",
            "expires_in": config.PASSWORD_EXPIRY,
        }

    def generate_password(self) -> Tuple[str, float]:
        """
        生成隨機密碼（AI 接收到口頭請求後呼叫）

        Returns:
            (明文密碼, 過期時間戳)
        """
        # 生成安全的隨機密碼
        password = ''.join(
            secrets.choice('0123456789') for _ in range(config.PASSWORD_LENGTH)
        )

        # 計算雜湊
        password_hash = hashlib.sha256(password.encode()).hexdigest()

        # 設定過期時間
        expires_at = time.time() + config.PASSWORD_EXPIRY

        # 儲存到記憶體和資料庫
        self._pending_password = password
        self._pending_hash = password_hash
        self._expires_at = expires_at
        self._awaiting = False

        # 儲存到資料庫
        db.save_password(password_hash, expires_at)

        logger.info(f"🔑 已生成驗證密碼 (有效期 {config.PASSWORD_EXPIRY} 秒)")

        return password, expires_at

    def verify_password(self, input_password: str) -> dict:
        """
        驗證使用者輸入的密碼

        Args:
            input_password: 使用者輸入的密碼

        Returns:
            {"valid": bool, "message": str}
        """
        if not input_password:
            return {"valid": False, "message": "請輸入密碼"}

        # 計算輸入密碼的雜湊
        input_hash = hashlib.sha256(input_password.encode()).hexdigest()

        # 先檢查記憶體中的密碼
        if self._pending_hash and time.time() < self._expires_at:
            if input_hash == self._pending_hash:
                self._pending_password = None
                self._pending_hash = None
                self._expires_at = 0.0
                logger.info("✅ 安全驗證通過（記憶體驗證）")
                return {"valid": True, "message": "驗證通過！操作已授權。"}

        # 備用：從資料庫驗證
        if db.verify_password(input_hash):
            logger.info("✅ 安全驗證通過（資料庫驗證）")
            return {"valid": True, "message": "驗證通過！操作已授權。"}

        logger.warning("❌ 安全驗證失敗")
        return {"valid": False, "message": "密碼錯誤或已過期，請重新獲取密碼。"}

    def is_awaiting(self) -> bool:
        """是否正在等待使用者口頭請求密碼"""
        return self._awaiting

    def get_status(self) -> dict:
        """取得密碼管理器狀態"""
        has_pending = (
            self._pending_hash is not None
            and time.time() < self._expires_at
        )
        remaining = max(0, self._expires_at - time.time()) if has_pending else 0

        return {
            "awaiting": self._awaiting,
            "has_pending_password": has_pending,
            "remaining_seconds": round(remaining),
        }


# 全域密碼管理器實例
password_manager = PasswordManager()
