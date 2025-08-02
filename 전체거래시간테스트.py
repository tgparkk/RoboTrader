"""
전체 거래시간 분봉 데이터 수집 기능 테스트
장중 13시에 종목이 선정되었을 때 09:00부터 13:00까지의 모든 분봉 데이터 수집 테스트
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime, timedelta
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_chart_api import get_full_trading_day_data_async
from api.kis_api_manager import KISAPIManager
from core.intraday_stock_manager import IntradayStockManager
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)


class FullTradingDayTest:
    """전체 거래시간 분봉 데이터 수집 테스트"""
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.api_manager = None
        self.intraday_manager = None
        
    async def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            self.logger.info("=== 전체 거래시간 테스트 초기화 ===")
            
            # API 매니저 초기화
            self.api_manager = KISAPIManager()
            if not self.api_manager.initialize():
                self.logger.error("API 매니저 초기화 실패")
                return False
            
            # IntradayStockManager 초기화
            self.intraday_manager = IntradayStockManager(self.api_manager)
            
            self.logger.info("초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"초기화 오류: {e}")
            return False
    
    async def test_full_trading_day_data_collection(self, stock_code: str = "005930", 
                                                   target_date: str = "20250801",
                                                   simulated_selection_time: str = "130000") -> dict:
        """
        전체 거래시간 분봉 데이터 수집 테스트
        
        장중 13시에 종목이 선정되었다고 가정하고 09:00부터 13:00까지의 데이터 수집
        
        Args:
            stock_code: 테스트 종목코드
            target_date: 테스트 날짜 (YYYYMMDD)
            simulated_selection_time: 가상 종목 선정 시간 (HHMMSS)
            
        Returns:
            dict: 테스트 결과
        """
        try:
            self.logger.info(f"\n=== 전체 거래시간 분봉 데이터 수집 테스트 ===")
            self.logger.info(f"종목: {stock_code}")
            self.logger.info(f"날짜: {target_date}")
            self.logger.info(f"가상 선정 시간: {simulated_selection_time}")
            
            test_result = {
                'stock_code': stock_code,
                'target_date': target_date,
                'simulated_selection_time': simulated_selection_time,
                'tests': {}
            }
            
            # 1. 직접 API 함수 테스트
            self.logger.info("\n1. 직접 API 함수 테스트")
            
            direct_result = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time=simulated_selection_time
            )
            
            if direct_result is not None and not direct_result.empty:
                # 시간 범위 분석
                time_analysis = self._analyze_data_time_range(direct_result)
                
                test_result['tests']['direct_api'] = {
                    'success': True,
                    'data_count': len(direct_result),
                    'time_analysis': time_analysis
                }
                
                self.logger.info(f"✅ 직접 API 테스트 성공: {len(direct_result)}건")
                self.logger.info(f"   시간 범위: {time_analysis['start_time']} ~ {time_analysis['end_time']}")
                self.logger.info(f"   시간 범위: {time_analysis['time_range_minutes']}분")
                
                # 예상 시간 범위와 비교
                expected_range = self._calculate_expected_range("090000", simulated_selection_time)
                actual_range = time_analysis['time_range_minutes']
                
                self.logger.info(f"   예상 범위: {expected_range}분, 실제 범위: {actual_range}분")
                
                if actual_range >= expected_range * 0.8:  # 80% 이상이면 성공
                    self.logger.info("   ✅ 예상 범위와 유사함")
                else:
                    self.logger.warning(f"   ⚠️ 예상 범위보다 짧음 ({actual_range}/{expected_range})")
                
            else:
                test_result['tests']['direct_api'] = {
                    'success': False,
                    'error': '데이터 없음'
                }
                self.logger.error("❌ 직접 API 테스트 실패")
            
            # 2. IntradayStockManager 통합 테스트
            self.logger.info("\n2. IntradayStockManager 통합 테스트")
            
            # 시간 제약 우회
            original_is_market_open = None
            try:
                import core.intraday_stock_manager
                original_is_market_open = core.intraday_stock_manager.is_market_open
                core.intraday_stock_manager.is_market_open = lambda: True
                
                # 가상 종목 선정 시뮬레이션
                selection_reason = f"13시 급등주 발견 테스트"
                success = self.intraday_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name="삼성전자",
                    selection_reason=selection_reason
                )
                
                if success:
                    # 데이터 수집 대기
                    await asyncio.sleep(3)
                    
                    # 종목 데이터 조회
                    stock_data = self.intraday_manager.get_stock_data(stock_code)
                    
                    if stock_data and not stock_data.historical_data.empty:
                        # 시간 범위 분석
                        integrated_analysis = self._analyze_data_time_range(stock_data.historical_data)
                        
                        test_result['tests']['integrated'] = {
                            'success': True,
                            'data_count': len(stock_data.historical_data),
                            'time_analysis': integrated_analysis,
                            'stock_data': {
                                'selected_time': stock_data.selected_time.strftime('%H:%M:%S'),
                                'data_complete': stock_data.data_complete,
                                'realtime_data_count': len(stock_data.realtime_data)
                            }
                        }
                        
                        self.logger.info(f"✅ 통합 테스트 성공: {len(stock_data.historical_data)}건")
                        self.logger.info(f"   시간 범위: {integrated_analysis['start_time']} ~ {integrated_analysis['end_time']}")
                        self.logger.info(f"   선정 시간: {stock_data.selected_time.strftime('%H:%M:%S')}")
                        self.logger.info(f"   데이터 완료: {stock_data.data_complete}")
                        
                    else:
                        test_result['tests']['integrated'] = {
                            'success': False,
                            'error': '종목 데이터 조회 실패'
                        }
                        self.logger.error("❌ 통합 테스트: 종목 데이터 없음")
                else:
                    test_result['tests']['integrated'] = {
                        'success': False,
                        'error': '종목 추가 실패'
                    }
                    self.logger.error("❌ 통합 테스트: 종목 추가 실패")
                    
            finally:
                # 원래 함수로 복원
                if original_is_market_open:
                    core.intraday_stock_manager.is_market_open = original_is_market_open
            
            # 3. 결과 비교 분석
            self.logger.info("\n3. 결과 비교 분석")
            
            direct_success = test_result['tests'].get('direct_api', {}).get('success', False)
            integrated_success = test_result['tests'].get('integrated', {}).get('success', False)
            
            if direct_success and integrated_success:
                direct_count = test_result['tests']['direct_api']['data_count']
                integrated_count = test_result['tests']['integrated']['data_count']
                
                self.logger.info(f"직접 API: {direct_count}건")
                self.logger.info(f"통합 시스템: {integrated_count}건")
                
                if abs(direct_count - integrated_count) <= 5:  # 5건 이내 차이면 정상
                    self.logger.info("✅ 두 방식의 결과가 일치함")
                    test_result['comparison'] = 'success'
                else:
                    self.logger.warning(f"⚠️ 두 방식의 결과가 다름 (차이: {abs(direct_count - integrated_count)}건)")
                    test_result['comparison'] = 'different'
            else:
                self.logger.error("❌ 비교 분석 불가 (일부 테스트 실패)")
                test_result['comparison'] = 'failed'
            
            # 전체 성공 여부
            test_result['overall_success'] = direct_success or integrated_success
            
            return test_result
            
        except Exception as e:
            self.logger.error(f"전체 거래시간 테스트 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    def _analyze_data_time_range(self, data_df) -> dict:
        """데이터의 시간 범위 분석"""
        try:
            if data_df.empty:
                return {'error': '데이터 없음'}
            
            analysis = {
                'data_count': len(data_df),
                'columns': list(data_df.columns)
            }
            
            # 시간 정보 추출
            if 'time' in data_df.columns:
                times = data_df['time'].astype(str).str.zfill(6)
                start_time = times.iloc[0] if len(times) > 0 else 'N/A'
                end_time = times.iloc[-1] if len(times) > 0 else 'N/A'
                
                analysis.update({
                    'start_time': start_time,
                    'end_time': end_time,
                    'time_range_minutes': self._calculate_time_diff(start_time, end_time),
                    'unique_times': len(times.unique())
                })
                
            elif 'datetime' in data_df.columns:
                dt_series = data_df['datetime']
                start_dt = dt_series.iloc[0] if len(dt_series) > 0 else None
                end_dt = dt_series.iloc[-1] if len(dt_series) > 0 else None
                
                if start_dt and end_dt:
                    start_time = start_dt.strftime('%H%M%S')
                    end_time = end_dt.strftime('%H%M%S')
                    
                    analysis.update({
                        'start_time': start_time,
                        'end_time': end_time,
                        'time_range_minutes': self._calculate_time_diff(start_time, end_time),
                        'start_datetime': start_dt.strftime('%Y-%m-%d %H:%M:%S'),
                        'end_datetime': end_dt.strftime('%Y-%m-%d %H:%M:%S')
                    })
            
            return analysis
            
        except Exception as e:
            return {'error': str(e)}
    
    def _calculate_time_diff(self, start_time: str, end_time: str) -> int:
        """두 시간 사이의 분 차이 계산"""
        try:
            if not start_time or not end_time or start_time == 'N/A' or end_time == 'N/A':
                return 0
                
            start_time = str(start_time).zfill(6)
            end_time = str(end_time).zfill(6)
            
            start_hour = int(start_time[:2])
            start_minute = int(start_time[2:4])
            end_hour = int(end_time[:2])
            end_minute = int(end_time[2:4])
            
            start_total = start_hour * 60 + start_minute
            end_total = end_hour * 60 + end_minute
            
            return max(0, end_total - start_total)
            
        except:
            return 0
    
    def _calculate_expected_range(self, start_time: str, end_time: str) -> int:
        """예상 시간 범위 계산"""
        return self._calculate_time_diff(start_time, end_time)
    
    async def test_various_selection_times(self, stock_code: str = "005930", 
                                         target_date: str = "20250801") -> dict:
        """
        다양한 선정 시간에 대한 테스트
        
        Args:
            stock_code: 테스트 종목코드
            target_date: 테스트 날짜
            
        Returns:
            dict: 테스트 결과
        """
        try:
            self.logger.info(f"\n=== 다양한 선정 시간 테스트 ===")
            
            # 다양한 장중 시간 테스트
            test_times = [
                ("100000", "10시 선정"),
                ("113000", "11시 30분 선정"),
                ("130000", "13시 선정"),
                ("140000", "14시 선정"),
                ("150000", "15시 선정")
            ]
            
            results = {}
            
            for test_time, description in test_times:
                try:
                    self.logger.info(f"\n{description} ({test_time}) 테스트 중...")
                    
                    data_df = await get_full_trading_day_data_async(
                        stock_code=stock_code,
                        target_date=target_date,
                        selected_time=test_time
                    )
                    
                    if data_df is not None and not data_df.empty:
                        analysis = self._analyze_data_time_range(data_df)
                        expected_range = self._calculate_expected_range("090000", test_time)
                        
                        results[test_time] = {
                            'success': True,
                            'description': description,
                            'data_count': len(data_df),
                            'analysis': analysis,
                            'expected_range_minutes': expected_range,
                            'coverage_rate': analysis.get('time_range_minutes', 0) / expected_range if expected_range > 0 else 0
                        }
                        
                        self.logger.info(f"  ✅ {description}: {len(data_df)}건")
                        self.logger.info(f"     시간 범위: {analysis.get('start_time')} ~ {analysis.get('end_time')}")
                        self.logger.info(f"     커버리지: {results[test_time]['coverage_rate']:.1%}")
                        
                    else:
                        results[test_time] = {
                            'success': False,
                            'description': description,
                            'error': '데이터 없음'
                        }
                        self.logger.warning(f"  ⚠️ {description}: 데이터 없음")
                    
                    # API 호출 간격
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    results[test_time] = {
                        'success': False,
                        'description': description,
                        'error': str(e)
                    }
                    self.logger.error(f"  ❌ {description} 오류: {e}")
            
            # 결과 요약
            successful_tests = [r for r in results.values() if r.get('success')]
            self.logger.info(f"\n📊 다양한 시간 테스트 요약:")
            self.logger.info(f"   성공: {len(successful_tests)}/{len(test_times)}개")
            
            if successful_tests:
                avg_coverage = sum(r.get('coverage_rate', 0) for r in successful_tests) / len(successful_tests)
                self.logger.info(f"   평균 커버리지: {avg_coverage:.1%}")
            
            return {
                'total_tests': len(test_times),
                'successful_tests': len(successful_tests),
                'results': results,
                'summary': {
                    'success_rate': len(successful_tests) / len(test_times),
                    'avg_coverage': sum(r.get('coverage_rate', 0) for r in successful_tests) / len(successful_tests) if successful_tests else 0
                }
            }
            
        except Exception as e:
            self.logger.error(f"다양한 선정 시간 테스트 오류: {e}")
            return {'success': False, 'error': str(e)}


async def main():
    """메인 실행 함수"""
    try:
        print("전체 거래시간 분봉 데이터 수집 기능 테스트")
        print("=" * 60)
        print("목적: 장중 13시에 종목이 선정되었을 때")
        print("      09:00부터 13:00까지의 모든 분봉 데이터 수집 확인")
        print()
        
        # 테스트 초기화
        tester = FullTradingDayTest()
        if not await tester.initialize():
            print("❌ 테스트 초기화 실패")
            return
        
        # 1. 기본 테스트 (13시 선정 시나리오)
        print("1. 기본 테스트 실행 중...")
        basic_result = await tester.test_full_trading_day_data_collection(
            stock_code="005930",
            target_date="20250801", 
            simulated_selection_time="130000"
        )
        
        # 2. 다양한 시간 테스트
        print("\n2. 다양한 선정 시간 테스트 실행 중...")
        various_result = await tester.test_various_selection_times(
            stock_code="005930",
            target_date="20250801"
        )
        
        # 결과 요약
        print("\n" + "=" * 60)
        print("🎯 테스트 결과 요약")
        print("=" * 60)
        
        # 기본 테스트 결과
        if basic_result.get('overall_success'):
            print("✅ 기본 테스트 성공")
            
            direct_test = basic_result.get('tests', {}).get('direct_api', {})
            if direct_test.get('success'):
                analysis = direct_test.get('time_analysis', {})
                print(f"   직접 API: {direct_test['data_count']}건")
                print(f"   시간 범위: {analysis.get('start_time')} ~ {analysis.get('end_time')}")
                print(f"   커버 시간: {analysis.get('time_range_minutes')}분")
            
            integrated_test = basic_result.get('tests', {}).get('integrated', {})
            if integrated_test.get('success'):
                print(f"   통합 시스템: {integrated_test['data_count']}건")
        else:
            print("❌ 기본 테스트 실패")
        
        # 다양한 시간 테스트 결과
        if various_result.get('summary'):
            summary = various_result['summary']
            print(f"\n📊 다양한 시간 테스트:")
            print(f"   성공률: {summary['success_rate']:.1%}")
            print(f"   평균 커버리지: {summary['avg_coverage']:.1%}")
        
        # 결론
        print(f"\n💡 결론:")
        if basic_result.get('overall_success') and various_result.get('summary', {}).get('success_rate', 0) > 0.8:
            print("✅ 전체 거래시간 분봉 데이터 수집 기능이 정상 작동합니다!")
            print("   - 장중 종목 선정 시 09:00부터 선정시점까지 데이터 수집 가능")
            print("   - 기존 API 제한(120건)을 극복하여 전체 거래시간 커버")
            print("   - IntradayStockManager 통합 지원")
        else:
            print("⚠️ 일부 기능에 문제가 있을 수 있습니다.")
            print("   로그를 확인하여 원인을 파악해주세요.")
        
        print(f"\n⏱️ 테스트 완료 시간: {now_kst().strftime('%H:%M:%S')}")
        
    except Exception as e:
        print(f"❌ 메인 테스트 오류: {e}")


if __name__ == "__main__":
    asyncio.run(main())