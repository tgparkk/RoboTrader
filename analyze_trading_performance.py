#!/usr/bin/env python3
"""
signal_replay 결과 파일의 시간대별 승패 분석 스크립트
"""
import re
from datetime import datetime, time

def parse_signal_replay_file(filename):
    """signal_replay 파일 파싱"""
    trades = []
    
    with open(filename, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # 종목별 섹션으로 분할
    sections = re.split(r'=== (\w+) - \d+ 눌림목.*? ===', content)[1:]  # 첫 번째 빈 요소 제거
    
    for i in range(0, len(sections), 2):
        if i + 1 >= len(sections):
            break
            
        stock_code = sections[i]
        section_content = sections[i + 1]
        
        # 체결 시뮬레이션 부분 추출
        simulation_match = re.search(r'체결 시뮬레이션:(.*?)(?=\n\n=|$)', section_content, re.DOTALL)
        if not simulation_match:
            continue
            
        simulation_text = simulation_match.group(1)
        
        # 개별 거래 파싱
        trade_pattern = r'(\d{2}:\d{2}) 매수\[.*?\] @([\d,]+) → (\d{2}:\d{2}) 매도\[.*?\] @([\d,]+) \(([+-][\d.]+)%\)'
        matches = re.findall(trade_pattern, simulation_text)
        
        for match in matches:
            buy_time_str, buy_price_str, sell_time_str, sell_price_str, profit_str = match
            
            buy_time = datetime.strptime(buy_time_str, '%H:%M').time()
            sell_time = datetime.strptime(sell_time_str, '%H:%M').time()
            profit_rate = float(profit_str)
            
            trades.append({
                'stock_code': stock_code,
                'buy_time': buy_time,
                'sell_time': sell_time,
                'profit_rate': profit_rate,
                'is_win': profit_rate > 0
            })
    
    return trades

def analyze_performance_by_timeframe(trades, buy_cutoff, sell_cutoff):
    """특정 시간대 매수의 특정 시간대까지의 승패 분석"""
    filtered_trades = []
    
    for trade in trades:
        # 매수 시간 필터링
        if trade['buy_time'] <= buy_cutoff:
            # 매도 시간 필터링 (해당 시간 이후 매도는 제외)
            if trade['sell_time'] <= sell_cutoff:
                filtered_trades.append(trade)
    
    if not filtered_trades:
        return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0}
    
    wins = sum(1 for trade in filtered_trades if trade['is_win'])
    losses = len(filtered_trades) - wins
    win_rate = wins / len(filtered_trades) * 100
    
    return {
        'total': len(filtered_trades),
        'wins': wins, 
        'losses': losses,
        'win_rate': win_rate,
        'trades': filtered_trades
    }

def main():
    filename = 'signal_replay_20250901_9_00_0.txt'
    
    print("signal_replay 시간대별 승패 분석")
    print("=" * 60)
    
    # 파일 파싱
    trades = parse_signal_replay_file(filename)
    print(f"총 거래 건수: {len(trades)}건\n")
    
    # 분석할 시간대 정의
    time_frames = [
        (time(12, 0), time(12, 30)),  # 12시까지 매수 → 12:30까지 승패
        (time(12, 0), time(13, 0)),   # 12시까지 매수 → 13:00까지 승패  
        (time(12, 0), time(13, 30)),  # 12시까지 매수 → 13:30까지 승패
        (time(12, 0), time(14, 0)),   # 12시까지 매수 → 14:00까지 승패
        (time(12, 0), time(14, 30)),  # 12시까지 매수 → 14:30까지 승패
        (time(12, 0), time(15, 0)),   # 12시까지 매수 → 15:00까지 승패
        (time(12, 0), time(15, 30)),  # 12시까지 매수 → 15:30까지 승패
    ]
    
    # 시간대별 분석
    for buy_cutoff, sell_cutoff in time_frames:
        result = analyze_performance_by_timeframe(trades, buy_cutoff, sell_cutoff)
        
        print(f"[시간분석] {buy_cutoff.strftime('%H:%M')}까지 매수 -> {sell_cutoff.strftime('%H:%M')}까지 승패")
        print(f"   총 거래: {result['total']}건")
        print(f"   승: {result['wins']}건, 패: {result['losses']}건")
        print(f"   승률: {result['win_rate']:.1f}%")
        print()
    
    # 추가: 전체 시간대별 매수 시점 분포 분석
    print("\n시간대별 매수 분포 분석")
    print("-" * 40)
    
    time_buckets = {
        '09:00-10:00': (time(9, 0), time(10, 0)),
        '10:00-11:00': (time(10, 0), time(11, 0)),
        '11:00-12:00': (time(11, 0), time(12, 0)),
        '12:00-13:00': (time(12, 0), time(13, 0)),
        '13:00-14:00': (time(13, 0), time(14, 0)),
        '14:00-15:00': (time(14, 0), time(15, 0)),
        '15:00-15:30': (time(15, 0), time(15, 30)),
    }
    
    for bucket_name, (start_time, end_time) in time_buckets.items():
        bucket_trades = [t for t in trades if start_time <= t['buy_time'] < end_time]
        if bucket_trades:
            wins = sum(1 for t in bucket_trades if t['is_win'])
            win_rate = wins / len(bucket_trades) * 100
            print(f"{bucket_name}: {len(bucket_trades)}건 (승률: {win_rate:.1f}%)")

if __name__ == "__main__":
    main()