# 프리마켓 분석 & 서킷브레이커 시스템

장전 NXT 프리마켓 데이터를 수집하여 당일 시장 심리를 판단하고, 위험 시 매수를 자동 중단하는 시스템입니다.

## 전체 흐름

```
08:00~08:55  NXT 스냅샷 수집 (5분 간격, 최대 12회)
    |
08:55        리포트 생성
    |        +--> 1) 서킷브레이커 체크 (전일 지수 기반)
    |        +--> 2) 심리 점수 계산 (스냅샷 가중 합산)
    |        +--> 3) 의사결정 (매수 중단 / 축소 / 정상)
    |
09:00~       매매 엔진에 리포트 적용 -> 장중 매수 제어
```

## 관련 파일

| 파일 | 역할 |
|------|------|
| `config/strategy_settings.py` > `PreMarket` | 임계값, 파라미터 설정 |
| `core/pre_market_analyzer.py` | 스냅샷 수집, 심리 계산, 리포트 생성 |
| `core/trading_decision_engine.py` | 리포트 적용, 최대 포지션 제어 |
| `main.py` > `_pre_market_task()` | 스냅샷 수집 스케줄링 |

---

## 1단계: NXT 스냅샷 수집

### 수집 대상
`NXT_BELLWETHER_STOCKS` (삼성전자, SK하이닉스 등 KOSPI200/KOSDAQ150 대표 30종목)의 NXT 프리마켓 현재가를 KIS API로 조회합니다.

### 수집 주기
- **08:00 ~ 08:55**, 5분 간격
- 각 스냅샷: 30종목 NXT 현재가 -> 전일종가 대비 등락률 계산
- 상승/하락/보합 종목 수, 평균 등락률, NXT 거래량 기록

### 코드 경로
`main.py:_pre_market_task()` -> `PreMarketAnalyzer.collect_snapshot()`

---

## 2단계: 서킷브레이커 체크

`generate_report()` 호출 시 가장 먼저 실행됩니다. DB(`daily_candles`)에서 전일 KOSPI/KOSDAQ 종가를 조회하여 판단합니다.

### 조건1: 전일 급락

```
전일 KOSPI 또는 KOSDAQ 등락률 <= -3.0%  -->  매수 완전 중단
```

- 설정: `CIRCUIT_BREAKER_PREV_DAY_PCT = -3.0` (4년 일봉 시뮬: -3% 이하만 마이너스)
- 코드: `_check_circuit_breaker()`

### 조건1b: 전일 소폭 하락 → 손절 축소

```
전일 KOSPI 또는 KOSDAQ 등락률 <= -1.0%  -->  매수 유지, 손절 3%/익절 4%로 축소
```

- 설정: `PREV_DAY_DECLINE_THRESHOLD = -1.0`, `PREV_DAY_DECLINE_STOP_LOSS_RATIO = 0.03`
- 코드: `_check_circuit_breaker()`

### 조건2: 전일 하락 + NXT 갭다운 복합

```
전일 지수 <= -1.0%  AND  NXT 갭 <= -0.5%  -->  매수 완전 중단
```

- 설정: `CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP = -1.0`, `CIRCUIT_BREAKER_NXT_GAP_PCT = -0.5`
- 코드: `_check_circuit_breaker_with_gap()`
- 5년 검증 결과: 적중률 61.3%, 손익비 2.60

### 해제 조건: 강한 반등

```
서킷브레이커 발동 상태에서 NXT 갭 >= +3.0%  -->  해제 (정상 복귀)
```

- 해제 시: 최대 포지션 5종목, neutral 모드(손절 5% / 익절 6%) — 정상 운영으로 전면 복귀
- 설정: `CIRCUIT_BREAKER_RELEASE_GAP_PCT = 3.0`

---

## 3단계: 심리 점수 계산

수집된 스냅샷들을 가중 합산하여 -1.0 ~ +1.0 범위의 심리 점수를 산출합니다.

### 가중치 구조

