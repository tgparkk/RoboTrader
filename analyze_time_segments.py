#!/usr/bin/env python3
"""
특정 시간 구간별 승패 분석 스크립트
"""
import re
from datetime import datetime, time

def parse_signal_replay_file(filename):
    """signal_replay 파일 파싱"""
    trades = []
    
    with open(filename, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    # 종목별 섹션으로 분할
    sections = re.split(r'=== (\w+) - \d+ 눌림목.*? ===', content)[1:]
    
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

def analyze_time_segment(trades, start_time, end_time):
    """특정 시간 구간 내 매수한 거래들의 승패 분석"""
    segment_trades = []
    
    for trade in trades:
        if start_time <= trade['buy_time'] <= end_time:
            segment_trades.append(trade)
    
    if not segment_trades:
        return {'total': 0, 'wins': 0, 'losses': 0, 'win_rate': 0.0}
    
    wins = sum(1 for trade in segment_trades if trade['is_win'])
    losses = len(segment_trades) - wins
    win_rate = wins / len(segment_trades) * 100
    
    return {
        'total': len(segment_trades),
        'wins': wins,
        'losses': losses, 
        'win_rate': win_rate
    }

def main():
    filename = 'signal_replay_20250901_9_00_0.txt'
    
    print("특정 시간대 매수 거래 승패 분석")
    print("=" * 50)
    
    # 파일 파싱
    trades = parse_signal_replay_file(filename)
    
    # 전체 통계 확인
    total_wins = sum(1 for trade in trades if trade['is_win'])
    total_losses = len(trades) - total_wins
    print(f"전체 통계: {len(trades)}건 ({total_wins}승 {total_losses}패)")
    print()
    
    # 요청한 시간 구간 분석
    segments = [
        ("09:00~12:00", time(9, 0), time(12, 0)),
        ("09:00~12:30", time(9, 0), time(12, 30)),
    ]
    
    for segment_name, start_time, end_time in segments:
        result = analyze_time_segment(trades, start_time, end_time)
        print(f"[{segment_name} 매수]")
        print(f"  총 거래: {result['total']}건")
        print(f"  승패: {result['wins']}승 {result['losses']}패")
        print(f"  승률: {result['win_rate']:.1f}%")
        print()

if __name__ == "__main__":
    main()