"""
전략 테스트용 차트 생성 스크립트
103840(우양) 종목의 2025-08-01 분봉 데이터로 전략1, 전략2 테스트
"""
import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timedelta
from pathlib import Path
import sys

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

# 프로젝트 모듈 임포트
from api.kis_chart_api import get_full_trading_day_data_async
from core.indicators.price_box import PriceBox
from core.indicators.bollinger_bands import BollingerBands
from core.indicators.bisector_line import BisectorLine
from utils.logger import setup_logger

# 한글 폰트 설정
import matplotlib.font_manager as fm
import platform

def setup_korean_font():
    """한글 폰트 설정"""
    if platform.system() == 'Windows':
        font_list = ['Malgun Gothic', 'Microsoft YaHei', 'SimHei', 'Gulim', 'Batang', 'Dotum']
    else:
        font_list = ['AppleGothic', 'Noto Sans CJK KR', 'DejaVu Sans']
    
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    for font_name in font_list:
        if font_name in available_fonts:
            plt.rcParams['font.family'] = font_name
            print(f"한글 폰트 설정: {font_name}")
            break
    else:
        if platform.system() == 'Windows':
            plt.rcParams['font.family'] = 'Malgun Gothic'
        else:
            plt.rcParams['font.family'] = 'DejaVu Sans'
        print(f"기본 폰트 사용: {plt.rcParams['font.family']}")

# 폰트 설정
setup_korean_font()
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 10
plt.rcParams['figure.dpi'] = 100


