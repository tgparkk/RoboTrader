# ML 특징 확장 제안서

## 현재 상태
- 특징 수: 26개
- 주요 문제: 과적합, 최신 데이터 성능 저하

## 추가 특징 제안 (20+ 개)

### 1. 거래량 관련 (7개)
```python
# 거래량 변동성
'uptrend_volume_std': np.std([c['volume'] for c in uptrend_candles_data])
'decline_volume_std': np.std([c['volume'] for c in decline_candles_data])
'support_volume_std': np.std([c['volume'] for c in support_candles_data])

# 거래량 최소값
'uptrend_min_volume': np.min([c['volume'] for c in uptrend_candles_data])
'decline_min_volume': np.min([c['volume'] for c in decline_candles_data])
'support_min_volume': np.min([c['volume'] for c in support_candles_data])

# 돌파양봉 대비 지지구간 거래량 비율
'volume_ratio_breakout_to_support': breakout_volume / support_avg_volume if support_avg_volume > 0 else 0
```

### 2. 가격 변동성 (8개)
```python
# 각 구간의 고가-저가 범위
'uptrend_price_range': np.mean([c['high'] - c['low'] for c in uptrend_candles_data])
'decline_price_range': np.mean([c['high'] - c['low'] for c in decline_candles_data])
'support_price_range': np.mean([c['high'] - c['low'] for c in support_candles_data])

# 가격 변동률 (표준편차)
'uptrend_price_std': np.std([c['close'] for c in uptrend_candles_data])
'decline_price_std': np.std([c['close'] for c in decline_candles_data])
'support_price_std': np.std([c['close'] for c in support_candles_data])

# 하락 깊이 (최고점 대비)
'decline_depth_from_peak': (max_price_in_uptrend - min_price_in_decline) / max_price_in_uptrend

# 회복률 (지지에서 돌파까지)
'recovery_rate': (breakout_close - support_min_price) / support_min_price if support_min_price > 0 else 0
```

### 3. 캔들 패턴 (6개)
```python
# 양봉/음봉 비율
'uptrend_bullish_ratio': sum([1 for c in uptrend_candles_data if c['close'] > c['open']]) / uptrend_candles
'decline_bearish_ratio': sum([1 for c in decline_candles_data if c['close'] < c['open']]) / decline_candles if decline_candles > 0 else 0
'support_bullish_ratio': sum([1 for c in support_candles_data if c['close'] > c['open']]) / support_candles if support_candles > 0 else 0

# 평균 캔들 몸통 크기
'decline_avg_body': np.mean([abs(c['close'] - c['open']) for c in decline_candles_data])
'support_avg_body': np.mean([abs(c['close'] - c['open']) for c in support_candles_data])

# 돌파양봉 특성
'breakout_body_ratio': breakout_body / breakout_range if breakout_range > 0 else 0  # 몸통/전체 비율
```

### 4. 추세 강도 (4개)
```python
# 상승 속도 (캔들당 상승률)
'uptrend_gain_per_candle': uptrend_gain / uptrend_candles if uptrend_candles > 0 else 0

# 하락 속도 (캔들당 하락률)
'decline_loss_per_candle': abs(decline_pct) / decline_candles if decline_candles > 0 else 0

# 전체 패턴 길이
'total_pattern_candles': uptrend_candles + decline_candles + support_candles + 1

# 지지 기간 비율
'support_duration_ratio': support_candles / (uptrend_candles + decline_candles + support_candles) if (uptrend_candles + decline_candles + support_candles) > 0 else 0
```

### 5. 이등분선 관련 (3개)
```python
# signal_snapshot에서 추출 가능
'bisector_distance': signal_snapshot.get('bisector_distance', 0)  # 이등분선까지 거리
'is_above_bisector': 1 if signal_snapshot.get('current_price', 0) > signal_snapshot.get('bisector_price', 0) else 0
'bisector_support_strength': signal_snapshot.get('bisector_support_count', 0)  # 이등분선 터치 횟수
```

### 6. 시간 관련 추가 (3개)
```python
# 장 초반/중반/후반
'session_early': 1 if time_in_minutes < 630 else 0  # 9:00-10:30
'session_middle': 1 if 630 <= time_in_minutes < 810 else 0  # 10:30-13:30
'session_late': 1 if time_in_minutes >= 810 else 0  # 13:30-15:30

# 또는
'time_segment': 0 if time_in_minutes < 630 else (1 if time_in_minutes < 810 else 2)
```

### 7. 거래량 집중도 (3개)
```python
# 상승구간에서 거래량 집중도 (최대/평균)
'uptrend_volume_concentration': uptrend_max_volume / volume_avg if volume_avg > 0 else 0

# 돌파양봉 거래량이 지지구간 최대치 대비
'breakout_vs_support_max': breakout_volume / max([c['volume'] for c in support_candles_data]) if support_candles_data else 0

# 전체 패턴의 거래량 변동 계수 (CV)
'total_volume_cv': np.std(all_volumes) / np.mean(all_volumes) if np.mean(all_volumes) > 0 else 0
```

## 총 추가 특징: 34개

### 우선순위

**High Priority (실제 패턴과 직접 관련):**
1. 거래량 변동성 (std)
2. 양봉/음봉 비율
3. 하락 깊이
4. 회복률
5. 돌파양봉 몸통 비율
6. 상승/하락 속도

**Medium Priority:**
7. 가격 범위 관련
8. 시간대 세분화
9. 거래량 집중도
10. 이등분선 관련

**Low Priority:**
11. 기타 파생 비율들

## 구현 전략

### 1단계: High Priority 특징 추가 (10개)
- 빠르게 구현 가능
- 패턴의 핵심 특성 반영
- 예상 효과: AUC +0.05~0.10

### 2단계: 데이터 검증
- 새 특징으로 11월 데이터 재학습
- 1월 백테스트로 검증
- 기존 ML(+20만원)과 비교

### 3단계: 추가 특징 실험
- Medium Priority 추가
- Feature Importance 분석
- 불필요한 특징 제거

## 예상 효과

**긍정적:**
- 더 많은 정보 → 더 정확한 예측
- 패턴의 미묘한 차이 포착
- 과적합 방지 (적절한 특징 선택 시)

**주의사항:**
- 너무 많은 특징 → 과적합 위험
- 데이터 부족 시 효과 제한
- Feature Selection 필요

## 다음 단계

1. High Priority 특징 구현
2. ml_prepare_dataset.py 수정
3. 11월 데이터로 재학습
4. 1월 백테스트 검증
5. 성능 비교 및 최적화
