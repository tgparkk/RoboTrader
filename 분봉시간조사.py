"""
분봉 데이터의 시간 범위 조사
09:00-15:30 vs 09:20-15:17 문제 분석
"""
import asyncio
import sys
from pathlib import Path
import pandas as pd
from datetime import datetime
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_chart_api import get_inquire_time_dailychartprice, get_inquire_time_itemchartprice
from api.kis_api_manager import KISAPIManager
from utils.logger import setup_logger
from utils.korean_time import now_kst

logger = setup_logger(__name__)


class MinuteDataTimeAnalyzer:
    """분봉 데이터 시간 범위 분석기"""
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.api_manager = None
        
    async def initialize(self) -> bool:
        """초기화"""
        try:
            self.logger.info("=== 분봉 시간 범위 분석기 초기화 ===")
            
            # API 매니저 초기화
            self.api_manager = KISAPIManager()
            if not self.api_manager.initialize():
                self.logger.error("API 매니저 초기화 실패")
                return False
            
            self.logger.info("초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"초기화 오류: {e}")
            return False
    
    def analyze_minute_data_time_range(self, stock_code: str, target_date: str) -> dict:
        """분봉 데이터 시간 범위 분석"""
        try:
            self.logger.info(f"\n=== {stock_code} {target_date} 분봉 시간 범위 분석 ===")
            
            analysis_result = {
                'stock_code': stock_code,
                'target_date': target_date,
                'api_tests': {}
            }
            
            # 1. 일별분봉조회 API 테스트 (다양한 시간으로)
            self.logger.info("1. 일별분봉조회 API 테스트")
            
            test_times = [
                "090000",  # 09:00 장 시작
                "093000",  # 09:30 
                "120000",  # 12:00 점심
                "153000",  # 15:30 장 마감
                "160000",  # 16:00 장 마감 후
                "170000"   # 17:00
            ]
            
            for test_time in test_times:
                try:
                    self.logger.info(f"  테스트 시간: {test_time}")
                    
                    result = get_inquire_time_dailychartprice(
                        stock_code=stock_code,
                        input_date=target_date,
                        input_hour=test_time,
                        past_data_yn="Y"
                    )
                    
                    if result:
                        summary_df, chart_df = result
                        
                        if not chart_df.empty:
                            # 시간 범위 분석
                            time_analysis = self._analyze_time_range(chart_df, test_time)
                            analysis_result['api_tests'][f'daily_{test_time}'] = time_analysis
                            
                            self.logger.info(f"    데이터 개수: {len(chart_df)}개")
                            self.logger.info(f"    시간 범위: {time_analysis['first_time']} ~ {time_analysis['last_time']}")
                        else:
                            analysis_result['api_tests'][f'daily_{test_time}'] = {
                                'success': False, 'error': '데이터 없음'
                            }
                    else:
                        analysis_result['api_tests'][f'daily_{test_time}'] = {
                            'success': False, 'error': 'API 호출 실패'
                        }
                        
                except Exception as e:
                    analysis_result['api_tests'][f'daily_{test_time}'] = {
                        'success': False, 'error': str(e)
                    }
                    self.logger.error(f"    오류: {e}")
            
            # 2. 당일분봉조회 API 테스트
            self.logger.info("\n2. 당일분봉조회 API 테스트")
            
            for test_time in test_times:
                try:
                    self.logger.info(f"  테스트 시간: {test_time}")
                    
                    result = get_inquire_time_itemchartprice(
                        stock_code=stock_code,
                        input_hour=test_time,
                        past_data_yn="Y"
                    )
                    
                    if result:
                        summary_df, chart_df = result
                        
                        if not chart_df.empty:
                            # 시간 범위 분석
                            time_analysis = self._analyze_time_range(chart_df, test_time)
                            analysis_result['api_tests'][f'today_{test_time}'] = time_analysis
                            
                            self.logger.info(f"    데이터 개수: {len(chart_df)}개")
                            self.logger.info(f"    시간 범위: {time_analysis['first_time']} ~ {time_analysis['last_time']}")
                        else:
                            analysis_result['api_tests'][f'today_{test_time}'] = {
                                'success': False, 'error': '데이터 없음'
                            }
                    else:
                        analysis_result['api_tests'][f'today_{test_time}'] = {
                            'success': False, 'error': 'API 호출 실패'
                        }
                        
                except Exception as e:
                    analysis_result['api_tests'][f'today_{test_time}'] = {
                        'success': False, 'error': str(e)
                    }
                    self.logger.error(f"    오류: {e}")
            
            # 3. 최적 시간 범위 확인
            self.logger.info("\n3. 최적 시간 범위 확인")
            best_result = self._find_best_time_range(analysis_result['api_tests'])
            analysis_result['best_result'] = best_result
            
            if best_result:
                self.logger.info(f"✅ 최적 결과: {best_result['api_type']} - {best_result['test_time']}")
                self.logger.info(f"   시간 범위: {best_result['first_time']} ~ {best_result['last_time']}")
                self.logger.info(f"   데이터 개수: {best_result['data_count']}개")
            else:
                self.logger.warning("⚠️ 최적 결과를 찾을 수 없음")
            
            return analysis_result
            
        except Exception as e:
            self.logger.error(f"분봉 시간 범위 분석 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    def _analyze_time_range(self, chart_df: pd.DataFrame, test_time: str) -> dict:
        """차트 데이터의 시간 범위 분석"""
        try:
            if chart_df.empty:
                return {'success': False, 'error': '데이터 없음'}
            
            time_analysis = {
                'success': True,
                'test_time': test_time,
                'data_count': len(chart_df),
                'columns': list(chart_df.columns)
            }
            
            # 시간 컬럼 확인
            if 'time' in chart_df.columns:
                times = chart_df['time'].astype(str)
                first_time = times.iloc[0] if len(times) > 0 else 'N/A'
                last_time = times.iloc[-1] if len(times) > 0 else 'N/A'
                
                time_analysis.update({
                    'first_time': first_time,
                    'last_time': last_time,
                    'time_count': len(times.unique()),
                    'all_times': times.tolist()[:5] + (['...'] if len(times) > 5 else [])
                })
            
            # datetime 컬럼 확인
            if 'datetime' in chart_df.columns:
                dt_series = chart_df['datetime']
                first_dt = dt_series.iloc[0] if len(dt_series) > 0 else None
                last_dt = dt_series.iloc[-1] if len(dt_series) > 0 else None
                
                time_analysis.update({
                    'first_datetime': first_dt.strftime('%H:%M:%S') if first_dt else 'N/A',
                    'last_datetime': last_dt.strftime('%H:%M:%S') if last_dt else 'N/A'
                })
            
            # 원본 컬럼 확인 (KIS API 원본)
            if 'stck_cntg_hour' in chart_df.columns:
                orig_times = chart_df['stck_cntg_hour'].astype(str)
                first_orig = orig_times.iloc[0] if len(orig_times) > 0 else 'N/A'
                last_orig = orig_times.iloc[-1] if len(orig_times) > 0 else 'N/A'
                
                time_analysis.update({
                    'first_orig_time': first_orig,
                    'last_orig_time': last_orig,
                    'orig_time_sample': orig_times.tolist()[:5]
                })
            
            return time_analysis
            
        except Exception as e:
            return {'success': False, 'error': str(e)}
    
    def _find_best_time_range(self, api_tests: dict) -> dict:
        """최적의 시간 범위 결과 찾기"""
        try:
            best_result = None
            max_data_count = 0
            
            for test_key, test_result in api_tests.items():
                if test_result.get('success') and test_result.get('data_count', 0) > max_data_count:
                    max_data_count = test_result['data_count']
                    best_result = test_result.copy()
                    best_result['api_type'] = test_key.split('_')[0]  # 'daily' or 'today'
                    best_result['test_time'] = test_key.split('_')[1]
            
            return best_result
            
        except Exception as e:
            self.logger.error(f"최적 결과 찾기 오류: {e}")
            return None
    
    def investigate_time_gap_reason(self, stock_code: str, target_date: str) -> dict:
        """시간 공백 발생 원인 조사"""
        try:
            self.logger.info(f"\n=== 시간 공백 원인 조사 ({stock_code}, {target_date}) ===")
            
            investigation = {
                'stock_code': stock_code,
                'target_date': target_date,
                'findings': {}
            }
            
            # 1. 다양한 input_hour로 테스트
            self.logger.info("1. 다양한 input_hour 테스트")
            
            # 매우 이른 시간부터 늦은 시간까지 테스트
            extended_times = [
                "080000", "085500", "090000", "090500", "091000", "091500", "092000",  # 장 시작 전후
                "152500", "153000", "153500", "154000", "154500", "155000", "160000"   # 장 마감 전후
            ]
            
            for test_time in extended_times:
                try:
                    result = get_inquire_time_dailychartprice(
                        stock_code=stock_code,
                        input_date=target_date,
                        input_hour=test_time,
                        past_data_yn="Y"
                    )
                    
                    if result:
                        summary_df, chart_df = result
                        
                        if not chart_df.empty and 'time' in chart_df.columns:
                            times = chart_df['time'].astype(str).str.zfill(6)
                            first_time = times.iloc[0]
                            last_time = times.iloc[-1]
                            
                            investigation['findings'][test_time] = {
                                'success': True,
                                'data_count': len(chart_df),
                                'first_time': first_time,
                                'last_time': last_time,
                                'time_range_minutes': self._calculate_time_difference(first_time, last_time)
                            }
                            
                            self.logger.info(f"  {test_time}: {len(chart_df)}개, {first_time}~{last_time}")
                        else:
                            investigation['findings'][test_time] = {
                                'success': False, 'error': '데이터 없음'
                            }
                    else:
                        investigation['findings'][test_time] = {
                            'success': False, 'error': 'API 호출 실패'
                        }
                        
                except Exception as e:
                    investigation['findings'][test_time] = {
                        'success': False, 'error': str(e)
                    }
            
            # 2. 결과 분석
            self.logger.info("\n2. 조사 결과 분석")
            
            successful_tests = {k: v for k, v in investigation['findings'].items() if v.get('success')}
            
            if successful_tests:
                # 가장 넓은 시간 범위를 가진 결과 찾기
                best_coverage = max(successful_tests.items(), 
                                  key=lambda x: x[1].get('data_count', 0))
                
                investigation['analysis'] = {
                    'best_input_hour': best_coverage[0],
                    'max_data_count': best_coverage[1]['data_count'],
                    'earliest_time': min([v['first_time'] for v in successful_tests.values()]),
                    'latest_time': max([v['last_time'] for v in successful_tests.values()]),
                    'conclusions': []
                }
                
                # 결론 도출
                earliest = investigation['analysis']['earliest_time']
                latest = investigation['analysis']['latest_time']
                
                self.logger.info(f"✅ 조사 완료:")
                self.logger.info(f"   최적 input_hour: {investigation['analysis']['best_input_hour']}")
                self.logger.info(f"   최대 데이터 수: {investigation['analysis']['max_data_count']}개")
                self.logger.info(f"   실제 가능한 시간 범위: {earliest} ~ {latest}")
                
                # 시간 공백 이유 분석
                if earliest > "090000":
                    conclusion = f"장 시작({earliest}) 이전 분봉 데이터는 제공되지 않음"
                    investigation['analysis']['conclusions'].append(conclusion)
                    self.logger.info(f"   - {conclusion}")
                
                if latest < "153000":
                    conclusion = f"장 마감({latest}) 이후 분봉 데이터는 제공되지 않음"
                    investigation['analysis']['conclusions'].append(conclusion)
                    self.logger.info(f"   - {conclusion}")
                
                if earliest == "092000" or earliest.startswith("092"):
                    conclusion = "실제 거래가 시작되는 09:20부터 데이터 제공 (콜옵션 9:20 시작)"
                    investigation['analysis']['conclusions'].append(conclusion)
                    self.logger.info(f"   - {conclusion}")
                
            else:
                investigation['analysis'] = {
                    'error': '모든 테스트 실패'
                }
                
            return investigation
            
        except Exception as e:
            self.logger.error(f"시간 공백 원인 조사 오류: {e}")
            return {'success': False, 'error': str(e)}
    
    def _calculate_time_difference(self, start_time: str, end_time: str) -> int:
        """두 시간 사이의 분 차이 계산"""
        try:
            start_hour = int(start_time[:2])
            start_minute = int(start_time[2:4])
            end_hour = int(end_time[:2])
            end_minute = int(end_time[2:4])
            
            start_total_minutes = start_hour * 60 + start_minute
            end_total_minutes = end_hour * 60 + end_minute
            
            return end_total_minutes - start_total_minutes
            
        except:
            return 0


async def main():
    """메인 실행 함수"""
    try:
        print("분봉 데이터 시간 범위 조사")
        print("=" * 50)
        
        # 분석기 초기화
        analyzer = MinuteDataTimeAnalyzer()
        if not await analyzer.initialize():
            print("초기화 실패")
            return
        
        # 테스트 설정
        stock_code = "005930"  # 삼성전자
        target_date = "20250801"  # 2025년 8월 1일
        
        print(f"테스트 종목: {stock_code}")
        print(f"테스트 날짜: {target_date}")
        print()
        
        # 1. 분봉 시간 범위 분석
        print("1. 분봉 시간 범위 분석 시작...")
        time_analysis = analyzer.analyze_minute_data_time_range(stock_code, target_date)
        
        # 2. 시간 공백 원인 조사
        print("\n2. 시간 공백 원인 조사 시작...")
        gap_investigation = analyzer.investigate_time_gap_reason(stock_code, target_date)
        
        # 결과 요약
        print("\n" + "=" * 60)
        print("🔍 조사 결과 요약")
        print("=" * 60)
        
        if gap_investigation.get('analysis'):
            analysis = gap_investigation['analysis']
            
            if 'error' not in analysis:
                print(f"✅ 최적 설정: input_hour = {analysis['best_input_hour']}")
                print(f"📊 최대 데이터 수: {analysis['max_data_count']}개")
                print(f"⏰ 실제 시간 범위: {analysis['earliest_time']} ~ {analysis['latest_time']}")
                print()
                
                if analysis.get('conclusions'):
                    print("📋 결론:")
                    for conclusion in analysis['conclusions']:
                        print(f"   - {conclusion}")
                else:
                    print("💡 일반적인 한국 주식시장 분봉 특성:")
                    print("   - 프리마켓: 08:30-09:00 (제한적)")
                    print("   - 정규장: 09:00-15:30")
                    print("   - 실제 활발한 거래: 09:20경부터 시작")
                    print("   - 장마감 후 시간외 거래: 15:30-16:00 (제한적)")
            else:
                print(f"❌ 조사 실패: {analysis['error']}")
        else:
            print("❌ 조사 결과를 가져올 수 없음")
        
        print(f"\n⏱️ 조사 완료 시간: {now_kst().strftime('%H:%M:%S')}")
        
    except Exception as e:
        print(f"❌ 메인 실행 오류: {e}")


if __name__ == "__main__":
    asyncio.run(main())