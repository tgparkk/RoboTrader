import pickle
import pandas as pd
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 승리 종목
wins = [
    ('000990', '09:36'),
    ('174900', '09:39'),
    ('007810', '09:51'),
    ('004800', '09:57'),
    ('000990', '10:36'),
    ('000230', '11:58')
]

# 패배 종목
losses = [
    ('053950', '09:33'),
    ('140430', '09:36'),
    ('077360', '09:42'),
    ('092300', '09:43'),
    ('281820', '09:44'),
    ('114190', '09:45'),
    ('089970', '09:57'),
    ('140430', '10:03'),
    ('243880', '10:18'),
    ('174900', '10:24'),
    ('007810', '11:13')
]

def analyze_signal_point(symbol, time_str):
    """매수 신호 발생 시점의 거래량 패턴 분석 (3분봉 기준)"""
    try:
        with open(f'cache/minute_data/{symbol}_20251111.pkl', 'rb') as f:
            df_1min = pickle.load(f)

        # datetime을 인덱스로 설정
        df_1min = df_1min.set_index('datetime')

        # 1분봉을 3분봉으로 재구성
        df_3min = df_1min.resample('3T', label='right', closed='right').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum'
        }).dropna()

        # 시간 파싱 (3분봉의 마지막 시점)
        target_time = pd.Timestamp(f'2025-11-11 {time_str}:00')

        # 해당 시점 찾기
        if target_time not in df_3min.index:
            idx = df_3min.index.get_indexer([target_time], method='nearest')[0]
            target_time = df_3min.index[idx]

        signal_idx = df_3min.index.get_loc(target_time)

        # 신호봉 포함 직전 5개 3분봉 (15분)
        start_idx = max(0, signal_idx - 4)
        before_signal = df_3min.iloc[start_idx:signal_idx+1]

        # 통계 계산
        avg_vol = before_signal['volume'][:-1].mean()  # 신호봉 제외한 평균
        signal_vol = df_3min.loc[target_time, 'volume']
        vol_ratio = signal_vol / avg_vol if avg_vol > 0 else 0

        # 거래량 증가 추세 확인 (최근 3개 3분봉)
        recent_vols = before_signal['volume'].tail(4).values  # 신호봉 포함 4개
        if len(recent_vols) >= 4:
            vol_increasing = recent_vols[-1] > recent_vols[-2] > recent_vols[-3]
        else:
            vol_increasing = False

        # 직전 4개 3분봉의 거래량 리스트
        prev_4_vols = before_signal['volume'][:-1].tail(4).values if len(before_signal) >= 5 else []

        return {
            'symbol': symbol,
            'time': time_str,
            'signal_vol': signal_vol,
            'avg_vol_prev': avg_vol,
            'vol_ratio': vol_ratio,
            'vol_increasing': vol_increasing,
            'prev_vols': prev_4_vols,
            'close': df_3min.loc[target_time, 'close']
        }
    except Exception as e:
        print(f"Error {symbol}: {e}")
        return None

print('='*100)
print('WIN - 승리 종목 매수 시점 분석 (3분봉 기준: 신호봉 vs 직전 4개 3분봉 평균)')
print('='*100)
win_data = []
for symbol, time in wins:
    data = analyze_signal_point(symbol, time)
    if data:
        inc_mark = 'UP' if data['vol_increasing'] else '--'
        print(f"{symbol} {time} | 신호봉:{data['signal_vol']:>10,} | 평균(4봉):{data['avg_vol_prev']:>10,.0f} | 비율:{data['vol_ratio']:>5.2f}x | {inc_mark}")
        win_data.append(data)

print()
print('='*100)
print('LOSS - 패배 종목 매수 시점 분석 (3분봉 기준: 신호봉 vs 직전 4개 3분봉 평균)')
print('='*100)
loss_data = []
for symbol, time in losses:
    data = analyze_signal_point(symbol, time)
    if data:
        inc_mark = 'UP' if data['vol_increasing'] else '--'
        print(f"{symbol} {time} | 신호봉:{data['signal_vol']:>10,} | 평균(4봉):{data['avg_vol_prev']:>10,.0f} | 비율:{data['vol_ratio']:>5.2f}x | {inc_mark}")
        loss_data.append(data)

print()
print('='*100)
print('통계 비교')
print('='*100)
if win_data:
    avg_ratio_win = sum(d['vol_ratio'] for d in win_data) / len(win_data)
    increasing_count = sum(1 for d in win_data if d['vol_increasing'])
    print(f'승리 평균 거래량 비율: {avg_ratio_win:.2f}배')
    print(f'승리 거래량 연속증가: {increasing_count}/{len(win_data)}건 ({increasing_count/len(win_data)*100:.1f}%)')

if loss_data:
    avg_ratio_loss = sum(d['vol_ratio'] for d in loss_data) / len(loss_data)
    increasing_count = sum(1 for d in loss_data if d['vol_increasing'])
    print(f'패배 평균 거래량 비율: {avg_ratio_loss:.2f}배')
    print(f'패배 거래량 연속증가: {increasing_count}/{len(loss_data)}건 ({increasing_count/len(loss_data)*100:.1f}%)')

print()
print('='*100)
print('차이점')
print('='*100)
if win_data and loss_data:
    ratio_diff = avg_ratio_win - avg_ratio_loss
    print(f'거래량 비율 차이: {ratio_diff:+.2f}배')
    if ratio_diff > 0:
        print('-> 승리 종목이 신호봉에서 더 큰 거래량 증가')
    else:
        print('-> 패배 종목이 신호봉에서 더 큰 거래량 증가')
