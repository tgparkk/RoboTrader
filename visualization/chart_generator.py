"""
차트 생성 모듈
후보 종목 선정 이력 및 성과 시각화
"""
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import warnings

from db.database_manager import DatabaseManager
from utils.logger import setup_logger
from utils.korean_time import now_kst

# 한글 폰트 설정
import matplotlib.font_manager as fm
import matplotlib
import platform
import os

# matplotlib 백엔드 설정
matplotlib.use('Agg')

# Windows 환경에서 한글 폰트 강제 설정
def setup_korean_font():
    if platform.system() == 'Windows':
        # Windows 한글 폰트 설정
        font_list = ['Malgun Gothic', 'Microsoft YaHei', 'SimHei', 'Gulim', 'Batang', 'Dotum']
    else:
        # macOS/Linux 한글 폰트 설정  
        font_list = ['AppleGothic', 'Noto Sans CJK KR', 'DejaVu Sans']
    
    # 사용 가능한 폰트 확인
    available_fonts = [f.name for f in fm.fontManager.ttflist]
    
    for font_name in font_list:
        if font_name in available_fonts:
            plt.rcParams['font.family'] = font_name
            print(f"한글 폰트 설정: {font_name}")
            break
    else:
        # 폰트를 찾지 못한 경우 강제로 설정
        if platform.system() == 'Windows':
            plt.rcParams['font.family'] = 'Malgun Gothic'
        else:
            plt.rcParams['font.family'] = 'DejaVu Sans'
        print(f"기본 폰트 사용: {plt.rcParams['font.family']}")

# 폰트 설정 실행
setup_korean_font()

# 기본 설정
plt.rcParams['axes.unicode_minus'] = False
plt.rcParams['font.size'] = 12
plt.rcParams['figure.dpi'] = 100

# 폰트 캐시 삭제 (필요시)
try:
    import shutil
    cache_dir = matplotlib.get_cachedir()
    font_cache = os.path.join(cache_dir, 'fontlist-v*.json')
    import glob
    for cache_file in glob.glob(font_cache):
        os.remove(cache_file)
        print(f"폰트 캐시 삭제: {cache_file}")
except:
    pass

warnings.filterwarnings('ignore')


