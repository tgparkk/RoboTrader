# 종목 상태 관리 시스템

## 개요

RoboTrader의 종목 상태 관리 시스템은 조건검색으로 선정된 종목부터 매수/매도 완료까지의 전체 라이프사이클을 통합 관리합니다.

## 종목 상태 (StockState)

### 상태 정의

```python
class StockState(Enum):
    SELECTED = "selected"           # 조건검색으로 선정됨
    BUY_CANDIDATE = "buy_candidate" # 매수 후보
    BUY_PENDING = "buy_pending"     # 매수 주문 중
    POSITIONED = "positioned"       # 매수 완료 (포지션 보유)
    SELL_CANDIDATE = "sell_candidate" # 매도 후보
    SELL_PENDING = "sell_pending"   # 매도 주문 중
    COMPLETED = "completed"         # 거래 완료
    FAILED = "failed"              # 거래 실패
```

### 상태 변화 흐름

```
조건검색 선정
    ↓
SELECTED (선정됨)
    ↓ move_to_buy_candidate()
BUY_CANDIDATE (매수 후보)
    ↓ execute_buy_order()
BUY_PENDING (매수 주문 중)
    ↓ 매수 체결 완료
POSITIONED (포지션 보유)
    ↓ move_to_sell_candidate()
SELL_CANDIDATE (매도 후보)
    ↓ execute_sell_order()
SELL_PENDING (매도 주문 중)
    ↓ 매도 체결 완료
COMPLETED (거래 완료)
```

### 예외 상황 처리

- **매수 실패**: `BUY_PENDING` → `BUY_CANDIDATE` (재시도 가능)
- **매도 실패**: `SELL_PENDING` → `SELL_CANDIDATE` (재시도 가능)
- **거래 실패**: 모든 상태에서 → `FAILED`
- **강제 종료**: 모든 상태에서 → `COMPLETED`

## 주요 관리 클래스

### 1. TradingStockManager (통합 관리자)

**위치**: `core/trading_stock_manager.py`

**역할**: 
- 종목별 거래 상태 통합 관리
- 상태 변화에 따른 자동 처리
- 매수/매도 후보 관리
- 포지션 및 주문 상태 동기화

**핵심 변수**:
```python
# 종목 상태 관리
self.trading_stocks: Dict[str, TradingStock] = {}
self.stocks_by_state: Dict[StockState, Dict[str, TradingStock]] = {}
```

**주요 메서드**:
- `add_selected_stock()`: 조건검색 종목 추가
- `move_to_buy_candidate()`: 매수 후보로 변경
- `execute_buy_order()`: 매수 주문 실행
- `move_to_sell_candidate()`: 매도 후보로 변경
- `execute_sell_order()`: 매도 주문 실행

### 2. IntradayStockManager (분봉 데이터 관리)

**위치**: `core/intraday_stock_manager.py`

**역할**:
- 조건검색으로 선정된 종목의 과거 분봉 데이터 수집
- 실시간 분봉 데이터 업데이트
- 차트 분석을 위한 데이터 제공

**핵심 변수**:
```python
self.selected_stocks: Dict[str, StockMinuteData] = {}  # 선정 종목별 분봉 데이터
self.selection_history: List[Dict[str, Any]] = []     # 선정 이력
```

### 3. RealTimeDataCollector (실시간 데이터)

**위치**: `core/data_collector.py`

**역할**:
- 후보 종목들의 실시간 OHLCV 데이터 수집
- 현재가 및 거래량 모니터링

**핵심 변수**:
```python
self.stocks: Dict[str, Stock] = {}  # 종목별 실시간 데이터
```

### 4. OrderManager (주문 관리)

**위치**: `core/order_manager.py`

**역할**:
- 매수/매도 주문 실행
- 미체결 주문 모니터링
- 주문 타임아웃 및 정정 처리

**핵심 변수**:
```python
self.pending_orders: Dict[str, Order] = {}    # 미체결 주문
self.completed_orders: List[Order] = []       # 완료된 주문
self.order_timeouts: Dict[str, datetime] = {} # 주문 타임아웃
```

## 데이터 모델

### TradingStock (거래 종목 통합 정보)

```python
@dataclass
class TradingStock:
    stock_code: str              # 종목코드
    stock_name: str              # 종목명  
    state: StockState            # 현재 상태
    selected_time: datetime      # 선정 시간
    
    # 포지션 정보
    position: Optional[Position] = None
    
    # 주문 정보
    current_order_id: Optional[str] = None
    order_history: List[str] = field(default_factory=list)
    
    # 상태 변화 이력
    state_history: List[Dict[str, Any]] = field(default_factory=list)
```

### Position (포지션 정보)

```python
@dataclass
class Position:
    stock_code: str        # 종목코드
    quantity: int          # 보유 수량
    avg_price: float       # 평균 매수가
    current_price: float   # 현재가
    unrealized_pnl: float  # 평가손익
    entry_time: datetime   # 진입 시간
```

