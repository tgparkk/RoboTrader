import os
import re
import pickle
import pandas as pd
import sys
from datetime import datetime

sys.stdout.reconfigure(encoding='utf-8')

def extract_trades_from_log(log_file_path):
    """로그 파일에서 승리/패배 거래 추출"""
    with open(log_file_path, 'r', encoding='utf-8') as f:
        content = f.read()

    # 파일명에서 날짜 추출
    match = re.search(r'(\d{8})_', os.path.basename(log_file_path))
    if not match:
        return [], []

    date = match.group(1)

    # 승패 요약 섹션 찾기 (예: 🟢 000990 09:36 매수 → +3.50%)
    wins = []
    losses = []

    lines = content.split('\n')
    for line in lines:
        # 🟢 승리 거래
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

        # 🔴 손실 거래
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

def analyze_signal_point(symbol, date, time_str):
    """3분봉 기준 거래량 패턴 분석"""
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

        # 시간 파싱
        year = date[:4]
        month = date[4:6]
        day = date[6:8]
        target_time = pd.Timestamp(f'{year}-{month}-{day} {time_str}:00')

        # 해당 시점 찾기
        if target_time not in df_3min.index:
            idx = df_3min.index.get_indexer([target_time], method='nearest')[0]
            target_time = df_3min.index[idx]

        signal_idx = df_3min.index.get_loc(target_time)

        # 신호봉 포함 직전 5개 3분봉
        start_idx = max(0, signal_idx - 4)
        before_signal = df_3min.iloc[start_idx:signal_idx+1]

        if len(before_signal) < 2:
            return None

        # 통계 계산
        avg_vol = before_signal['volume'][:-1].mean()
        signal_vol = df_3min.loc[target_time, 'volume']
        vol_ratio = signal_vol / avg_vol if avg_vol > 0 else 0

        # 거래량 연속 증가 확인
        recent_vols = before_signal['volume'].tail(4).values
        if len(recent_vols) >= 4:
            vol_increasing = recent_vols[-1] > recent_vols[-2] > recent_vols[-3]
        else:
            vol_increasing = False

        return {
            'symbol': symbol,
            'date': date,
            'time': time_str,
            'signal_vol': signal_vol,
            'avg_vol_prev': avg_vol,
            'vol_ratio': vol_ratio,
            'vol_increasing': vol_increasing
        }
    except Exception as e:
        return None

# 모든 로그 파일 처리
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

# 거래량 패턴 분석
print('='*100)
print('거래량 패턴 분석 중... (시간이 걸릴 수 있습니다)')
print('='*100)

win_analysis = []
loss_analysis = []

# 승리 거래 분석
for i, trade in enumerate(all_wins):
    if i % 50 == 0:
        print(f'승리 거래 분석 중... {i}/{len(all_wins)}')

    result = analyze_signal_point(trade['symbol'], trade['date'], trade['time'])
    if result:
        result['profit'] = trade['profit']
        win_analysis.append(result)

# 패배 거래 분석
for i, trade in enumerate(all_losses):
    if i % 50 == 0:
        print(f'패배 거래 분석 중... {i}/{len(all_losses)}')

    result = analyze_signal_point(trade['symbol'], trade['date'], trade['time'])
    if result:
        result['profit'] = trade['profit']
        loss_analysis.append(result)

print()
print('='*100)
print('분석 완료!')
print('='*100)
print(f'승리 거래 분석 완료: {len(win_analysis)}/{len(all_wins)}건')
print(f'패배 거래 분석 완료: {len(loss_analysis)}/{len(all_losses)}건')
print()

# 통계 계산
if win_analysis:
    avg_ratio_win = sum(d['vol_ratio'] for d in win_analysis) / len(win_analysis)
    increasing_win = sum(1 for d in win_analysis if d['vol_increasing'])

if loss_analysis:
    avg_ratio_loss = sum(d['vol_ratio'] for d in loss_analysis) / len(loss_analysis)
    increasing_loss = sum(1 for d in loss_analysis if d['vol_increasing'])

print('='*100)
print('통계 요약')
print('='*100)
print(f'승리 평균 거래량 비율: {avg_ratio_win:.2f}배')
print(f'승리 연속증가 비율: {increasing_win}/{len(win_analysis)}건 ({increasing_win/len(win_analysis)*100:.1f}%)')
print()
print(f'패배 평균 거래량 비율: {avg_ratio_loss:.2f}배')
print(f'패배 연속증가 비율: {increasing_loss}/{len(loss_analysis)}건 ({increasing_loss/len(loss_analysis)*100:.1f}%)')
print()
print(f'거래량 비율 차이: {avg_ratio_win - avg_ratio_loss:+.2f}배')

# 상세 분포 분석
print()
print('='*100)
print('거래량 비율 분포')
print('='*100)

# 구간별 집계
bins = [0, 0.5, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 100]
bin_labels = ['<0.5x', '0.5-0.8x', '0.8-1.0x', '1.0-1.2x', '1.2-1.5x', '1.5-2.0x', '2.0-3.0x', '>3.0x']

print('승리 거래:')
for i in range(len(bins)-1):
    count = sum(1 for d in win_analysis if bins[i] <= d['vol_ratio'] < bins[i+1])
    pct = count / len(win_analysis) * 100 if win_analysis else 0
    print(f'  {bin_labels[i]:>10s}: {count:>4d}건 ({pct:>5.1f}%)')

print()
print('패배 거래:')
for i in range(len(bins)-1):
    count = sum(1 for d in loss_analysis if bins[i] <= d['vol_ratio'] < bins[i+1])
    pct = count / len(loss_analysis) * 100 if loss_analysis else 0
    print(f'  {bin_labels[i]:>10s}: {count:>4d}건 ({pct:>5.1f}%)')

# 결과 저장
print()
print('='*100)
print('결과를 파일로 저장 중...')
print('='*100)

import json

with open('trade_analysis_results.json', 'w', encoding='utf-8') as f:
    json.dump({
        'summary': {
            'total_wins': len(win_analysis),
            'total_losses': len(loss_analysis),
            'avg_vol_ratio_win': avg_ratio_win,
            'avg_vol_ratio_loss': avg_ratio_loss,
            'increasing_ratio_win': increasing_win / len(win_analysis) if win_analysis else 0,
            'increasing_ratio_loss': increasing_loss / len(loss_analysis) if loss_analysis else 0
        },
        'win_trades': win_analysis,
        'loss_trades': loss_analysis
    }, f, ensure_ascii=False, indent=2)

print('결과 저장 완료: trade_analysis_results.json')
