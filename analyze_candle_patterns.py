import os
import re
import pickle
import pandas as pd
import numpy as np
import sys

sys.stdout.reconfigure(encoding='utf-8')

def extract_trades_from_log(log_file_path):
    """로그 파일에서 승리/패배 거래 추출"""
    with open(log_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    match = re.search(r'(\d{8})_', os.path.basename(log_file_path))
    if not match:
        return [], []

    date = match.group(1)
    wins = []
    losses = []
    lines = content.split('\n')

    for line in lines:
        if '🟢' in line and '매수 →' in line:
            symbol_match = re.search(r'🟢\s*(\d{6})\s+(\d{2}:\d{2})', line)
            profit_match = re.search(r'\+(\d+\.\d+)%', line)
            if symbol_match and profit_match:
                wins.append({
                    'date': date,
                    'symbol': symbol_match.group(1),
                    'time': symbol_match.group(2),
                    'profit': float(profit_match.group(1))
                })

        if '🔴' in line and '매수 →' in line:
            symbol_match = re.search(r'🔴\s*(\d{6})\s+(\d{2}:\d{2})', line)
            loss_match = re.search(r'-(\d+\.\d+)%', line)
            if symbol_match and loss_match:
                losses.append({
                    'date': date,
                    'symbol': symbol_match.group(1),
                    'time': symbol_match.group(2),
                    'profit': -float(loss_match.group(1))
                })

    return wins, losses

def analyze_candle_pattern(symbol, date, time_str):
    """3분봉 기준 캔들 패턴 분석"""
    try:
        pkl_file = f'cache/minute_data/{symbol}_{date}.pkl'
        if not os.path.exists(pkl_file):
            return None

        with open(pkl_file, 'rb') as f:
            df_1min = pickle.load(f)

        df_1min = df_1min.set_index('datetime')

        # 1분봉을 3분봉으로 재구성
        df_3min = df_1min.resample('3min', label='right', closed='right').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        year, month, day = date[:4], date[4:6], date[6:8]
        target_time = pd.Timestamp(f'{year}-{month}-{day} {time_str}:00')

        if target_time not in df_3min.index:
            idx = df_3min.index.get_indexer([target_time], method='nearest')[0]
            target_time = df_3min.index[idx]

        signal_idx = df_3min.index.get_loc(target_time)

        # 신호봉 포함 직전 5개 3분봉
        start_idx = max(0, signal_idx - 4)
        candles = df_3min.iloc[start_idx:signal_idx+1]

        if len(candles) < 2:
            return None

        # 신호봉 분석
        signal = candles.iloc[-1]

        # 1. 캔들 크기 분석
        candle_range = signal['high'] - signal['low']  # 전체 범위
        body_size = abs(signal['close'] - signal['open'])  # 몸통
        body_ratio = body_size / candle_range if candle_range > 0 else 0

        # 2. 꼬리 길이
        if signal['close'] >= signal['open']:  # 양봉
            upper_tail = signal['high'] - signal['close']
            lower_tail = signal['open'] - signal['low']
        else:  # 음봉
            upper_tail = signal['high'] - signal['open']
            lower_tail = signal['close'] - signal['low']

        upper_tail_ratio = upper_tail / candle_range if candle_range > 0 else 0
        lower_tail_ratio = lower_tail / candle_range if candle_range > 0 else 0

        # 3. 캔들 방향
        is_bullish = signal['close'] >= signal['open']

        # 4. 직전 4봉 평균 대비 비율
        prev_candles = candles.iloc[:-1]
        avg_prev_range = (prev_candles['high'] - prev_candles['low']).mean()
        range_ratio = candle_range / avg_prev_range if avg_prev_range > 0 else 0

        # 5. 가격 변동성 (직전 4봉의 종가 변동 계수)
        prev_volatility = prev_candles['close'].std() / prev_candles['close'].mean() if len(prev_candles) > 0 else 0

        # 6. 종가 위치 (캔들 내에서 종가의 상대적 위치)
        close_position = (signal['close'] - signal['low']) / candle_range if candle_range > 0 else 0.5

        return {
            'symbol': symbol,
            'date': date,
            'time': time_str,
            'candle_range': candle_range,
            'body_size': body_size,
            'body_ratio': body_ratio,
            'upper_tail_ratio': upper_tail_ratio,
            'lower_tail_ratio': lower_tail_ratio,
            'is_bullish': is_bullish,
            'range_ratio': range_ratio,
            'prev_volatility': prev_volatility,
            'close_position': close_position,
            'close': signal['close']
        }
    except Exception as e:
        return None

# 전체 거래 수집
print('='*100)
print('전체 거래 데이터 수집 중...')
print('='*100)

all_wins = []
all_losses = []

log_dir = 'signal_replay_log'
for file in sorted(os.listdir(log_dir)):
    if file.startswith('signal_new2_replay_') and file.endswith('.txt'):
        match = re.search(r'(\d{8})_', file)
        if match:
            date = match.group(1)
            if '20250901' <= date <= '20251111':
                wins, losses = extract_trades_from_log(os.path.join(log_dir, file))
                all_wins.extend(wins)
                all_losses.extend(losses)

print(f'총 승리 거래: {len(all_wins)}건')
print(f'총 패배 거래: {len(all_losses)}건')
print()

# 캔들 패턴 분석
print('='*100)
print('캔들 패턴 분석 중...')
print('='*100)

win_patterns = []
loss_patterns = []

for i, trade in enumerate(all_wins):
    if i % 50 == 0:
        print(f'승리 거래 분석 중... {i}/{len(all_wins)}')
    result = analyze_candle_pattern(trade['symbol'], trade['date'], trade['time'])
    if result:
        result['profit'] = trade['profit']
        win_patterns.append(result)

for i, trade in enumerate(all_losses):
    if i % 50 == 0:
        print(f'패배 거래 분석 중... {i}/{len(all_losses)}')
    result = analyze_candle_pattern(trade['symbol'], trade['date'], trade['time'])
    if result:
        result['profit'] = trade['profit']
        loss_patterns.append(result)

print()
print('='*100)
print('분석 완료!')
print('='*100)
print(f'승리 거래 분석: {len(win_patterns)}/{len(all_wins)}건')
print(f'패배 거래 분석: {len(loss_patterns)}/{len(all_losses)}건')
print()

# 통계 계산
def calc_stats(patterns):
    if not patterns:
        return {}

    return {
        'avg_body_ratio': np.mean([p['body_ratio'] for p in patterns]),
        'avg_upper_tail': np.mean([p['upper_tail_ratio'] for p in patterns]),
        'avg_lower_tail': np.mean([p['lower_tail_ratio'] for p in patterns]),
        'bullish_pct': sum(1 for p in patterns if p['is_bullish']) / len(patterns) * 100,
        'avg_range_ratio': np.mean([p['range_ratio'] for p in patterns]),
        'avg_volatility': np.mean([p['prev_volatility'] for p in patterns]),
        'avg_close_position': np.mean([p['close_position'] for p in patterns])
    }

win_stats = calc_stats(win_patterns)
loss_stats = calc_stats(loss_patterns)

print('='*100)
print('캔들 패턴 통계 비교')
print('='*100)
print()
print('1. 몸통 비율 (캔들 범위 대비 몸통 크기)')
print(f'   승리: {win_stats["avg_body_ratio"]:.3f} ({win_stats["avg_body_ratio"]*100:.1f}%)')
print(f'   패배: {loss_stats["avg_body_ratio"]:.3f} ({loss_stats["avg_body_ratio"]*100:.1f}%)')
print(f'   차이: {win_stats["avg_body_ratio"] - loss_stats["avg_body_ratio"]:+.3f}')
print()

print('2. 위꼬리 비율')
print(f'   승리: {win_stats["avg_upper_tail"]:.3f} ({win_stats["avg_upper_tail"]*100:.1f}%)')
print(f'   패배: {loss_stats["avg_upper_tail"]:.3f} ({loss_stats["avg_upper_tail"]*100:.1f}%)')
print(f'   차이: {win_stats["avg_upper_tail"] - loss_stats["avg_upper_tail"]:+.3f}')
print()

print('3. 아래꼬리 비율')
print(f'   승리: {win_stats["avg_lower_tail"]:.3f} ({win_stats["avg_lower_tail"]*100:.1f}%)')
print(f'   패배: {loss_stats["avg_lower_tail"]:.3f} ({loss_stats["avg_lower_tail"]*100:.1f}%)')
print(f'   차이: {win_stats["avg_lower_tail"] - loss_stats["avg_lower_tail"]:+.3f}')
print()

print('4. 양봉 비율')
print(f'   승리: {win_stats["bullish_pct"]:.1f}%')
print(f'   패배: {loss_stats["bullish_pct"]:.1f}%')
print(f'   차이: {win_stats["bullish_pct"] - loss_stats["bullish_pct"]:+.1f}%p')
print()

print('5. 캔들 크기 비율 (직전 4봉 평균 대비)')
print(f'   승리: {win_stats["avg_range_ratio"]:.3f}배')
print(f'   패배: {loss_stats["avg_range_ratio"]:.3f}배')
print(f'   차이: {win_stats["avg_range_ratio"] - loss_stats["avg_range_ratio"]:+.3f}배')
print()

print('6. 직전 변동성 (CV)')
print(f'   승리: {win_stats["avg_volatility"]:.4f}')
print(f'   패배: {loss_stats["avg_volatility"]:.4f}')
print(f'   차이: {win_stats["avg_volatility"] - loss_stats["avg_volatility"]:+.4f}')
print()

print('7. 종가 위치 (0=저가, 1=고가)')
print(f'   승리: {win_stats["avg_close_position"]:.3f}')
print(f'   패배: {loss_stats["avg_close_position"]:.3f}')
print(f'   차이: {win_stats["avg_close_position"] - loss_stats["avg_close_position"]:+.3f}')
print()

# 세부 분포
print('='*100)
print('종가 위치 분포 (캔들 내 종가 위치)')
print('='*100)

bins = [0, 0.3, 0.5, 0.7, 1.0]
labels = ['하단(0-30%)', '중하(30-50%)', '중상(50-70%)', '상단(70-100%)']

print('승리 거래:')
for i in range(len(bins)-1):
    count = sum(1 for p in win_patterns if bins[i] <= p['close_position'] < bins[i+1])
    pct = count / len(win_patterns) * 100 if win_patterns else 0
    print(f'  {labels[i]:15s}: {count:>4d}건 ({pct:>5.1f}%)')

print()
print('패배 거래:')
for i in range(len(bins)-1):
    count = sum(1 for p in loss_patterns if bins[i] <= p['close_position'] < bins[i+1])
    pct = count / len(loss_patterns) * 100 if loss_patterns else 0
    print(f'  {labels[i]:15s}: {count:>4d}건 ({pct:>5.1f}%)')
