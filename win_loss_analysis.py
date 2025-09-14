import re

def extract_trades_from_file(file_path):
    """매매 기록에서 승리/패배 종목 추출"""
    trades = {'wins': [], 'losses': []}
    current_stock = None
    
    with open(file_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()
    
    for i, line in enumerate(lines):
        # 종목 코드 찾기 (=== 000000 - 날짜 형태)
        stock_match = re.search(r'=== (\d{6}) - ', line)
        if stock_match:
            current_stock = stock_match.group(1)
            continue
        
        # 매매 결과 찾기
        if current_stock and ('profit_' in line or 'stop_loss' in line):
            # 승리/패배 판단
            if 'profit_' in line and '+' in line:
                trades['wins'].append({
                    'stock_code': current_stock,
                    'line': line.strip()
                })
            elif 'stop_loss' in line and '-' in line:
                trades['losses'].append({
                    'stock_code': current_stock,
                    'line': line.strip()
                })
    
    return trades

# 09/09 데이터 분석
trades_0909 = extract_trades_from_file('signal_qqw_replay_20250909_9_00_0.txt')
print("=== 09/09 매매 결과 ===")
print(f"승리 종목: {len(trades_0909['wins'])}개")
print(f"패배 종목: {len(trades_0909['losses'])}개")

print("\n[승리 종목]")
win_stocks_0909 = set()
for trade in trades_0909['wins']:
    print(f"종목코드 {trade['stock_code']}: {trade['line']}")
    win_stocks_0909.add(trade['stock_code'])

print("\n[패배 종목]")
loss_stocks_0909 = set()
for trade in trades_0909['losses']:
    print(f"종목코드 {trade['stock_code']}: {trade['line']}")
    loss_stocks_0909.add(trade['stock_code'])

# 09/10 데이터 분석
trades_0910 = extract_trades_from_file('signal_qqw_replay_20250910_9_00_0.txt')
print("\n\n=== 09/10 매매 결과 ===")
print(f"승리 종목: {len(trades_0910['wins'])}개")
print(f"패배 종목: {len(trades_0910['losses'])}개")

print("\n[승리 종목]")
win_stocks_0910 = set()
for trade in trades_0910['wins']:
    print(f"종목코드 {trade['stock_code']}: {trade['line']}")
    win_stocks_0910.add(trade['stock_code'])

print("\n[패배 종목]")
loss_stocks_0910 = set()
for trade in trades_0910['losses']:
    print(f"종목코드 {trade['stock_code']}: {trade['line']}")
    loss_stocks_0910.add(trade['stock_code'])

# 전체 통계
all_wins = win_stocks_0909.union(win_stocks_0910)
all_losses = loss_stocks_0909.union(loss_stocks_0910)

print(f"\n\n=== 전체 통계 ===")
print(f"전체 승리 종목 수: {len(all_wins)}")
print(f"전체 패배 종목 수: {len(all_losses)}")
print(f"승률: {len(all_wins)/(len(all_wins)+len(all_losses))*100:.1f}%")

print(f"\n승리 종목 코드: {sorted(list(all_wins))}")
print(f"패배 종목 코드: {sorted(list(all_losses))}")

# 중복 종목 체크 (승리와 패배 모두 있는 종목)
overlap = all_wins.intersection(all_losses)
if overlap:
    print(f"\n승패가 모두 있는 종목: {sorted(list(overlap))}")