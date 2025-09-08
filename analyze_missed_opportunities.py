#!/usr/bin/env python3
"""
놓친 기회들 분석 - 2025-09-05 데이터
"""

import sys
import os
sys.path.append(os.getcwd())

from core.indicators.pullback_candle_pattern import PullbackCandlePattern
from core.indicators.pullback_utils import SignalType, PullbackUtils
import pandas as pd
import re
from datetime import datetime

def parse_minute_data(file_path):
    """분봉 데이터 파싱"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        data_rows = []
        seen_candles = set()
        
        for line in lines:
            line = line.strip()
            if not line or '캔들시간=' not in line:
                continue
                
            patterns = {
                '캔들시간': r'캔들시간=(\d+)',
                '시가': r'시가=([\d,]+\.?\d*)',
                '고가': r'고가=([\d,]+\.?\d*)',
                '저가': r'저가=([\d,]+\.?\d*)',
                '종가': r'종가=([\d,]+\.?\d*)',
                '거래량': r'거래량=([\d,]+\.?\d*)'
            }
            
            row_data = {}
            for key, pattern in patterns.items():
                match = re.search(pattern, line)
                if match:
                    value = match.group(1).replace(',', '')
                    if key == '캔들시간':
                        row_data[key] = value
                    else:
                        row_data[key] = float(value)
                        
            if len(row_data) == 6:
                candle_key = row_data['캔들시간']
                if candle_key not in seen_candles:
                    seen_candles.add(candle_key)
                    data_rows.append(row_data)
        
        if len(data_rows) < 10:
            return None
            
        df = pd.DataFrame(data_rows)
        df = df.rename(columns={
            '시가': 'open',
            '고가': 'high', 
            '저가': 'low',
            '종가': 'close',
            '거래량': 'volume',
            '캔들시간': 'time'
        })
        
        df = df.sort_values('time').reset_index(drop=True)
        return df
        
    except Exception as e:
        return None

def analyze_price_performance(data):
    """가격 성과 분석 - 실제로 상승했는지 확인"""
    if len(data) < 20:
        return None
    
    # 초기 20% 구간과 후반 20% 구간 비교
    early_section = data.head(int(len(data) * 0.3))  # 초기 30%
    late_section = data.tail(int(len(data) * 0.3))   # 후반 30%
    
    early_avg_price = early_section['close'].mean()
    late_avg_price = late_section['close'].mean()
    
    performance = (late_avg_price - early_avg_price) / early_avg_price * 100
    
    # 최고가 대비 성과
    max_price = data['high'].max()
    min_price = early_section['low'].min()
    max_gain = (max_price - min_price) / min_price * 100
    
    return {
        'performance_pct': performance,
        'max_gain_pct': max_gain,
        'early_price': early_avg_price,
        'late_price': late_avg_price,
        'max_price': max_price
    }

def analyze_missed_patterns(data):
    """놓친 패턴들 분석"""
    patterns_found = []
    
    if len(data) < 10:
        return patterns_found
    
    # 1. 거래량 폭증 패턴
    avg_volume = data['volume'].mean()
    max_volume_idx = data['volume'].idxmax()
    max_volume = data['volume'].iloc[max_volume_idx]
    
    if max_volume > avg_volume * 3:  # 평균의 3배 이상
        max_vol_price = data['close'].iloc[max_volume_idx]
        later_prices = data['close'].iloc[max_volume_idx+1:]
        if len(later_prices) > 0:
            max_later_price = later_prices.max()
            if max_later_price > max_vol_price * 1.02:  # 2% 이상 상승
                patterns_found.append("거래량폭증후상승")
    
    # 2. 연속 상승 패턴
    returns = data['close'].pct_change()
    consecutive_up = 0
    max_consecutive_up = 0
    
    for ret in returns:
        if ret > 0:
            consecutive_up += 1
            max_consecutive_up = max(max_consecutive_up, consecutive_up)
        else:
            consecutive_up = 0
    
    if max_consecutive_up >= 3:
        patterns_found.append(f"연속상승{max_consecutive_up}봉")
    
    # 3. V자 반등 패턴
    if len(data) >= 20:
        mid_point = len(data) // 2
        first_half_min = data['low'].iloc[:mid_point].min()
        second_half_max = data['high'].iloc[mid_point:].max()
        
        recovery_ratio = second_half_max / first_half_min
        if recovery_ratio > 1.05:  # 5% 이상 회복
            patterns_found.append("V자반등")
    
    # 4. 돌파 후 지속 상승
    high_ma = data['high'].rolling(5).mean()
    for i in range(5, len(data)-5):
        if data['high'].iloc[i] > high_ma.iloc[i-1] * 1.02:  # 2% 돌파
            later_performance = data['close'].iloc[i+1:i+6].max() / data['close'].iloc[i]
            if later_performance > 1.03:  # 돌파 후 3% 더 상승
                patterns_found.append("돌파후지속상승")
                break
    
    return patterns_found

def analyze_missed_opportunities():
    """놓친 기회들 종합 분석"""
    data_dir = 'realtime_data/20250905'
    files = [f for f in os.listdir(data_dir) if f.endswith('_minute.txt')]
    
    total_files = 0
    signal_generated = 0
    profitable_missed = 0
    missed_opportunities = []
    
    print("MISSED OPPORTUNITIES ANALYSIS - 2025-09-05")
    print("="*80)
    
    for i, file in enumerate(files[:40]):  # 40개 파일 분석
        try:
            file_path = os.path.join(data_dir, file)
            parts = file.split('_')
            stock_code = parts[1] if len(parts) > 1 else 'UNKNOWN'
            stock_name = parts[2] if len(parts) > 2 else 'UNKNOWN'
            
            data = parse_minute_data(file_path)
            if data is None or len(data) < 20:
                continue
                
            total_files += 1
            
            # 현재 신호 시스템 결과
            signal_result = PullbackCandlePattern.generate_improved_signals(
                data, stock_code=stock_code, debug=False
            )
            
            has_signal = (signal_result and 
                         signal_result.signal_type in [SignalType.STRONG_BUY, SignalType.CAUTIOUS_BUY])
            
            if has_signal:
                signal_generated += 1
                continue
            
            # 실제 가격 성과 분석
            performance = analyze_price_performance(data)
            if performance is None:
                continue
            
            # 놓친 패턴들 분석
            missed_patterns = analyze_missed_patterns(data)
            
            # 수익성 있는 기회였는지 판단
            is_profitable = (performance['performance_pct'] > 2.0 or  # 2% 이상 상승
                           performance['max_gain_pct'] > 4.0)         # 또는 최대 4% 이상 상승
            
            if is_profitable:
                profitable_missed += 1
                
                print(f"{profitable_missed:2d}. {stock_code} ({stock_name})")
                print(f"    실제성과: {performance['performance_pct']:+.1f}% (최대: {performance['max_gain_pct']:+.1f}%)")
                print(f"    놓친패턴: {', '.join(missed_patterns) if missed_patterns else '일반상승'}")
                print(f"    가격변화: {performance['early_price']:,.0f} -> {performance['late_price']:,.0f} (최고: {performance['max_price']:,.0f})")
                
                missed_opportunities.append({
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'performance': performance['performance_pct'],
                    'max_gain': performance['max_gain_pct'],
                    'patterns': missed_patterns
                })
        
        except Exception as e:
            continue
    
    print("="*80)
    print("SUMMARY:")
    print(f"전체 분석: {total_files}개")
    print(f"신호 발생: {signal_generated}개 ({signal_generated/total_files*100:.1f}%)")
    print(f"놓친 수익기회: {profitable_missed}개 ({profitable_missed/total_files*100:.1f}%)")
    print(f"기회비용: {profitable_missed}개의 수익기회를 놓쳤습니다.")
    
    # 패턴별 분석
    all_patterns = []
    for opp in missed_opportunities:
        all_patterns.extend(opp['patterns'])
    
    if all_patterns:
        print(f"\n자주 놓친 패턴들:")
        from collections import Counter
        pattern_counts = Counter(all_patterns)
        for pattern, count in pattern_counts.most_common(5):
            print(f"  - {pattern}: {count}회")
    
    return missed_opportunities

if __name__ == "__main__":
    try:
        missed_opps = analyze_missed_opportunities()
    except Exception as e:
        print(f"분석 실패: {e}")