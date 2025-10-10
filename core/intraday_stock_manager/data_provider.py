"""
데이터 조회 및 분석 제공
"""
from typing import Optional, Dict, Any
import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.realtime_candle_builder import get_realtime_candle_builder
from core.minute_data_collector import MinuteDataCollector
from .stock_repository import StockRepository


class DataProvider:
    """
    데이터 조회 및 분석 정보 제공 클래스
    """
    
    def __init__(self, repository: StockRepository, collector: MinuteDataCollector):
        """
        초기화
        
        Args:
            repository: 종목 저장소
            collector: 분봉 데이터 수집기
        """
        self.logger = setup_logger(__name__)
        self.repository = repository
        self.collector = collector
    
    def get_combined_chart_data(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        종목의 당일 전체 차트 데이터 조회 (08:00~현재, 완성된 봉만)
        
        종목 선정 시 수집한 historical_data와 실시간으로 업데이트되는 realtime_data를 결합하여
        당일 전체 분봉 데이터를 반환합니다. API 30건 제한을 우회하여 전체 거래시간 데이터 제공.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 당일 전체 차트 데이터 (완성된 봉만)
        """
        try:
            stock_data = self.repository.get_stock(stock_code)
            if stock_data is None:
                self.logger.debug(f"❌ {stock_code} 선정된 종목 아님")
                return None
            
            historical_data = stock_data.historical_data.copy() if not stock_data.historical_data.empty else pd.DataFrame()
            realtime_data = stock_data.realtime_data.copy() if not stock_data.realtime_data.empty else pd.DataFrame()
            selected_time = stock_data.selected_time
            
            # collector를 사용하여 데이터 결합
            combined_data = self.collector.get_combined_chart_data(
                historical_data, realtime_data, selected_time, stock_code
            )
            
            if combined_data is None or combined_data.empty:
                self.logger.debug(f"❌ {stock_code} 결합된 데이터 없음")
                return None
            
            return combined_data
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 결합 차트 데이터 생성 오류: {e}")
            return None
    
    def get_combined_chart_data_with_realtime(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        종목의 당일 전체 차트 데이터 조회 (완성된 봉 + 실시간 진행중인 봉)
        
        기존 get_combined_chart_data()에 현재가 API를 이용한 실시간 생성 1분봉을 추가하여
        3분봉 매매 판단 시 지연을 최소화합니다.
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 당일 전체 차트 데이터 (완성된 봉 + 실시간 진행중인 봉)
        """
        try:
            # 기존 완성된 분봉 데이터 가져오기
            completed_data = self.get_combined_chart_data(stock_code)
            if completed_data is None or completed_data.empty:
                return completed_data
            
            # 실시간 캔들 빌더를 통해 누락된 완성 분봉 보완 + 진행중인 1분봉 추가
            candle_builder = get_realtime_candle_builder()
            enhanced_data = candle_builder.fill_missing_candles_and_combine(stock_code, completed_data)
            
            # 종목명 가져오기 (로깅용)
            stock_data = self.repository.get_stock(stock_code)
            stock_name = stock_data.stock_name if stock_data else ""
            
            # 실시간 데이터가 추가되었는지 로깅
            if len(enhanced_data) > len(completed_data):
                self.logger.debug(f"🔄 {stock_code}({stock_name}) 실시간 1분봉 추가: {len(completed_data)} → {len(enhanced_data)}건")
            
            return enhanced_data
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 실시간 포함 차트 데이터 생성 오류: {e}")
            # 오류 시 기존 완성된 데이터라도 반환
            return self.get_combined_chart_data(stock_code)
    
    def get_stock_analysis(self, stock_code: str) -> Optional[Dict[str, Any]]:
        """
        종목 분석 정보 조회
        
        Args:
            stock_code: 종목코드
            
        Returns:
            Dict: 분석 정보
        """
        try:
            combined_data = self.get_combined_chart_data(stock_code)
            
            if combined_data is None or combined_data.empty:
                return None
            
            stock_data = self.repository.get_stock(stock_code)
            if stock_data is None:
                return None
            
            # 기본 정보
            analysis = {
                'stock_code': stock_code,
                'stock_name': stock_data.stock_name,
                'selected_time': stock_data.selected_time,
                'data_complete': stock_data.data_complete,
                'last_update': stock_data.last_update,
                'total_minutes': len(combined_data),
                'historical_minutes': len(stock_data.historical_data),
                'realtime_minutes': len(stock_data.realtime_data)
            }
            
            # 가격 분석 (close 컬럼이 있는 경우)
            if 'close' in combined_data.columns and len(combined_data) > 0:
                prices = combined_data['close']
                
                analysis.update({
                    'first_price': float(prices.iloc[0]) if len(prices) > 0 else 0,
                    'current_price': float(prices.iloc[-1]) if len(prices) > 0 else 0,
                    'high_price': float(prices.max()),
                    'low_price': float(prices.min()),
                    'price_change': float(prices.iloc[-1] - prices.iloc[0]) if len(prices) > 1 else 0,
                    'price_change_rate': float((prices.iloc[-1] - prices.iloc[0]) / prices.iloc[0] * 100) if len(prices) > 1 and prices.iloc[0] > 0 else 0
                })
            
            # 거래량 분석 (volume 컬럼이 있는 경우)
            if 'volume' in combined_data.columns:
                volumes = combined_data['volume']
                analysis.update({
                    'total_volume': int(volumes.sum()),
                    'avg_volume': int(volumes.mean()) if len(volumes) > 0 else 0,
                    'max_volume': int(volumes.max()) if len(volumes) > 0 else 0
                })
            
            return analysis
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 분석 정보 생성 오류: {e}")
            return None
    
    def get_all_stocks_summary(self) -> Dict[str, Any]:
        """
        모든 관리 종목 요약 정보
        
        Returns:
            Dict: 전체 요약 정보
        """
        try:
            stock_codes = self.repository.get_all_stock_codes()
            
            summary = {
                'total_stocks': len(stock_codes),
                'max_stocks': self.repository.max_stocks,
                'current_time': now_kst().strftime('%Y-%m-%d %H:%M:%S'),
                'stocks': []
            }
            
            for stock_code in stock_codes:
                analysis = self.get_stock_analysis(stock_code)
                if analysis:
                    summary['stocks'].append({
                        'stock_code': stock_code,
                        'stock_name': analysis['stock_name'],
                        'selected_time': analysis['selected_time'].strftime('%H:%M:%S'),
                        'data_complete': analysis['data_complete'],
                        'total_minutes': analysis['total_minutes'],
                        'price_change_rate': analysis.get('price_change_rate', 0)
                    })
            
            return summary
        
        except Exception as e:
            self.logger.error(f"❌ 전체 요약 정보 생성 오류: {e}")
            return {}

