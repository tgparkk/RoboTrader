# RoboTrader 매매 로직 문서

## 개요

RoboTrader는 장중 종목 선정 이후 분봉 데이터 수집과 눌림목 매매 전략을 통해 자동 매매를 수행하는 시스템입니다.

## 1. 분봉 데이터 수집 시스템

### 1.1 데이터 수집 구조

**핵심 파일**: `core/data_collector.py`, `api/kis_chart_api.py`

분봉 데이터 수집은 두 가지 방식으로 동작합니다:

#### 실시간 데이터 수집 (RealTimeDataCollector)
- **수집 주기**: 설정 가능한 간격으로 실시간 수집
- **대상**: 후보 종목들의 현재가 및 거래량 정보
- **비동기 처리**: ThreadPoolExecutor를 사용하여 동시 수집

#### 분봉 히스토리 데이터 수집 (KIS API)
- **API**: 한국투자증권 Open API
- **수집 방식**: 
  - 당일분봉: `FHKST03010200` (최대 30건)
  - 일별분봉: `FHKST03010230` (최대 120건)
- **데이터 형식**: OHLCV (시가/고가/저가/종가/거래량)

### 1.2 분봉 데이터 수집 프로세스

```python
# 전체 거래시간 분봉 수집
def get_full_trading_day_data(stock_code: str, target_date: str = "", selected_time: str = "")
```

**수집 범위**:
- KRX 종목: 09:00 ~ 15:30
- NXT 종목: 08:00 ~ 15:30

**수집 전략**:
1. API 제한(120건)을 우회하기 위해 시간 구간을 분할
2. 구간별 수집: 2시간 단위로 분할하여 순차 수집
3. 데이터 중복 제거 및 시간순 정렬
4. 폴백 메커니즘: 데이터 없을 시 최대 3일 이전까지 시도

### 1.3 데이터 전처리

**컬럼 표준화**:
```
stck_prpr -> close (종가)
stck_oprc -> open (시가)
stck_hgpr -> high (고가)
stck_lwpr -> low (저가)
cntg_vol -> volume (거래량)
stck_bsop_date -> date (날짜)
stck_cntg_hour -> time (시간)
```

**데이터 검증**:
- 숫자 컬럼 안전 변환
- 날짜/시간 파싱 및 datetime 컬럼 생성
- 시간순 정렬 및 중복 제거

## 2. 눌림목 매매 전략

### 2.1 전략 개요

**기본 원리**: 주가 상승 후 저거래량 조정 구간에서 거래량 회복과 함께 나타나는 반등 신호를 포착

**적용 시간프레임**: 3분봉 (권장)

### 2.2 매수 신호 조건

#### 핵심 구성요소

1. **이등분선 (Bisector Line)**
   - 계산: `(최근 고점 + 최근 저점) / 2`
   - 역할: 주요 지지/저항선 역할

2. **기준 거래량 (Baseline Volume)**
   - 계산: 당일 최대 거래량
   - 용도: 저거래량/고거래량 구분 기준

#### 매수 신호 패턴

**패턴 1: 눌림목 캔들패턴**
```python
# 조건 확인 순서:
1. 저거래 하락 조정 (최근 2-3봉, 기준 거래량의 25% 이하)
2. 회복 양봉 (현재 캔들이 양봉)
3. 거래량 회복 (직전 저거래량보다 증가)
4. 이등분선 지지/돌파 (현재가 >= 이등분선 또는 돌파)
```

**패턴 2: 이등분선 회복**
```python
# 조건:
1. 이등분선 아래에서 위로 돌파
2. 양봉으로 돌파
3. 충분한 거래량 (직전 봉의 2배 이상)
```

### 2.3 신호 강도 계산

**신호 타입**:
- `STRONG_BUY`: 신뢰도 80% 이상, 목표 수익률 2.5%
- `CAUTIOUS_BUY`: 신뢰도 65% 이상, 목표 수익률 2.0%
- `WAIT`: 신뢰도 40% 이상, 목표 수익률 1.5%
- `AVOID`: 신뢰도 40% 미만

**점수 체계**:
```python
confidence = 0
if is_recovery_candle: confidence += 20    # 회복양봉
if volume_recovers: confidence += 25       # 거래량회복
if has_retrace: confidence += 15           # 저거래조정
if bisector_holding: confidence += 20      # 이등분선지지
if crosses_bisector_up: confidence += 15   # 이등분선돌파
if volume_surge: confidence += 10          # 거래량급증

# 페널티
if has_overhead_supply: confidence -= 15   # 머리위물량
if bisector_broken: confidence -= 20       # 이등분선이탈
```

