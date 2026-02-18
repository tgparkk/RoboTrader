import re

def parse_simul_log(filepath):
    trades = {}
    total_profit = 0
    print(f"Parsing Simul Log: {filepath}")
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            
        for line in lines:
            # Format: 🟢 043260(성호전자) 09:27 매수 → +3.50% [ML: 58.9%]
            # Format: 🔴 272210(한화시스템) 09:54 매수 → -0.81% [ML: 62.7%]
            if "매수 →" in line and ("🟢" in line or "🔴" in line):
                # Extract Code
                code_match = re.search(r'(\d{6})', line)
                if not code_match: continue
                code = code_match.group(1)
                
                # Extract PnL %
                pnl_match = re.search(r'([+-]?\d+\.\d+)%', line)
                pnl_pct = float(pnl_match.group(1)) if pnl_match else 0.0
                
                # Extract Result Type
                result = "WIN" if "🟢" in line else "LOSS"
                
                trades[code] = {
                    "pnl_pct": pnl_pct,
                    "result": result,
                    "line": line.strip()
                }
    except Exception as e:
        print(f"Error reading simul log: {e}")
    return trades

def parse_real_log(filepath):
    trades = {}
    print(f"Parsing Real Log: {filepath}")
    
    # We need to find Sell executions to get P&L
    # Or "Profit" / "Loss" statements.
    # Looking for lines like: "매도 체결" or "손익: ..."
    # Based on previous log reads, we might need to dig into "Sell Order" or "Execution"
    
    # Let's try to find trade summaries or sell executions.
    # Since I don't have the full log structure for Sells handy, I'll search for "청산" or "매도"
    
    try:
        content = ""
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            with open(filepath, 'r', encoding='cp949') as f:
                content = f.read()
                
        lines = content.split('\n')
        
        current_trade = {} 
        
        for line in lines:
            # Look for Sell execution logs that usually contain profit info
            # "매도 체결" -> "실현손익", "수익률"
            if "매도" in line and "체결" in line:
                 # Try to extract code
                code_match = re.search(r'(\d{6})', line)
                if code_match:
                    code = code_match.group(1)
                    if code not in trades:
                        trades[code] = {"pnl_pct": 0.0, "result": "UNKNOWN", "details": []}
                    trades[code]["details"].append(line.strip())

            # Look for explicit profit report logs if they exist
            # "손익률" or "수익률"
            if "수익률" in line and "%" in line and ("매도" in line or "청산" in line):
                # Try to extract percentage
                pnl_match = re.search(r'([+-]?\d+\.\d+)%', line)
                if pnl_match:
                     # Try to find code in the same line
                    code_match = re.search(r'(\d{6})', line)
                    if code_match:
                        code = code_match.group(1)
                        if code not in trades:
                            trades[code] = {"pnl_pct": 0.0, "result": "UNKNOWN", "details": []}
                        
                        pnl = float(pnl_match.group(1))
                        trades[code]["pnl_pct"] = pnl
                        trades[code]["result"] = "WIN" if pnl > 0 else "LOSS"

    except Exception as e:
        print(f"Error reading real log: {e}")
        
    return trades

def compare(simul_path, real_path):
    simul_trades = parse_simul_log(simul_path)
    real_trades = parse_real_log(real_path)
    
    all_codes = set(simul_trades.keys()) | set(real_trades.keys())
    
    print(f"{'CODE':<8} | {'SIMULATION PnL':<20} | {'REAL PnL':<20} | {'DIFF'}")
    print("-" * 70)
    
    for code in sorted(list(all_codes)):
        s_data = simul_trades.get(code, {})
        r_data = real_trades.get(code, {})
        
        s_pnl = s_data.get('pnl_pct', None)
        r_pnl = r_data.get('pnl_pct', None)
        
        s_str = f"{s_pnl:+.2f}%" if s_pnl is not None else "N/A"
        r_str = f"{r_pnl:+.2f}%" if r_pnl is not None else "N/A" # Real log parsing might be tricky
        
        # If Real PnL is missing but we have details, indicate that
        if r_pnl is None and r_data.get('details'):
            r_str = "Traded (Chk Details)"
            
        print(f"{code:<8} | {s_str:<20} | {r_str:<20} |")
        
        if r_pnl is None and r_data.get('details'):
            for d in r_data['details']:
                print(f"    -> Real Log: {d}")

if __name__ == "__main__":
    simul_path = "signal_replay_log_ml/signal_ml_replay_20260114_9_00_0.txt"
    real_path = "D:/GIT/RoboTrader_orb/logs/trading_20260114.log"
    compare(simul_path, real_path)
