"""
장중 동작 코드 시뮬레이션 테스트
종목코드와 날짜를 입력받아 전체 프로세스를 테스트
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_chart_api import (
    get_inquire_time_dailychartprice,
    get_inquire_time_itemchartprice,
    get_recent_minute_data,
    get_realtime_minute_data
)
from api.kis_api_manager import KISAPIManager
from core.intraday_stock_manager import IntradayStockManager
from post_market_chart_generator import PostMarketChartGenerator
from utils.logger import setup_logger
from utils.korean_time import now_kst


class MarketSimulationTest:
    """
    장중 동작 시뮬레이션 테스트 클래스
    
    기능:
    1. 종목코드와 날짜를 입력받아 데이터 수집
    2. IntradayStockManager에 종목 추가 시뮬레이션
    3. 분봉 데이터 수집 (과거 + 실시간)
    4. 캔들스틱 차트 생성
    5. 전체 플로우 검증
    """
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.api_manager = None
        self.intraday_manager = None
        self.chart_generator = None
        
        self.logger.info("장중 동작 시뮬레이션 테스트 초기화")
    
    async def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            self.logger.info("=== 시스템 초기화 시작 ===")
            
            # API 매니저 초기화
            self.api_manager = KISAPIManager()
            if not self.api_manager.initialize():
                self.logger.error("API 매니저 초기화 실패")
                return False
            
            # IntradayStockManager 초기화
            self.intraday_manager = IntradayStockManager(self.api_manager)
            
            # 차트 생성기 초기화
            self.chart_generator = PostMarketChartGenerator()
            if not self.chart_generator.initialize():
                self.logger.error("차트 생성기 초기화 실패")
                return False
            
            self.logger.info("시스템 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"시스템 초기화 오류: {e}")
            return False
    
    async def test_api_functions(self, stock_code: str, stock_name: str, target_date: str) -> dict:
        """분봉 조회 API 함수들 테스트"""
        try:
            self.logger.info(f"\n=== 1. 분봉 조회 API 테스트 ({stock_code}) ===")
            
            api_results = {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'target_date': target_date,
                'tests': {}
            }
            
            # 1. 일별분봉조회 테스트
            self.logger.info("1-1. 일별분봉조회 API 테스트")
            try:
                result1 = get_inquire_time_dailychartprice(
                    stock_code=stock_code,
                    input_date=target_date,
                    input_hour="153000"  # 15:30 장마감
                )
                
                if result1:
                    summary_df, chart_df = result1
                    api_results['tests']['daily_chart'] = {
                        'success': True,
                        'data_count': len(chart_df),
                        'data_sample': chart_df.head(3).to_dict('records') if not chart_df.empty else []
                    }
                    self.logger.info(f"일별분봉조회 성공: {len(chart_df)}건")
                else:
                    api_results['tests']['daily_chart'] = {'success': False, 'error': 'No data'}
                    
            except Exception as e:
                api_results['tests']['daily_chart'] = {'success': False, 'error': str(e)}
                self.logger.error(f"일별분봉조회 오류: {e}")
            
            # 2. 당일분봉조회 테스트
            self.logger.info("1-2. 당일분봉조회 API 테스트")
            try:
                result2 = get_inquire_time_itemchartprice(
                    stock_code=stock_code,
                    input_hour="153000"
                )
                
                if result2:
                    summary_df, chart_df = result2
                    api_results['tests']['today_chart'] = {
                        'success': True,
                        'data_count': len(chart_df),
                        'data_sample': chart_df.head(3).to_dict('records') if not chart_df.empty else []
                    }
                    self.logger.info(f"당일분봉조회 성공: {len(chart_df)}건")
                else:
                    api_results['tests']['today_chart'] = {'success': False, 'error': 'No data'}
                    
            except Exception as e:
                api_results['tests']['today_chart'] = {'success': False, 'error': str(e)}
                self.logger.error(f"당일분봉조회 오류: {e}")
            
            # 3. 최근 분봉 데이터 조회 테스트
            self.logger.info("1-3. 최근 분봉 데이터 조회 테스트")
            try:
                chart_df = get_recent_minute_data(stock_code=stock_code, minutes=60)
                
                if chart_df is not None and not chart_df.empty:
                    api_results['tests']['recent_data'] = {
                        'success': True,
                        'data_count': len(chart_df),
                        'data_sample': chart_df.head(3).to_dict('records')
                    }
                    self.logger.info(f"최근 분봉 데이터 조회 성공: {len(chart_df)}건")
                else:
                    api_results['tests']['recent_data'] = {'success': False, 'error': 'No data'}
                    
            except Exception as e:
                api_results['tests']['recent_data'] = {'success': False, 'error': str(e)}
                self.logger.error(f"최근 분봉 데이터 조회 오류: {e}")
            
            return api_results
            
        except Exception as e:
            self.logger.error(f"API 테스트 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    async def test_intraday_manager(self, stock_code: str, stock_name: str) -> dict:
        """IntradayStockManager 테스트"""
        try:
            self.logger.info(f"\n=== 2. IntradayStockManager 테스트 ({stock_code}) ===")
            
            # 장 시간 체크 임시 비활성화
            original_is_market_open = None
            try:
                import core.intraday_stock_manager
                original_is_market_open = core.intraday_stock_manager.is_market_open
                core.intraday_stock_manager.is_market_open = lambda: True
                
                # 종목 추가 시뮬레이션
                selection_reason = f"시뮬레이션 테스트 선정 종목"
                success = self.intraday_manager.add_selected_stock(
                    stock_code=stock_code,
                    stock_name=stock_name,
                    selection_reason=selection_reason
                )
                
                if success:
                    self.logger.info(f"IntradayStockManager 종목 추가 성공: {stock_code}")
                    
                    # 과거 분봉 데이터 수집 대기
                    await asyncio.sleep(2)
                    
                    # 종목 데이터 조회
                    stock_data = self.intraday_manager.get_stock_data(stock_code)
                    
                    if stock_data:
                        # 분석 정보 조회
                        analysis = self.intraday_manager.get_stock_analysis(stock_code)
                        
                        result = {
                            'success': True,
                            'stock_data': {
                                'stock_code': stock_data.stock_code,
                                'stock_name': stock_data.stock_name,
                                'selected_time': stock_data.selected_time.strftime('%H:%M:%S'),
                                'data_complete': stock_data.data_complete,
                                'historical_data_count': len(stock_data.historical_data),
                                'realtime_data_count': len(stock_data.realtime_data)
                            },
                            'analysis': analysis
                        }
                        
                        self.logger.info(f"종목 데이터 조회 성공:")
                        self.logger.info(f"  - 과거 분봉: {len(stock_data.historical_data)}건")
                        self.logger.info(f"  - 실시간 분봉: {len(stock_data.realtime_data)}건")
                        self.logger.info(f"  - 데이터 완료: {stock_data.data_complete}")
                        
                        return result
                    else:
                        return {'success': False, 'error': '종목 데이터 조회 실패'}
                else:
                    return {'success': False, 'error': '종목 추가 실패'}
                    
            finally:
                # 원래 함수로 복원
                if original_is_market_open:
                    core.intraday_stock_manager.is_market_open = original_is_market_open
            
        except Exception as e:
            self.logger.error(f"IntradayStockManager 테스트 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    async def test_chart_generation(self, stock_code: str, stock_name: str, target_date: str) -> dict:
        """차트 생성 테스트"""
        try:
            self.logger.info(f"\n=== 3. 차트 생성 테스트 ({stock_code}) ===")
            
            # 차트 데이터 조회
            chart_df = self.chart_generator.get_historical_chart_data(stock_code, target_date)
            
            if chart_df is None or chart_df.empty:
                return {
                    'success': False,
                    'error': f'{target_date} 날짜의 데이터가 없습니다'
                }
            
            self.logger.info(f"차트 데이터 조회 성공: {len(chart_df)}건")
            
            # 차트 생성
            selection_reason = f"시뮬레이션 테스트 - {target_date}"
            chart_file = self.chart_generator.create_post_market_candlestick_chart(
                stock_code=stock_code,
                stock_name=stock_name,
                chart_df=chart_df,
                target_date=target_date,
                selection_reason=selection_reason
            )
            
            if chart_file:
                # 차트 통계 정보
                stats = {
                    'data_count': len(chart_df),
                    'start_price': float(chart_df.iloc[0]['close']) if 'close' in chart_df.columns else 0,
                    'end_price': float(chart_df.iloc[-1]['close']) if 'close' in chart_df.columns else 0,
                    'high_price': float(chart_df['high'].max()) if 'high' in chart_df.columns else 0,
                    'low_price': float(chart_df['low'].min()) if 'low' in chart_df.columns else 0,
                    'total_volume': int(chart_df['volume'].sum()) if 'volume' in chart_df.columns else 0
                }
                
                if stats['start_price'] > 0:
                    price_change = stats['end_price'] - stats['start_price']
                    price_change_rate = (price_change / stats['start_price']) * 100
                    stats['price_change'] = price_change
                    stats['price_change_rate'] = price_change_rate
                
                result = {
                    'success': True,
                    'chart_file': chart_file,
                    'stats': stats
                }
                
                self.logger.info(f"차트 생성 성공: {chart_file}")
                self.logger.info(f"데이터 통계:")
                self.logger.info(f"  - 분봉 수: {stats['data_count']}개")
                self.logger.info(f"  - 시작가: {stats['start_price']:,.0f}원")
                self.logger.info(f"  - 종료가: {stats['end_price']:,.0f}원")
                if 'price_change_rate' in stats:
                    self.logger.info(f"  - 등락률: {stats['price_change_rate']:+.2f}%")
                self.logger.info(f"  - 거래량: {stats['total_volume']:,}주")
                
                return result
            else:
                return {'success': False, 'error': '차트 생성 실패'}
                
        except Exception as e:
            self.logger.error(f"차트 생성 테스트 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    async def run_simulation(self, stock_code: str, stock_name: str, target_date: str) -> dict:
        """전체 시뮬레이션 실행"""
        try:
            start_time = now_kst()
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"장중 동작 시뮬레이션 테스트 시작")
            self.logger.info(f"종목: {stock_code}({stock_name})")
            self.logger.info(f"날짜: {target_date}")
            self.logger.info(f"시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"{'='*80}")
            
            # 시스템 초기화
            if not await self.initialize():
                return {'success': False, 'error': '시스템 초기화 실패'}
            
            # 전체 테스트 실행
            results = {
                'test_info': {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'target_date': target_date,
                    'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S')
                },
                'tests': {}
            }
            
            # 1. API 테스트
            api_result = await self.test_api_functions(stock_code, stock_name, target_date)
            results['tests']['api'] = api_result
            
            # 2. IntradayStockManager 테스트
            intraday_result = await self.test_intraday_manager(stock_code, stock_name)
            results['tests']['intraday_manager'] = intraday_result
            
            # 3. 차트 생성 테스트
            chart_result = await self.test_chart_generation(stock_code, stock_name, target_date)
            results['tests']['chart_generation'] = chart_result
            
            # 전체 성공 여부 판단
            api_success = any(test.get('success', False) for test in api_result.get('tests', {}).values())
            intraday_success = intraday_result.get('success', False)
            chart_success = chart_result.get('success', False)
            
            overall_success = api_success and intraday_success and chart_success
            
            # 결과 정리
            end_time = now_kst()
            duration = (end_time - start_time).total_seconds()
            
            results['test_info'].update({
                'end_time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                'duration_seconds': duration
            })
            
            results['summary'] = {
                'overall_success': overall_success,
                'api_success': api_success,
                'intraday_success': intraday_success,
                'chart_success': chart_success,
                'chart_file': chart_result.get('chart_file') if chart_success else None
            }
            
            # 최종 결과 로그
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"시뮬레이션 테스트 완료 - 소요시간: {duration:.1f}초")
            self.logger.info(f"{'='*80}")
            
            if overall_success:
                self.logger.info("전체 시뮬레이션 성공!")
                self.logger.info(f"  - API 테스트: {'성공' if api_success else '실패'}")
                self.logger.info(f"  - IntradayStockManager: {'성공' if intraday_success else '실패'}")
                self.logger.info(f"  - 차트 생성: {'성공' if chart_success else '실패'}")
                
                if chart_result.get('chart_file'):
                    self.logger.info(f"  - 생성된 차트: {chart_result['chart_file']}")
            else:
                self.logger.error("시뮬레이션 일부 실패")
            
            return results
            
        except Exception as e:
            self.logger.error(f"시뮬레이션 실행 오류: {e}")
            return {'success': False, 'error': str(e)}


def get_user_input():
    """사용자 입력 받기"""
    try:
        print("장중 동작 시뮬레이션 테스트")
        print("=" * 50)
        
        # 종목코드 입력
        stock_code = input("종목코드를 입력하세요 (예: 005930): ").strip()
        if not stock_code:
            stock_code = "005930"  # 기본값: 삼성전자
            print(f"기본값 사용: {stock_code}")
        
        # 종목명 입력
        stock_name = input("종목명을 입력하세요 (예: 삼성전자): ").strip()
        if not stock_name:
            if stock_code == "005930":
                stock_name = "삼성전자"
            else:
                stock_name = f"종목{stock_code}"
            print(f"기본값 사용: {stock_name}")
        
        # 날짜 입력
        target_date = input("날짜를 입력하세요 (YYYYMMDD, 예: 20250801): ").strip()
        if not target_date:
            target_date = "20250801"  # 기본값
            print(f"기본값 사용: {target_date}")
        
        # 날짜 형식 검증
        try:
            datetime.strptime(target_date, "%Y%m%d")
        except ValueError:
            print("날짜 형식이 올바르지 않습니다. 기본값 사용: 20250801")
            target_date = "20250801"
        
        print(f"\n테스트 설정:")
        print(f"  - 종목: {stock_code}({stock_name})")
        print(f"  - 날짜: {target_date}")
        print()
        
        return stock_code, stock_name, target_date
        
    except KeyboardInterrupt:
        print("\n\n사용자가 취소했습니다.")
        return None, None, None
    except Exception as e:
        print(f"입력 오류: {e}")
        return None, None, None


async def main():
    """메인 실행 함수"""
    try:
        # 기본값으로 테스트 (사용자 입력 대신)
        stock_code = "005930"  # 삼성전자
        stock_name = "삼성전자"
        target_date = "20250801"  # 2025년 8월 1일
        
        print("장중 동작 시뮬레이션 테스트")
        print("=" * 50)
        print(f"테스트 설정:")
        print(f"  - 종목: {stock_code}({stock_name})")
        print(f"  - 날짜: {target_date}")
        print()
        
        # 시뮬레이션 실행
        simulator = MarketSimulationTest()
        result = await simulator.run_simulation(stock_code, stock_name, target_date)
        
        # 결과 출력
        print("\n" + "=" * 80)
        print("테스트 결과 요약")
        print("=" * 80)
        
        if result.get('summary', {}).get('overall_success'):
            print("✅ 전체 시뮬레이션 성공!")
            
            summary = result.get('summary', {})
            print(f"  - API 테스트: {'✅ 성공' if summary.get('api_success') else '❌ 실패'}")
            print(f"  - IntradayStockManager: {'✅ 성공' if summary.get('intraday_success') else '❌ 실패'}")
            print(f"  - 차트 생성: {'✅ 성공' if summary.get('chart_success') else '❌ 실패'}")
            
            chart_file = summary.get('chart_file')
            if chart_file:
                print(f"\n📈 생성된 차트 파일: {chart_file}")
        else:
            print("❌ 시뮬레이션 일부 실패")
            if 'error' in result:
                print(f"오류: {result['error']}")
        
        test_info = result.get('test_info', {})
        duration = test_info.get('duration_seconds', 0)
        print(f"\n⏱️ 총 소요시간: {duration:.1f}초")
        
    except Exception as e:
        print(f"❌ 메인 실행 오류: {e}")


if __name__ == "__main__":
    asyncio.run(main())