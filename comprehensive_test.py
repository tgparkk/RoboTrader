"""
시간 제약 없는 종합 테스트 - 전체 플로우 검증
조건검색 → IntradayStockManager → 차트생성 전체 과정 테스트
"""
import asyncio
import sys
from pathlib import Path
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from main import DayTradingBot
from post_market_chart_generator import PostMarketChartGenerator
from utils.logger import setup_logger
from utils.korean_time import now_kst


class ComprehensiveTestSuite:
    """
    종합 테스트 스위트 - 시간 제약 없이 모든 기능 테스트
    
    테스트하는 기능들:
    1. 조건검색 실행 및 결과 조회
    2. IntradayStockManager에 종목 추가
    3. 종목별 분봉 데이터 수집
    4. 장 마감 후 차트 생성
    5. 전체 플로우 통합 테스트
    """
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.bot = None
        self.chart_generator = None
        
        self.logger.info("종합 테스트 스위트 초기화")
    
    async def setup(self) -> bool:
        """테스트 환경 설정"""
        try:
            self.logger.info("=== 테스트 환경 설정 시작 ===")
            
            # DayTradingBot 인스턴스 생성
            self.bot = DayTradingBot()
            
            # 시스템 초기화
            if not await self.bot.initialize():
                self.logger.error("시스템 초기화 실패")
                return False
            
            # 차트 생성기 초기화
            self.chart_generator = PostMarketChartGenerator()
            if not self.chart_generator.initialize():
                self.logger.error("차트 생성기 초기화 실패")
                return False
            
            self.logger.info("테스트 환경 설정 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"테스트 환경 설정 오류: {e}")
            return False
    
    async def test_condition_search(self) -> dict:
        """조건검색 기능 테스트"""
        try:
            self.logger.info("\n=== 1. 조건검색 기능 테스트 ===")
            
            test_result = {
                'name': '조건검색 테스트',
                'success': False,
                'details': {},
                'found_stocks': []
            }
            
            # 조건검색 실행 (0번부터 2번까지 테스트)
            all_results = []
            
            for seq in ["0", "1", "2"]:
                try:
                    self.logger.info(f"조건검색 {seq}번 실행 중...")
                    
                    condition_results = self.bot.candidate_selector.get_condition_search_candidates(seq=seq)
                    
                    if condition_results:
                        all_results.extend(condition_results)
                        test_result['details'][f'seq_{seq}'] = {
                            'success': True,
                            'count': len(condition_results),
                            'stocks': condition_results[:3]  # 상위 3개만 저장
                        }
                        
                        self.logger.info(f"조건검색 {seq}번: {len(condition_results)}개 종목 발견")
                        
                        # 발견된 종목 로그
                        for i, stock in enumerate(condition_results[:3]):
                            code = stock.get('code', 'N/A')
                            name = stock.get('name', 'N/A')
                            price = stock.get('price', 'N/A')
                            chgrate = stock.get('chgrate', 'N/A')
                            self.logger.info(f"  {i+1}. {code}({name}): {price}원 ({chgrate}%)")
                    else:
                        test_result['details'][f'seq_{seq}'] = {
                            'success': True,
                            'count': 0,
                            'message': '조건에 맞는 종목 없음'
                        }
                        self.logger.info(f"조건검색 {seq}번: 조건에 맞는 종목 없음")
                        
                except Exception as e:
                    test_result['details'][f'seq_{seq}'] = {
                        'success': False,
                        'error': str(e)
                    }
                    self.logger.error(f"조건검색 {seq}번 오류: {e}")
            
            # 결과 정리
            test_result['found_stocks'] = all_results
            test_result['total_found'] = len(all_results)
            test_result['success'] = len(all_results) > 0
            
            if test_result['success']:
                self.logger.info(f"조건검색 테스트 성공: 총 {len(all_results)}개 종목 발견")
            else:
                self.logger.warning("조건검색 테스트: 발견된 종목 없음 (정상적인 상황일 수 있음)")
            
            return test_result
            
        except Exception as e:
            self.logger.error(f"조건검색 테스트 오류: {e}")
            return {
                'name': '조건검색 테스트',
                'success': False,
                'error': str(e)
            }
    
    async def test_intraday_stock_manager(self, found_stocks: list) -> dict:
        """IntradayStockManager 기능 테스트"""
        try:
            self.logger.info("\n=== 2. IntradayStockManager 기능 테스트 ===")
            
            test_result = {
                'name': 'IntradayStockManager 테스트',
                'success': False,
                'details': {},
                'added_stocks': []
            }
            
            if not found_stocks:
                # 조건검색에서 종목이 없으면 테스트용 종목 사용
                self.logger.info("조건검색 결과가 없어 테스트용 종목 사용")
                test_stocks = [
                    {"code": "005930", "name": "삼성전자", "chgrate": "2.5"},
                    {"code": "000660", "name": "SK하이닉스", "chgrate": "3.2"}
                ]
            else:
                # 조건검색 결과 사용 (최대 5개)
                test_stocks = found_stocks[:5]
            
            # 장 시간 체크 임시 비활성화
            original_is_market_open = None
            try:
                import core.intraday_stock_manager
                original_is_market_open = core.intraday_stock_manager.is_market_open
                core.intraday_stock_manager.is_market_open = lambda: True
                
                self.logger.info(f"{len(test_stocks)}개 종목을 IntradayStockManager에 추가 중...")
                
                added_count = 0
                for stock in test_stocks:
                    try:
                        stock_code = stock.get('code', '')
                        stock_name = stock.get('name', '')
                        change_rate = stock.get('chgrate', '0')
                        
                        if not stock_code:
                            continue
                        
                        # IntradayStockManager에 종목 추가
                        selection_reason = f"테스트 선정 종목 (등락률: {change_rate}%)"
                        success = self.bot.intraday_manager.add_selected_stock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            selection_reason=selection_reason
                        )
                        
                        if success:
                            test_result['added_stocks'].append({
                                'code': stock_code,
                                'name': stock_name,
                                'change_rate': change_rate
                            })
                            added_count += 1
                            self.logger.info(f"종목 추가 성공: {stock_code}({stock_name})")
                        else:
                            self.logger.warning(f"종목 추가 실패: {stock_code}({stock_name})")
                            
                    except Exception as e:
                        self.logger.error(f"종목 {stock.get('code', 'N/A')} 추가 중 오류: {e}")
                
                # 결과 확인
                summary = self.bot.intraday_manager.get_all_stocks_summary()
                total_managed = summary.get('total_stocks', 0)
                
                test_result['details'] = {
                    'attempted_to_add': len(test_stocks),
                    'successfully_added': added_count,
                    'total_managed': total_managed,
                    'summary': summary
                }
                
                test_result['success'] = total_managed > 0
                
                if test_result['success']:
                    self.logger.info(f"IntradayStockManager 테스트 성공: {total_managed}개 종목 관리 중")
                    
                    # 관리 중인 종목 상세 정보 로그
                    for stock_info in summary.get('stocks', []):
                        stock_code = stock_info.get('stock_code', '')
                        stock_name = stock_info.get('stock_name', '')
                        selected_time = stock_info.get('selected_time', '')
                        self.logger.info(f"  - {stock_code}({stock_name}): {selected_time} 선정")
                else:
                    self.logger.error("IntradayStockManager 테스트 실패: 관리 중인 종목 없음")
                
            finally:
                # 원래 함수로 복원
                if original_is_market_open:
                    core.intraday_stock_manager.is_market_open = original_is_market_open
            
            return test_result
            
        except Exception as e:
            self.logger.error(f"IntradayStockManager 테스트 오류: {e}")
            return {
                'name': 'IntradayStockManager 테스트',
                'success': False,
                'error': str(e)
            }
    
    async def test_chart_generation(self, target_date: str = "20250801") -> dict:
        """차트 생성 기능 테스트"""
        try:
            self.logger.info(f"\n=== 3. 차트 생성 기능 테스트 ({target_date}) ===")
            
            test_result = {
                'name': '차트 생성 테스트',
                'success': False,
                'details': {},
                'generated_charts': []
            }
            
            # IntradayStockManager에서 관리 중인 종목 조회
            summary = self.bot.intraday_manager.get_all_stocks_summary()
            managed_stocks = summary.get('stocks', [])
            
            if not managed_stocks:
                self.logger.warning("관리 중인 종목이 없어 차트 생성 테스트 건너뜀")
                return {
                    'name': '차트 생성 테스트',
                    'success': False,
                    'message': '관리 중인 종목 없음'
                }
            
            self.logger.info(f"{len(managed_stocks)}개 관리 종목의 차트 생성 중...")
            
            success_count = 0
            total_count = len(managed_stocks)
            
            for stock_info in managed_stocks:
                try:
                    stock_code = stock_info.get('stock_code', '')
                    stock_name = stock_info.get('stock_name', '')
                    
                    if not stock_code:
                        continue
                    
                    self.logger.info(f"차트 생성 중: {stock_code}({stock_name})")
                    
                    # 분봉 데이터 조회
                    chart_df = self.chart_generator.get_historical_chart_data(stock_code, target_date)
                    
                    if chart_df is None or chart_df.empty:
                        self.logger.warning(f"{stock_code} {target_date} 데이터 없음")
                        test_result['details'][stock_code] = {
                            'success': False,
                            'error': '데이터 없음'
                        }
                        continue
                    
                    # 차트 생성
                    selection_reason = f"종합 테스트 차트 ({target_date})"
                    chart_file = self.chart_generator.create_post_market_candlestick_chart(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        chart_df=chart_df,
                        target_date=target_date,
                        selection_reason=selection_reason
                    )
                    
                    if chart_file:
                        test_result['generated_charts'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'chart_file': chart_file,
                            'data_count': len(chart_df)
                        })
                        
                        test_result['details'][stock_code] = {
                            'success': True,
                            'chart_file': chart_file,
                            'data_count': len(chart_df)
                        }
                        
                        success_count += 1
                        self.logger.info(f"차트 생성 성공: {stock_code} -> {chart_file}")
                    else:
                        test_result['details'][stock_code] = {
                            'success': False,
                            'error': '차트 생성 실패'
                        }
                        self.logger.error(f"차트 생성 실패: {stock_code}")
                        
                except Exception as e:
                    test_result['details'][stock_code] = {
                        'success': False,
                        'error': str(e)
                    }
                    self.logger.error(f"{stock_code} 차트 생성 중 오류: {e}")
            
            # 결과 정리
            test_result['success'] = success_count > 0
            test_result['success_count'] = success_count
            test_result['total_count'] = total_count
            test_result['success_rate'] = f"{success_count}/{total_count}"
            
            if test_result['success']:
                self.logger.info(f"차트 생성 테스트 성공: {success_count}/{total_count}개")
                self.logger.info("생성된 차트 파일:")
                for chart in test_result['generated_charts']:
                    self.logger.info(f"  - {chart['chart_file']} ({chart['data_count']}분봉)")
            else:
                self.logger.error("차트 생성 테스트 실패: 생성된 차트 없음")
            
            return test_result
            
        except Exception as e:
            self.logger.error(f"차트 생성 테스트 오류: {e}")
            return {
                'name': '차트 생성 테스트',
                'success': False,
                'error': str(e)
            }
    
    async def test_full_workflow(self) -> dict:
        """전체 워크플로우 통합 테스트"""
        try:
            self.logger.info("\n=== 4. 전체 워크플로우 통합 테스트 ===")
            
            workflow_result = {
                'name': '전체 워크플로우 테스트',
                'success': False,
                'steps': {},
                'summary': {}
            }
            
            # 1단계: 조건검색
            condition_result = await self.test_condition_search()
            workflow_result['steps']['condition_search'] = condition_result
            
            # 2단계: IntradayStockManager
            intraday_result = await self.test_intraday_stock_manager(
                condition_result.get('found_stocks', [])
            )
            workflow_result['steps']['intraday_manager'] = intraday_result
            
            # 3단계: 차트 생성
            chart_result = await self.test_chart_generation("20250801")
            workflow_result['steps']['chart_generation'] = chart_result
            
            # 전체 성공 여부 판단
            all_success = (
                intraday_result.get('success', False) and 
                chart_result.get('success', False)
            )
            
            workflow_result['success'] = all_success
            workflow_result['summary'] = {
                'condition_search_found': condition_result.get('total_found', 0),
                'stocks_added': len(intraday_result.get('added_stocks', [])),
                'charts_generated': chart_result.get('success_count', 0),
                'overall_success': all_success
            }
            
            if all_success:
                self.logger.info("전체 워크플로우 테스트 성공!")
                self.logger.info(f"  - 조건검색: {workflow_result['summary']['condition_search_found']}개 발견")
                self.logger.info(f"  - 종목 추가: {workflow_result['summary']['stocks_added']}개")
                self.logger.info(f"  - 차트 생성: {workflow_result['summary']['charts_generated']}개")
            else:
                self.logger.error("전체 워크플로우 테스트 실패")
            
            return workflow_result
            
        except Exception as e:
            self.logger.error(f"전체 워크플로우 테스트 오류: {e}")
            return {
                'name': '전체 워크플로우 테스트',
                'success': False,
                'error': str(e)
            }
    
    async def run_comprehensive_test(self) -> dict:
        """종합 테스트 실행"""
        try:
            start_time = now_kst()
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"🔬 종합 테스트 시작 - {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
            self.logger.info(f"{'='*60}")
            
            # 테스트 환경 설정
            if not await self.setup():
                return {'success': False, 'error': '테스트 환경 설정 실패'}
            
            # 전체 워크플로우 테스트 실행
            workflow_result = await self.test_full_workflow()
            
            # 결과 정리
            end_time = now_kst()
            duration = (end_time - start_time).total_seconds()
            
            final_result = {
                'test_info': {
                    'start_time': start_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'end_time': end_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'duration_seconds': duration
                },
                'workflow_result': workflow_result,
                'overall_success': workflow_result.get('success', False)
            }
            
            # 최종 결과 로그
            self.logger.info(f"\n{'='*60}")
            self.logger.info(f"🎯 종합 테스트 완료 - 소요시간: {duration:.1f}초")
            self.logger.info(f"{'='*60}")
            
            if final_result['overall_success']:
                self.logger.info("✅ 전체 시스템 정상 작동 확인!")
            else:
                self.logger.error("❌ 전체 시스템 일부 기능 이상")
            
            return final_result
            
        except Exception as e:
            self.logger.error(f"종합 테스트 실행 오류: {e}")
            return {'success': False, 'error': str(e)}
        
        finally:
            # 정리
            if self.bot:
                try:
                    await self.bot.shutdown()
                except:
                    pass


