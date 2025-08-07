"""
리팩토링된 장 마감 후 선정 종목 차트 생성기
성능 개선 및 모듈 분리 버전
"""
import asyncio
import sys
import pandas as pd
from pathlib import Path
from typing import Optional, Dict, List, Any
from datetime import datetime

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_api_manager import KISAPIManager
from core.candidate_selector import CandidateSelector
from core.intraday_stock_manager import IntradayStockManager
from utils.logger import setup_logger
from utils.korean_time import now_kst

# 분리된 모듈들 import
from visualization.chart_renderer import ChartRenderer
from visualization.data_processor import DataProcessor
from visualization.strategy_manager import StrategyManager
from visualization.signal_calculator import SignalCalculator


class PostMarketChartGenerator:
    """
    리팩토링된 장 마감 후 선정 종목 차트 생성 클래스
    
    주요 개선사항:
    1. 모듈 분리로 코드 가독성 향상
    2. 데이터 재사용으로 성능 개선
    3. 캐싱을 통한 중복 처리 방지
    4. 비동기 처리 최적화
    """
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        
        # API 관련 인스턴스
        self.api_manager = None
        self.candidate_selector = None
        self.intraday_manager = None
        
        # 분리된 모듈 인스턴스들
        self.chart_renderer = ChartRenderer()
        self.data_processor = DataProcessor()
        self.strategy_manager = StrategyManager()
        self.signal_calculator = SignalCalculator()
        
        # 성능 개선을 위한 캐시
        self._data_cache = {}  # 종목별 데이터 캐시
        self._indicator_cache = {}  # 지표 계산 결과 캐시
        
        self.logger.info("리팩토링된 차트 생성기 초기화 완료")
    
    def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            # API 매니저 초기화
            self.api_manager = KISAPIManager()
            if not self.api_manager.initialize():
                self.logger.error("API 매니저 초기화 실패")
                return False
            
            # 후보 선정기 초기화
            self.candidate_selector = CandidateSelector(
                config=None,  # 설정은 나중에 로드
                api_manager=self.api_manager
            )
            
            # 장중 종목 관리자 초기화
            self.intraday_manager = IntradayStockManager(self.api_manager)
            
            self.logger.info("시스템 초기화 성공")
            return True
            
        except Exception as e:
            self.logger.error(f"시스템 초기화 오류: {e}")
            return False
    
    def get_condition_search_stocks(self, condition_seq: str = "0") -> List[Dict[str, Any]]:
        """조건검색 종목 조회"""
        try:
            if not self.candidate_selector:
                self.logger.error("후보 선정기가 초기화되지 않음")
                return []
            
            # 실제 조건검색 결과 조회
            condition_results = self.candidate_selector.get_condition_search_candidates(seq=condition_seq)
            
            if condition_results:
                self.logger.info(f"조건검색 {condition_seq}번 결과: {len(condition_results)}개 종목")
                return condition_results
            else:
                self.logger.info(f"조건검색 {condition_seq}번: 해당 종목 없음")
                return []
            
        except Exception as e:
            self.logger.error(f"조건검색 종목 조회 오류: {e}")
            return []
    
    def clear_cache(self):
        """캐시 클리어"""
        self._data_cache.clear()
        self._indicator_cache.clear()
        self.logger.info("캐시 클리어 완료")
    
    def _get_cache_key(self, stock_code: str, target_date: str, timeframe: str) -> str:
        """캐시 키 생성"""
        return f"{stock_code}_{target_date}_{timeframe}"
    
    async def _get_cached_data(self, stock_code: str, target_date: str, timeframe: str):
        """캐시된 데이터 조회 (없으면 새로 가져오기)"""
        cache_key = self._get_cache_key(stock_code, target_date, timeframe)
        
        if cache_key in self._data_cache:
            self.logger.debug(f"캐시에서 데이터 조회: {cache_key}")
            return self._data_cache[cache_key]
        
        # 캐시에 없으면 새로 조회
        if timeframe == "1min":
            # 1분봉 데이터 조회
            data = await self.data_processor.get_historical_chart_data(stock_code, target_date)
        else:
            # 1분봉을 먼저 조회하고 변환
            base_data = await self.data_processor.get_historical_chart_data(stock_code, target_date)
            data = self.data_processor.get_timeframe_data(stock_code, target_date, timeframe, base_data)
        
        # 캐시에 저장
        if data is not None:
            self._data_cache[cache_key] = data
            self.logger.debug(f"데이터 캐시에 저장: {cache_key}")
        
        return data
    
    async def _get_cached_indicators(self, cache_key: str, data, strategy, stock_code: str):
        """캐시된 지표 데이터 조회 (없으면 새로 계산)"""
        if cache_key in self._indicator_cache:
            self.logger.debug(f"캐시에서 지표 조회: {cache_key}")
            return self._indicator_cache[cache_key]
        
        # 캐시에 없으면 새로 계산
        # 가격박스가 포함된 전략이면 일봉 데이터도 수집
        daily_data = None
        current_price = None
        
        if "price_box" in strategy.indicators:
            # 29일 일봉 데이터 수집
            daily_data = await self._collect_daily_data_for_chart(stock_code)
            # 현재가 추출 (분봉 데이터의 마지막 종가)
            if not data.empty and 'close' in data.columns:
                current_price = float(data['close'].iloc[-1])
        
        # 일봉 데이터를 포함한 지표 계산
        indicators_data = self.data_processor.calculate_indicators_with_daily_data(
            data, strategy, daily_data, current_price)
        
        # 캐시에 저장
        if indicators_data:
            self._indicator_cache[cache_key] = indicators_data
            self.logger.debug(f"지표 캐시에 저장: {cache_key}")
        
        return indicators_data
    
    async def create_post_market_candlestick_chart(self, stock_code: str, stock_name: str, 
                                                  chart_df=None, target_date: str = None,
                                                  selection_reason: str = "") -> Optional[str]:
        """
        장 마감 후 캔들스틱 차트 생성 (성능 최적화 버전)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            chart_df: 차트 데이터 (제공되지 않으면 자동 조회)
            target_date: 대상 날짜
            selection_reason: 선정 사유
            
        Returns:
            str: 저장된 파일 경로
        """
        try:
            if target_date is None:
                target_date = now_kst().strftime("%Y%m%d")
            
            self.logger.info(f"{stock_code} {target_date} 차트 생성 시작")
            
            # 우선순위 순으로 전략 시도
            strategies = self.strategy_manager.get_strategies_by_priority()
            
            for strategy_key, strategy in strategies:
                try:
                    # 전략별 시간프레임 데이터 조회 (캐시 활용)
                    if chart_df is not None and strategy.timeframe == "1min":
                        # 제공된 데이터 사용
                        timeframe_data = chart_df
                    else:
                        # 캐시된 데이터 조회/생성
                        timeframe_data = await self._get_cached_data(stock_code, target_date, strategy.timeframe)
                    
                    if timeframe_data is None or timeframe_data.empty:
                        self.logger.warning(f"{strategy.name} - 데이터 없음")
                        continue
                    
                    # 전략별 지표 계산 (캐시 활용)
                    indicator_cache_key = f"{stock_code}_{target_date}_{strategy.timeframe}_{strategy_key}"
                    indicators_data = await self._get_cached_indicators(indicator_cache_key, timeframe_data, strategy, stock_code)
                    
                    # 차트 생성
                    chart_path = self.chart_renderer.create_strategy_chart(
                        stock_code, stock_name, target_date, strategy, 
                        timeframe_data, indicators_data, selection_reason
                    )
                    
                    if chart_path:
                        self.logger.info(f"✅ {strategy.name} 차트 생성: {chart_path}")
                        return chart_path  # 첫 번째 성공한 차트 반환
                    
                except Exception as e:
                    self.logger.error(f"{strategy.name} 차트 생성 오류: {e}")
                    continue
            
            # 모든 전략이 실패한 경우 기본 차트 생성
            self.logger.warning("모든 전략 차트 생성 실패 - 기본 차트 생성 시도")
            if chart_df is not None:
                return self.chart_renderer.create_basic_chart(
                    stock_code, stock_name, chart_df, target_date, selection_reason
                )
            else:
                # 기본 1분봉 데이터로 기본 차트 생성
                base_data = await self._get_cached_data(stock_code, target_date, "1min")
                if base_data is not None:
                    return self.chart_renderer.create_basic_chart(
                        stock_code, stock_name, base_data, target_date, selection_reason
                    )
            
            self.logger.warning("기본 차트 생성도 실패")
            return None
            
        except Exception as e:
            self.logger.error(f"차트 생성 오류: {e}")
            return None
    
    async def create_dual_strategy_charts(self, stock_code: str, stock_name: str,
                                         chart_df=None, target_date: str = None,
                                         selection_reason: str = "") -> Dict[str, Optional[str]]:
        """
        두 개의 전략 차트 생성 (가격박스+이등분선, 다중볼린저밴드+이등분선)
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명 
            chart_df: 차트 데이터
            target_date: 대상 날짜
            selection_reason: 선정 사유
            
        Returns:
            Dict[str, Optional[str]]: 각 전략별 차트 파일 경로
        """
        try:
            if target_date is None:
                target_date = now_kst().strftime("%Y%m%d")
            
            self.logger.info(f"{stock_code} {target_date} 듀얼 차트 생성 시작")
            
            results = {
                'price_box': None,
                'multi_bollinger': None
            }
            
            # 1분봉 데이터 준비
            if chart_df is not None:
                timeframe_data = chart_df
            else:
                timeframe_data = await self._get_cached_data(stock_code, target_date, "1min")
            
            if timeframe_data is None or timeframe_data.empty:
                self.logger.warning("1분봉 데이터 없음")
                return results
            
            # 전략 1: 가격박스 + 이등분선
            try:
                price_box_strategy = self.strategy_manager.get_strategy('price_box')
                if price_box_strategy:
                    indicator_cache_key = f"{stock_code}_{target_date}_1min_price_box"
                    price_box_indicators = await self._get_cached_indicators(indicator_cache_key, timeframe_data, price_box_strategy, stock_code)
                    
                    price_box_path = self.chart_renderer.create_strategy_chart(
                        stock_code, stock_name, target_date, price_box_strategy,
                        timeframe_data, price_box_indicators, selection_reason,
                        chart_suffix="price_box"
                    )
                    
                    if price_box_path:
                        results['price_box'] = price_box_path
                        self.logger.info(f"✅ 가격박스 차트 생성: {price_box_path}")
                    
            except Exception as e:
                self.logger.error(f"가격박스 차트 생성 오류: {e}")
            
            # 전략 2: 다중볼린저밴드 + 이등분선 (5분봉 기준)
            try:
                multi_bb_strategy = self.strategy_manager.get_strategy('multi_bollinger')
                if multi_bb_strategy:
                    # 5분봉 데이터 준비 (1분봉에서 변환)
                    timeframe_data_5min = await self._get_cached_data(stock_code, target_date, "5min")
                    
                    if timeframe_data_5min is None or timeframe_data_5min.empty:
                        self.logger.warning("5분봉 데이터 없음")
                    else:
                        indicator_cache_key = f"{stock_code}_{target_date}_5min_multi_bollinger"
                        multi_bb_indicators = await self._get_cached_indicators(indicator_cache_key, timeframe_data_5min, multi_bb_strategy, stock_code)
                        
                        # 다중볼린저밴드는 5분봉 기준이므로 전략 정보 수정
                        multi_bb_strategy_5min = type(multi_bb_strategy)(
                            multi_bb_strategy.name,
                            "5min",  # timeframe을 5min으로 변경
                            multi_bb_strategy.indicators,
                            multi_bb_strategy.description + " (5분봉 기준)"
                        )
                        
                        multi_bb_path = self.chart_renderer.create_strategy_chart(
                            stock_code, stock_name, target_date, multi_bb_strategy_5min,
                            timeframe_data_5min, multi_bb_indicators, selection_reason,
                            chart_suffix="multi_bollinger", timeframe="5min"
                        )
                        
                        if multi_bb_path:
                            results['multi_bollinger'] = multi_bb_path
                            self.logger.info(f"✅ 다중볼린저밴드 차트 생성: {multi_bb_path}")
                        
            except Exception as e:
                self.logger.error(f"다중볼린저밴드 차트 생성 오류: {e}")
            
            return results
            
        except Exception as e:
            self.logger.error(f"듀얼 차트 생성 오류: {e}")
            return {'price_box': None, 'multi_bollinger': None}
    
    async def _process_single_stock(self, stock_code: str, stock_name: str, 
                                   target_date: str, selection_reason: str, change_rate: str) -> Dict[str, Any]:
        """단일 종목 처리 (내부 메서드)"""
        try:
            # 듀얼 차트 생성 (가격박스+이등분선, 다중볼린저밴드+이등분선)
            chart_results = await self.create_dual_strategy_charts(
                stock_code=stock_code,
                stock_name=stock_name,
                target_date=target_date,
                selection_reason=selection_reason
            )
            
            # 성공한 차트가 하나라도 있으면 성공으로 처리
            success_charts = [path for path in chart_results.values() if path is not None]
            
            if success_charts:
                # 데이터 건수 조회 (캐시에서)
                cache_key = self._get_cache_key(stock_code, target_date, "1min")
                data_count = len(self._data_cache.get(cache_key, []))
                
                return {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'success': True,
                    'chart_files': chart_results,  # 두 차트 경로 모두 반환
                    'chart_count': len(success_charts),
                    'data_count': data_count,
                    'change_rate': change_rate
                }
            else:
                return {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'success': False,
                    'error': '차트 생성 실패'
                }
        
        except Exception as e:
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'success': False,
                'error': str(e)
            }
    
    async def generate_post_market_charts_for_intraday_stocks(self, intraday_manager=None, telegram_integration=None) -> Dict[str, Any]:
        """
        장중 선정된 종목들의 장 마감 후 차트 생성 (최적화 버전)
        
        Args:
            intraday_manager: IntradayStockManager 인스턴스 (None이면 기본 사용)
            telegram_integration: 텔레그램 통합 객체 (선택사항)
            
        Returns:
            Dict: 차트 생성 결과
        """
        try:
            current_time = now_kst()
            
            # 장 마감 시간 체크 (15:30 이후)
            market_close_hour = 15
            market_close_minute = 30
            
            if current_time.hour < market_close_hour or (current_time.hour == market_close_hour and current_time.minute < market_close_minute):
                #self.logger.debug("아직 장 마감 시간이 아님 - 차트 생성 건너뛰기")
                return {'success': False, 'message': '아직 장 마감 시간이 아님'}
            
            # 주말이나 공휴일 체크
            if current_time.weekday() >= 5:  # 토요일(5), 일요일(6)
                #self.logger.debug("주말 - 차트 생성 건너뛰기")
                return {'success': False, 'message': '주말'}
            
            self.logger.info("🎨 장 마감 후 선정 종목 차트 생성 시작")
            
            # intraday_manager 결정
            if intraday_manager is None:
                intraday_manager = self.intraday_manager
            
            if intraday_manager is None:
                self.logger.error("IntradayStockManager가 초기화되지 않음")
                return {'success': False, 'error': 'IntradayStockManager 없음'}
            
            # 장중 선정된 종목들 조회
            selected_stocks = []
            summary = intraday_manager.get_all_stocks_summary()
            
            if summary.get('total_stocks', 0) > 0:
                for stock_info in summary.get('stocks', []):
                    stock_code = stock_info.get('stock_code', '')
                    
                    # 종목 상세 정보 조회
                    stock_data = intraday_manager.get_stock_data(stock_code)
                    if stock_data:
                        selected_stocks.append({
                            'code': stock_code,
                            'name': stock_data.stock_name,
                            'chgrate': f"+{stock_info.get('price_change_rate', 0):.1f}",
                            'selection_reason': f"장중 선정 종목 ({stock_data.selected_time.strftime('%H:%M')} 선정)"
                        })
            
            if not selected_stocks:
                self.logger.info("ℹ️ 오늘 선정된 종목이 없어 차트 생성을 건너뜁니다")
                return {'success': False, 'message': '선정된 종목이 없음'}
            
            # 당일 날짜로 차트 생성
            target_date = current_time.strftime("%Y%m%d")
            
            self.logger.info(f"📊 {len(selected_stocks)}개 선정 종목의 {target_date} 차트 생성 중...")
            
            # 캐시 클리어 (새로운 배치 작업 시작)
            self.clear_cache()
            
            # 병렬 처리
            tasks = []
            for stock_data in selected_stocks:
                stock_code = stock_data.get('code', '')
                stock_name = stock_data.get('name', '')
                selection_reason = stock_data.get('selection_reason', '')
                
                task = self._process_single_stock(
                    stock_code, stock_name, target_date, selection_reason, ""
                )
                tasks.append(task)
            
            # 병렬 실행 (최대 3개씩 동시 처리)
            semaphore = asyncio.Semaphore(3)
            
            async def limited_task(task):
                async with semaphore:
                    return await task
            
            stock_results = await asyncio.gather(*[limited_task(task) for task in tasks], return_exceptions=True)
            
            # 결과 집계
            success_count = 0
            chart_files = []
            final_results = []
            
            for result in stock_results:
                if isinstance(result, Exception):
                    self.logger.error(f"종목 처리 중 예외 발생: {result}")
                    continue
                
                final_results.append(result)
                if result['success']:
                    success_count += 1
                    if 'chart_file' in result:
                        chart_files.append(result['chart_file'])
            
            # 결과 반환
            total_stocks = len(selected_stocks)
            return {
                'success': success_count > 0,
                'success_count': success_count,
                'total_stocks': total_stocks,
                'chart_files': chart_files,
                'stock_results': final_results,
                'message': f"차트 생성 완료: {success_count}/{total_stocks}개 성공"
            }
            
        except Exception as e:
            self.logger.error(f"❌ 장 마감 후 차트 생성 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    async def _collect_daily_data_for_chart(self, stock_code: str) -> Optional[pd.DataFrame]:
        """
        TMA30 계산용 59일 일봉 데이터 수집
        
        Args:
            stock_code: 종목코드
            
        Returns:
            pd.DataFrame: 59일 일봉 데이터 (None: 실패)
        """
        try:
            from api.kis_market_api import get_inquire_daily_itemchartprice
            from datetime import timedelta
            
            # 88일 전 날짜 계산 (영업일 기준으로 여유있게 120일 전부터)
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=130)).strftime("%Y%m%d")
            
            self.logger.info(f"📊 {stock_code} TMA30 계산용 88일 일봉 데이터 수집 시작 ({start_date} ~ {end_date})")
            
            # 일봉 데이터 조회
            daily_data = get_inquire_daily_itemchartprice(
                output_dv="2",  # 상세 데이터
                div_code="J",   # 주식
                itm_no=stock_code,
                inqr_strt_dt=start_date,
                inqr_end_dt=end_date,
                period_code="D",  # 일봉
                adj_prc="1"     # 원주가
            )
            
            if daily_data is None or daily_data.empty:
                self.logger.warning(f"⚠️ {stock_code} TMA30용 일봉 데이터 조회 실패 또는 빈 데이터")
                return None
            
            # 최근 88일 데이터만 선택 (오늘 제외)
            if len(daily_data) > 88:
                daily_data = daily_data.head(88)
            
            # 데이터 정렬 (오래된 날짜부터)
            if 'stck_bsop_date' in daily_data.columns:
                daily_data = daily_data.sort_values('stck_bsop_date', ascending=True)
            
            self.logger.info(f"✅ {stock_code} TMA30용 일봉 데이터 수집 성공! ({len(daily_data)}일, 9시부터 계산 가능)")
            
            return daily_data
            
        except Exception as e:
            self.logger.error(f"❌ {stock_code} TMA30용 일봉 데이터 수집 오류: {e}")
            return None


def main():
    """테스트용 메인 함수"""
    try:
        print("리팩토링된 차트 생성기 테스트")
        generator = PostMarketChartGenerator()
        if generator.initialize():
            print("초기화 성공")
            
            # 전략 현황 출력
            summary = generator.strategy_manager.get_strategy_summary()
            print(f"사용 가능한 전략: {summary['enabled_strategies']}/{summary['total_strategies']}개")
            
        else:
            print("초기화 실패")
    except Exception as e:
        print(f"메인 실행 오류: {e}")


if __name__ == "__main__":
    main()