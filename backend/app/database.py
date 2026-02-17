"""
🧀 CheeseDog - 資料庫管理模組
使用 SQLite 儲存所有系統運行數據。
"""

import sqlite3
import json
import time
import logging
from pathlib import Path
from contextlib import contextmanager
from typing import Optional, List, Dict, Any

from app.config import DB_PATH

logger = logging.getLogger("cheesedog.database")


class Database:
    """SQLite 資料庫管理器"""

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化資料庫 Schema"""
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
            logger.info(f"資料庫已初始化: {self.db_path}")

    @contextmanager
    def _connect(self):
        """取得資料庫連線的 Context Manager"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── 市場數據操作 ──────────────────────────────────────────

    def save_kline(self, symbol: str, interval: str, data: dict):
        """儲存 K 線數據"""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO klines
                   (symbol, interval, open_time, open, high, low, close, volume)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (symbol, interval, data["t"], data["o"], data["h"],
                 data["l"], data["c"], data["v"])
            )

    def save_market_snapshot(self, data: dict):
        """儲存市場快照（多源數據合併）"""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO market_snapshots
                   (timestamp, btc_price, pm_up_price, pm_down_price,
                    chainlink_price, bias_score, signal, trading_mode,
                    indicators_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (data.get("timestamp", time.time()),
                 data.get("btc_price"),
                 data.get("pm_up_price"),
                 data.get("pm_down_price"),
                 data.get("chainlink_price"),
                 data.get("bias_score"),
                 data.get("signal"),
                 data.get("trading_mode"),
                 json.dumps(data.get("indicators", {})))
            )

    def get_recent_snapshots(self, limit: int = 100) -> List[Dict]:
        """取得最近的市場快照"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM market_snapshots
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ── 交易記錄操作 ──────────────────────────────────────────

    def save_trade(self, trade: dict):
        """儲存交易記錄（模擬或實盤）"""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO trades
                   (trade_type, direction, entry_time, entry_price,
                    exit_time, exit_price, quantity, pnl, fee,
                    signal_score, trading_mode, status, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (trade.get("trade_type", "simulation"),
                 trade.get("direction"),
                 trade.get("entry_time"),
                 trade.get("entry_price"),
                 trade.get("exit_time"),
                 trade.get("exit_price"),
                 trade.get("quantity"),
                 trade.get("pnl"),
                 trade.get("fee"),
                 trade.get("signal_score"),
                 trade.get("trading_mode"),
                 trade.get("status", "open"),
                 json.dumps(trade.get("metadata", {})))
            )
            return conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    def update_trade(self, trade_id: int, updates: dict):
        """更新交易記錄"""
        with self._connect() as conn:
            fields = []
            values = []
            for key, val in updates.items():
                if key == "metadata":
                    fields.append("metadata_json = ?")
                    values.append(json.dumps(val))
                else:
                    fields.append(f"{key} = ?")
                    values.append(val)
            values.append(trade_id)
            conn.execute(
                f"UPDATE trades SET {', '.join(fields)} WHERE id = ?",
                values
            )

    def get_trades(self, trade_type: str = "simulation",
                   limit: int = 50) -> List[Dict]:
        """取得交易記錄"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM trades
                   WHERE trade_type = ?
                   ORDER BY entry_time DESC LIMIT ?""",
                (trade_type, limit)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_open_trades(self, trade_type: str = "simulation") -> List[Dict]:
        """取得未平倉交易"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM trades
                   WHERE trade_type = ? AND status = 'open'
                   ORDER BY entry_time DESC""",
                (trade_type,)
            ).fetchall()
            return [dict(row) for row in rows]

    def get_trade_stats(self, trade_type: str = "simulation") -> Dict:
        """取得交易統計"""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT
                     COUNT(*) as total_trades,
                     SUM(CASE WHEN pnl > 0 THEN 1 ELSE 0 END) as wins,
                     SUM(CASE WHEN pnl < 0 THEN 1 ELSE 0 END) as losses,
                     SUM(CASE WHEN pnl = 0 THEN 1 ELSE 0 END) as breakeven,
                     COALESCE(SUM(pnl), 0) as total_pnl,
                     COALESCE(AVG(pnl), 0) as avg_pnl,
                     COALESCE(MAX(pnl), 0) as best_trade,
                     COALESCE(MIN(pnl), 0) as worst_trade,
                     COALESCE(SUM(fee), 0) as total_fees
                   FROM trades
                   WHERE trade_type = ? AND status = 'closed'""",
                (trade_type,)
            ).fetchone()

            stats = dict(row)
            total = stats["wins"] + stats["losses"]
            stats["win_rate"] = (stats["wins"] / total * 100) if total > 0 else 0
            return stats

    # ── 信號記錄操作 ──────────────────────────────────────────

    def save_signal(self, signal: dict):
        """儲存交易信號"""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO signals
                   (timestamp, direction, score, confidence,
                    trading_mode, indicators_json, acted_on)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (signal.get("timestamp", time.time()),
                 signal.get("direction"),
                 signal.get("score"),
                 signal.get("confidence"),
                 signal.get("trading_mode"),
                 json.dumps(signal.get("indicators", {})),
                 signal.get("acted_on", False))
            )

    def get_recent_signals(self, limit: int = 50) -> List[Dict]:
        """取得最近的交易信號"""
        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM signals
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,)
            ).fetchall()
            return [dict(row) for row in rows]

    # ── LLM 建議記錄 ─────────────────────────────────────────

    def save_llm_advice(self, advice: dict):
        """儲存 LLM 建議"""
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO llm_advices
                   (timestamp, advice_type, recommended_mode,
                    reasoning, market_context_json, applied)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (advice.get("timestamp", time.time()),
                 advice.get("advice_type"),
                 advice.get("recommended_mode"),
                 advice.get("reasoning"),
                 json.dumps(advice.get("market_context", {})),
                 advice.get("applied", False))
            )

    # ── 安全密碼操作 ──────────────────────────────────────────

    def save_password(self, password_hash: str, expires_at: float):
        """儲存隨機密碼（加密雜湊）"""
        with self._connect() as conn:
            # 清理過期密碼
            conn.execute(
                "DELETE FROM security_passwords WHERE expires_at < ?",
                (time.time(),)
            )
            conn.execute(
                """INSERT INTO security_passwords
                   (password_hash, created_at, expires_at, used)
                   VALUES (?, ?, ?, 0)""",
                (password_hash, time.time(), expires_at)
            )

    def verify_password(self, password_hash: str) -> bool:
        """驗證密碼是否有效"""
        with self._connect() as conn:
            row = conn.execute(
                """SELECT id FROM security_passwords
                   WHERE password_hash = ?
                   AND expires_at > ?
                   AND used = 0""",
                (password_hash, time.time())
            ).fetchone()
            if row:
                conn.execute(
                    "UPDATE security_passwords SET used = 1 WHERE id = ?",
                    (row["id"],)
                )
                return True
            return False

    # ── 系統狀態 ──────────────────────────────────────────────

    def save_system_state(self, key: str, value: str):
        """儲存系統狀態"""
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO system_state (key, value, updated_at)
                   VALUES (?, ?, ?)""",
                (key, value, time.time())
            )

    def get_system_state(self, key: str) -> Optional[str]:
        """取得系統狀態"""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM system_state WHERE key = ?",
                (key,)
            ).fetchone()
            return row["value"] if row else None


# ═══════════════════════════════════════════════════════════════
# 資料庫 Schema
# ═══════════════════════════════════════════════════════════════
SCHEMA_SQL = """
-- K 線歷史數據
CREATE TABLE IF NOT EXISTS klines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    interval TEXT NOT NULL,
    open_time REAL NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume REAL NOT NULL,
    UNIQUE(symbol, interval, open_time)
);