class StrategyTester:
    """전략 테스트 클래스"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        
        # 차트 저장 디렉토리
        self.chart_dir = Path(__file__).parent / "test_charts"
        self.chart_dir.mkdir(exist_ok=True)
        
        self.logger.info("전략 테스터 초기화 완료")
    
    async def collect_test_data(self, stock_code: str, target_date: str) -> pd.DataFrame:
        """
        테스트용 분봉 데이터 수집
        
        Args:
            stock_code: 종목코드 (예: "103840")
            target_date: 날짜 (예: "20250801")
            
        Returns:
            pd.DataFrame: 분봉 데이터
        """
        try:
            self.logger.info(f"{stock_code} {target_date} 분봉 데이터 수집 시작")
            
            # 15:30까지의 데이터 수집
            data = await get_full_trading_day_data_async(
                stock_code=stock_code,
                target_date=target_date,
                selected_time="153000"  # 15:30까지
            )
            
            if data is None or data.empty:
                self.logger.error(f"{stock_code} 데이터 수집 실패")
                return pd.DataFrame()
            
            # 09:00~15:30 범위 필터링
            if 'time' in data.columns:
                data['time_str'] = data['time'].astype(str).str.zfill(6)
                filtered_data = data[
                    (data['time_str'] >= "090000") & 
                    (data['time_str'] <= "153000")
                ].copy()
            else:
                filtered_data = data.copy()
            
            self.logger.info(f"데이터 수집 완료: {len(filtered_data)}건")
            
            # 데이터 구조 확인
            self.logger.info(f"데이터 컬럼: {list(filtered_data.columns)}")
            if not filtered_data.empty:
                self.logger.info(f"첫 번째 데이터: {filtered_data.iloc[0].to_dict()}")
            
            return filtered_data
            
        except Exception as e:
            self.logger.error(f"데이터 수집 오류: {e}")
            return pd.DataFrame()
    
    def create_strategy1_chart(self, data: pd.DataFrame, stock_code: str, target_date: str) -> str:
        """
        전략1 차트 생성: 가격박스 + 이등분선
        
        Args:
            data: 분봉 데이터
            stock_code: 종목코드
            target_date: 날짜
            
        Returns:
            str: 차트 파일 경로
        """
        try:
            if data.empty:
                self.logger.error("데이터가 없어 차트를 생성할 수 없습니다")
                return None
            
            self.logger.info("전략1 차트 생성 시작 (가격박스 + 이등분선)")
            
            # 데이터 준비
            prices = data['close']
            
            # 이등분선 계산
            bisector_signals = BisectorLine.generate_trading_signals(data)
            
            # 가격박스 계산
            box_signals = PriceBox.generate_trading_signals(prices)
            
            # 차트 생성
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12))
            fig.suptitle(f'전략1: 가격박스 + 이등분선 - {stock_code} ({target_date})', 
                        fontsize=16, fontweight='bold')
            
            # 상단: 캔들스틱 + 가격박스 + 이등분선
            ax1.plot(range(len(data)), data['close'], 'b-', linewidth=1, label='종가', alpha=0.8)
            
            # 이등분선 표시
            if 'bisector_line' in bisector_signals.columns:
                ax1.plot(range(len(data)), bisector_signals['bisector_line'], 
                        'r--', linewidth=2, label='이등분선', alpha=0.8)
            
            # 이등분선 상하 영역 표시
            if 'bullish_zone' in bisector_signals.columns:
                bullish_mask = bisector_signals['bullish_zone']
                ax1.fill_between(range(len(data)), data['close'].min(), data['close'].max(),
                               where=bullish_mask, alpha=0.1, color='green', label='상승구간')
            
            # 가격박스 표시
            if 'upper_line' in box_signals.columns:
                ax1.plot(range(len(data)), box_signals['upper_line'], 
                        'g-', linewidth=1, label='박스상한선', alpha=0.7)
            if 'lower_line' in box_signals.columns:
                ax1.plot(range(len(data)), box_signals['lower_line'], 
                        'orange', linewidth=1, label='박스하한선', alpha=0.7)
            if 'center_line' in box_signals.columns:
                ax1.plot(range(len(data)), box_signals['center_line'], 
                        'purple', linewidth=1, label='박스중심선', alpha=0.7)
            
            # 매수 신호 표시
            if 'first_lower_touch' in box_signals.columns:
                buy_signals = box_signals['first_lower_touch']
                buy_indices = buy_signals[buy_signals].index
                if len(buy_indices) > 0:
                    ax1.scatter(buy_indices, data['close'].iloc[buy_indices], 
                              color='red', marker='^', s=100, label='매수신호', zorder=5)
            
            ax1.set_title('가격 차트 및 신호', fontsize=14)
            ax1.set_ylabel('가격', fontsize=12)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            
            # 하단: 신호 상태
            ax2.plot(range(len(data)), bisector_signals.get('bullish_zone', [False]*len(data)), 
                    'g-', linewidth=2, label='이등분선 위')
            ax2.plot(range(len(data)), box_signals.get('first_lower_touch', [False]*len(data)), 
                    'r-', linewidth=2, label='첫 박스하한선 터치')
            
            ax2.set_title('신호 상태', fontsize=14)
            ax2.set_xlabel('시간 (분봉)', fontsize=12)
            ax2.set_ylabel('신호', fontsize=12)
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # 저장
            filename = f"strategy1_{stock_code}_{target_date}.png"
            filepath = self.chart_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            self.logger.info(f"전략1 차트 저장: {filepath}")
            
            plt.close()
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"전략1 차트 생성 오류: {e}")
            return None
    
    def create_strategy2_chart(self, data: pd.DataFrame, stock_code: str, target_date: str) -> str:
        """
        전략2 차트 생성: 볼린저밴드 + 이등분선
        
        Args:
            data: 분봉 데이터
            stock_code: 종목코드
            target_date: 날짜
            
        Returns:
            str: 차트 파일 경로
        """
        try:
            if data.empty:
                self.logger.error("데이터가 없어 차트를 생성할 수 없습니다")
                return None
            
            self.logger.info("전략2 차트 생성 시작 (볼린저밴드 + 이등분선)")
            
            # 데이터 준비
            prices = data['close']
            
            # 이등분선 계산
            bisector_signals = BisectorLine.generate_trading_signals(data)
            
            # 볼린저밴드 계산
            bb_signals = BollingerBands.generate_trading_signals(prices)
            
            # 차트 생성
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(16, 12))
            fig.suptitle(f'전략2: 볼린저밴드 + 이등분선 - {stock_code} ({target_date})', 
                        fontsize=16, fontweight='bold')
            
            # 상단: 캔들스틱 + 볼린저밴드 + 이등분선
            ax1.plot(range(len(data)), data['close'], 'b-', linewidth=1, label='종가', alpha=0.8)
            
            # 이등분선 표시
            if 'bisector_line' in bisector_signals.columns:
                ax1.plot(range(len(data)), bisector_signals['bisector_line'], 
                        'r--', linewidth=2, label='이등분선', alpha=0.8)
            
            # 이등분선 상하 영역 표시
            if 'bullish_zone' in bisector_signals.columns:
                bullish_mask = bisector_signals['bullish_zone']
                ax1.fill_between(range(len(data)), data['close'].min(), data['close'].max(),
                               where=bullish_mask, alpha=0.1, color='green', label='상승구간')
            
            # 볼린저밴드 표시
            if 'upper_band' in bb_signals.columns:
                ax1.plot(range(len(data)), bb_signals['upper_band'], 
                        'g-', linewidth=1, label='상한선', alpha=0.7)
            if 'lower_band' in bb_signals.columns:
                ax1.plot(range(len(data)), bb_signals['lower_band'], 
                        'orange', linewidth=1, label='하한선', alpha=0.7)
            if 'sma' in bb_signals.columns:
                ax1.plot(range(len(data)), bb_signals['sma'], 
                        'purple', linewidth=1, label='중심선(SMA)', alpha=0.7)
            
            # 볼린저밴드 영역 표시
            if 'upper_band' in bb_signals.columns and 'lower_band' in bb_signals.columns:
                ax1.fill_between(range(len(data)), bb_signals['upper_band'], bb_signals['lower_band'],
                               alpha=0.1, color='blue', label='볼린저밴드')
            
            # 매수 신호 표시
            if 'upper_breakout' in bb_signals.columns:
                buy_signals = bb_signals['upper_breakout']
                buy_indices = buy_signals[buy_signals].index
                if len(buy_indices) > 0:
                    ax1.scatter(buy_indices, data['close'].iloc[buy_indices], 
                              color='red', marker='^', s=100, label='상한선돌파', zorder=5)
            
            if 'lower_touch' in bb_signals.columns:
                support_signals = bb_signals['lower_touch']
                support_indices = support_signals[support_signals].index
                if len(support_indices) > 0:
                    ax1.scatter(support_indices, data['close'].iloc[support_indices], 
                              color='blue', marker='v', s=100, label='하한선터치', zorder=5)
            
            ax1.set_title('가격 차트 및 신호', fontsize=14)
            ax1.set_ylabel('가격', fontsize=12)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            
            # 하단: 밴드폭과 신호 상태
            if 'band_width' in bb_signals.columns:
                ax2_twin = ax2.twinx()
                ax2_twin.plot(range(len(data)), bb_signals['band_width'], 
                            'cyan', linewidth=1, label='밴드폭', alpha=0.7)
                ax2_twin.set_ylabel('밴드폭', fontsize=12, color='cyan')
                ax2_twin.legend(loc='upper right', fontsize=10)
            
            ax2.plot(range(len(data)), bisector_signals.get('bullish_zone', [False]*len(data)), 
                    'g-', linewidth=2, label='이등분선 위')
            ax2.plot(range(len(data)), bb_signals.get('upper_breakout', [False]*len(data)), 
                    'r-', linewidth=2, label='상한선 돌파')
            ax2.plot(range(len(data)), bb_signals.get('lower_touch', [False]*len(data)), 
                    'b-', linewidth=2, label='하한선 터치')
            
            ax2.set_title('신호 상태', fontsize=14)
            ax2.set_xlabel('시간 (분봉)', fontsize=12)
            ax2.set_ylabel('신호', fontsize=12)
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # 저장
            filename = f"strategy2_{stock_code}_{target_date}.png"
            filepath = self.chart_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            self.logger.info(f"전략2 차트 저장: {filepath}")
            
            plt.close()
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"전략2 차트 생성 오류: {e}")
            return None
    
    async def run_test(self, stock_code: str = "103840", target_date: str = "20250801"):
        """
        전체 테스트 실행
        
        Args:
            stock_code: 종목코드 (기본: 103840-우양)
            target_date: 날짜 (기본: 20250801)
        """
        try:
            self.logger.info(f"전략 테스트 시작: {stock_code} ({target_date})")
            
            # 1. 데이터 수집
            data = await self.collect_test_data(stock_code, target_date)
            
            if data.empty:
                self.logger.error("데이터가 없어 테스트를 중단합니다")
                return
            
            # 2. 전략1 차트 생성
            chart1_path = self.create_strategy1_chart(data, stock_code, target_date)
            if chart1_path:
                self.logger.info(f"전략1 차트 완료: {chart1_path}")
            
            # 3. 전략2 차트 생성
            chart2_path = self.create_strategy2_chart(data, stock_code, target_date)
            if chart2_path:
                self.logger.info(f"전략2 차트 완료: {chart2_path}")
            
            # 4. 결과 요약
            self.logger.info("테스트 완료 요약:")
            self.logger.info(f"   종목: {stock_code}")
            self.logger.info(f"   날짜: {target_date}")
            self.logger.info(f"   데이터 수: {len(data)}개 분봉")
            if 'time' in data.columns:
                start_time = data['time'].iloc[0] if len(data) > 0 else 'N/A'
                end_time = data['time'].iloc[-1] if len(data) > 0 else 'N/A'
                self.logger.info(f"   시간 범위: {start_time} ~ {end_time}")
            self.logger.info(f"   저장 위치: {self.chart_dir}")
            
        except Exception as e:
            self.logger.error(f"테스트 실행 오류: {e}")


async def main():
    """메인 함수"""
    try:
        # 테스터 생성
        tester = StrategyTester()
        
        # 테스트 실행
        await tester.run_test(stock_code="103840", target_date="20250801")
        
    except Exception as e:
        print(f"테스트 오류: {e}")


if __name__ == "__main__":
    asyncio.run(main())