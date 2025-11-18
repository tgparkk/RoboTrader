import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

def extract_trades_with_details(log_file_path):
    """로그 파일에서 거래 상세 정보 추출"""
    with open(log_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    match = re.search(r'(\d{8})_', os.path.basename(log_file_path))
    if not match:
        return []

    date = match.group(1)
    trades = []

    # 각 종목 섹션 찾기
    sections = re.split(r'=== (\d{6}) - \d{8}', content)

    for i in range(1, len(sections), 2):
        if i+1 >= len(sections):
            break

        symbol = sections[i]
        section_content = sections[i+1]

        # 매매신호 및 체결 시뮬레이션 파싱
        signal_matches = re.findall(r'(\d{2}:\d{2}) \[pullback_pattern\]', section_content)

        for signal_time in signal_matches:
            # 해당 시간의 결과 찾기
            profit_pattern = rf'{signal_time} 매수\[pullback_pattern\].*?\(([-+]\d+\.\d+)%\)'
            profit_match = re.search(profit_pattern, section_content)

            if profit_match:
                profit = float(profit_match.group(1))
                is_win = profit > 0

                # 신뢰도 찾기 (신호 시간 근처)
                time_pattern = rf'{signal_time.replace(":", "→")[:-3]}→.*?신뢰도:\s*(\d+)%'
                confidence_match = re.search(time_pattern, section_content)
                confidence = int(confidence_match.group(1)) if confidence_match else 0

                # 상세 3분봉 분석에서 해당 시점 찾기
                candle_pattern = rf'{signal_time.replace(":", "→")[:-3]}→\d{{2}}:\d{{2}}:.*?종가:([0-9,]+).*?거래량:([0-9,]+)'
                candle_match = re.search(candle_pattern, section_content)

                if candle_match:
                    close = int(candle_match.group(1).replace(',', ''))
                    volume = int(candle_match.group(2).replace(',', ''))

                    # 직전 4개 캔들의 거래량 찾기
                    all_candles = re.findall(r'(\d{2}:\d{2})→(\d{2}:\d{2}).*?거래량:([0-9,]+)', section_content)

                    signal_idx = -1
                    for idx, (start_t, end_t, vol) in enumerate(all_candles):
                        if end_t == signal_time:
                            signal_idx = idx
                            break

                    prev_volumes = []
                    if signal_idx >= 4:
                        for j in range(signal_idx-4, signal_idx):
                            prev_volumes.append(int(all_candles[j][2].replace(',', '')))

                    # Stage 분석 (거래량 추세)
                    stage1_vol_decreasing = False
                    stage3_low_volume = False
                    stage4_vol_increase = 0

                    if len(prev_volumes) >= 4:
                        # Stage 1-2-3-4 대략적 추정
                        # Stage 1: 초반 2개
                        # Stage 2-3: 중간 2개
                        # Stage 4: 신호봉

                        stage1_vols = prev_volumes[:2]
                        stage23_vols = prev_volumes[2:4]
                        stage4_vol = volume

                        # Stage 1 거래량 감소 확인
                        if len(stage1_vols) >= 2:
                            stage1_vol_decreasing = stage1_vols[1] < stage1_vols[0]

                        # Stage 3 저거래량 확인
                        if len(stage23_vols) >= 1:
                            avg_prev = sum(prev_volumes) / len(prev_volumes)
                            min_stage23 = min(stage23_vols)
                            stage3_low_volume = min_stage23 < avg_prev * 0.5

                        # Stage 4 거래량 증가율
                        if len(prev_volumes) >= 1:
                            prev_avg = sum(prev_volumes[-2:]) / 2 if len(prev_volumes) >= 2 else prev_volumes[-1]
                            stage4_vol_increase = (stage4_vol / prev_avg - 1) * 100 if prev_avg > 0 else 0

                    trades.append({
                        'date': date,
                        'symbol': symbol,
                        'time': signal_time,
                        'profit': profit,
                        'is_win': is_win,
                        'confidence': confidence,
                        'volume': volume,
                        'prev_volumes': prev_volumes,
                        'stage1_vol_decreasing': stage1_vol_decreasing,
                        'stage3_low_volume': stage3_low_volume,
                        'stage4_vol_increase': stage4_vol_increase
                    })

    return trades

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
                trades = extract_trades_with_details(os.path.join(log_dir, file))
                all_trades.extend(trades)

print()
print(f'총 {len(all_trades)}건 거래 수집 완료')
print()

# 1. 신뢰도 vs 실제 승률 분석
print('='*100)
print('1. 신뢰도 vs 실제 승률 분석')
print('='*100)
print()

# 신뢰도 구간별 집계
confidence_buckets = {
    '0-70%': [],
    '70-80%': [],
    '80-85%': [],
    '85-90%': [],
    '90-95%': [],
    '95-100%': []
}

for trade in all_trades:
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
# 상관관계 확인
valid_trades = [t for t in all_trades if t['confidence'] > 0]
if valid_trades:
    import numpy as np
    confidences = [t['confidence'] for t in valid_trades]
    outcomes = [1 if t['is_win'] else 0 for t in valid_trades]
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

# 거래량 패턴별 분류
pattern_analysis = {
    'stage1_decreasing': {'wins': 0, 'losses': 0},
    'stage1_increasing': {'wins': 0, 'losses': 0},
    'stage3_low_volume': {'wins': 0, 'losses': 0},
    'stage3_normal_volume': {'wins': 0, 'losses': 0},
    'stage4_strong_increase': {'wins': 0, 'losses': 0},  # 50% 이상
    'stage4_moderate_increase': {'wins': 0, 'losses': 0},  # 20-50%
    'stage4_weak_increase': {'wins': 0, 'losses': 0},  # 20% 미만
}

for trade in all_trades:
    if not trade['prev_volumes']:
        continue

    # Stage 1 (상승 시 거래량 감소)
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

    # Stage 3 (지지 구간 저거래량)
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

    # Stage 4 (돌파 거래량 증가)
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

print(f"{'패턴 특징':30s} | {'승리':>6s} | {'패배':>6s} | {'승률':>8s} | {'차이':>10s}")
print('-' * 100)

print('Stage 1 (상승 구간 거래량 추세):')
for pattern in ['stage1_decreasing', 'stage1_increasing']:
    data = pattern_analysis[pattern]
    total = data['wins'] + data['losses']
    if total > 0:
        win_rate = data['wins'] / total * 100
        label = '거래량 감소 (이상적)' if 'decreasing' in pattern else '거래량 증가'
        print(f"  {label:28s} | {data['wins']:6d} | {data['losses']:6d} | {win_rate:7.1f}% |")

print()
print('Stage 3 (지지 구간 거래량):')
for pattern in ['stage3_low_volume', 'stage3_normal_volume']:
    data = pattern_analysis[pattern]
    total = data['wins'] + data['losses']
    if total > 0:
        win_rate = data['wins'] / total * 100
        label = '저거래량 (이상적)' if 'low' in pattern else '보통 거래량'
        print(f"  {label:28s} | {data['wins']:6d} | {data['losses']:6d} | {win_rate:7.1f}% |")

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
        print(f"  {label:28s} | {data['wins']:6d} | {data['losses']:6d} | {win_rate:7.1f}% |")

print()
print('💡 분석 결론:')
print('  - Stage 1 거래량 감소 vs 증가의 승률 차이')
print('  - Stage 3 저거래량의 중요성')
print('  - Stage 4 거래량 증가율과 승률의 관계')