### Order (주문 정보)

```python
@dataclass
class Order:
    order_id: str              # 주문 ID
    stock_code: str            # 종목코드
    order_type: OrderType      # 매수/매도
    price: float               # 주문가격
    quantity: int              # 주문수량
    status: OrderStatus        # 주문상태
    filled_quantity: int       # 체결수량
    remaining_quantity: int    # 미체결수량
    timestamp: datetime        # 주문시간
```

## 실제 사용 시나리오

### 1. 조건검색 → 매수 → 매도 완료 (정상 케이스)

```python
# 1. 조건검색으로 종목 선정
trading_manager.add_selected_stock("005930", "삼성전자", "급등 패턴")
# 상태: SELECTED

# 2. 분석 후 매수 후보로 변경
trading_manager.move_to_buy_candidate("005930", "이동평균선 돌파")
# 상태: BUY_CANDIDATE

# 3. 매수 주문 실행
await trading_manager.execute_buy_order("005930", 100, 75000, "강세 신호")
# 상태: BUY_PENDING → 체결 시 POSITIONED

# 4. 수익 실현 시점에 매도 후보로 변경
trading_manager.move_to_sell_candidate("005930", "목표가 달성")
# 상태: SELL_CANDIDATE

# 5. 매도 주문 실행
await trading_manager.execute_sell_order("005930", 100, 78000, "수익 실현")
# 상태: SELL_PENDING → 체결 시 COMPLETED
```

### 2. 주문 실패 후 재시도

```python
# 매수 주문 실행
await trading_manager.execute_buy_order("005930", 100, 75000)
# 상태: BUY_PENDING

# 주문 실패 시 자동으로 BUY_CANDIDATE로 복귀
# 재시도 가능

# 다시 매수 주문 실행
await trading_manager.execute_buy_order("005930", 100, 74500)
```

### 3. 포지션 모니터링

```python
# 포트폴리오 전체 현황 조회
summary = trading_manager.get_portfolio_summary()

# 특정 상태의 종목들 조회
positioned_stocks = trading_manager.get_stocks_by_state(StockState.POSITIONED)
buy_candidates = trading_manager.get_stocks_by_state(StockState.BUY_CANDIDATE)

# 개별 종목 정보 조회
trading_stock = trading_manager.get_trading_stock("005930")
if trading_stock and trading_stock.position:
    print(f"평가손익: {trading_stock.position.unrealized_pnl:,.0f}원")
```

## 리스크 관리

### 1. 상태별 제한사항

- **BUY_CANDIDATE**: 최대 보유 가능한 후보 종목 수 제한
- **POSITIONED**: 최대 동시 보유 포지션 수 제한
- **BUY_PENDING/SELL_PENDING**: 주문 타임아웃 관리

### 2. 자동 처리

- **주문 타임아웃**: 설정 시간 초과 시 자동 취소
- **가격 정정**: 시장가격 변동 시 자동 정정
- **손절/익절**: 설정된 비율 도달 시 자동 매도 후보 전환

### 3. 모니터링

- **실시간 상태 추적**: 10초마다 모든 종목 상태 확인
- **포지션 평가**: 실시간 현재가 반영한 평가손익 계산
- **알림**: 중요 상태 변화 시 텔레그램 알림

## 확장 가능한 구조

### 1. 새로운 상태 추가

필요에 따라 `StockState`에 새로운 상태를 추가할 수 있습니다:
- `WATCHLIST`: 관심종목
- `ANALYSIS`: 분석 중
- `HOLD`: 장기 보유

### 2. 전략별 관리

여러 전략을 동시에 운영할 경우 전략별로 `TradingStockManager` 인스턴스를 분리할 수 있습니다.

### 3. 백테스팅 지원

동일한 상태 관리 구조를 사용하여 백테스팅 시스템을 구축할 수 있습니다.

## 주의사항

1. **동시성**: 모든 상태 변경은 스레드 안전하게 처리됩니다.
2. **데이터 일관성**: 여러 관리자 간 데이터 동기화가 자동으로 처리됩니다.
3. **예외 처리**: 모든 상태 변경에서 예외 발생 시 안전한 상태로 복구됩니다.
4. **로깅**: 모든 상태 변화는 상세히 로깅되어 추적 가능합니다.

## 설정 및 튜닝

관련 설정들은 `config/settings.py`에서 조정할 수 있습니다:

- 주문 타임아웃 시간
- 최대 동시 보유 종목 수
- 모니터링 주기
- 리스크 관리 비율

이러한 통합 관리 시스템을 통해 종목의 전체 라이프사이클을 체계적으로 관리하고, 자동매매의 안정성과 효율성을 크게 향상시킬 수 있습니다.