
import sqlite3
import logging
from pathlib import Path
import sys

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("db_migrate")

# 資料庫路徑 (假設在專案根目錄或 data 目錄)
DB_PATH = Path("cheesedog.db")

def migrate_db():
    if not DB_PATH.exists():
        logger.info(f"資料庫檔案 {DB_PATH} 不存在，將由主程式自動建立，無需遷移。")
        return

    logger.info(f"正在檢查資料庫 schema: {DB_PATH}")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    try:
        # 1. 檢查 trades 表是否存在
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trades'")
        if not cursor.fetchone():
            logger.info("trades 表不存在，跳過遷移。")
            return

        # 取得現有欄位
        cursor.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]
        
        # 2. 檢查並新增 trade_type 欄位
        if "trade_type" not in columns:
            logger.info("正在新增 trade_type 欄位...")
            cursor.execute("ALTER TABLE trades ADD COLUMN trade_type TEXT DEFAULT 'simulation'")
            # 更新現有資料為 simulation
            cursor.execute("UPDATE trades SET trade_type = 'simulation' WHERE trade_type IS NULL")
        else:
            logger.info("trade_type 欄位已存在。")

        # 3. 檢查並新增 metadata_json 欄位
        if "metadata_json" not in columns:
            logger.info("正在新增 metadata_json 欄位...")
            cursor.execute("ALTER TABLE trades ADD COLUMN metadata_json TEXT")
        else:
            logger.info("metadata_json 欄位已存在。")
            
        # 4. 檢查並新增 fee 欄位 (Phase 2 新增)
        if "fee" not in columns:
            logger.info("正在新增 fee 欄位...")
            cursor.execute("ALTER TABLE trades ADD COLUMN fee REAL DEFAULT 0")
        
        # 5. 檢查並新增 signal_score 欄位
        if "signal_score" not in columns:
            logger.info("正在新增 signal_score 欄位...")
            cursor.execute("ALTER TABLE trades ADD COLUMN signal_score REAL")

        # 6. 檢查並新增 trading_mode 欄位
        if "trading_mode" not in columns:
            logger.info("正在新增 trading_mode 欄位...")
            cursor.execute("ALTER TABLE trades ADD COLUMN trading_mode TEXT")

        conn.commit()
        logger.info("✅ 資料庫遷移完成！")
        
    except Exception as e:
        logger.error(f"❌ 遷移失敗: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_db()
