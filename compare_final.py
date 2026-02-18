import re
import sqlite3
import pandas as pd

def parse_simul_log(filepath):
    trades = {}
    print(f"Parsing Simul Log: {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in lines:
            # Format: 🟢 043260(성호전자) 09:27 매수 → +3.50% [ML: 58.9%]
            # Format: 🔴 272210(한화시스템) 09:54 매수 → -0.81% [ML: 62.7%]
            if "매수 →" in line:
                # Extract Code
                code_match = re.search(r'(\d{6})', line)
                if not code_match: continue
                code = code_match.group(1)
                
                # Extract PnL % (Look for arrow)
                pnl_match = re.search(r'→\s*([+-]?\d+\.\d+)%', line)
                pnl_pct = float(pnl_match.group(1)) if pnl_match else 0.0
                
                # Extract Result Type
                result = "WIN" if "🟢" in line else "LOSS"
                
                # Filtered?
                is_filtered = "[ML 필터링" in line
                
                if not is_filtered:
                    trades[code] = {
                        "pnl_pct": pnl_pct,
                        "result": result,
                        "line": line.strip()
                    }
    except Exception as e:
        print(f"Error reading simul log: {e}")
    return trades

def get_real_trades_from_db(db_path):
    trades = {}
    print(f"Reading DB: {db_path}")
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        # Get Buys and Sells for today
        query = "SELECT stock_code, stock_name, action, price, quantity, timestamp FROM real_trading_records WHERE timestamp LIKE '2026-01-14%'"
        cursor.execute(query)
        rows = cursor.fetchall()
        
        buys = {}
        sells = {}
        
        for r in rows:
            code, name, action, price, qty, ts = r
            if action == 'BUY':
                buys[code] = {'price': price, 'qty': qty, 'time': ts}
            elif action == 'SELL':
                sells[code] = {'price': price, 'qty': qty, 'time': ts}
        
        # Match them
        for code, buy in buys.items():
            sell = sells.get(code)
            pnl = 0.0
            note = "Open"
            
            if sell:
                buy_price = buy['price']
                sell_price = sell['price']
                
                if buy_price > 0:
                    pnl = ((sell_price - buy_price) / buy_price) * 100
                    note = "Closed"
                
                # Special check for 0 price (error)
                if sell_price == 0:
                    note = "Error(Price=0)"
            
            trades[code] = {
                "name": r[1], # Last name found
                "buy_price": buy['price'],
                "sell_price": sell['price'] if sell else 0,
                "pnl_pct": pnl,
                "note": note
            }
            
        conn.close()
    except Exception as e:
        print(f"Error reading DB: {e}")
        
    return trades

def compare(simul_path, db_path):
    simul_trades = parse_simul_log(simul_path)
    real_trades = get_real_trades_from_db(db_path)
    
    all_codes = set(simul_trades.keys()) | set(real_trades.keys())
    
    print(f"\n{'CODE':<8} | {'SIMULATION PnL':<20} | {'REAL PnL':<20} | {'NOTE'}")
    print("-" * 80)
    
    total_real_loss_pct = 0
    total_simul_loss_pct = 0
    
    for code in sorted(list(all_codes)):
        s_data = simul_trades.get(code, {})
        r_data = real_trades.get(code, {})
        
        s_pnl = s_data.get('pnl_pct', 0.0)
        r_pnl = r_data.get('pnl_pct', 0.0)
        
        if code in simul_trades: total_simul_loss_pct += s_pnl
        if code in real_trades: total_real_loss_pct += r_pnl
        
        s_str = f"{s_pnl:+.2f}%" if code in simul_trades else "-"
        r_str = f"{r_pnl:+.2f}%" if code in real_trades else "-"
        
        note = r_data.get('note', '')
        if code not in real_trades and code in simul_trades:
            note = "Simul Only"
        if code in real_trades and code not in simul_trades:
            note = "Real Only"
            
        print(f"{code:<8} | {s_str:<20} | {r_str:<20} | {note}")

    print("-" * 80)
    print(f"Total PnL % Sum | {total_simul_loss_pct:+.2f}%            | {total_real_loss_pct:+.2f}%")

if __name__ == "__main__":
    simul_path = "signal_replay_log_ml/signal_ml_replay_20260114_9_00_0.txt"
    db_path = "data/robotrader.db"
    compare(simul_path, db_path)
