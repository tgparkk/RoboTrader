"""
실제 데이터를 사용한 전략 테스트 차트 생성 스크립트
103840(우양) 종목의 2025-08-01 분봉 데이터로 전략1, 전략2 테스트
"""
import asyncio
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import sys

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

# 프로젝트 모듈 임포트
from api.kis_api_manager import KISAPIManager
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


class RealDataStrategyTester:
    """실제 데이터를 사용한 전략 테스트 클래스"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        
        # API 매니저 초기화
        self.api_manager = KISAPIManager()
        
        # 차트 저장 디렉토리
        self.chart_dir = Path(__file__).parent / "test_charts"
        self.chart_dir.mkdir(exist_ok=True)
        
        self.logger.info("실제 데이터 전략 테스터 초기화 완료")
    
    async def initialize_api(self) -> bool:
        """API 초기화"""
        try:
            self.logger.info("API 초기화 시작...")
            
            if not self.api_manager.initialize():
                self.logger.error("API 초기화 실패")
                return False
            
            self.logger.info("API 초기화 성공")
            return True
            
        except Exception as e:
            self.logger.error(f"API 초기화 오류: {e}")
            return False
    
    async def collect_real_data(self, stock_code: str, target_date: str) -> pd.DataFrame:
        """
        실제 분봉 데이터 수집
        
        Args:
            stock_code: 종목코드 (예: "103840")
            target_date: 날짜 (예: "20250801")
            
        Returns:
            pd.DataFrame: 분봉 데이터
        """
        try:
            self.logger.info(f"{stock_code} {target_date} 실제 분봉 데이터 수집 시작")
            
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
                first_data = filtered_data.iloc[0]
                last_data = filtered_data.iloc[-1]
                self.logger.info(f"첫 번째: {first_data['time']} {first_data['close']:.0f}원")
                self.logger.info(f"마지막: {last_data['time']} {last_data['close']:.0f}원")
                
                # 가격 범위 정보
                price_change = ((last_data['close'] - first_data['close']) / first_data['close']) * 100
                self.logger.info(f"하루 변동률: {price_change:+.2f}%")
            
            return filtered_data
            
        except Exception as e:
            self.logger.error(f"데이터 수집 오류: {e}")
            return pd.DataFrame()
    
    def create_strategy1_chart(self, data: pd.DataFrame, stock_code: str, target_date: str) -> str:
        """
        전략1 차트 생성: 가격박스 + 이등분선
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
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 14))
            fig.suptitle(f'전략1: 가격박스 + 이등분선 - {stock_code}(우양) {target_date}', 
                        fontsize=16, fontweight='bold')
            
            # 상단: 캔들스틱 + 가격박스 + 이등분선
            x_axis = range(len(data))
            
            # 캔들스틱 그리기
            for i in x_axis:
                color = 'red' if data['close'].iloc[i] >= data['open'].iloc[i] else 'blue'
                ax1.plot([i, i], [data['low'].iloc[i], data['high'].iloc[i]], color='black', linewidth=0.5)
                ax1.plot([i, i], [data['open'].iloc[i], data['close'].iloc[i]], color=color, linewidth=2)
            
            # 이등분선 표시
            if 'bisector_line' in bisector_signals.columns:
                ax1.plot(x_axis, bisector_signals['bisector_line'], 
                        'purple', linewidth=2, label='이등분선', alpha=0.8)
            
            # 이등분선 상하 영역 표시
            if 'bullish_zone' in bisector_signals.columns:
                bullish_mask = bisector_signals['bullish_zone']
                for i in range(len(data)):
                    if bullish_mask.iloc[i]:
                        ax1.axvspan(i-0.5, i+0.5, alpha=0.1, color='green')
            
            # 가격박스 표시
            if 'upper_line' in box_signals.columns:
                ax1.plot(x_axis, box_signals['upper_line'], 
                        'orange', linewidth=1.5, label='박스상한선', alpha=0.8)
            if 'lower_line' in box_signals.columns:
                ax1.plot(x_axis, box_signals['lower_line'], 
                        'brown', linewidth=1.5, label='박스하한선', alpha=0.8)
            if 'center_line' in box_signals.columns:
                ax1.plot(x_axis, box_signals['center_line'], 
                        'navy', linewidth=1.5, label='박스중심선', alpha=0.8)
            
            # 매수 신호 표시
            buy_signals = []
            if 'first_lower_touch' in box_signals.columns:
                buy_signals.extend(box_signals[box_signals['first_lower_touch']].index.tolist())
            if 'support_bounce' in box_signals.columns and 'center_breakout_up' in box_signals.columns:
                recent_support = box_signals[box_signals['support_bounce']].tail(10).index.tolist()
                recent_breakout = box_signals[box_signals['center_breakout_up']].tail(10).index.tolist()
                buy_signals.extend(recent_breakout)
            
            if buy_signals:
                ax1.scatter(buy_signals, data['close'].iloc[buy_signals], 
                          color='red', marker='^', s=100, label='매수신호', zorder=5)
            
            ax1.set_title('캔들스틱 차트 및 가격박스', fontsize=14)
            ax1.set_ylabel('가격 (원)', fontsize=12)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            
            # 중간: 이등분선 상태와 가격박스 신호
            if 'bullish_zone' in bisector_signals.columns:
                ax2.fill_between(x_axis, 0, bisector_signals['bullish_zone'].astype(int), 
                               alpha=0.3, color='green', label='이등분선 위 구간')
            
            if 'first_lower_touch' in box_signals.columns:
                touch_signals = box_signals['first_lower_touch'].astype(int)
                touch_indices = [i for i in x_axis if touch_signals.iloc[i] == 1]
                if touch_indices:
                    ax2.scatter(touch_indices, [1]*len(touch_indices), 
                              color='red', marker='^', s=50, label='첫 박스하한선 터치')
            
            if 'center_breakout_up' in box_signals.columns:
                breakout_signals = box_signals['center_breakout_up'].astype(int)
                breakout_indices = [i for i in x_axis if breakout_signals.iloc[i] == 1]
                if breakout_indices:
                    ax2.scatter(breakout_indices, [0.5]*len(breakout_indices), 
                              color='blue', marker='o', s=50, label='박스중심선 돌파')
            
            ax2.set_title('신호 상태', fontsize=14)
            ax2.set_ylabel('신호', fontsize=12)
            ax2.set_ylim(-0.2, 1.2)
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.3)
            
            # 하단: 거래량
            ax3.bar(x_axis, data['volume'], alpha=0.5, color='gray', label='거래량')
            ax3.set_title('거래량', fontsize=14)
            ax3.set_xlabel('시간 (분봉)', fontsize=12)
            ax3.set_ylabel('거래량', fontsize=12)
            ax3.legend(loc='upper left', fontsize=10)
            ax3.grid(True, alpha=0.3)
            
            # x축 라벨 설정 (시간 표시)
            time_ticks = range(0, len(data), 60)  # 1시간마다
            time_labels = []
            for i in time_ticks:
                if i < len(data):
                    time_val = data['time'].iloc[i]
                    if isinstance(time_val, str):
                        time_val = int(time_val)
                    hour = time_val // 10000
                    minute = (time_val // 100) % 100
                    time_labels.append(f"{hour:02d}:{minute:02d}")
                else:
                    break
            
            for ax in [ax1, ax2, ax3]:
                ax.set_xticks(time_ticks)
                ax.set_xticklabels(time_labels, rotation=45)
            
            plt.tight_layout()
            
            # 저장
            filename = f"strategy1_{stock_code}_{target_date}_real.png"
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
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 14))
            fig.suptitle(f'전략2: 볼린저밴드 + 이등분선 - {stock_code}(우양) {target_date}', 
                        fontsize=16, fontweight='bold')
            
            # 상단: 캔들스틱 + 볼린저밴드 + 이등분선
            x_axis = range(len(data))
            
            # 캔들스틱 그리기
            for i in x_axis:
                color = 'red' if data['close'].iloc[i] >= data['open'].iloc[i] else 'blue'
                ax1.plot([i, i], [data['low'].iloc[i], data['high'].iloc[i]], color='black', linewidth=0.5)
                ax1.plot([i, i], [data['open'].iloc[i], data['close'].iloc[i]], color=color, linewidth=2)
            
            # 이등분선 표시
            if 'bisector_line' in bisector_signals.columns:
                ax1.plot(x_axis, bisector_signals['bisector_line'], 
                        'purple', linewidth=2, label='이등분선', alpha=0.8)
            
            # 이등분선 상하 영역 표시
            if 'bullish_zone' in bisector_signals.columns:
                bullish_mask = bisector_signals['bullish_zone']
                for i in range(len(data)):
                    if bullish_mask.iloc[i]:
                        ax1.axvspan(i-0.5, i+0.5, alpha=0.1, color='green')
            
            # 볼린저밴드 표시
            if 'upper_band' in bb_signals.columns:
                ax1.plot(x_axis, bb_signals['upper_band'], 
                        'orange', linewidth=1.5, label='상한선', alpha=0.8)
            if 'lower_band' in bb_signals.columns:
                ax1.plot(x_axis, bb_signals['lower_band'], 
                        'brown', linewidth=1.5, label='하한선', alpha=0.8)
            if 'sma' in bb_signals.columns:
                ax1.plot(x_axis, bb_signals['sma'], 
                        'navy', linewidth=1.5, label='중심선(SMA)', alpha=0.8)
            
            # 볼린저밴드 영역 표시
            if 'upper_band' in bb_signals.columns and 'lower_band' in bb_signals.columns:
                ax1.fill_between(x_axis, bb_signals['upper_band'], bb_signals['lower_band'],
                               alpha=0.1, color='blue', label='볼린저밴드')
            
            # 매수 신호 표시
            buy_signals = []
            if 'upper_breakout' in bb_signals.columns:
                buy_signals.extend(bb_signals[bb_signals['upper_breakout']].index.tolist())
            if 'lower_touch' in bb_signals.columns:
                buy_signals.extend(bb_signals[bb_signals['lower_touch']].index.tolist())
            
            if buy_signals:
                ax1.scatter(buy_signals, data['close'].iloc[buy_signals], 
                          color='red', marker='^', s=100, label='매수신호', zorder=5)
            
            ax1.set_title('캔들스틱 차트 및 볼린저밴드', fontsize=14)
            ax1.set_ylabel('가격 (원)', fontsize=12)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            
            # 중간: 밴드폭과 신호 상태
            if 'band_width' in bb_signals.columns:
                ax2_twin = ax2.twinx()
                ax2_twin.plot(x_axis, bb_signals['band_width'], 
                            'cyan', linewidth=1, label='밴드폭', alpha=0.7)
                ax2_twin.set_ylabel('밴드폭 (%)', fontsize=12, color='cyan')
                ax2_twin.legend(loc='upper right', fontsize=10)
            
            if 'bullish_zone' in bisector_signals.columns:
                ax2.fill_between(x_axis, 0, bisector_signals['bullish_zone'].astype(int), 
                               alpha=0.3, color='green', label='이등분선 위 구간')
            
            if 'upper_breakout' in bb_signals.columns:
                breakout_signals = bb_signals['upper_breakout'].astype(int)
                breakout_indices = [i for i in x_axis if breakout_signals.iloc[i] == 1]
                if breakout_indices:
                    ax2.scatter(breakout_indices, [1]*len(breakout_indices), 
                              color='red', marker='^', s=50, label='상한선 돌파')
            
            if 'lower_touch' in bb_signals.columns:
                touch_signals = bb_signals['lower_touch'].astype(int)
                touch_indices = [i for i in x_axis if touch_signals.iloc[i] == 1]
                if touch_indices:
                    ax2.scatter(touch_indices, [0.5]*len(touch_indices), 
                              color='blue', marker='v', s=50, label='하한선 터치')
            
            ax2.set_title('신호 상태', fontsize=14)
            ax2.set_ylabel('신호', fontsize=12)
            ax2.set_ylim(-0.2, 1.2)
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.3)
            
            # 하단: 거래량
            ax3.bar(x_axis, data['volume'], alpha=0.5, color='gray', label='거래량')
            ax3.set_title('거래량', fontsize=14)
            ax3.set_xlabel('시간 (분봉)', fontsize=12)
            ax3.set_ylabel('거래량', fontsize=12)
            ax3.legend(loc='upper left', fontsize=10)
            ax3.grid(True, alpha=0.3)
            
            # x축 라벨 설정 (시간 표시)
            time_ticks = range(0, len(data), 60)  # 1시간마다
            time_labels = []
            for i in time_ticks:
                if i < len(data):
                    time_val = data['time'].iloc[i]
                    if isinstance(time_val, str):
                        time_val = int(time_val)
                    hour = time_val // 10000
                    minute = (time_val // 100) % 100
                    time_labels.append(f"{hour:02d}:{minute:02d}")
                else:
                    break
            
            for ax in [ax1, ax2, ax3]:
                ax.set_xticks(time_ticks)
                ax.set_xticklabels(time_labels, rotation=45)
            
            plt.tight_layout()
            
            # 저장
            filename = f"strategy2_{stock_code}_{target_date}_real.png"
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
        """
        try:
            self.logger.info(f"실제 데이터 전략 테스트 시작: {stock_code} ({target_date})")
            
            # 1. API 초기화
            if not await self.initialize_api():
                self.logger.error("API 초기화 실패로 테스트 중단")
                return
            
            # 2. 실제 데이터 수집
            data = await self.collect_real_data(stock_code, target_date)
            
            if data.empty:
                self.logger.error("데이터가 없어 테스트를 중단합니다")
                return
            
            # 3. 전략1 차트 생성
            chart1_path = self.create_strategy1_chart(data, stock_code, target_date)
            if chart1_path:
                self.logger.info(f"전략1 차트 완료: {chart1_path}")
            
            # 4. 전략2 차트 생성
            chart2_path = self.create_strategy2_chart(data, stock_code, target_date)
            if chart2_path:
                self.logger.info(f"전략2 차트 완료: {chart2_path}")
            
            # 5. 결과 요약
            self.logger.info("실제 데이터 테스트 완료 요약:")
            self.logger.info(f"   종목: {stock_code} (우양)")
            self.logger.info(f"   날짜: {target_date}")
            self.logger.info(f"   데이터 수: {len(data)}개 분봉")
            if not data.empty:
                start_time_val = data['time'].iloc[0]
                end_time_val = data['time'].iloc[-1]
                if isinstance(start_time_val, str):
                    start_time_val = int(start_time_val)
                if isinstance(end_time_val, str):
                    end_time_val = int(end_time_val)
                
                start_time = f"{start_time_val//10000:02d}:{(start_time_val//100)%100:02d}"
                end_time = f"{end_time_val//10000:02d}:{(end_time_val//100)%100:02d}"
                self.logger.info(f"   시간 범위: {start_time} ~ {end_time}")
                
                start_price = data['close'].iloc[0]
                end_price = data['close'].iloc[-1]
                change_rate = ((end_price - start_price) / start_price) * 100
                self.logger.info(f"   가격 범위: {start_price:,.0f}원 → {end_price:,.0f}원 ({change_rate:+.2f}%)")
            self.logger.info(f"   저장 위치: {self.chart_dir}")
            
        except Exception as e:
            self.logger.error(f"테스트 실행 오류: {e}")


async def main():
    """메인 함수"""
    try:
        # 테스터 생성
        tester = RealDataStrategyTester()
        
        # 테스트 실행
        await tester.run_test(stock_code="103840", target_date="20250801")
        
    except Exception as e:
        print(f"테스트 오류: {e}")


if __name__ == "__main__":
    asyncio.run(main())