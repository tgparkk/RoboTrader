"""
종목 저장소 관리
"""
import threading
from typing import Dict, List, Optional, Any
from datetime import datetime

from utils.logger import setup_logger
from .stock_data import StockMinuteData


class StockRepository:
    """
    종목 데이터 저장소 (Thread-safe)
    
    종목 추가/조회/삭제 및 선정 이력 관리
    """
    
    def __init__(self, max_stocks: int = 80):
        """
        초기화
        
        Args:
            max_stocks: 최대 관리 종목 수
        """
        self.logger = setup_logger(__name__)
        self.max_stocks = max_stocks
        
        # 메모리 저장소
        self._stocks: Dict[str, StockMinuteData] = {}
        self._selection_history: List[Dict[str, Any]] = []
        
        # Thread-safe 락
        self._lock = threading.RLock()
    
    def add_stock(self, stock_data: StockMinuteData) -> bool:
        """
        종목 추가
        
        Args:
            stock_data: 종목 데이터
            
        Returns:
            bool: 추가 성공 여부
        """
        with self._lock:
            stock_code = stock_data.stock_code
            
            # 이미 존재하는 종목
            if stock_code in self._stocks:
                return True
            
            # 최대 관리 종목 수 체크
            if len(self._stocks) >= self.max_stocks:
                self.logger.warning(f"⚠️ 최대 관리 종목 수({self.max_stocks})에 도달. 추가 불가")
                return False
            
            self._stocks[stock_code] = stock_data
            return True
    
    def get_stock(self, stock_code: str) -> Optional[StockMinuteData]:
        """
        종목 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            StockMinuteData: 종목 데이터 또는 None
        """
        with self._lock:
            return self._stocks.get(stock_code)
    
    def update_stock(self, stock_code: str, **kwargs) -> bool:
        """
        종목 데이터 업데이트
        
        Args:
            stock_code: 종목코드
            **kwargs: 업데이트할 필드 (historical_data, realtime_data 등)
            
        Returns:
            bool: 업데이트 성공 여부
        """
        with self._lock:
            if stock_code not in self._stocks:
                return False
            
            stock_data = self._stocks[stock_code]
            
            for key, value in kwargs.items():
                if hasattr(stock_data, key):
                    setattr(stock_data, key, value)
            
            return True
    
    def remove_stock(self, stock_code: str) -> bool:
        """
        종목 제거
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 제거 성공 여부
        """
        with self._lock:
            if stock_code in self._stocks:
                stock_name = self._stocks[stock_code].stock_name
                del self._stocks[stock_code]
                self.logger.info(f"🗑️ {stock_code}({stock_name}) 관리 목록에서 제거")
                return True
            return False
    
    def get_all_stock_codes(self) -> List[str]:
        """
        모든 종목코드 조회
        
        Returns:
            List[str]: 종목코드 리스트
        """
        with self._lock:
            return list(self._stocks.keys())
    
    def get_stock_count(self) -> int:
        """
        관리 중인 종목 수
        
        Returns:
            int: 종목 수
        """
        with self._lock:
            return len(self._stocks)
    
    def exists(self, stock_code: str) -> bool:
        """
        종목 존재 여부
        
        Args:
            stock_code: 종목코드
            
        Returns:
            bool: 존재 여부
        """
        with self._lock:
            return stock_code in self._stocks
    
    def add_selection_history(self, stock_code: str, stock_name: str, 
                            selected_time: datetime, selection_reason: str = "") -> None:
        """
        선정 이력 추가
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            selected_time: 선정 시간
            selection_reason: 선정 사유
        """
        with self._lock:
            self._selection_history.append({
                'stock_code': stock_code,
                'stock_name': stock_name,
                'selected_time': selected_time,
                'selection_reason': selection_reason,
                'market_time': selected_time.strftime('%H:%M:%S')
            })
    
    def get_selection_history(self) -> List[Dict[str, Any]]:
        """
        선정 이력 조회
        
        Returns:
            List[Dict]: 선정 이력
        """
        with self._lock:
            return self._selection_history.copy()
    
    def clear_all(self) -> None:
        """모든 데이터 초기화"""
        with self._lock:
            self._stocks.clear()
            self._selection_history.clear()
            self.logger.info("🗑️ 모든 종목 데이터 초기화")

