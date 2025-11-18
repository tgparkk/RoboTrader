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
        return []

    date = match.group(1)
    trades = []
    lines = content.split('\n')

    for line in lines:
        if '🟢' in line and '매수 →' in line:
            symbol_match = re.search(r'🟢\s*(\d{6})\s+(\d{2}:\d{2})', line)
            profit_match = re.search(r'\+(\d+\.\d+)%', line)
            if symbol_match and profit_match:
                trades.append({
                    'date': date,
                    'symbol': symbol_match.group(1),
                    'time': symbol_match.group(2),
                    'profit': float(profit_match.group(1)),
                    'is_win': True
                })

        if '🔴' in line and '매수 →' in line:
            symbol_match = re.search(r'🔴\s*(\d{6})\s+(\d{2}:\d{2})', line)
            loss_match = re.search(r'-(\d+\.\d+)%', line)
            if symbol_match and loss_match:
                trades.append({
                    'date': date,
                    'symbol': symbol_match.group(1),
                    'time': symbol_match.group(2),
                    'profit': -float(loss_match.group(1)),
                    'is_win': False
                })

    return trades

def extract_confidence_from_log(log_file_path, symbol, time_str):
    """특정 종목/시간의 신뢰도 추출"""
    try:
        with open(log_file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        # 해당 종목 섹션 찾기
        section_pattern = rf'=== {symbol} - \d{{8}}.*?(?====|$)'
        section_match = re.search(section_pattern, content, re.DOTALL)

        if not section_match:
            return None

        section = section_match.group(0)

        # 해당 시간의 신뢰도 찾기
        # 예: 09→36: 신뢰도: 85%
        time_formatted = time_str.replace(':', '→')[:-3] + '→'  # "09:36" -> "09→36→"
        confidence_pattern = rf'{time_formatted}.*?신뢰도:\s*(\d+)%'
        confidence_match = re.search(confidence_pattern, section)

        if confidence_match:
            return int(confidence_match.group(1))

        return None
    except Exception as e:
        return None

def analyze_4stage_volume(symbol, date, time_str):
    """4단계 거래량 패턴 분석"""
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

        # 거래량 데이터
        volumes = candles['volume'].values
        if len(volumes) < 5:
            return None

        # Stage 1-2-3-4 분석
        stage1_vols = volumes[:2]  # 초반 2개
        stage23_vols = volumes[2:4]  # 중간 2개
        stage4_vol = volumes[-1]  # 신호봉

        # Stage 1: 거래량 감소 확인
        stage1_vol_decreasing = False
        if len(stage1_vols) >= 2:
            stage1_vol_decreasing = stage1_vols[1] < stage1_vols[0]

        # Stage 3: 저거래량 확인
        stage3_low_volume = False
        if len(stage23_vols) >= 1:
            avg_prev = np.mean(volumes[:-1])
            min_stage23 = min(stage23_vols)
            stage3_low_volume = min_stage23 < avg_prev * 0.5

        # Stage 4: 거래량 증가율
        stage4_vol_increase = 0
        if len(volumes) >= 2:
            prev_avg = np.mean(volumes[-3:-1]) if len(volumes) >= 3 else volumes[-2]
            stage4_vol_increase = (stage4_vol / prev_avg - 1) * 100 if prev_avg > 0 else 0

        return {
            'stage1_vol_decreasing': stage1_vol_decreasing,
            'stage3_low_volume': stage3_low_volume,
            'stage4_vol_increase': stage4_vol_increase,
            'volumes': volumes.tolist()
        }
    except Exception as e:
        return None

# 전체 거래 수집
print('='*100)
print('전체 거래 데이터 수집 중...')
print('='*100)

all_trades = []

log_dir = 'signal_replay_log'
for file in sorted(os.listdir(log_dir)):
    if file.startswith('signal_new2_replay_') and file.endswith('.txt'):
        match = re.search(r'(\d{8})_', file)
        if match:
            date = match.group(1)
            if '20250901' <= date <= '20251111':
                print(f'처리 중: {date}', end='\r')
                trades = extract_trades_from_log(os.path.join(log_dir, file))

                # 각 거래에 신뢰도 추가
                log_path = os.path.join(log_dir, file)
                for trade in trades:
                    confidence = extract_confidence_from_log(log_path, trade['symbol'], trade['time'])
                    trade['confidence'] = confidence if confidence is not None else 0

                all_trades.extend(trades)

print()
print(f'총 {len(all_trades)}건 거래 수집 완료')
print()

# 4단계 거래량 분석 추가
print('='*100)
print('4단계 거래량 패턴 분석 중...')
print('='*100)

for i, trade in enumerate(all_trades):
    if i % 50 == 0:
        print(f'분석 중... {i}/{len(all_trades)}', end='\r')

    vol_analysis = analyze_4stage_volume(trade['symbol'], trade['date'], trade['time'])
    if vol_analysis:
        trade.update(vol_analysis)
    else:
        trade['stage1_vol_decreasing'] = None
        trade['stage3_low_volume'] = None
        trade['stage4_vol_increase'] = None

print()
print('분석 완료!')
print()

# 유효한 거래만 필터링
valid_trades = [t for t in all_trades if t.get('stage4_vol_increase') is not None]

print(f'거래량 분석 완료: {len(valid_trades)}/{len(all_trades)}건')
print()

# 1. 신뢰도 vs 실제 승률 분석
print('='*100)
print('1. 신뢰도 vs 실제 승률 분석')
print('='*100)
print()

confidence_buckets = {
    '0-70%': [],
    '70-80%': [],
    '80-85%': [],
    '85-90%': [],
    '90-95%': [],
    '95-100%': []
}

for trade in valid_trades:
    conf = trade['confidence']
    if conf < 70:
        bucket = '0-70%'
    elif conf < 80:
        bucket = '70-80%'
    elif conf < 85:
        bucket = '80-85%'
    elif conf < 90:
        bucket = '85-90%'
    elif conf < 95:
        bucket = '90-95%'
    else:
        bucket = '95-100%'

    confidence_buckets[bucket].append(trade)

print(f"{'신뢰도 구간':15s} | {'거래수':>8s} | {'승리':>6s} | {'패배':>6s} | {'실제승률':>10s} | {'평균수익':>10s}")
print('-' * 100)

for bucket_name in ['0-70%', '70-80%', '80-85%', '85-90%', '90-95%', '95-100%']:
    trades = confidence_buckets[bucket_name]
    if trades:
        total = len(trades)
        wins = sum(1 for t in trades if t['is_win'])
        losses = total - wins
        win_rate = wins / total * 100
        avg_profit = sum(t['profit'] for t in trades) / total

        print(f"{bucket_name:15s} | {total:8d} | {wins:6d} | {losses:6d} | {win_rate:9.1f}% | {avg_profit:+9.2f}%")
    else:
        print(f"{bucket_name:15s} | {0:8d} | {0:6d} | {0:6d} | {0:9.1f}% | {0:+9.2f}%")

print()
print('💡 분석:')
confidences = [t['confidence'] for t in valid_trades if t['confidence'] > 0]
outcomes = [1 if t['is_win'] else 0 for t in valid_trades if t['confidence'] > 0]
if confidences and outcomes:
    correlation = np.corrcoef(confidences, outcomes)[0, 1]
    print(f'  - 신뢰도와 승률의 상관계수: {correlation:.3f}')
    if correlation > 0.1:
        print('    → 신뢰도가 높을수록 승률도 높음 (양의 상관관계)')
    elif correlation < -0.1:
        print('    → 신뢰도가 높을수록 승률이 낮음 (음의 상관관계 - 문제!)')
    else:
        print('    → 신뢰도와 승률이 거의 무관함 (상관관계 약함)')

print()
print()

# 2. 4단계 패턴의 거래량 품질 분석
print('='*100)
print('2. 4단계 패턴의 거래량 품질 분석')
print('='*100)
print()

pattern_analysis = {
    'stage1_decreasing': {'wins': 0, 'losses': 0},
    'stage1_increasing': {'wins': 0, 'losses': 0},
    'stage3_low_volume': {'wins': 0, 'losses': 0},
    'stage3_normal_volume': {'wins': 0, 'losses': 0},
    'stage4_strong_increase': {'wins': 0, 'losses': 0},  # 50% 이상
    'stage4_moderate_increase': {'wins': 0, 'losses': 0},  # 20-50%
    'stage4_weak_increase': {'wins': 0, 'losses': 0},  # 20% 미만
}

for trade in valid_trades:
    # Stage 1
    if trade['stage1_vol_decreasing']:
        if trade['is_win']:
            pattern_analysis['stage1_decreasing']['wins'] += 1
        else:
            pattern_analysis['stage1_decreasing']['losses'] += 1
    else:
        if trade['is_win']:
            pattern_analysis['stage1_increasing']['wins'] += 1
        else:
            pattern_analysis['stage1_increasing']['losses'] += 1

    # Stage 3
    if trade['stage3_low_volume']:
        if trade['is_win']:
            pattern_analysis['stage3_low_volume']['wins'] += 1
        else:
            pattern_analysis['stage3_low_volume']['losses'] += 1
    else:
        if trade['is_win']:
            pattern_analysis['stage3_normal_volume']['wins'] += 1
        else:
            pattern_analysis['stage3_normal_volume']['losses'] += 1

    # Stage 4
    vol_inc = trade['stage4_vol_increase']
    if vol_inc >= 50:
        key = 'stage4_strong_increase'
    elif vol_inc >= 20:
        key = 'stage4_moderate_increase'
    else:
        key = 'stage4_weak_increase'

    if trade['is_win']:
        pattern_analysis[key]['wins'] += 1
    else:
        pattern_analysis[key]['losses'] += 1

print(f"{'패턴 특징':30s} | {'승리':>6s} | {'패배':>6s} | {'승률':>8s}")
print('-' * 100)

print('Stage 1 (상승 구간 거래량 추세):')
for pattern in ['stage1_decreasing', 'stage1_increasing']:
    data = pattern_analysis[pattern]
    total = data['wins'] + data['losses']
    if total > 0:
        win_rate = data['wins'] / total * 100
        label = '거래량 감소 (이상적)' if 'decreasing' in pattern else '거래량 증가'
        print(f"  {label:28s} | {data['wins']:6d} | {data['losses']:6d} | {win_rate:7.1f}%")

print()
print('Stage 3 (지지 구간 거래량):')
for pattern in ['stage3_low_volume', 'stage3_normal_volume']:
    data = pattern_analysis[pattern]
    total = data['wins'] + data['losses']
    if total > 0:
        win_rate = data['wins'] / total * 100
        label = '저거래량 (이상적)' if 'low' in pattern else '보통 거래량'
        print(f"  {label:28s} | {data['wins']:6d} | {data['losses']:6d} | {win_rate:7.1f}%")

print()
print('Stage 4 (돌파 거래량 증가):')
for pattern in ['stage4_strong_increase', 'stage4_moderate_increase', 'stage4_weak_increase']:
    data = pattern_analysis[pattern]
    total = data['wins'] + data['losses']
    if total > 0:
        win_rate = data['wins'] / total * 100
        if 'strong' in pattern:
            label = '강한 증가 (50%+)'
        elif 'moderate' in pattern:
            label = '보통 증가 (20-50%)'
        else:
            label = '약한 증가 (<20%)'
        print(f"  {label:28s} | {data['wins']:6d} | {data['losses']:6d} | {win_rate:7.1f}%")

print()
print('='*100)
print('💡 핵심 결론')
print('='*100)

# Stage 4 강한 증가 vs 약한 증가 비교
strong = pattern_analysis['stage4_strong_increase']
weak = pattern_analysis['stage4_weak_increase']

strong_total = strong['wins'] + strong['losses']
weak_total = weak['wins'] + weak['losses']

if strong_total > 0 and weak_total > 0:
    strong_wr = strong['wins'] / strong_total * 100
    weak_wr = weak['wins'] / weak_total * 100

    print(f"Stage 4 거래량 증가율 50% 이상: {strong['wins']}승 {strong['losses']}패 (승률 {strong_wr:.1f}%)")
    print(f"Stage 4 거래량 증가율 20% 미만: {weak['wins']}승 {weak['losses']}패 (승률 {weak_wr:.1f}%)")
    print(f"승률 차이: {strong_wr - weak_wr:+.1f}%p")
    print()
    print(f"✅ 필터 효과: Stage 4 거래량 50% 이상 증가만 매매하면")
    print(f"   거래 건수: {len(valid_trades)}건 → {strong_total}건 ({strong_total/len(valid_trades)*100:.1f}%)")
    print(f"   승률: {len([t for t in valid_trades if t['is_win']])/len(valid_trades)*100:.1f}% → {strong_wr:.1f}% ({strong_wr - len([t for t in valid_trades if t['is_win']])/len(valid_trades)*100:+.1f}%p)")
