"""
전략 테스트용 차트 생성 스크립트 (더미 데이터 사용)
103840(우양) 종목 시뮬레이션 데이터로 전략1, 전략2 테스트
"""
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
import sys

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

# 프로젝트 모듈 임포트
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


class StrategyTesterWithDummy:
    """전략 테스트 클래스 (더미 데이터 사용)"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        
        # 차트 저장 디렉토리
        self.chart_dir = Path(__file__).parent / "test_charts"
        self.chart_dir.mkdir(exist_ok=True)
        
        self.logger.info("전략 테스터 초기화 완료 (더미 데이터 모드)")
    
    def generate_dummy_data(self, stock_code: str, target_date: str, num_minutes: int = 390) -> pd.DataFrame:
        """
        더미 분봉 데이터 생성 (실제적인 패턴 포함)
        
        Args:
            stock_code: 종목코드 (예: "103840")
            target_date: 날짜 (예: "20250801")
            num_minutes: 분봉 수 (09:00~15:30 = 390분)
            
        Returns:
            pd.DataFrame: 분봉 데이터
        """
        try:
            self.logger.info(f"{stock_code} {target_date} 더미 분봉 데이터 생성 시작")
            
            # 기본 설정
            base_price = 2000  # 기준가격
            start_time = datetime.strptime(f"{target_date} 090000", "%Y%m%d %H%M%S")
            
            # 시간 배열 생성
            times = []
            datetimes = []
            for i in range(num_minutes):
                current_time = start_time + timedelta(minutes=i)
                times.append(int(current_time.strftime("%H%M%S")))
                datetimes.append(current_time)
            
            # 가격 시뮬레이션 (실제적인 패턴)
            np.random.seed(42)  # 재현 가능한 결과
            
            # 랜덤 워크 + 트렌드 + 변동성
            returns = np.random.normal(0, 0.002, num_minutes)  # 0.2% 표준편차
            
            # 트렌드 추가 (오전에 상승, 오후에 하락)
            for i in range(num_minutes):
                if i < 150:  # 오전 (09:00~11:30)
                    returns[i] += 0.0005  # 상승 편향
                elif i > 300:  # 오후 늦은 시간 (14:30~15:30)
                    returns[i] -= 0.0003  # 하락 편향
            
            # 가격 계산
            prices = [base_price]
            for i in range(1, num_minutes):
                new_price = prices[-1] * (1 + returns[i])
                prices.append(new_price)
            
            # OHLCV 데이터 생성
            data = []
            for i in range(num_minutes):
                base = prices[i]
                
                # 고가, 저가 생성 (현실적인 범위)
                volatility = np.random.uniform(0.005, 0.02)  # 0.5%~2% 변동
                high = base * (1 + volatility * np.random.uniform(0.3, 1.0))
                low = base * (1 - volatility * np.random.uniform(0.3, 1.0))
                
                # 시가, 종가 조정
                if i == 0:
                    open_price = base
                else:
                    open_price = prices[i-1] + np.random.normal(0, base * 0.001)
                
                close_price = prices[i]
                
                # 고가, 저가 재조정 (시가, 종가보다 벗어나지 않도록)
                high = max(high, open_price, close_price)
                low = min(low, open_price, close_price)
                
                # 거래량 생성 (현실적인 패턴)
                base_volume = np.random.randint(50000, 200000)
                if abs(returns[i]) > 0.01:  # 큰 변동시 거래량 증가
                    base_volume *= 2
                
                data.append({
                    'date': target_date,
                    'time': times[i],
                    'datetime': datetimes[i],
                    'open': round(open_price, 0),
                    'high': round(high, 0),
                    'low': round(low, 0),
                    'close': round(close_price, 0),
                    'volume': base_volume
                })
            
            df = pd.DataFrame(data)
            
            self.logger.info(f"더미 데이터 생성 완료: {len(df)}건")
            self.logger.info(f"가격 범위: {df['low'].min():.0f} ~ {df['high'].max():.0f}")
            self.logger.info(f"시작가: {df['open'].iloc[0]:.0f}, 종료가: {df['close'].iloc[-1]:.0f}")
            
            return df
            
        except Exception as e:
            self.logger.error(f"더미 데이터 생성 오류: {e}")
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
                recent_support = box_signals[box_signals['support_bounce']].tail(5).index.tolist()
                recent_breakout = box_signals[box_signals['center_breakout_up']].tail(5).index.tolist()
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
                ax2.scatter(x_axis[touch_signals], touch_signals[touch_signals], 
                          color='red', marker='^', s=50, label='첫 박스하한선 터치')
            
            if 'center_breakout_up' in box_signals.columns:
                breakout_signals = box_signals['center_breakout_up'].astype(int)
                ax2.scatter(x_axis[breakout_signals], breakout_signals[breakout_signals], 
                          color='blue', marker='o', s=50, label='박스중심선 돌파')
            
            ax2.set_title('신호 상태', fontsize=14)
            ax2.set_ylabel('신호', fontsize=12)
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
            time_labels = [f"{data['time'].iloc[i]//10000:02d}:{(data['time'].iloc[i]//100)%100:02d}" 
                          for i in time_ticks if i < len(data)]
            
            for ax in [ax1, ax2, ax3]:
                ax.set_xticks(time_ticks)
                ax.set_xticklabels(time_labels, rotation=45)
            
            plt.tight_layout()
            
            # 저장
            filename = f"strategy1_{stock_code}_{target_date}_dummy.png"
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
                ax2.scatter(x_axis[breakout_signals], breakout_signals[breakout_signals], 
                          color='red', marker='^', s=50, label='상한선 돌파')
            
            if 'lower_touch' in bb_signals.columns:
                touch_signals = bb_signals['lower_touch'].astype(int)
                ax2.scatter(x_axis[touch_signals], touch_signals[touch_signals], 
                          color='blue', marker='v', s=50, label='하한선 터치')
            
            ax2.set_title('신호 상태', fontsize=14)
            ax2.set_ylabel('신호', fontsize=12)
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
            time_labels = [f"{data['time'].iloc[i]//10000:02d}:{(data['time'].iloc[i]//100)%100:02d}" 
                          for i in time_ticks if i < len(data)]
            
            for ax in [ax1, ax2, ax3]:
                ax.set_xticks(time_ticks)
                ax.set_xticklabels(time_labels, rotation=45)
            
            plt.tight_layout()
            
            # 저장
            filename = f"strategy2_{stock_code}_{target_date}_dummy.png"
            filepath = self.chart_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            self.logger.info(f"전략2 차트 저장: {filepath}")
            
            plt.close()
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"전략2 차트 생성 오류: {e}")
            return None
    
    def run_test(self, stock_code: str = "103840", target_date: str = "20250801"):
        """
        전체 테스트 실행
        """
        try:
            self.logger.info(f"전략 테스트 시작: {stock_code} ({target_date})")
            
            # 1. 더미 데이터 생성
            data = self.generate_dummy_data(stock_code, target_date)
            
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
            self.logger.info(f"   종목: {stock_code} (우양)")
            self.logger.info(f"   날짜: {target_date}")
            self.logger.info(f"   데이터 수: {len(data)}개 분봉")
            start_time = f"{data['time'].iloc[0]//10000:02d}:{(data['time'].iloc[0]//100)%100:02d}"
            end_time = f"{data['time'].iloc[-1]//10000:02d}:{(data['time'].iloc[-1]//100)%100:02d}"
            self.logger.info(f"   시간 범위: {start_time} ~ {end_time}")
            self.logger.info(f"   저장 위치: {self.chart_dir}")
            
        except Exception as e:
            self.logger.error(f"테스트 실행 오류: {e}")


def main():
    """메인 함수"""
    try:
        # 테스터 생성
        tester = StrategyTesterWithDummy()
        
        # 테스트 실행
        tester.run_test(stock_code="103840", target_date="20250801")
        
    except Exception as e:
        print(f"테스트 오류: {e}")


if __name__ == "__main__":
    main()