| 요소 | 비중 | 계산 방법 | 정규화 |
|------|------|-----------|--------|
| 방향 점수 | 40% | 가중 평균 등락률 | +-1%를 +-1.0으로 |
| 폭 점수 | 30% | (상승 - 하락) / 전체 종목 수 | 이미 -1~+1 범위 |
| 추세 점수 | 30% | 후반 스냅샷 평균 - 전반 스냅샷 평균 | +-0.5%를 +-1.0으로 |

### 시간 가중치
- **08:30 이전** 스냅샷: 가중치 1.0
- **08:30 이후** 스냅샷: 가중치 **2.0** (장 직전 데이터가 더 중요)

### 심리 분류

| 점수 범위 | 분류 | 동작 |
|-----------|------|------|
| <= -0.9 | `extreme_bearish` | 매수 완전 중단 (0종목) |
| <= -0.7 | `very_bearish` | 최대 3종목, 손절 3% / 익절 4% (매수 허용) |
| <= -0.3 | `bearish` | 최대 3종목, 손절 3% / 익절 4% |
| >= +0.3 | `bullish` | 정상 5종목, 손절 5% / 익절 6% |
| 그 외 | `neutral` | 정상 5종목, 손절 5% / 익절 6% |

코드: `_calculate_sentiment_score()`, `_score_to_sentiment()`

---

## 4단계: 의사결정 분기

`generate_report()` 내부의 의사결정 우선순위:

```
1. 서킷브레이커 발동 상태?
   |-- YES --> NXT 갭 >= +3%?
   |           |-- YES --> 해제 (정상 복귀: 5종목, neutral 모드)
   |           |-- NO  --> 매수 완전 중단 (circuit_breaker)
   |
   |-- NO  --> 심리 = extreme_bearish (NXT <= -0.9)?
               |-- YES --> 매수 완전 중단 (조건3: NXT 자체 극약세)
               |-- NO  --> 심리 = very_bearish (NXT <= -0.7)?
                           |-- YES --> 3종목, 손절 3%/익절 4% (매수 허용)
                           |-- NO  --> 심리 = bearish (NXT <= -0.3)?
                                       |-- YES --> 복합 조건2 체크
                                       |           |-- 발동 --> 매수 중단
                                       |           |-- 미발동 --> 3종목, bearish 모드
                                       |-- NO  --> 정상 운영 (5종목)
```

### 조건3: NXT 자체 극약세 (전일 지수 무관)

서킷브레이커 조건1,2는 "전일 지수 하락"이 전제입니다. 하지만 전일이 급등이더라도 NXT에서 극약세(-0.9 이하)가 감지되면 매수를 중단합니다. -0.7~-0.9 구간은 very_bearish로 매수는 허용하되 손절을 축소합니다.

- 설정: `EXTREME_BEARISH_THRESHOLD = -0.9`, `VERY_BEARISH_THRESHOLD = -0.7`
- 전형적 발동 패턴: 전일 급등 -> 당일 갭다운 되돌림

---

## 5단계: 장중 적용

리포트가 `trading_decision_engine.set_pre_market_report()`로 전달되면, 장중 매수 판단 시 `get_effective_max_positions()`가 리포트의 `recommended_max_positions` 값을 반환합니다.

```python
# 매수 판단 시 (trading_decision_engine.py)
effective_max = self.get_effective_max_positions()  # 리포트의 max_positions
if current_holding >= effective_max:
    return False, "동시 보유 최대 N종목 도달 (프리마켓: extreme_bearish)"
```

매수 중단 시에도 스크리너는 정상 동작하며, 장 마감 데이터 저장도 정상 수행됩니다.

---

## 설정 요약

`config/strategy_settings.py` > `PreMarket` 클래스:

