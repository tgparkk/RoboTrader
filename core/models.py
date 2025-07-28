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
class DataCollectionConfig:
    """데이터 수집 설정"""
    interval_seconds: int = 30
    candidate_stocks: List[str] = field(default_factory=list)


@dataclass
class OrderManagementConfig:
    """주문 관리 설정"""
    buy_timeout_seconds: int = 300
    sell_timeout_seconds: int = 180
    max_adjustments: int = 3
    adjustment_threshold_percent: float = 0.5
    market_order_threshold_percent: float = 2.0


@dataclass
class RiskManagementConfig:
    """리스크 관리 설정"""
    max_position_count: int = 3
    max_position_ratio: float = 0.3
    stop_loss_ratio: float = 0.03
    take_profit_ratio: float = 0.05
    max_daily_loss: float = 0.1


@dataclass
class StrategyConfig:
    """전략 설정"""
    name: str = "simple_momentum"
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LoggingConfig:
    """로깅 설정"""
    level: str = "INFO"
    file_retention_days: int = 30


@dataclass
class TradingConfig:
    """거래 설정 통합"""
    data_collection: DataCollectionConfig = field(default_factory=DataCollectionConfig)
    order_management: OrderManagementConfig = field(default_factory=OrderManagementConfig)
    risk_management: RiskManagementConfig = field(default_factory=RiskManagementConfig)
    strategy: StrategyConfig = field(default_factory=StrategyConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    
    @classmethod
    def from_json(cls, json_data: Dict[str, Any]) -> 'TradingConfig':
        """JSON 데이터로부터 TradingConfig 객체 생성"""
        return cls(
            data_collection=DataCollectionConfig(
                interval_seconds=json_data.get('data_collection', {}).get('interval_seconds', 30),
                candidate_stocks=json_data.get('data_collection', {}).get('candidate_stocks', [])
            ),
            order_management=OrderManagementConfig(
                buy_timeout_seconds=json_data.get('order_management', {}).get('buy_timeout_seconds', 300),
                sell_timeout_seconds=json_data.get('order_management', {}).get('sell_timeout_seconds', 180),
                max_adjustments=json_data.get('order_management', {}).get('max_adjustments', 3),
                adjustment_threshold_percent=json_data.get('order_management', {}).get('adjustment_threshold_percent', 0.5),
                market_order_threshold_percent=json_data.get('order_management', {}).get('market_order_threshold_percent', 2.0)
            ),
            risk_management=RiskManagementConfig(
                max_position_count=json_data.get('risk_management', {}).get('max_position_count', 3),
                max_position_ratio=json_data.get('risk_management', {}).get('max_position_ratio', 0.3),
                stop_loss_ratio=json_data.get('risk_management', {}).get('stop_loss_ratio', 0.03),
                take_profit_ratio=json_data.get('risk_management', {}).get('take_profit_ratio', 0.05),
                max_daily_loss=json_data.get('risk_management', {}).get('max_daily_loss', 0.1)
            ),
            strategy=StrategyConfig(
                name=json_data.get('strategy', {}).get('name', 'simple_momentum'),
                parameters=json_data.get('strategy', {}).get('parameters', {})
            ),
            logging=LoggingConfig(
                level=json_data.get('logging', {}).get('level', 'INFO'),
                file_retention_days=json_data.get('logging', {}).get('file_retention_days', 30)
            )
        )