-- 市場快照（多源整合數據）
CREATE TABLE IF NOT EXISTS market_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    btc_price REAL,
    pm_up_price REAL,
    pm_down_price REAL,
    chainlink_price REAL,
    bias_score REAL,
    signal TEXT,
    trading_mode TEXT,
    indicators_json TEXT
);

-- 交易記錄（模擬 & 實盤）
CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_type TEXT NOT NULL DEFAULT 'simulation',
    direction TEXT NOT NULL,
    entry_time REAL NOT NULL,
    entry_price REAL,
    exit_time REAL,
    exit_price REAL,
    quantity REAL,
    pnl REAL DEFAULT 0,
    fee REAL DEFAULT 0,
    signal_score REAL,
    trading_mode TEXT,
    status TEXT DEFAULT 'open',
    metadata_json TEXT
);

-- 交易信號歷史
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    direction TEXT NOT NULL,
    score REAL,
    confidence REAL,
    trading_mode TEXT,
    indicators_json TEXT,
    acted_on INTEGER DEFAULT 0
);

-- LLM 建議歷史
CREATE TABLE IF NOT EXISTS llm_advices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL NOT NULL,
    advice_type TEXT,
    recommended_mode TEXT,
    reasoning TEXT,
    market_context_json TEXT,
    applied INTEGER DEFAULT 0
);

-- 安全密碼（短期有效）
CREATE TABLE IF NOT EXISTS security_passwords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    password_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    used INTEGER DEFAULT 0
);

-- 系統狀態鍵值對
CREATE TABLE IF NOT EXISTS system_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at REAL
);

-- 建立索引以加速查詢
CREATE INDEX IF NOT EXISTS idx_klines_symbol_time
    ON klines(symbol, interval, open_time);
CREATE INDEX IF NOT EXISTS idx_snapshots_time
    ON market_snapshots(timestamp);
CREATE INDEX IF NOT EXISTS idx_trades_type_time
    ON trades(trade_type, entry_time);
CREATE INDEX IF NOT EXISTS idx_trades_status
    ON trades(trade_type, status);
CREATE INDEX IF NOT EXISTS idx_signals_time
    ON signals(timestamp);
CREATE INDEX IF NOT EXISTS idx_passwords_expiry
    ON security_passwords(expires_at, used);
"""


# 全域資料庫實例
db = Database()