async def main():
    """메인 실행 함수"""
    try:
        print("시간 제약 없는 종합 테스트 시작")
        print("테스트 항목:")
        print("  1. 조건검색 기능")
        print("  2. IntradayStockManager")
        print("  3. 차트 생성 기능")
        print("  4. 전체 워크플로우 통합")
        print()
        
        # 종합 테스트 실행
        test_suite = ComprehensiveTestSuite()
        result = await test_suite.run_comprehensive_test()
        
        # 결과 출력
        if result.get('overall_success'):
            print("종합 테스트 성공!")
            
            workflow = result.get('workflow_result', {})
            summary = workflow.get('summary', {})
            
            print(f"테스트 결과:")
            print(f"  - 조건검색: {summary.get('condition_search_found', 0)}개 종목 발견")
            print(f"  - 종목 추가: {summary.get('stocks_added', 0)}개 성공")
            print(f"  - 차트 생성: {summary.get('charts_generated', 0)}개 성공")
            
            # 생성된 차트 파일 목록
            chart_step = workflow.get('steps', {}).get('chart_generation', {})
            generated_charts = chart_step.get('generated_charts', [])
            
            if generated_charts:
                print(f"\n생성된 차트 파일:")
                for chart in generated_charts:
                    print(f"  - {chart['chart_file']}")
        else:
            print("종합 테스트 실패")
            if 'error' in result:
                print(f"오류: {result['error']}")
        
        test_info = result.get('test_info', {})
        duration = test_info.get('duration_seconds', 0)
        print(f"\n총 소요시간: {duration:.1f}초")
        
    except Exception as e:
        print(f"메인 실행 오류: {e}")


if __name__ == "__main__":
    asyncio.run(main())