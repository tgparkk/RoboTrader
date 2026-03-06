# 일봉 필터 사용 가이드

## 개요

일봉 데이터 기반 필터를 통해 승률을 49.6% → 52.7%~53.3%로 개선할 수 있습니다.

## 빠른 시작

### 1. 일봉 필터 켜기/끄기

[config/advanced_filter_settings.py](../config/advanced_filter_settings.py) 파일에서 `ACTIVE_DAILY_PRESET` 값만 변경하면 됩니다.

```python
# 일봉 필터 끄기 (기본값)
ACTIVE_DAILY_PRESET = None

# 일봉 필터 켜기 - 최고 수익 전략 (추천)
ACTIVE_DAILY_PRESET = 'volume_surge'

# 일봉 필터 켜기 - 최고 승률 전략
ACTIVE_DAILY_PRESET = 'consecutive_2days'
```

### 2. 전략 선택 가이드

| 프리셋 | 승률 | 수익 (90%ile) | 거래수 | 특징 | 추천도 |
|--------|------|---------------|--------|------|--------|
| **volume_surge** | 52.7% | **200만원** ⭐ | 262건 | 거래량 급증 포착 | 최고 수익 |
| **consecutive_2days** | **53.3%** 🏆 | 185만원 | 246건 | 연속 상승 확인 | 최고 승률 |
| prev_day_up | 52.7% | 184만원 | 391건 | 전일 상승 종목 | 거래 빈도 유지 |
| consecutive_1day | 52.8% | 182만원 | 381건 | 최소 1일 상승 | 균형잡힌 선택 |
| balanced | 52.5% | 173만원 | 373건 | 복합 조건 | - |
| **None** (필터 없음) | 49.6% ❌ | 144만원 ❌ | 516건 | 필터 미사용 | 비추천 |

### 3. 추천 전략

#### 수익 최우선: `volume_surge`
```python
ACTIVE_DAILY_PRESET = 'volume_surge'  # 거래량 1.5배 이상
```
- 전일 거래량이 20일 평균의 1.5배 이상인 종목만 거래
- 최고 수익: 200만원 (+39% vs 필터 없음)
- 승률: 52.7% (+3.1%p)
- 거래수: 262건 (적절한 수준)

#### 승률 최우선: `consecutive_2days`
```python
ACTIVE_DAILY_PRESET = 'consecutive_2days'  # 2일 연속 상승
```
- 최소 2일 연속 상승한 종목만 거래
- 최고 승률: 53.3% (+3.7%p)
- 수익: 185만원 (+28% vs 필터 없음)
- 거래수: 246건

#### 거래 빈도 유지: `prev_day_up`
```python
ACTIVE_DAILY_PRESET = 'prev_day_up'  # 전일 상승 (보합 포함)
```
- 전일 종가가 상승한 종목만 거래
- 승률: 52.7% (+3.1%p)
- 수익: 184만원
- 거래수: 391건 (많은 편)

## 상세 설정

### 프리셋 대신 개별 필터 설정

`ACTIVE_DAILY_PRESET = None`으로 두고 개별 필터를 직접 제어할 수 있습니다.

#### 연속 상승일 필터
```python
DAILY_CONSECUTIVE_UP = {
    'enabled': True,    # True로 변경
    'min_days': 2,      # 1 또는 2 선택
    'description': '...',
}
```

#### 전일 등락률 필터
```python
DAILY_PREV_CHANGE = {
    'enabled': True,    # True로 변경
    'min_change': 0.0,  # 0% 이상 (보합 포함)
    'description': '...',
}
```

#### 거래량 비율 필터
```python
DAILY_VOLUME_RATIO = {
    'enabled': True,    # True로 변경
    'min_ratio': 1.5,   # 1.5배 이상
    'description': '...',
}
```

#### 가격 위치 필터
```python
DAILY_PRICE_POSITION = {
    'enabled': False,   # 효과 미미 (비활성화 권장)
    'min_position': 0.5,
    'description': '...',
}
```

## 작동 원리

### 일봉 데이터 수집
- 종목 선정 시 과거 20일치 일봉 데이터 자동 로드
- DuckDB 캐시 사용으로 빠른 조회

### 특징 추출
각 종목에 대해 다음 특징을 계산합니다:

1. **연속 상승일 수**: 최근 몇 일 연속 상승했는지
2. **전일 등락률**: 전일 종가 변화율
3. **거래량 비율**: 전일 거래량 / 20일 평균 거래량
4. **가격 위치**: 20일 범위 내 현재 위치 (0~1)

### 필터 적용
매수 신호 발생 시 일봉 특징이 조건을 만족하는지 검증하고, 미달 시 거래를 차단합니다.

## 실전 적용 절차

### 1단계: 일봉 데이터 수집 (최초 1회)
```bash
python scripts/collect_daily_for_analysis.py
```

### 2단계: 설정 파일 수정
[config/advanced_filter_settings.py](../config/advanced_filter_settings.py)에서 프리셋 선택

### 3단계: 시뮬레이션으로 검증 (선택)
```bash
python compare_daily_filters.py
```

### 4단계: 실거래 적용
```bash
python bot.py
```

## 주의사항

### 일봉 데이터 자동 갱신
- 매일 장 마감 후 일봉 데이터가 자동으로 수집됩니다
- 처음 사용 시에만 수동 수집이 필요합니다

### 3분봉 필터와 병행 가능
- `ACTIVE_PRESET` (3분봉 필터)와 `ACTIVE_DAILY_PRESET` (일봉 필터)는 독립적입니다
- 두 필터를 동시에 사용하면 더 엄격한 선별이 이루어집니다

### 과도한 필터링 주의
- 필터가 너무 많으면 거래 기회가 줄어듭니다
- 승률과 거래 빈도의 균형을 고려하세요

## 분석 결과 요약 (2026-01-31)

### 데이터
- 기간: 2025-09-01 ~ 2026-01-29
- 총 거래: 516건
- 투자금: 1,000만원 기준

### 주요 발견
1. **일봉 필터 없이 거래 시 성과가 가장 나쁨**
   - 승률: 49.6% (거의 반반)
   - 수익: 144만원

2. **거래량 급증 필터 (volume_surge) 최고 수익**
   - 승률: 52.7% (+3.1%p)
   - 수익: 200만원 (+39%)
   - 1/7 투자 (142만원/건)

3. **연속 2일 상승 필터 (consecutive_2days) 최고 승률**
   - 승률: 53.3% (+3.7%p)
   - 수익: 185만원 (+28%)
   - 1/7 투자 (142만원/건)

## FAQ

### Q: 일봉 필터를 끄고 싶어요
```python
ACTIVE_DAILY_PRESET = None
```

### Q: 여러 필터를 동시에 사용하고 싶어요
프리셋 대신 개별 필터를 `enabled: True`로 설정하세요.

### Q: 일봉 데이터가 오래되었어요
```bash
python scripts/collect_daily_for_analysis.py
```

### Q: 실시간 거래에서 작동하나요?
네, `trade_date` 파라미터만 전달하면 자동으로 일봉 필터가 적용됩니다.

### Q: 성능에 영향이 있나요?
DuckDB 캐시를 사용하므로 성능 영향은 미미합니다 (1ms 이내).
