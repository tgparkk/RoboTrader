"""
장 마감 후 선정 종목 차트 생성기
"""
import asyncio
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from matplotlib.patches import Rectangle
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
import sys
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from api.kis_chart_api import (
    get_inquire_time_dailychartprice,
    get_historical_minute_data
)
from api.kis_api_manager import KISAPIManager
from core.candidate_selector import CandidateSelector
from core.intraday_stock_manager import IntradayStockManager
from utils.logger import setup_logger
from utils.korean_time import now_kst


class PostMarketChartGenerator:
    """
    장 마감 후 선정 종목 차트 생성 클래스
    
    주요 기능:
    1. 조건검색으로 선정된 종목 조회
    2. 특정 날짜의 분봉 데이터로 캔들스틱 차트 생성
    3. 장중 선정 종목들의 일괄 차트 생성
    """
    
    def __init__(self):
        """초기화"""
        self.logger = setup_logger(__name__)
        self.api_manager = None
        self.candidate_selector = None
        self.intraday_manager = None
        
        # 차트 설정
        plt.rcParams['font.family'] = ['Malgun Gothic', 'DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False
        
        self.logger.info("장 마감 후 차트 생성기 초기화 완료")
    
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
        """
        조건검색 종목 조회 (실제 조건검색 결과 사용)
        
        Args:
            condition_seq: 조건검색 시퀀스
            
        Returns:
            List[Dict]: 조건검색 결과 종목 리스트
        """
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
    
    def get_historical_chart_data(self, stock_code: str, target_date: str) -> Optional[pd.DataFrame]:
        """
        특정 날짜의 분봉 데이터 조회
        
        Args:
            stock_code: 종목코드
            target_date: 조회 날짜 (YYYYMMDD)
            
        Returns:
            pd.DataFrame: 분봉 데이터
        """
        try:
            self.logger.info(f"{stock_code} {target_date} 분봉 데이터 조회 시작")
            
            # 일별분봉조회 API 사용 (해당 날짜의 장마감 시간까지)
            result = get_inquire_time_dailychartprice(
                stock_code=stock_code,
                input_date=target_date,
                input_hour="153000",  # 15:30 장마감
                past_data_yn="Y"
            )
            
            if result is None:
                self.logger.error(f"{stock_code} {target_date} 분봉 데이터 조회 실패")
                return None
            
            summary_df, chart_df = result
            
            if chart_df.empty:
                self.logger.warning(f"{stock_code} {target_date} 분봉 데이터 없음")
                return None
            
            # 데이터 검증
            required_columns = ['open', 'high', 'low', 'close', 'volume']
            missing_columns = [col for col in required_columns if col not in chart_df.columns]
            
            if missing_columns:
                self.logger.error(f"필수 컬럼 누락: {missing_columns}")
                return None
            
            # 숫자 데이터 타입 확인
            for col in required_columns:
                chart_df[col] = pd.to_numeric(chart_df[col], errors='coerce')
            
            # 유효하지 않은 데이터 제거
            chart_df = chart_df.dropna(subset=required_columns)
            
            if chart_df.empty:
                self.logger.warning(f"{stock_code} {target_date} 유효한 분봉 데이터 없음")
                return None
            
            self.logger.info(f"{stock_code} {target_date} 분봉 데이터 조회 성공: {len(chart_df)}건")
            return chart_df
            
        except Exception as e:
            self.logger.error(f"{stock_code} {target_date} 분봉 데이터 조회 오류: {e}")
            return None
    
    def create_post_market_candlestick_chart(self, stock_code: str, stock_name: str, 
                                           chart_df: pd.DataFrame, target_date: str,
                                           selection_reason: str = "") -> Optional[str]:
        """
        장 마감 후 캔들스틱 차트 생성
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            chart_df: 차트 데이터
            target_date: 대상 날짜
            selection_reason: 선정 사유
            
        Returns:
            str: 저장된 파일 경로
        """
        try:
            if chart_df.empty:
                self.logger.error("차트 데이터가 비어있음")
                return None
            
            self.logger.info(f"{stock_code} {target_date} 장 마감 후 캔들스틱 차트 생성 시작")
            
            # 그래프 설정
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12), 
                                         gridspec_kw={'height_ratios': [3, 1]})
            
            # 데이터 준비
            data = chart_df.copy()
            data['x_pos'] = range(len(data))
            
            # 캔들스틱 차트 그리기
            for idx, row in data.iterrows():
                x = row['x_pos']
                open_price = row['open']
                high_price = row['high']
                low_price = row['low']
                close_price = row['close']
                volume = row['volume']
                
                # 캔들 색상 결정 (상승: 빨강, 하락: 파랑)
                color = 'red' if close_price >= open_price else 'blue'
                
                # High-Low 선 그리기
                ax1.plot([x, x], [low_price, high_price], color='black', linewidth=1)
                
                # 캔들 몸통 그리기
                candle_height = abs(close_price - open_price)
                candle_bottom = min(open_price, close_price)
                
                if candle_height > 0:
                    # 실체가 있는 캔들
                    candle = Rectangle((x - 0.3, candle_bottom), 0.6, candle_height,
                                     facecolor=color, edgecolor='black', alpha=0.8)
                    ax1.add_patch(candle)
                else:
                    # 도지 캔들
                    ax1.plot([x - 0.3, x + 0.3], [close_price, close_price], 
                           color='black', linewidth=2)
                
                # 거래량 바 차트
                ax2.bar(x, volume, color=color, alpha=0.6, width=0.6)
            
            # 차트 제목 및 레이블 설정
            chart_title = f"{stock_code} {stock_name} - {target_date} 장 마감 후 분봉 차트"
            if selection_reason:
                chart_title += f"\n{selection_reason}"
            
            ax1.set_title(chart_title, fontsize=16, fontweight='bold', pad=20)
            ax1.set_ylabel('가격 (원)', fontsize=12)
            ax1.grid(True, alpha=0.3)
            
            ax2.set_ylabel('거래량', fontsize=12)
            ax2.set_xlabel('시간 (분)', fontsize=12)
            ax2.grid(True, alpha=0.3)
            
            # X축 시간 레이블 설정
            if len(data) > 0:
                time_labels = []
                x_positions = []
                
                # 장 시작부터 마감까지의 주요 시간대 표시
                interval = max(1, len(data) // 12)  # 약 12개 레이블
                for i in range(0, len(data), interval):
                    x_positions.append(i)
                    if 'time' in data.columns:
                        time_str = str(data.iloc[i]['time']).zfill(6)
                        time_label = f"{time_str[:2]}:{time_str[2:4]}"
                    else:
                        # 장 시작 시간을 09:00으로 가정하고 계산
                        minutes_from_start = i
                        start_hour = 9
                        start_minute = 0
                        total_minutes = start_hour * 60 + start_minute + minutes_from_start
                        hour = total_minutes // 60
                        minute = total_minutes % 60
                        time_label = f"{hour:02d}:{minute:02d}"
                    time_labels.append(time_label)
                
                ax1.set_xticks(x_positions)
                ax1.set_xticklabels(time_labels, rotation=45)
                ax2.set_xticks(x_positions)
                ax2.set_xticklabels(time_labels, rotation=45)
            
            # 가격 및 거래량 통계 정보 추가
            if len(data) > 0:
                start_price = data.iloc[0]['open']
                end_price = data.iloc[-1]['close']
                high_price = data['high'].max()
                low_price = data['low'].min()
                total_volume = data['volume'].sum()
                price_change = end_price - start_price
                price_change_rate = (price_change / start_price * 100) if start_price > 0 else 0
                
                stats_text = (f"시가: {start_price:,.0f}원\n"
                            f"종가: {end_price:,.0f}원\n"
                            f"고가: {high_price:,.0f}원\n"
                            f"저가: {low_price:,.0f}원\n"
                            f"변화: {price_change:+,.0f}원 ({price_change_rate:+.2f}%)\n"
                            f"거래량: {total_volume:,.0f}주\n"
                            f"분봉수: {len(data)}개")
                
                ax1.text(0.02, 0.98, stats_text, transform=ax1.transAxes, 
                        verticalalignment='top', bbox=dict(boxstyle='round', 
                        facecolor='lightblue', alpha=0.8), fontsize=10)
            
            plt.tight_layout()
            
            # 파일 저장
            timestamp = now_kst().strftime("%Y%m%d_%H%M%S")
            filename = f"post_market_chart_{stock_code}_{target_date}_{timestamp}.png"
            filepath = Path(filename)
            
            plt.savefig(filepath, dpi=150, bbox_inches='tight')
            self.logger.info(f"장 마감 후 차트 저장 완료: {filepath}")
            
            plt.close()  # 메모리 절약을 위해 차트 닫기
            return str(filepath)
                
        except Exception as e:
            self.logger.error(f"장 마감 후 캔들스틱 차트 생성 오류: {e}")
            return None
    
    def generate_charts_for_selected_stocks(self, target_date: str = "20250801") -> Dict[str, Any]:
        """
        선정된 종목들의 차트 일괄 생성
        
        Args:
            target_date: 대상 날짜 (YYYYMMDD)
            
        Returns:
            Dict: 생성 결과
        """
        try:
            self.logger.info(f"{target_date} 선정 종목 차트 일괄 생성 시작")
            
            # 조건검색 종목 조회
            selected_stocks = self.get_condition_search_stocks()
            
            if not selected_stocks:
                self.logger.warning("선정된 종목이 없습니다")
                return {'success': False, 'message': '선정된 종목이 없습니다'}
            
            results = {
                'target_date': target_date,
                'total_stocks': len(selected_stocks),
                'success_count': 0,
                'failed_count': 0,
                'chart_files': [],
                'stock_results': []
            }
            
            # 각 종목별 차트 생성
            for stock_data in selected_stocks:
                stock_code = stock_data.get('code', '')
                stock_name = stock_data.get('name', '')
                change_rate = stock_data.get('chgrate', '')
                
                if not stock_code:
                    continue
                
                try:
                    self.logger.info(f"{stock_code}({stock_name}) 차트 생성 중...")
                    
                    # 분봉 데이터 조회
                    chart_df = self.get_historical_chart_data(stock_code, target_date)
                    
                    if chart_df is None or chart_df.empty:
                        self.logger.warning(f"{stock_code} 데이터 없음")
                        results['stock_results'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': False,
                            'error': '데이터 없음'
                        })
                        results['failed_count'] += 1
                        continue
                    
                    # 차트 생성
                    selection_reason = f"조건검색 급등주 (등락률: {change_rate}%)"
                    chart_file = self.create_post_market_candlestick_chart(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        chart_df=chart_df,
                        target_date=target_date,
                        selection_reason=selection_reason
                    )
                    
                    if chart_file:
                        results['chart_files'].append(chart_file)
                        results['stock_results'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': True,
                            'chart_file': chart_file,
                            'data_count': len(chart_df),
                            'change_rate': change_rate
                        })
                        results['success_count'] += 1
                        self.logger.info(f"{stock_code} 차트 생성 성공")
                    else:
                        results['stock_results'].append({
                            'stock_code': stock_code,
                            'stock_name': stock_name,
                            'success': False,
                            'error': '차트 생성 실패'
                        })
                        results['failed_count'] += 1
                        self.logger.error(f"{stock_code} 차트 생성 실패")
                
                except Exception as e:
                    self.logger.error(f"{stock_code} 처리 중 오류: {e}")
                    results['stock_results'].append({
                        'stock_code': stock_code,
                        'stock_name': stock_name,
                        'success': False,
                        'error': str(e)
                    })
                    results['failed_count'] += 1
            
            # 결과 요약
            success_rate = f"{results['success_count']}/{results['total_stocks']}"
            results['summary'] = f"차트 생성 완료: {success_rate} ({results['success_count']/results['total_stocks']*100:.1f}%)"
            
            self.logger.info(f"차트 일괄 생성 완료: {results['summary']}")
            return results
            
        except Exception as e:
            self.logger.error(f"차트 일괄 생성 오류: {e}")
            return {'success': False, 'error': str(e)}