class ChartGenerator:
    """차트 생성기"""
    
    def __init__(self, db_manager: DatabaseManager = None):
        self.logger = setup_logger(__name__)
        self.db_manager = db_manager or DatabaseManager()
        
        # 차트 저장 디렉토리
        self.chart_dir = Path(__file__).parent.parent / "charts"
        self.chart_dir.mkdir(exist_ok=True)
        
        # 스타일 설정
        plt.style.use('default')
        plt.rcParams['axes.grid'] = True
        plt.rcParams['grid.alpha'] = 0.3
    
    def create_candidate_trend_chart(self, days: int = 30, save: bool = True) -> str:
        """후보 종목 선정 추이 차트"""
        try:
            self.logger.info(f"후보 종목 추이 차트 생성 시작 ({days}일)")
            
            # 데이터 조회
            daily_stats = self.db_manager.get_daily_candidate_count(days)
            
            if daily_stats.empty:
                self.logger.warning("표시할 데이터가 없습니다")
                return None
            
            # 차트 생성
            fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 10))
            fig.suptitle(f'후보 종목 선정 추이 ({days}일)', fontsize=16, fontweight='bold')
            
            # 1. 일별 선정 종목 수
            ax1.bar(daily_stats['date'], daily_stats['count'], 
                   alpha=0.7, color='steelblue', edgecolor='navy')
            ax1.set_title('일별 후보 종목 선정 수', fontsize=14)
            ax1.set_ylabel('선정 종목 수', fontsize=12)
            ax1.grid(True, alpha=0.3)
            
            # 평균선 추가
            avg_count = daily_stats['count'].mean()
            ax1.axhline(y=avg_count, color='red', linestyle='--', 
                       label=f'평균: {avg_count:.1f}개')
            ax1.legend()
            
            # 2. 일별 평균 점수
            ax2.plot(daily_stats['date'], daily_stats['avg_score'], 
                    marker='o', linewidth=2, markersize=6, color='green')
            ax2.fill_between(daily_stats['date'], daily_stats['avg_score'], 
                           alpha=0.3, color='green')
            ax2.set_title('일별 평균 선정 점수', fontsize=14)
            ax2.set_ylabel('평균 점수', fontsize=12)
            ax2.set_xlabel('날짜', fontsize=12)
            ax2.grid(True, alpha=0.3)
            
            # 날짜 포맷 설정
            for ax in [ax1, ax2]:
                ax.xaxis.set_major_formatter(mdates.DateFormatter('%m-%d'))
                ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, days//10)))
                plt.setp(ax.xaxis.get_majorticklabels(), rotation=45)
            
            plt.tight_layout()
            
            # 저장
            if save:
                filename = f"candidate_trend_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                filepath = self.chart_dir / filename
                plt.savefig(filepath, dpi=300, bbox_inches='tight')
                self.logger.info(f"차트 저장: {filepath}")
                
                plt.show()
                return str(filepath)
            else:
                plt.show()
                return None
                
        except Exception as e:
            self.logger.error(f"추이 차트 생성 실패: {e}")
            return None
    
    def create_candidate_score_distribution(self, days: int = 30, save: bool = True) -> str:
        """후보 종목 점수 분포 차트"""
        try:
            self.logger.info(f"점수 분포 차트 생성 시작 ({days}일)")
            
            # 데이터 조회
            candidates = self.db_manager.get_candidate_history(days)
            
            if candidates.empty:
                self.logger.warning("표시할 데이터가 없습니다")
                return None
            
            # 차트 생성
            fig, ((ax1, ax2), (ax3, ax4)) = plt.subplots(2, 2, figsize=(16, 12))
            fig.suptitle(f'후보 종목 점수 분석 ({days}일)', fontsize=16, fontweight='bold')
            
            # 1. 점수 히스토그램
            ax1.hist(candidates['score'], bins=20, alpha=0.7, color='skyblue', edgecolor='black')
            ax1.set_title('점수 분포', fontsize=14)
            ax1.set_xlabel('점수', fontsize=12)
            ax1.set_ylabel('빈도', fontsize=12)
            mean_score = candidates['score'].mean()
            ax1.axvline(mean_score, color='red', linestyle='--', 
                       label=f'평균: {mean_score:.1f}')
            ax1.legend()
            ax1.grid(True, alpha=0.3)
            
            # 2. 일별 점수 박스플롯
            candidates['date'] = candidates['selection_date'].dt.date
            daily_scores = candidates.groupby('date')['score'].apply(list).reset_index()
            
            if len(daily_scores) > 1:
                ax2.boxplot([scores for scores in daily_scores['score']], 
                           labels=[d.strftime('%m-%d') for d in daily_scores['date']])
                ax2.set_title('일별 점수 분포', fontsize=14)
                ax2.set_ylabel('점수', fontsize=12)
                ax2.tick_params(axis='x', rotation=45)
                ax2.grid(True, alpha=0.3)
            else:
                ax2.text(0.5, 0.5, '데이터 부족', ha='center', va='center', transform=ax2.transAxes)
                ax2.set_title('일별 점수 분포 (데이터 부족)', fontsize=14)
            
            # 3. 상위 종목 (점수 기준)
            top_stocks = candidates.nlargest(10, 'score')[['stock_name', 'score']]
            y_pos = np.arange(len(top_stocks))
            ax3.barh(y_pos, top_stocks['score'], color='gold', alpha=0.8)
            ax3.set_yticks(y_pos)
            ax3.set_yticklabels(top_stocks['stock_name'], fontsize=10)
            ax3.set_title('상위 10개 종목 (점수순)', fontsize=14)
            ax3.set_xlabel('점수', fontsize=12)
            ax3.grid(True, alpha=0.3)
            
            # 4. 선정 빈도 상위 종목
            stock_counts = candidates['stock_name'].value_counts().head(10)
            ax4.bar(range(len(stock_counts)), stock_counts.values, color='lightcoral', alpha=0.8)
            ax4.set_xticks(range(len(stock_counts)))
            ax4.set_xticklabels(stock_counts.index, rotation=45, fontsize=10)
            ax4.set_title('선정 빈도 상위 10개 종목', fontsize=14)
            ax4.set_ylabel('선정 횟수', fontsize=12)
            ax4.grid(True, alpha=0.3)
            
            plt.tight_layout()
            
            # 저장
            if save:
                filename = f"score_distribution_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                filepath = self.chart_dir / filename
                plt.savefig(filepath, dpi=300, bbox_inches='tight')
                self.logger.info(f"차트 저장: {filepath}")
                
                plt.show()
                return str(filepath)
            else:
                plt.show()
                return None
                
        except Exception as e:
            self.logger.error(f"점수 분포 차트 생성 실패: {e}")
            return None
    
    def create_candidate_reasons_analysis(self, days: int = 30, save: bool = True) -> str:
        """후보 종목 선정 사유 분석 차트"""
        try:
            self.logger.info(f"선정 사유 분석 차트 생성 시작 ({days}일)")
            
            # 데이터 조회
            candidates = self.db_manager.get_candidate_history(days)
            
            if candidates.empty:
                self.logger.warning("표시할 데이터가 없습니다")
                return None
            
            # 선정 사유 분석
            all_reasons = []
            for reasons in candidates['reasons'].dropna():
                all_reasons.extend([r.strip() for r in reasons.split(',')])
            
            reason_counts = pd.Series(all_reasons).value_counts()
            
            # 차트 생성
            fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(16, 8))
            fig.suptitle(f'후보 종목 선정 사유 분석 ({days}일)', fontsize=16, fontweight='bold')
            
            # 1. 선정 사유 빈도 (파이 차트)
            colors = plt.cm.Set3(np.linspace(0, 1, len(reason_counts)))
            wedges, texts, autotexts = ax1.pie(reason_counts.values, labels=reason_counts.index, 
                                              autopct='%1.1f%%', colors=colors, startangle=90)
            ax1.set_title('선정 사유 분포', fontsize=14)
            
            # 텍스트 크기 조정
            for text in texts:
                text.set_fontsize(10)
            for autotext in autotexts:
                autotext.set_fontsize(8)
                autotext.set_color('white')
                autotext.set_weight('bold')
            
            # 2. 선정 사유 빈도 (막대 차트)
            y_pos = np.arange(len(reason_counts))
            bars = ax2.barh(y_pos, reason_counts.values, color=colors)
            ax2.set_yticks(y_pos)
            ax2.set_yticklabels(reason_counts.index, fontsize=10)
            ax2.set_title('선정 사유 빈도', fontsize=14)
            ax2.set_xlabel('빈도', fontsize=12)
            ax2.grid(True, alpha=0.3)
            
            # 막대에 값 표시
            for bar, value in zip(bars, reason_counts.values):
                ax2.text(bar.get_width() + 0.1, bar.get_y() + bar.get_height()/2, 
                        str(value), ha='left', va='center', fontsize=10)
            
            plt.tight_layout()
            
            # 저장
            if save:
                filename = f"reasons_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                filepath = self.chart_dir / filename
                plt.savefig(filepath, dpi=300, bbox_inches='tight')
                self.logger.info(f"차트 저장: {filepath}")
                
                plt.show()
                return str(filepath)
            else:
                plt.show()
                return None
                
        except Exception as e:
            self.logger.error(f"선정 사유 분석 차트 생성 실패: {e}")
            return None
    
    def create_performance_summary(self, days: int = 30, save: bool = True) -> str:
        """성과 요약 대시보드"""
        try:
            self.logger.info(f"성과 요약 대시보드 생성 시작 ({days}일)")
            
            # 데이터 조회
            candidates = self.db_manager.get_candidate_history(days)
            daily_stats = self.db_manager.get_daily_candidate_count(days)
            
            if candidates.empty:
                self.logger.warning("표시할 데이터가 없습니다")
                return None
            
            # 통계 계산
            total_candidates = len(candidates)
            avg_daily_count = daily_stats['count'].mean() if not daily_stats.empty else 0
            avg_score = candidates['score'].mean()
            max_score = candidates['score'].max()
            unique_stocks = candidates['stock_code'].nunique()
            
            # 차트 생성
            fig = plt.figure(figsize=(20, 12))
            gs = fig.add_gridspec(3, 4, hspace=0.3, wspace=0.3)
            
            # 제목
            fig.suptitle(f'RoboTrader 후보 종목 선정 성과 대시보드 ({days}일)', 
                        fontsize=18, fontweight='bold', y=0.95)
            
            # 1. 주요 지표 (텍스트)
            ax_stats = fig.add_subplot(gs[0, :2])
            ax_stats.axis('off')
            
            stats_text = f"""
            📊 주요 통계 지표
            
            • 총 선정 종목 수: {total_candidates:,}개
            • 일평균 선정 수: {avg_daily_count:.1f}개
            • 평균 선정 점수: {avg_score:.1f}점
            • 최고 선정 점수: {max_score:.1f}점
            • 고유 종목 수: {unique_stocks:,}개
            • 분석 기간: {days}일
            """
            
            ax_stats.text(0.1, 0.5, stats_text, fontsize=14, verticalalignment='center',
                         bbox=dict(boxstyle="round,pad=0.5", facecolor="lightblue", alpha=0.7))
            
            # 2. 일별 추이 (미니 차트)
            ax_trend = fig.add_subplot(gs[0, 2:])
            if not daily_stats.empty:
                ax_trend.plot(daily_stats['date'], daily_stats['count'], 
                            marker='o', linewidth=2, color='steelblue')
                ax_trend.set_title('일별 선정 추이', fontsize=12)
                ax_trend.set_ylabel('종목 수', fontsize=10)
                ax_trend.grid(True, alpha=0.3)
                ax_trend.tick_params(axis='x', rotation=45, labelsize=8)
            
            # 3. 점수 분포
            ax_hist = fig.add_subplot(gs[1, :2])
            ax_hist.hist(candidates['score'], bins=15, alpha=0.7, color='skyblue', edgecolor='black')
            ax_hist.set_title('점수 분포', fontsize=12)
            ax_hist.set_xlabel('점수', fontsize=10)
            ax_hist.set_ylabel('빈도', fontsize=10)
            ax_hist.grid(True, alpha=0.3)
            
            # 4. 상위 종목
            ax_top = fig.add_subplot(gs[1, 2:])
            top_stocks = candidates.nlargest(8, 'score')[['stock_name', 'score']]
            bars = ax_top.barh(range(len(top_stocks)), top_stocks['score'], color='gold', alpha=0.8)
            ax_top.set_yticks(range(len(top_stocks)))
            ax_top.set_yticklabels(top_stocks['stock_name'], fontsize=10)
            ax_top.set_title('상위 종목 (점수순)', fontsize=12)
            ax_top.set_xlabel('점수', fontsize=10)
            ax_top.grid(True, alpha=0.3)
            
            # 점수 표시
            for bar, score in zip(bars, top_stocks['score']):
                ax_top.text(bar.get_width() + 1, bar.get_y() + bar.get_height()/2, 
                           f'{score:.1f}', ha='left', va='center', fontsize=9)
            
            # 5. 선정 사유 분석
            ax_reasons = fig.add_subplot(gs[2, :2])
            all_reasons = []
            for reasons in candidates['reasons'].dropna():
                all_reasons.extend([r.strip() for r in reasons.split(',')])
            
            reason_counts = pd.Series(all_reasons).value_counts().head(8)
            colors = plt.cm.Set3(np.linspace(0, 1, len(reason_counts)))
            bars = ax_reasons.bar(range(len(reason_counts)), reason_counts.values, color=colors)
            ax_reasons.set_xticks(range(len(reason_counts)))
            ax_reasons.set_xticklabels(reason_counts.index, rotation=45, fontsize=10, ha='right')
            ax_reasons.set_title('주요 선정 사유', fontsize=12)
            ax_reasons.set_ylabel('빈도', fontsize=10)
            ax_reasons.grid(True, alpha=0.3)
            
            # 6. 선정 빈도 상위 종목
            ax_freq = fig.add_subplot(gs[2, 2:])
            stock_freq = candidates['stock_name'].value_counts().head(8)
            bars = ax_freq.bar(range(len(stock_freq)), stock_freq.values, color='lightcoral', alpha=0.8)
            ax_freq.set_xticks(range(len(stock_freq)))
            ax_freq.set_xticklabels(stock_freq.index, rotation=45, fontsize=10, ha='right')
            ax_freq.set_title('자주 선정되는 종목', fontsize=12)
            ax_freq.set_ylabel('선정 횟수', fontsize=10)
            ax_freq.grid(True, alpha=0.3)
            
            # 저장
            if save:
                filename = f"performance_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
                filepath = self.chart_dir / filename
                plt.savefig(filepath, dpi=300, bbox_inches='tight')
                self.logger.info(f"성과 대시보드 저장: {filepath}")
                
                plt.show()
                return str(filepath)
            else:
                plt.show()
                return None
                
        except Exception as e:
            self.logger.error(f"성과 대시보드 생성 실패: {e}")
            return None
    
    def generate_all_charts(self, days: int = 30) -> List[str]:
        """모든 차트 생성"""
        try:
            self.logger.info(f"전체 차트 생성 시작 ({days}일)")
            
            chart_files = []
            
            # 1. 추이 차트
            file1 = self.create_candidate_trend_chart(days, save=True)
            if file1:
                chart_files.append(file1)
            
            # 2. 점수 분포 차트
            file2 = self.create_candidate_score_distribution(days, save=True)
            if file2:
                chart_files.append(file2)
            
            # 3. 선정 사유 분석
            file3 = self.create_candidate_reasons_analysis(days, save=True)
            if file3:
                chart_files.append(file3)
            
            # 4. 성과 요약
            file4 = self.create_performance_summary(days, save=True)
            if file4:
                chart_files.append(file4)
            
            self.logger.info(f"전체 차트 생성 완료: {len(chart_files)}개")
            return chart_files
            
        except Exception as e:
            self.logger.error(f"전체 차트 생성 실패: {e}")
            return []
    
    def create_strategy_chart(self, data: pd.DataFrame, stock_code: str, stock_name: str, 
                            strategy_type: str, timeframe: str = "1min", 
                            indicators: dict = None, signals: dict = None) -> str:
        """
        전략별 차트 생성 (1분봉/3분봉 구분)
        
        Args:
            data: 분봉 데이터
            stock_code: 종목코드
            stock_name: 종목명
            strategy_type: 전략 타입 ("price_box", "bollinger_bands")
            timeframe: 시간프레임 ("1min", "3min")
            indicators: 기술적 지표 데이터
            signals: 매매 신호 데이터
            
        Returns:
            str: 차트 파일 경로
        """
        try:
            if data.empty:
                self.logger.error("데이터가 없어 차트를 생성할 수 없습니다")
                return None
            
            self.logger.info(f"{strategy_type} 전략 {timeframe} 차트 생성 시작: {stock_code}")
            
            # 전략별 제목 설정
            strategy_names = {
                "price_box": "가격박스 + 이등분선",
                "bollinger_bands": "볼린저밴드 + 이등분선"
            }
            strategy_name = strategy_names.get(strategy_type, strategy_type)
            
            # 시간프레임별 설정
            timeframe_settings = {
                "1min": {"title": "1분봉", "time_interval": 60, "tick_interval": 60},
                "3min": {"title": "3분봉", "time_interval": 180, "tick_interval": 180}
            }
            tf_setting = timeframe_settings.get(timeframe, timeframe_settings["1min"])
            
            # 차트 생성
            fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(16, 14))
            fig.suptitle(f'{strategy_name} - {stock_code}({stock_name}) {tf_setting["title"]} 차트', 
                        fontsize=16, fontweight='bold')
            
            # 데이터 인덱스
            x_axis = range(len(data))
            
            # 상단: 캔들스틱 차트 + 기술적 지표
            self._draw_candlestick(ax1, data, x_axis)
            
            if indicators is not None and not indicators.empty:
                self._draw_indicators(ax1, indicators, x_axis, strategy_type)
            
            if signals is not None and not signals.empty:
                self._draw_signals(ax1, data, signals, x_axis)
            
            ax1.set_title(f'가격 차트 및 {strategy_name}', fontsize=14)
            ax1.set_ylabel('가격 (원)', fontsize=12)
            ax1.legend(loc='upper left', fontsize=10)
            ax1.grid(True, alpha=0.3)
            
            # 중간: 신호 상태
            if signals is not None and not signals.empty:
                self._draw_signal_status(ax2, signals, x_axis, strategy_type)
            
            ax2.set_title('매매 신호 상태', fontsize=14)
            ax2.set_ylabel('신호', fontsize=12)
            ax2.legend(loc='upper left', fontsize=10)
            ax2.grid(True, alpha=0.3)
            
            # 하단: 거래량
            ax3.bar(x_axis, data['volume'], alpha=0.5, color='gray', label='거래량')
            ax3.set_title('거래량', fontsize=14)
            ax3.set_xlabel(f'시간 ({tf_setting["title"]})', fontsize=12)
            ax3.set_ylabel('거래량', fontsize=12)
            ax3.legend(loc='upper left', fontsize=10)
            ax3.grid(True, alpha=0.3)
            
            # x축 시간 라벨 설정 (전략별 시간간격 적용)
            self._set_time_axis(data, [ax1, ax2, ax3], tf_setting["tick_interval"])
            
            plt.tight_layout()
            
            # 저장
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timeframe}_{strategy_type}_{stock_code}_{timestamp}.png"
            filepath = self.chart_dir / filename
            plt.savefig(filepath, dpi=300, bbox_inches='tight')
            plt.close()
            
            self.logger.info(f"{strategy_type} {timeframe} 차트 저장: {filepath}")
            return str(filepath)
            
        except Exception as e:
            self.logger.error(f"{strategy_type} 차트 생성 오류: {e}")
            return None
    
    def _draw_candlestick(self, ax, data, x_axis):
        """캔들스틱 그리기"""
        for i in x_axis:
            color = 'red' if data['close'].iloc[i] >= data['open'].iloc[i] else 'blue'
            ax.plot([i, i], [data['low'].iloc[i], data['high'].iloc[i]], color='black', linewidth=0.5)
            ax.plot([i, i], [data['open'].iloc[i], data['close'].iloc[i]], color=color, linewidth=2)
    
    def _draw_indicators(self, ax, indicators, x_axis, strategy_type):
        """기술적 지표 그리기"""
        if strategy_type == "price_box":
            # 가격박스 지표
            if 'upper_line' in indicators:
                ax.plot(x_axis, indicators['upper_line'], 'orange', linewidth=1.5, label='박스상한선', alpha=0.8)
            if 'lower_line' in indicators:
                ax.plot(x_axis, indicators['lower_line'], 'brown', linewidth=1.5, label='박스하한선', alpha=0.8)
            if 'center_line' in indicators:
                ax.plot(x_axis, indicators['center_line'], 'navy', linewidth=1.5, label='박스중심선', alpha=0.8)
                
        elif strategy_type == "bollinger_bands":
            # 볼린저밴드 지표
            if 'upper_band' in indicators:
                ax.plot(x_axis, indicators['upper_band'], 'orange', linewidth=1.5, label='상한선', alpha=0.8)
            if 'lower_band' in indicators:
                ax.plot(x_axis, indicators['lower_band'], 'brown', linewidth=1.5, label='하한선', alpha=0.8)
            if 'sma' in indicators:
                ax.plot(x_axis, indicators['sma'], 'navy', linewidth=1.5, label='중심선(SMA)', alpha=0.8)
            if 'upper_band' in indicators and 'lower_band' in indicators:
                ax.fill_between(x_axis, indicators['upper_band'], indicators['lower_band'],
                               alpha=0.1, color='blue', label='볼린저밴드')
        
        # 이등분선 (공통)
        if 'bisector_line' in indicators:
            ax.plot(x_axis, indicators['bisector_line'], 'purple', linewidth=2, label='이등분선', alpha=0.8)
        
        # 이등분선 상하 영역
        if 'bullish_zone' in indicators:
            bullish_mask = indicators['bullish_zone']
            for i in range(len(bullish_mask)):
                if bullish_mask.iloc[i]:
                    ax.axvspan(i-0.5, i+0.5, alpha=0.1, color='green')
    
    def _draw_signals(self, ax, data, signals, x_axis):
        """매매 신호 그리기"""
        # 매수 신호들 수집
        buy_signals = []
        
        # 가격박스 신호
        if 'first_lower_touch' in signals:
            buy_signals.extend(signals[signals['first_lower_touch']].index.tolist())
        
        # 볼린저밴드 신호
        if 'upper_breakout' in signals:
            buy_signals.extend(signals[signals['upper_breakout']].index.tolist())
        if 'lower_touch' in signals:
            buy_signals.extend(signals[signals['lower_touch']].index.tolist())
        
        if buy_signals:
            buy_signals = list(set(buy_signals))  # 중복 제거
            ax.scatter(buy_signals, data['close'].iloc[buy_signals], 
                      color='red', marker='^', s=100, label='매수신호', zorder=5)
    
    def _draw_signal_status(self, ax, signals, x_axis, strategy_type):
        """신호 상태 그리기"""
        if strategy_type == "price_box":
            if 'first_lower_touch' in signals:
                touch_signals = signals['first_lower_touch'].astype(int)
                touch_indices = [i for i in x_axis if touch_signals.iloc[i] == 1]
                if touch_indices:
                    ax.scatter(touch_indices, [1]*len(touch_indices), 
                              color='red', marker='^', s=50, label='첫 박스하한선 터치')
            
            if 'center_breakout_up' in signals:
                breakout_signals = signals['center_breakout_up'].astype(int)
                breakout_indices = [i for i in x_axis if breakout_signals.iloc[i] == 1]
                if breakout_indices:
                    ax.scatter(breakout_indices, [0.5]*len(breakout_indices), 
                              color='blue', marker='o', s=50, label='박스중심선 돌파')
                              
        elif strategy_type == "bollinger_bands":
            if 'upper_breakout' in signals:
                breakout_signals = signals['upper_breakout'].astype(int)
                breakout_indices = [i for i in x_axis if breakout_signals.iloc[i] == 1]
                if breakout_indices:
                    ax.scatter(breakout_indices, [1]*len(breakout_indices), 
                              color='red', marker='^', s=50, label='상한선 돌파')
            
            if 'lower_touch' in signals:
                touch_signals = signals['lower_touch'].astype(int)
                touch_indices = [i for i in x_axis if touch_signals.iloc[i] == 1]
                if touch_indices:
                    ax.scatter(touch_indices, [0.5]*len(touch_indices), 
                              color='blue', marker='v', s=50, label='하한선 터치')
        
        # 이등분선 상태 (공통)
        if 'bullish_zone' in signals:
            ax.fill_between(x_axis, 0, signals['bullish_zone'].astype(int), 
                           alpha=0.3, color='green', label='이등분선 위 구간')
    
    def _set_time_axis(self, data, axes, tick_interval_minutes):
        """시간축 설정 (1분봉/3분봉 구분)"""
        try:
            if 'time' in data.columns:
                # 시간 간격에 따른 틱 설정
                if tick_interval_minutes == 60:  # 1분봉 - 1시간마다 표시
                    time_ticks = range(0, len(data), 60)
                elif tick_interval_minutes == 180:  # 3분봉 - 3시간마다 표시 
                    time_ticks = range(0, len(data), 60)  # 3분봉이므로 60개 = 3시간
                else:
                    time_ticks = range(0, len(data), max(1, len(data) // 10))
                
                # 시간 라벨 생성
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
                
                # 모든 축에 시간 라벨 적용
                for ax in axes:
                    ax.set_xticks(time_ticks)
                    ax.set_xticklabels(time_labels, rotation=45)
            else:
                # time 컬럼이 없는 경우 인덱스 기반
                for ax in axes:
                    ax.set_xlabel('데이터 인덱스')
                    
        except Exception as e:
            self.logger.error(f"시간축 설정 오류: {e}")
            for ax in axes:
                ax.set_xlabel('데이터 인덱스')