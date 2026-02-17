
import sys
import os

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import db

def check_snapshots():
    try:
        snapshots = db.get_recent_snapshots(1)
        # Hack to get count if not exposed methods
        # Actually looking at backtester.py, it uses db.get_recent_snapshots(limit)
        # Let's just try to fetch some
        print(f"Successfully fetched {len(snapshots)} snapshots.")
        
        # Try to count total
        with db.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM market_snapshots")
            count = cursor.fetchone()[0]
            print(f"Total market_snapshots in DB: {count}")
            
    except Exception as e:
        print(f"Error checking DB: {e}")

if __name__ == "__main__":
    check_snapshots()