def main():
    """메인 실행 함수"""
    try:
        print("장 마감 후 차트 생성기 테스트 시작")
        
        # 차트 생성기 객체 생성 및 초기화
        generator = PostMarketChartGenerator()
        
        if not generator.initialize():
            print("시스템 초기화 실패")
            return
        
        # 2025년 8월 1일 데이터로 차트 생성
        target_date = "20250801"
        print(f"{target_date} 선정 종목 차트 생성 중...")
        
        results = generator.generate_charts_for_selected_stocks(target_date)
        
        if results.get('success', True):  # success 키가 없으면 성공으로 간주
            print("차트 생성 완료!")
            print(f"결과: {results.get('summary', 'N/A')}")
            
            if results.get('chart_files'):
                print("생성된 차트 파일:")
                for file in results['chart_files']:
                    print(f"  - {file}")
                    
            # 성공한 종목들 요약
            success_stocks = [
                stock for stock in results.get('stock_results', []) 
                if stock.get('success', False)
            ]
            
            if success_stocks:
                print("\n성공한 종목들:")
                for stock in success_stocks:
                    print(f"  - {stock['stock_code']}({stock['stock_name']}): "
                          f"{stock['data_count']}분봉, 등락률 {stock['change_rate']}%")
        else:
            print(f"차트 생성 실패: {results.get('error', 'Unknown error')}")
        
    except Exception as e:
        print(f"메인 실행 오류: {e}")


if __name__ == "__main__":
    main()