```python
# 심리 임계값 (5단계: extreme_bearish / very_bearish / bearish / neutral / bullish)
BEARISH_THRESHOLD = -0.3
VERY_BEARISH_THRESHOLD = -0.7       # 강약세 (손절축소, 매수 허용)
EXTREME_BEARISH_THRESHOLD = -0.9    # 극약세 (매수 완전 중단)
BULLISH_THRESHOLD = 0.3

# 약세장 파라미터 (bearish: -0.3 이하)
BEARISH_MAX_POSITIONS = 3
BEARISH_STOP_LOSS_RATIO = 0.03    # 5% → 3%
BEARISH_TAKE_PROFIT_RATIO = 0.04  # 6% → 4%

# 강약세장 파라미터 (very_bearish: -0.7 ~ -0.9)
VERY_BEARISH_MAX_POSITIONS = 3
VERY_BEARISH_STOP_LOSS_RATIO = 0.03   # 3%
VERY_BEARISH_TAKE_PROFIT_RATIO = 0.04 # 4%

# 극약세장 (extreme_bearish: -0.9 이하)
EXTREME_BEARISH_MAX_POSITIONS = 0  # 매수 중단

# 서킷브레이커: 전일 지수 기반
CIRCUIT_BREAKER_PREV_DAY_PCT = -3.0           # 조건1: 전일 -3% → 매수 중단
PREV_DAY_DECLINE_THRESHOLD = -1.0             # 조건1b: 전일 -1% → 손절 축소
PREV_DAY_DECLINE_STOP_LOSS_RATIO = 0.03       # 조건1b: 손절 3%
PREV_DAY_DECLINE_TAKE_PROFIT_RATIO = 0.04     # 조건1b: 익절 4%
CIRCUIT_BREAKER_PREV_DAY_PCT_WITH_GAP = -1.0  # 조건2: 전일 -1%
CIRCUIT_BREAKER_NXT_GAP_PCT = -0.5            # 조건2: + NXT 갭 -0.5%
CIRCUIT_BREAKER_RELEASE_GAP_PCT = 3.0         # 해제: NXT 갭 +3% → 정상 복귀 (5종목, neutral)

# 장 시작 갭 체크
MARKET_OPEN_GAP_CHECK_ENABLED = True
MARKET_OPEN_GAP_THRESHOLD_PCT = -1.5          # 지수 시가 갭 -1.5% 이하 → 매수 중단
MARKET_OPEN_GAP_CHECK_MINUTE = 1              # 09:01에 체크

# 장중 지수 모니터링
INTRADAY_INDEX_CHECK_ENABLED = True
INTRADAY_INDEX_CHECK_INTERVAL_MINUTES = 30    # 30분 주기
INTRADAY_INDEX_DROP_THRESHOLD_PCT = -2.0      # 전일 대비 -2% 이하 → 매수 중단
INTRADAY_INDEX_RECOVERY_PCT = -1.0            # -1% 이상 회복 시 → 매수 재개
```

---

## 로그 확인

```bash
# 스냅샷 수집 현황
grep "스냅샷 #" logs/trading_YYYYMMDD.log

# 서킷브레이커 발동 여부
grep "서킷브레이커" logs/trading_YYYYMMDD.log

# 심리 점수 상세
grep "심리 점수" logs/trading_YYYYMMDD.log

# 리포트 적용 결과
grep "리포트 적용" logs/trading_YYYYMMDD.log

# 매수 차단 사유
grep "최대.*종목 도달" logs/trading_YYYYMMDD.log
```

---

## 발동 사례

### 2026-03-06: 조건3 (NXT 극약세) 발동

- 전일: KOSPI +9.63%, KOSDAQ +14.10% (급등) -> 조건1,2 해당 없음
- NXT: 30종목 중 25~29개 하락, 평균 -1.95%
- 심리 점수: **-0.86** (방향 -1.00, 폭 -0.62, 추세 -0.91)
- 결과: `extreme_bearish` -> 매수 완전 중단
- 사후 분석: 실제 매매했다면 5건 전승 +1.29% 예상 (오판 케이스)

### 2026-03-04: 조건1 (전일 급락) 발동

- 전일 KOSPI/KOSDAQ 급락 -> 매수 완전 중단
- 결과: 실손실 0원 (실제 2건 시뮬 시 0승 2패, -4.00% 예상)
