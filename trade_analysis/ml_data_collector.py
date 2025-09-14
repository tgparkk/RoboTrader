#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
머신러닝 학습을 위한 데이터 수집 및 캐시 시스템
- 일봉 데이터 수집 및 캐시 관리
- 분봉 데이터와 일봉 데이터 결합
- 학습용 특성 추출
"""

import os
import sys
import sqlite3
import pickle
import pandas as pd
import numpy as np
import re
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any
import logging
from pathlib import Path
import warnings
warnings.filterwarnings('ignore')

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.kis_market_api import get_inquire_daily_itemchartprice
from api.kis_auth import auth
from utils.korean_time import now_kst
from utils.logger import setup_logger
from .ml_feature_engineer import MLFeatureEngineer

logger = setup_logger(__name__)

class MLDataCollector:
    """머신러닝 학습을 위한 데이터 수집기"""
    
    def __init__(self, 
                 db_path: str = "data/robotrader.db",
                 minute_cache_dir: str = "cache/minute_data",
                 daily_cache_dir: str = "cache/daily_data",
                 signal_log_dir: str = "signal_replay_log"):
        self.db_path = db_path
        self.minute_cache_dir = Path(minute_cache_dir)
        self.daily_cache_dir = Path(daily_cache_dir)
        self.signal_log_dir = Path(signal_log_dir)
        
        # 특성 추출 엔진 초기화
        self.feature_engineer = MLFeatureEngineer()
        
        # 캐시 디렉토리 생성
        self.daily_cache_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"ML 데이터 수집기 초기화 완료")
        logger.info(f"   - DB: {db_path}")
        logger.info(f"   - 분봉 캐시: {self.minute_cache_dir}")
        logger.info(f"   - 일봉 캐시: {self.daily_cache_dir}")
        logger.info(f"   - 신호 로그: {self.signal_log_dir}")
    
    def get_candidate_stocks_by_date(self, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
        """특정 기간의 후보 종목 조회 (신호 로그에서 추출)"""
        try:
            # 먼저 데이터베이스에서 조회 시도
            if os.path.exists(self.db_path):
                with sqlite3.connect(self.db_path) as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        SELECT stock_code, stock_name, selection_date, selection_reason
                        FROM candidate_stocks 
                        WHERE DATE(selection_date) BETWEEN ? AND ?
                        ORDER BY selection_date, stock_code
                    """, (start_date, end_date))
                    
                    results = cursor.fetchall()
                    
                    if results:
                        # 날짜별로 그룹화
                        stocks_by_date = {}
                        for row in results:
                            stock_code, stock_name, selection_date, selection_reason = row
                            date_str = selection_date.split(' ')[0]  # 날짜 부분만 추출
                            
                            if date_str not in stocks_by_date:
                                stocks_by_date[date_str] = []
                            
                            stocks_by_date[date_str].append({
                                'stock_code': stock_code,
                                'stock_name': stock_name,
                                'selection_date': selection_date,
                                'selection_reason': selection_reason
                            })
                        
                        logger.info(f"{start_date}~{end_date} 기간 후보 종목: {len(results)}개")
                        return stocks_by_date
            
            # 데이터베이스에 데이터가 없으면 신호 로그에서 추출
            logger.info("신호 로그에서 종목 정보 추출")
            return self._extract_stocks_from_logs(start_date, end_date)
                
        except Exception as e:
            logger.error(f"후보 종목 조회 실패: {e}")
            return self._extract_stocks_from_logs(start_date, end_date)
    
    def _extract_stocks_from_logs(self, start_date: str, end_date: str) -> Dict[str, List[Dict]]:
        """신호 로그에서 종목 정보 추출"""
        stocks_by_date = {}
        
        try:
            for log_file in self.signal_log_dir.glob("signal_*.txt"):
                date_match = re.search(r'(\d{8})', log_file.name)
                if date_match:
                    log_date = date_match.group(1)
                    if start_date <= log_date <= end_date:
                        # 로그 파일에서 종목 코드 추출
                        with open(log_file, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # 종목 코드 패턴 찾기 (=== 054540 - 20250905 형태)
                        stock_matches = re.findall(r'=== (\d{6}) - (\d{8})', content)
                        
                        for stock_code, date_str in stock_matches:
                            if date_str not in stocks_by_date:
                                stocks_by_date[date_str] = []
                            
                            stocks_by_date[date_str].append({
                                'stock_code': stock_code,
                                'stock_name': f'종목_{stock_code}',  # 이름은 추후 조회
                                'selection_date': f'{date_str} 09:00:00',
                                'selection_reason': 'signal_log_extracted'
                            })
            
            total_stocks = sum(len(stocks) for stocks in stocks_by_date.values())
            logger.info(f"신호 로그에서 추출한 종목: {total_stocks}개")
            return stocks_by_date
            
        except Exception as e:
            logger.error(f"신호 로그에서 종목 추출 실패: {e}")
            return {}
    
    def collect_daily_data(self, stock_code: str, days: int = 60) -> Optional[pd.DataFrame]:
        """일봉 데이터 수집 및 캐시"""
        try:
            # 캐시 파일 경로
            cache_file = self.daily_cache_dir / f"{stock_code}_daily.pkl"
            
            # 캐시된 데이터가 있는지 확인
            if cache_file.exists():
                cache_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                # 시간대 문제 해결: naive datetime을 KST로 변환
                if cache_time.tzinfo is None:
                    cache_time = cache_time.replace(tzinfo=None)
                current_time = now_kst().replace(tzinfo=None)
                if (current_time - cache_time).days < 1:  # 1일 이내 캐시
                    logger.debug(f"{stock_code} 일봉 데이터 캐시 사용")
                    with open(cache_file, 'rb') as f:
                        return pickle.load(f)
            
            # KIS API 인증 확인 및 실행
            logger.info(f"KIS API 인증 확인")
            auth_result = auth()
            if not auth_result:
                logger.error(f"KIS API 인증 실패")
                return None
            
            # API로 일봉 데이터 수집
            logger.info(f"{stock_code} 일봉 데이터 수집 시작 ({days}일)")
            
            end_date = now_kst().strftime("%Y%m%d")
            start_date = (now_kst() - timedelta(days=days+10)).strftime("%Y%m%d")  # 여유분 추가
            
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
                logger.warning(f"{stock_code} 일봉 데이터 조회 실패")
                return None
            
            # 데이터 정제
            daily_data = daily_data.copy()
            daily_data['stck_bsop_date'] = pd.to_datetime(daily_data['stck_bsop_date'])
            daily_data = daily_data.sort_values('stck_bsop_date').reset_index(drop=True)
            
            # 최근 days일만 선택
            if len(daily_data) > days:
                daily_data = daily_data.tail(days)
            
            # 캐시에 저장
            with open(cache_file, 'wb') as f:
                pickle.dump(daily_data, f)
            
            logger.info(f"{stock_code} 일봉 데이터 수집 완료: {len(daily_data)}개")
            return daily_data
            
        except Exception as e:
            logger.error(f"{stock_code} 일봉 데이터 수집 실패: {e}")
            return None
    
    def load_minute_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """분봉 데이터 로드"""
        try:
            # 분봉 캐시 파일 경로 (기존 형식 유지)
            minute_file = self.minute_cache_dir / f"{stock_code}_{date}.pkl"
            
            if not minute_file.exists():
                logger.warning(f"분봉 데이터 없음: {stock_code} {date}")
                return None
            
            with open(minute_file, 'rb') as f:
                minute_data = pickle.load(f)
            
            logger.debug(f"{stock_code} {date} 분봉 데이터 로드: {len(minute_data)}개")
            return minute_data
            
        except Exception as e:
            logger.error(f"{stock_code} {date} 분봉 데이터 로드 실패: {e}")
            return None
    
    def parse_signal_log(self, log_file: Path) -> List[Dict[str, Any]]:
        """신호 재현 로그 파싱"""
        trades = []
        
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 승패 정보 추출
            win_loss_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', content)
            if win_loss_match:
                total_wins = int(win_loss_match.group(1))
                total_losses = int(win_loss_match.group(2))
            
            # 종목별 거래 정보 추출
            stock_sections = re.split(r'=== (\d{6}) - (\d{8})', content)[1:]  # 첫 번째 빈 요소 제거
            
            for i in range(0, len(stock_sections), 3):  # 매 3개씩 처리 (stock_code, date, content)
                if i + 2 < len(stock_sections):
                    stock_code = stock_sections[i]
                    date = stock_sections[i + 1]
                    section_content = stock_sections[i + 2]
                    
                    # 승패 정보 추출
                    win_loss_match = re.search(r'승패: (\d+)승 (\d+)패', section_content)
                    if win_loss_match:
                        wins = int(win_loss_match.group(1))
                        losses = int(win_loss_match.group(2))
                        
                        # 체결 시뮬레이션 정보 추출
                        trade_matches = re.findall(
                            r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.?\d*)%\)',
                            section_content
                        )
                        
                        for trade in trade_matches:
                            buy_time, signal_type, buy_price, sell_time, sell_reason, sell_price, profit_pct = trade
                            
                            trades.append({
                                'stock_code': stock_code,
                                'date': date,
                                'buy_time': buy_time,
                                'sell_time': sell_time,
                                'buy_price': float(buy_price.replace(',', '')),
                                'sell_price': float(sell_price.replace(',', '')),
                                'profit_pct': float(profit_pct),
                                'signal_type': signal_type,
                                'sell_reason': sell_reason,
                                'is_win': float(profit_pct) > 0,
                                'wins': wins,
                                'losses': losses
                            })
            
            logger.info(f"{log_file.name} 파싱 완료: {len(trades)}개 거래")
            return trades
            
        except Exception as e:
            logger.error(f"{log_file.name} 파싱 실패: {e}")
            return []
    
    def collect_ml_training_data(self, start_date: str, end_date: str) -> pd.DataFrame:
        """머신러닝 학습용 데이터 수집"""
        logger.info(f"ML 학습 데이터 수집 시작: {start_date} ~ {end_date}")
        
        all_trades = []
        
        # 1. 후보 종목 조회
        stocks_by_date = self.get_candidate_stocks_by_date(start_date, end_date)
        
        # 2. 신호 로그에서 거래 정보 추출
        for log_file in self.signal_log_dir.glob("signal_*.txt"):
            date_match = re.search(r'(\d{8})', log_file.name)
            if date_match:
                log_date = date_match.group(1)
                if start_date <= log_date <= end_date:
                    trades = self.parse_signal_log(log_file)
                    all_trades.extend(trades)
        
        # 3. 거래별 특성 데이터 수집
        training_data = []
        
        for trade in all_trades:
            stock_code = trade['stock_code']
            date = trade['date']
            
            logger.info(f"특성 데이터 수집: {stock_code} {date}")
            
            # 분봉 데이터 로드
            minute_data = self.load_minute_data(stock_code, date)
            if minute_data is None:
                continue
            
            # 일봉 데이터 수집
            daily_data = self.collect_daily_data(stock_code, 60)
            if daily_data is None:
                continue
            
            # 특성 추출
            features = self.feature_engineer.extract_comprehensive_features(minute_data, daily_data, trade)
            if features:
                training_data.append(features)
        
        # DataFrame으로 변환
        if training_data:
            df = pd.DataFrame(training_data)
            logger.info(f"ML 학습 데이터 수집 완료: {len(df)}개 샘플")
            return df
        else:
            logger.warning("수집된 학습 데이터가 없습니다")
            return pd.DataFrame()
    
    def extract_features(self, minute_data: pd.DataFrame, daily_data: pd.DataFrame, trade: Dict) -> Optional[Dict]:
        """특성 추출"""
        try:
            # 기본 거래 정보
            features = {
                'stock_code': trade['stock_code'],
                'date': trade['date'],
                'buy_time': trade['buy_time'],
                'sell_time': trade['sell_time'],
                'profit_pct': trade['profit_pct'],
                'is_win': trade['is_win'],
                'signal_type': trade['signal_type'],
                'sell_reason': trade['sell_reason']
            }
            
            # 분봉 특성 추출
            minute_features = self.extract_minute_features(minute_data, trade)
            features.update(minute_features)
            
            # 일봉 특성 추출
            daily_features = self.extract_daily_features(daily_data, trade)
            features.update(daily_features)
            
            return features
            
        except Exception as e:
            logger.error(f"특성 추출 실패 {trade['stock_code']}: {e}")
            return None
    
    def extract_minute_features(self, minute_data: pd.DataFrame, trade: Dict) -> Dict:
        """분봉 특성 추출"""
        features = {}
        
        try:
            # 기본 통계
            features['minute_data_count'] = len(minute_data)
            features['avg_volume'] = minute_data['volume'].mean()
            features['max_volume'] = minute_data['volume'].max()
            features['volume_std'] = minute_data['volume'].std()
            
            # 가격 변동성
            features['price_volatility'] = minute_data['close'].std() / minute_data['close'].mean()
            features['price_range'] = (minute_data['high'].max() - minute_data['low'].min()) / minute_data['close'].mean()
            
            # 거래량 패턴
            features['volume_trend'] = self.calculate_volume_trend(minute_data)
            features['volume_consistency'] = 1 - (minute_data['volume'].std() / minute_data['volume'].mean())
            
            # 시간대별 특성
            buy_time = trade['buy_time']
            hour = int(buy_time.split(':')[0])
            features['buy_hour'] = hour
            features['is_morning_session'] = 1 if 9 <= hour < 12 else 0
            features['is_afternoon_session'] = 1 if 12 <= hour < 15 else 0
            
            return features
            
        except Exception as e:
            logger.error(f"분봉 특성 추출 실패: {e}")
            return {}
    
    def extract_daily_features(self, daily_data: pd.DataFrame, trade: Dict) -> Dict:
        """일봉 특성 추출"""
        features = {}
        
        try:
            # 이동평균선
            daily_data['ma5'] = daily_data['stck_clpr'].rolling(5).mean()
            daily_data['ma20'] = daily_data['stck_clpr'].rolling(20).mean()
            daily_data['ma60'] = daily_data['stck_clpr'].rolling(60).mean()
            
            # 현재가 대비 이동평균 위치
            current_price = daily_data['stck_clpr'].iloc[-1]
            features['ma5_position'] = (current_price - daily_data['ma5'].iloc[-1]) / daily_data['ma5'].iloc[-1]
            features['ma20_position'] = (current_price - daily_data['ma20'].iloc[-1]) / daily_data['ma20'].iloc[-1]
            features['ma60_position'] = (current_price - daily_data['ma60'].iloc[-1]) / daily_data['ma60'].iloc[-1]
            
            # RSI 계산
            features['rsi_14'] = self.calculate_rsi(daily_data['stck_clpr'], 14)
            
            # 거래량 분석
            features['volume_ma20_ratio'] = daily_data['acml_vol'].iloc[-1] / daily_data['acml_vol'].rolling(20).mean().iloc[-1]
            features['volume_trend_5d'] = self.calculate_volume_trend(daily_data.tail(5))
            
            # 가격 모멘텀
            features['price_momentum_5d'] = (daily_data['stck_clpr'].iloc[-1] - daily_data['stck_clpr'].iloc[-6]) / daily_data['stck_clpr'].iloc[-6]
            features['price_momentum_20d'] = (daily_data['stck_clpr'].iloc[-1] - daily_data['stck_clpr'].iloc[-21]) / daily_data['stck_clpr'].iloc[-21]
            
            return features
            
        except Exception as e:
            logger.error(f"일봉 특성 추출 실패: {e}")
            return {}
    
    def calculate_volume_trend(self, data: pd.DataFrame) -> float:
        """거래량 트렌드 계산"""
        try:
            if len(data) < 2:
                return 0.0
            
            volumes = data['volume'] if 'volume' in data.columns else data['acml_vol']
            x = np.arange(len(volumes))
            y = volumes.values
            
            # 선형 회귀로 트렌드 계산
            slope = np.polyfit(x, y, 1)[0]
            return slope / volumes.mean()  # 정규화
            
        except:
            return 0.0
    
    def calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """RSI 계산"""
        try:
            if len(prices) < period + 1:
                return 50.0
            
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            
            return rsi.iloc[-1] if not pd.isna(rsi.iloc[-1]) else 50.0
            
        except:
            return 50.0

def main():
    """메인 실행 함수"""
    collector = MLDataCollector()
    
    # 최근 2주간 데이터 수집
    end_date = now_kst().strftime("%Y%m%d")
    start_date = (now_kst() - timedelta(days=14)).strftime("%Y%m%d")
    
    logger.info(f"🚀 ML 학습 데이터 수집 시작: {start_date} ~ {end_date}")
    
    # 학습 데이터 수집
    training_data = collector.collect_ml_training_data(start_date, end_date)
    
    if not training_data.empty:
        # 결과 저장
        output_file = f"trade_analysis/ml_training_data_{start_date}_{end_date}.pkl"
        with open(output_file, 'wb') as f:
            pickle.dump(training_data, f)
        
        logger.info(f"✅ 학습 데이터 저장 완료: {output_file}")
        logger.info(f"📊 총 {len(training_data)}개 샘플, 승률: {training_data['is_win'].mean():.2%}")
    else:
        logger.warning("⚠️ 수집된 데이터가 없습니다")

if __name__ == "__main__":
    main()