### 2.4 매수 실행

#### 매수 가격 결정
**3/5가 방식**:
```python
# 3분봉 기준 변곡점 캔들의 3/5 지점 계산
three_fifths_price = low + (high - low) * 0.6
```

#### 매수 수량
- 가상 매매: 설정된 투자 금액 기준 최대 수량
- 실전 매매: 계좌 잔고 기준 계산

### 2.5 매도 조건

#### 손절 조건 (우선순위 순)

1. **신호 강도별 손절**
   ```python
   stop_loss_rate = target_profit_rate / 2.0  # 손익비 2:1
   if profit_rate <= -stop_loss_rate: SELL
   ```

2. **기술적 손절**
   - 이등분선 0.2% 이탈
   - 진입 양봉 저가 0.2% 이탈
   - 지지 저점 이탈

#### 익절 조건

1. **신호 강도별 익절**
   ```python
   # 신호 타입별 목표 수익률 달성시 익절
   if profit_rate >= target_profit_rate: SELL
   ```

### 2.6 위험 관리

#### 회피 조건

1. **거래량 회복 미충족**: 기본 필수 조건
2. **매물 부담**: 3% 상승 후 하락시 고거래량
3. **음봉 최대거래량 제한**: 당일 최대 음봉보다 큰 양봉 대기
4. **이등분선 돌파 거래량 부족**: 직전 봉의 2배 미만

#### 실시간 모니터링
- 30초마다 현재가 기반 손익 체크
- 3분봉 확정시 정밀 기술적 분석
- 캐시된 실시간 현재가 활용

## 3. 시스템 구조

### 3.1 주요 클래스

**TradingDecisionEngine** (`core/trading_decision_engine.py`)
- 매수/매도 판단 총괄
- 가상 매매 실행
- 전략별 손익 관리

**PullbackCandlePattern** (`core/indicators/pullback_candle_pattern.py`)
- 눌림목 패턴 신호 계산
- 매수/매도 조건 검증
- 신호 강도 평가

**VolumeAnalyzer** (`core/indicators/pullback/volume_analyzer.py`)
- 거래량 패턴 분석
- 기준 거래량 계산
- 거래량 회복 판단

### 3.2 데이터 플로우

```
1. 분봉 데이터 수집 (1분봉)
   ↓
2. 3분봉 변환 (TimeFrameConverter)
   ↓
3. 눌림목 패턴 분석 (PullbackCandlePattern)
   ↓
4. 신호 강도 계산 (SignalCalculator)
   ↓
5. 매매 판단 (TradingDecisionEngine)
   ↓
6. 가상 매매 실행 (VirtualTradingManager)
```

### 3.3 백테스팅 및 리플레이

**신호 리플레이** (`utils/signal_replay.py`)
- 과거 데이터로 신호 재현
- 전략 성능 검증
- 매개변수 최적화

## 4. 설정 및 매개변수

### 4.1 주요 설정값

```python
# 거래량 분석
low_volume_threshold = 0.25      # 저거래량 기준 (25%)
volume_recovery_ratio = 1.0      # 거래량 회복 기준

# 캔들 분석
min_body_pct = 0.5              # 최소 실체 크기 (0.5%)
bisector_tolerance = 0.005       # 이등분선 허용 오차 (0.5%)

# 손절/익절
stop_loss_tolerance = 0.002      # 손절 허용 오차 (0.2%)
profit_target_ratios = {         # 신호별 목표 수익률
    'STRONG_BUY': 0.025,        # 2.5%
    'CAUTIOUS_BUY': 0.020,      # 2.0%
    'WAIT': 0.015               # 1.5%
}
```

### 4.2 시간 관리

**3분봉 확정 체크**:
```python
# 3분봉 라벨 + 3분 경과 후 확정
candle_end_time = last_candle_time + pd.Timedelta(minutes=3)
is_confirmed = current_time >= candle_end_time
```

## 5. 매수 체결 실패 처리

### 5.1 체결 실패 원인

**API 레벨 실패**:
- 주문 API 호출 실패 (네트워크, 서버 오류)
- 주문번호(ODNO) 미반환
- 계좌 잔고 부족
- 호가 단위 위반
- 거래소 시스템 오류

