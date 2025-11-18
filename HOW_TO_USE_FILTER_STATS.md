# 필터 통계 사용 가이드

## 개요
`filter_stats` 모듈은 각 필터가 차단한 매매 횟수와, 차단된 매매가 실제로는 승리/손실이었는지를 추적합니다.

## 기본 사용법

### 1. 필터 차단 기록 (현재)
```python
from core.indicators.filter_stats import filter_stats

# 마이너스 조합 필터 차단
filter_stats.increment('pattern_combination_filter', 'Stage 1 상승 지속성 부족')

# 종가 위치 필터 차단
filter_stats.increment('close_position_filter', '종가 하단위치 45.2% < 55%')
```

### 2. 차단된 매매의 결과 기록 (신규)
```python
from core.indicators.filter_stats import filter_stats

# 필터가 손실을 막은 경우 (좋은 차단)
filter_stats.increment(
    'pattern_combination_filter',
    'Stage 1 상승 지속성 부족',
    would_win=False  # 필터 없었다면 손실
)

# 필터가 승리를 차단한 경우 (아쉬운 차단)
filter_stats.increment(
    'close_position_filter',
    '종가 하단위치 48.2% < 55%',
    would_win=True  # 필터 없었다면 승리
)

# 결과를 모르는 경우 (실시간)
filter_stats.increment(
    'close_position_filter',
    '종가 하단위치 48.2% < 55%'
    # would_win 생략 = None
)
```

## 시뮬레이션/백테스트에서 사용하기

### signal_replay.py 또는 백테스트 코드에서

```python
# 1. 매수 신호 생성
signals = PullbackCandlePattern.generate_trading_signals(df_3min, ...)

# 2. 각 신호에 대해 처리
for signal in signals:
    # 패턴 분석
    pattern_info = PullbackCandlePattern.analyze_support_pattern(
        data_up_to_signal, debug=True
    )

    # 필터가 차단했는지 확인
    if not pattern_info['has_support_pattern']:
        # ✨ 가상으로 매매를 시뮬레이션하여 결과 계산
        would_win = simulate_virtual_trade(signal, df_3min)

        # 차단 사유 확인
        if '조합 필터' in pattern_info['reasons']:
            filter_stats.increment(
                'pattern_combination_filter',
                pattern_info['reasons'][0],
                would_win=would_win
            )
        elif '종가 위치' in pattern_info['reasons']:
            filter_stats.increment(
                'close_position_filter',
                pattern_info['reasons'][0],
                would_win=would_win
            )
        continue

    # 실제 매매 실행
    execute_trade(signal)

def simulate_virtual_trade(signal, df_3min):
    """
    차단된 신호에 대해 가상으로 매매했다면 승리였는지 계산

    Returns:
        bool: True = 승리, False = 손실
    """
    buy_price = signal['buy_price']
    entry_time = signal['datetime']

    # 매수 후 향후 봉에서 익절/손절 체크
    future_candles = df_3min[df_3min['datetime'] > entry_time].head(20)

    profit_target = buy_price * 1.03  # +3% 익절
    stop_loss = buy_price * 0.975     # -2.5% 손절

    for _, candle in future_candles.iterrows():
        # 익절 도달
        if candle['high'] >= profit_target:
            return True

        # 손절 도달
        if candle['low'] <= stop_loss:
            return False

    # 종가 기준 평가
    final_price = future_candles.iloc[-1]['close']
    return final_price >= buy_price
```

## 통계 확인

```python
from core.indicators.filter_stats import filter_stats

# 통계 요약 출력
print(filter_stats.get_summary())
```

### 출력 예시
```
=== 📊 필터 통계 ===
전체 패턴 체크: 64건
  ✅ 통과: 35건 (54.7%)
  🚫 마이너스 조합 필터 차단: 16건 (25.0%)
     → 필터 없었다면: 승 2건, 패 14건 (승률 12.5%)
  🚫 종가 위치 필터 차단: 13건 (20.3%)
     → 필터 없었다면: 승 3건, 패 10건 (승률 23.1%)
```

## 필터 효과성 평가

- **좋은 필터**: 차단된 매매의 승률이 50% 미만 (손실을 잘 걸러냄)
- **과도한 필터**: 차단된 매매의 승률이 50% 이상 (승리를 너무 많이 차단)

## 주의사항

1. `would_win` 파라미터는 **백테스트/시뮬레이션에서만** 사용 가능
2. 실시간 매매에서는 향후 가격을 알 수 없으므로 `would_win=None` (생략)
3. 정확한 분석을 위해서는 충분한 샘플 (최소 20건 이상) 필요

## 필터 최적화 프로세스

1. 백테스트 실행 (필터 ON)
2. 차단된 매매의 승률 확인
3. 승률이 높으면 필터 완화 검토
4. 승률이 낮으면 필터 유지 또는 강화
5. 전체 시뮬레이션 승률과 비교하여 최종 결정
