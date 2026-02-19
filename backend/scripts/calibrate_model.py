import sys
import os
import sqlite3
import pandas as pd
import numpy as np
import talib
from itertools import product
import logging
import json


# Setup path to import app modules
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
sys.path.append(os.path.join(project_root, 'backend'))

# Configure Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Use absolute path to avoid ambiguity
DB_PATH = os.path.join(project_root, 'data', 'marketprice_(1).db')

def load_and_prep_data(db_path):
    """Load data from SQLite and resample to 1-minute candles."""
    logger.info(f"📂 Loading DB from: {db_path}")
    
    if not os.path.exists(db_path):
        logger.error(f"❌ Database not found: {db_path}")
        return None

    try:
        conn = sqlite3.connect(db_path)
        
        # Check columns first
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(market_history)")
        columns_info = cursor.fetchall()
        columns = [info[1] for info in columns_info]
        logger.info(f"📋 Table 'market_history' Columns: {columns}")
        
        # Load all data using * to avoid column name errors
        query = "SELECT * FROM market_history ORDER BY timestamp ASC"
        df = pd.read_sql(query, conn)
        conn.close()
        
        # Convert timestamp to datetime
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='s')
        df.set_index('datetime', inplace=True)
        
        # Resample to 1-minute candles
        # OHLC for BTC + Option Prices
        agg_dict = {
            'btc_price': 'ohlc',
            'pm_up_price': 'last',
            'pm_down_price': 'last'
        }
        
        # Hard check for columns
        if 'pm_up_price' not in df.columns:
            logger.error(f"FATAL: pm_up_price missing from dataframe columns: {df.columns.tolist()}")
            return None
        
        df_1m = df.resample('1min').agg(agg_dict)
        
        # Flatten columns
        df_1m.columns = ['_'.join(str(c) for c in col).strip() if isinstance(col, tuple) else str(col) for col in df_1m.columns.values]
        
        logger.info(f"Flattened Columns: {df_1m.columns.tolist()}")

        # Rename
        rename_map = {
            'btc_price_open': 'open',
            'btc_price_high': 'high',
            'btc_price_low': 'low',
            'btc_price_close': 'close',
        }
        
        # Dynamic mapping for option prices
        for col in df_1m.columns:
            if 'pm_up' in col:
                rename_map[col] = 'up_price'
            elif 'pm_down' in col:
                rename_map[col] = 'down_price'
        
        logger.info(f"Rename Map: {rename_map}")
        
        df_1m.rename(columns=rename_map, inplace=True)
        
        # Final check
        if 'up_price' not in df_1m.columns:
            logger.error(f"❌ Failed to map up_price! Available: {df_1m.columns.tolist()}")
            # Last ditch mock
            df_1m['up_price'] = 0.5
            df_1m['down_price'] = 0.5

        # Drop NaNs (gaps in data)
        df_1m.dropna(inplace=True)
        
        return df_1m

    except Exception as e:
        logger.error(f"❌ Error loading data: {e}", exc_info=True)
        return None

def calc_signals(df, weights):
    """
    Simulate signal generation based on weights.
    """
    close = df['close'].values
    
    # RSI (14)
    rsi = talib.RSI(close, timeperiod=14)
    # Score: (50 - RSI) * 2
    rsi_score = (50 - rsi) * 2
    
    # EMA Cross (5 vs 20)
    ema5 = talib.EMA(close, timeperiod=5)
    ema20 = talib.EMA(close, timeperiod=20)
    # Binary score
    ema_score = np.where(ema5 > ema20, 50, -50)
    
    # MACD
    macd, signal, hist = talib.MACD(close)
    # Binary score
    macd_score = np.where(hist > 0, 50, -50)
    
    # Weighted Sum
    total_score = np.zeros_like(close)
    total_score = total_score + np.nan_to_num(rsi_score) * weights['rsi'] / 10.0
    total_score = total_score + np.nan_to_num(ema_score) * weights['ema'] / 10.0
    total_score = total_score + np.nan_to_num(macd_score) * weights['macd'] / 10.0
    
    # Determine Signal
    threshold = 40
    signals = np.full_like(close, 0)
    signals = np.where(total_score > threshold, 1, signals)
    signals = np.where(total_score < -threshold, -1, signals)
    
    return signals

def run_backtest(df, signals):
    """
    Simple Vectorized Backtest
    """
    balance = 1000.0
    position = 0
    entry_price = 0.0
    
    trades = 0
    wins = 0
    
    up_prices = df['up_price'].values
    down_prices = df['down_price'].values
    
    for i in range(len(signals)):
        sig = signals[i]
        price_up = up_prices[i]
        price_down = down_prices[i]
        
        if i == 0: continue
        
        # Close positions
        if position == 1 and sig == -1: # Long UP, Signal Sell
            pnl = (price_up - entry_price) * 100
            balance += pnl
            position = 0
            trades += 1
            if pnl > 0: wins += 1
            
        elif position == -1 and sig == 1: # Short UP (Long DOWN), Signal Buy
            pnl = (price_down - entry_price) * 100
            balance += pnl
            position = 0
            trades += 1
            if pnl > 0: wins += 1

        # Open positions
        if position == 0:
            if sig == 1: # Buy UP
                position = 1
                entry_price = price_up
            elif sig == -1: # Buy DOWN
                position = -1
                entry_price = price_down
                
    return {
        'final_balance': balance,
        'trades': trades,
        'win_rate': (wins / trades * 100) if trades > 0 else 0,
        'return': (balance - 1000) / 1000 * 100
    }

def calibrate():
    logger.info("🚀 Starting Model Calibration...")
    df = load_and_prep_data(DB_PATH)
    
    if df is None:
        return
    
    logger.info(f"📊 Loaded {len(df)} 1-minute candles from {df.index.min()} to {df.index.max()}")
    
    # Simple Grid Search
    weight_ranges = {
        'rsi': [3, 5, 8],
        'ema': [5, 8, 12],
        'macd': [5, 8, 10]
    }
    
    keys, values = zip(*weight_ranges.items())
    combinations = [dict(zip(keys, v)) for v in product(*values)]
    
    logger.info(f"🧪 Testing {len(combinations)} parameter combinations...")
    
    results = []
    
    for i, w in enumerate(combinations):
        signals = calc_signals(df, w)
        res = run_backtest(df, signals)
        res['weights'] = w
        results.append(res)
        
        if i % 10 == 0:
            print(f".", end="", flush=True) # Progress
            
    print("\n")
    
    if not results:
        logger.error("No results generated.")
        return

    best_res = max(results, key=lambda x: x['final_balance'])
    
    logger.info("🏆 Best Parameters Found:")
    logger.info(f"Weights: {best_res['weights']}")
    logger.info(f"Final Balance: ${best_res['final_balance']:.2f}")
    logger.info(f"Trades: {best_res['trades']}")
    logger.info(f"Win Rate: {best_res['win_rate']:.1f}%")
    
    # Save to JSON
    output_file = os.path.join(project_root, 'data', 'calibration_result.json')
    with open(output_file, 'w') as f:
        json.dump(best_res, f, indent=2)
    logger.info(f"💾 Results saved to {output_file}")

if __name__ == "__main__":
    calibrate()