**주문 레벨 실패**:
- 체결 타임아웃 (설정된 시간 경과)
- 3분봉 타임아웃 (매수 주문 후 3봉 경과)
- 가격 괴리로 인한 미체결
- 거래량 부족

### 5.2 실패 감지 메커니즘

#### 실시간 주문 모니터링
```python
# OrderManager의 모니터링 주기
await self._monitor_pending_orders()  # 10초마다 실행

# 체결 상태 확인
status_data = await self.api_manager.get_order_status(order_id)
```

**체결 상태 분류**:
- `FILLED`: 전량 체결 완료
- `PARTIAL`: 부분 체결
- `CANCELLED`: 취소됨
- `PENDING`: 미체결 대기 중

#### 타임아웃 조건

**1. 일반 타임아웃**:
```python
timeout_seconds = config.order_management.buy_timeout_seconds
# 설정된 시간(예: 300초) 경과 시 주문 취소
```

**2. 3분봉 기준 타임아웃**:
```python
# 매수 주문 후 3분봉 3개(9분) 경과 시 강제 취소
def _has_3_candles_passed(self, order_candle_time: datetime) -> bool:
    three_candles_later = order_candle_time + timedelta(minutes=9)
    return now_time >= three_candles_later
```

### 5.3 실패 처리 흐름

#### 매수 주문 실행 단계
```python
1. 매수 신호 발생
   ↓
2. place_buy_order() 호출
   ↓  
3. KIS API 주문 전송
   ↓
4. 주문번호 수신 확인
   ↓
5. 미체결 관리에 등록 (pending_orders)
```

#### 실패 감지 및 처리
```python
1. 주문 모니터링 (10초 주기)
   ↓
2. 체결 상태 확인
   ↓
3. 타임아웃 조건 체크
   - 일반 타임아웃 (예: 5분)
   - 3분봉 타임아웃 (9분)
   ↓
4. 미체결 주문 취소
   ↓
5. 종목 상태 복구 (BUY_PENDING → BUY_CANDIDATE)
```

### 5.4 상태 관리 및 복구

**종목 상태 변화**:
```python
# 정상 흐름
BUY_CANDIDATE → BUY_PENDING → POSITIONED

# 체결 실패 시
BUY_PENDING → BUY_CANDIDATE  # 재시도 가능 상태로 복구
```

**복구 메커니즘**:
- 미체결 주문 자동 취소
- 종목을 매수 후보로 재등록
- 다음 매수 조건 발생 시 재시도 가능

### 5.5 알림 및 로깅

#### 체결 실패 알림
```python
# 텔레그램 알림 (OrderManager)
await self.telegram.notify_order_cancelled({
    'stock_code': stock_code,
    'stock_name': stock_name,
    'order_type': 'buy'
}, reason)
```

#### 로깅 레벨
- `INFO`: 정상 주문 및 체결
- `WARNING`: 타임아웃 및 취소
- `ERROR`: API 오류 및 시스템 장애

**로그 예시**:
```
⏰ 주문 타임아웃: ORDER_123 (005930) - 일반 타임아웃
📊 매수 주문 3봉 타임아웃: ORDER_456 (삼성전자) - 3분봉 경과
❌ 매수 주문 실패: API 호출 오류 - 잔고 부족
```

### 5.6 개선 방안

**가격 정정 기능** (현재 비활성화):
```python
# 미체결 시 현재가 추적하여 가격 정정
if current_price > order.price * 1.005:  # 0.5% 괴리
    new_price = current_price * 1.001     # 현재가 + 0.1%
    await self._adjust_order_price(order_id, new_price)
```

**재시도 로직**:
- 동일 봉 내 재주문 방지
- 연속 실패 시 일시 제외
- 호가 단위 자동 조정

**성능 개선**:
- 주문 모니터링 주기 최적화
- API 호출 빈도 조절
- 캐시된 현재가 활용

## 6. 로깅 및 모니터링

### 6.1 신호 디버깅
- 실시간 신호 상태 로깅
- 미충족 조건 분석
- 신호 일관성 검증

### 6.2 성과 추적
- 가상 매매 손익 기록
- 전략별 성과 분석
- 텔레그램 알림 연동

### 6.3 주문 체결 모니터링
- 실시간 체결 상태 추적
- 타임아웃 및 실패 감지
- 자동 복구 및 재시도 메커니즘

---

**참고**: 본 문서는 2024년 12월 기준 코드베이스를 바탕으로 작성되었습니다. 실제 매매시에는 충분한 테스트와 검증을 거쳐 사용하시기 바랍니다.