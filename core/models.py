"""
데이터 모델 정의
"""
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Dict, Any
from enum import Enum


class OrderType(Enum):
    BUY = "buy"
    SELL = "sell"


class OrderStatus(Enum):
    PENDING = "pending"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"


class PositionType(Enum):
    NONE = "none"
    LONG = "long"


@dataclass
class OHLCVData:
    """OHLCV 데이터"""
    timestamp: datetime
    stock_code: str
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: int
    
    def __post_init__(self):
        """데이터 검증"""
        if self.high_price < max(self.open_price, self.close_price):
            raise ValueError("고가가 시가/종가보다 낮습니다")
        if self.low_price > min(self.open_price, self.close_price):
            raise ValueError("저가가 시가/종가보다 높습니다")


@dataclass
class Stock:
    """종목 정보"""
    code: str
    name: str
    ohlcv_data: List[OHLCVData] = field(default_factory=list)
    last_price: float = 0.0
    is_candidate: bool = False
    position: PositionType = PositionType.NONE
    position_quantity: int = 0
    position_avg_price: float = 0.0
    
    def add_ohlcv(self, ohlcv: OHLCVData):
        """OHLCV 데이터 추가"""
        self.ohlcv_data.append(ohlcv)
        self.last_price = ohlcv.close_price
        
        # 최대 1000개 데이터만 유지 (메모리 관리)
        if len(self.ohlcv_data) > 1000:
            self.ohlcv_data = self.ohlcv_data[-1000:]
    
    def get_recent_ohlcv(self, count: int = 20) -> List[OHLCVData]:
        """최근 N개 데이터 반환"""
        return self.ohlcv_data[-count:] if count <= len(self.ohlcv_data) else self.ohlcv_data


@dataclass
class Order:
    """주문 정보"""
    order_id: str
    stock_code: str
    order_type: OrderType
    price: float
    quantity: int
    timestamp: datetime
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: int = 0
    remaining_quantity: int = 0
    adjustment_count: int = 0  # 정정 횟수
    
    def __post_init__(self):
        """초기화 후 처리"""
        if self.remaining_quantity == 0:
            self.remaining_quantity = self.quantity


@dataclass
class TradingSignal:
    """매매 신호"""
    stock_code: str
    signal_type: OrderType
    price: float
    quantity: int
    confidence: float  # 신호 신뢰도 (0.0 ~ 1.0)
    reason: str       # 신호 발생 이유
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class Position:
    """포지션 정보"""
    stock_code: str
    quantity: int
    avg_price: float
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    entry_time: datetime = field(default_factory=datetime.now)
    
    def update_current_price(self, price: float):
        """현재가 업데이트 및 평가손익 계산"""
        self.current_price = price
        self.unrealized_pnl = (price - self.avg_price) * self.quantity


@dataclass
class TradingConfig:
    """거래 설정"""
    # 기본 설정
    data_collection_interval: int = 30  # 데이터 수집 주기 (초)
    candidate_stocks: List[str] = field(default_factory=list)
    
    # 주문 관리
    buy_timeout: int = 300      # 매수 주문 대기시간 (초)
    sell_timeout: int = 180     # 매도 주문 대기시간 (초)
    max_adjustments: int = 3    # 최대 정정 횟수
    
    # 리스크 관리
    max_position_count: int = 5     # 최대 동시 보유 종목 수
    max_position_ratio: float = 0.2 # 종목별 최대 투자 비율
    stop_loss_ratio: float = 0.03   # 손절 비율 (3%)
    take_profit_ratio: float = 0.05 # 익절 비율 (5%)
    
    # 전략 설정
    strategy_params: Dict[str, Any] = field(default_factory=dict)