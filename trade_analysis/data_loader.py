#!/usr/bin/env python3
"""
분석용 데이터 로더
수집된 데이터를 분석에 적합한 형태로 변환 및 통합
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
import sys

# 프로젝트 루트를 sys.path에 추가
project_root = Path(__file__).parent.parent
sys.path.append(str(project_root))

from utils.logger import setup_logger

logger = setup_logger(__name__)


class AnalysisDataLoader:
    """분석용 데이터 로더"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
    
    def prepare_stock_data(self, stock_code: str, stock_name: str, 
                          daily_data: Dict[str, pd.DataFrame], 
                          minute_data: Dict[str, pd.DataFrame]) -> Dict[str, Any]:
        """
        종목별 데이터를 분석용 형태로 변환
        
        Args:
            stock_code: 종목코드
            stock_name: 종목명
            daily_data: {날짜: 일봉데이터} 딕셔너리
            minute_data: {날짜: 분봉데이터} 딕셔너리
            
        Returns:
            Dict: 종목별 분석 데이터
        """
        try:
            # 1. 일봉 데이터 통합
            daily_df = self._merge_daily_data(daily_data)
            
            # 2. 분봉 데이터 통합
            minute_df = self._merge_minute_data(minute_data)
            
            # 3. 기본 통계 계산
            stats = self._calculate_basic_stats(daily_df, minute_df)
            
            # 4. 기술적 지표 계산
            technical_indicators = self._calculate_technical_indicators(daily_df, minute_df)
            
            # 5. 거래 패턴 분석
            trading_patterns = self._analyze_trading_patterns(daily_df, minute_df)
            
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'daily_data': daily_df,
                'minute_data': minute_df,
                'basic_stats': stats,
                'technical_indicators': technical_indicators,
                'trading_patterns': trading_patterns,
                'data_quality': self._assess_data_quality(daily_df, minute_df)
            }
            
        except Exception as e:
            self.logger.error(f"종목 데이터 준비 실패 ({stock_code}): {e}")
            return {
                'stock_code': stock_code,
                'stock_name': stock_name,
                'daily_data': pd.DataFrame(),
                'minute_data': pd.DataFrame(),
                'basic_stats': {},
                'technical_indicators': {},
                'trading_patterns': {},
                'data_quality': {'error': str(e)}
            }
    
    def _merge_daily_data(self, daily_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """일봉 데이터 통합"""
        if not daily_data:
            return pd.DataFrame()
        
        all_daily = []
        for date_str, df in daily_data.items():
            if df is not None and not df.empty:
                df_copy = df.copy()
                df_copy['date'] = pd.to_datetime(date_str, format='%Y%m%d')
                all_daily.append(df_copy)
        
        if not all_daily:
            return pd.DataFrame()
        
        merged_df = pd.concat(all_daily, ignore_index=True)
        merged_df = merged_df.sort_values('date').reset_index(drop=True)
        
        return merged_df
    
    def _merge_minute_data(self, minute_data: Dict[str, pd.DataFrame]) -> pd.DataFrame:
        """분봉 데이터 통합"""
        if not minute_data:
            return pd.DataFrame()
        
        all_minute = []
        for date_str, df in minute_data.items():
            if df is not None and not df.empty:
                df_copy = df.copy()
                # datetime 컬럼이 있으면 그대로 사용, 없으면 생성
                if 'datetime' not in df_copy.columns:
                    if 'date' in df_copy.columns and 'time' in df_copy.columns:
                        df_copy['datetime'] = pd.to_datetime(
                            df_copy['date'].astype(str) + ' ' + 
                            df_copy['time'].astype(str).str.zfill(6),
                            format='%Y%m%d %H%M%S',
                            errors='coerce'
                        )
                all_minute.append(df_copy)
        
        if not all_minute:
            return pd.DataFrame()
        
        merged_df = pd.concat(all_minute, ignore_index=True)
        merged_df = merged_df.sort_values('datetime').reset_index(drop=True)
        
        return merged_df
    
    def _calculate_basic_stats(self, daily_df: pd.DataFrame, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """기본 통계 계산"""
        stats = {
            'daily_count': len(daily_df),
            'minute_count': len(minute_df),
            'date_range': None,
            'price_stats': {},
            'volume_stats': {}
        }
        
        # 일봉 통계
        if not daily_df.empty and 'close' in daily_df.columns:
            close_prices = daily_df['close']
            stats['price_stats'] = {
                'first_price': float(close_prices.iloc[0]) if len(close_prices) > 0 else 0,
                'last_price': float(close_prices.iloc[-1]) if len(close_prices) > 0 else 0,
                'max_price': float(close_prices.max()) if len(close_prices) > 0 else 0,
                'min_price': float(close_prices.min()) if len(close_prices) > 0 else 0,
                'avg_price': float(close_prices.mean()) if len(close_prices) > 0 else 0,
                'price_change': float(close_prices.iloc[-1] - close_prices.iloc[0]) if len(close_prices) > 0 else 0,
                'price_change_rate': float((close_prices.iloc[-1] - close_prices.iloc[0]) / close_prices.iloc[0] * 100) if len(close_prices) > 0 and close_prices.iloc[0] > 0 else 0
            }
            
            if 'date' in daily_df.columns:
                stats['date_range'] = {
                    'start_date': daily_df['date'].min().strftime('%Y-%m-%d'),
                    'end_date': daily_df['date'].max().strftime('%Y-%m-%d')
                }
        
        # 거래량 통계
        if not daily_df.empty and 'volume' in daily_df.columns:
            volumes = daily_df['volume']
            stats['volume_stats'] = {
                'total_volume': int(volumes.sum()) if len(volumes) > 0 else 0,
                'avg_volume': float(volumes.mean()) if len(volumes) > 0 else 0,
                'max_volume': int(volumes.max()) if len(volumes) > 0 else 0,
                'min_volume': int(volumes.min()) if len(volumes) > 0 else 0
            }
        
        return stats
    
    def _calculate_technical_indicators(self, daily_df: pd.DataFrame, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """기술적 지표 계산"""
        indicators = {}
        
        # 일봉 기반 지표
        if not daily_df.empty and 'close' in daily_df.columns:
            close_prices = daily_df['close']
            
            # 이동평균
            if len(close_prices) >= 5:
                indicators['ma5'] = float(close_prices.tail(5).mean())
            if len(close_prices) >= 20:
                indicators['ma20'] = float(close_prices.tail(20).mean())
            
            # 변동성 (표준편차)
            if len(close_prices) >= 20:
                returns = close_prices.pct_change().dropna()
                indicators['volatility'] = float(returns.std() * np.sqrt(252))  # 연환산 변동성
            
            # RSI (간단한 버전)
            if len(close_prices) >= 14:
                indicators['rsi'] = self._calculate_rsi(close_prices, 14)
        
        # 분봉 기반 지표
        if not minute_df.empty and 'close' in minute_df.columns:
            close_prices = minute_df['close']
            
            # 분봉 변동성
            if len(close_prices) >= 60:  # 1시간 이상 데이터
                returns = close_prices.pct_change().dropna()
                indicators['minute_volatility'] = float(returns.std())
            
            # 거래량 패턴
            if 'volume' in minute_df.columns:
                volumes = minute_df['volume']
                indicators['volume_pattern'] = {
                    'avg_volume': float(volumes.mean()),
                    'volume_std': float(volumes.std()),
                    'high_volume_ratio': float((volumes > volumes.mean() * 2).sum() / len(volumes))
                }
        
        return indicators
    
    def _calculate_rsi(self, prices: pd.Series, period: int = 14) -> float:
        """RSI 계산"""
        try:
            delta = prices.diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs))
            return float(rsi.iloc[-1]) if not rsi.empty and not pd.isna(rsi.iloc[-1]) else 50.0
        except:
            return 50.0
    
    def _analyze_trading_patterns(self, daily_df: pd.DataFrame, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """거래 패턴 분석"""
        patterns = {}
        
        # 일봉 패턴
        if not daily_df.empty and all(col in daily_df.columns for col in ['open', 'high', 'low', 'close']):
            patterns['daily_patterns'] = self._analyze_daily_patterns(daily_df)
        
        # 분봉 패턴
        if not minute_df.empty and all(col in minute_df.columns for col in ['open', 'high', 'low', 'close']):
            patterns['minute_patterns'] = self._analyze_minute_patterns(minute_df)
        
        return patterns
    
    def _analyze_daily_patterns(self, daily_df: pd.DataFrame) -> Dict[str, Any]:
        """일봉 패턴 분석"""
        patterns = {}
        
        # 상승/하락 일수
        if 'close' in daily_df.columns:
            close_prices = daily_df['close']
            price_changes = close_prices.diff().dropna()
            
            patterns['up_days'] = int((price_changes > 0).sum())
            patterns['down_days'] = int((price_changes < 0).sum())
            patterns['flat_days'] = int((price_changes == 0).sum())
            
            # 연속 상승/하락
            patterns['max_consecutive_up'] = self._max_consecutive(price_changes > 0)
            patterns['max_consecutive_down'] = self._max_consecutive(price_changes < 0)
        
        # 캔들 패턴
        if all(col in daily_df.columns for col in ['open', 'high', 'low', 'close']):
            patterns['candle_patterns'] = self._analyze_candle_patterns(daily_df)
        
        return patterns
    
    def _analyze_minute_patterns(self, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """분봉 패턴 분석"""
        patterns = {}
        
        # 시간대별 패턴
        if 'datetime' in minute_df.columns:
            minute_df['hour'] = minute_df['datetime'].dt.hour
            patterns['hourly_patterns'] = self._analyze_hourly_patterns(minute_df)
        
        # 거래량 패턴
        if 'volume' in minute_df.columns:
            patterns['volume_patterns'] = self._analyze_volume_patterns(minute_df)
        
        return patterns
    
    def _analyze_candle_patterns(self, df: pd.DataFrame) -> Dict[str, Any]:
        """캔들 패턴 분석"""
        patterns = {}
        
        # 도지 캔들
        doji_threshold = 0.001  # 0.1%
        body_size = abs(df['close'] - df['open'])
        total_range = df['high'] - df['low']
        doji_condition = (body_size / total_range) < doji_threshold
        patterns['doji_count'] = int(doji_condition.sum())
        
        # 해머/슈팅스타
        upper_shadow = df['high'] - df[['open', 'close']].max(axis=1)
        lower_shadow = df[['open', 'close']].min(axis=1) - df['low']
        body_size = abs(df['close'] - df['open'])
        
        hammer_condition = (lower_shadow > body_size * 2) & (upper_shadow < body_size)
        shooting_star_condition = (upper_shadow > body_size * 2) & (lower_shadow < body_size)
        
        patterns['hammer_count'] = int(hammer_condition.sum())
        patterns['shooting_star_count'] = int(shooting_star_condition.sum())
        
        return patterns
    
    def _analyze_hourly_patterns(self, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """시간대별 패턴 분석"""
        patterns = {}
        
        if 'close' in minute_df.columns and 'hour' in minute_df.columns:
            hourly_returns = minute_df.groupby('hour')['close'].apply(lambda x: (x.iloc[-1] - x.iloc[0]) / x.iloc[0] if len(x) > 0 and x.iloc[0] > 0 else 0)
            patterns['hourly_returns'] = hourly_returns.to_dict()
            
            # 가장 활발한 시간대
            if 'volume' in minute_df.columns:
                hourly_volume = minute_df.groupby('hour')['volume'].sum()
                patterns['most_active_hour'] = int(hourly_volume.idxmax()) if not hourly_volume.empty else None
        
        return patterns
    
    def _analyze_volume_patterns(self, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """거래량 패턴 분석"""
        patterns = {}
        
        if 'volume' in minute_df.columns:
            volumes = minute_df['volume']
            patterns['volume_stats'] = {
                'mean': float(volumes.mean()),
                'std': float(volumes.std()),
                'max': int(volumes.max()),
                'min': int(volumes.min())
            }
            
            # 거래량 급증 패턴
            volume_mean = volumes.mean()
            volume_std = volumes.std()
            high_volume_threshold = volume_mean + 2 * volume_std
            patterns['high_volume_count'] = int((volumes > high_volume_threshold).sum())
            patterns['high_volume_ratio'] = float(patterns['high_volume_count'] / len(volumes))
        
        return patterns
    
    def _max_consecutive(self, series: pd.Series) -> int:
        """연속된 True의 최대 개수"""
        if series.empty:
            return 0
        
        max_consecutive = 0
        current_consecutive = 0
        
        for value in series:
            if value:
                current_consecutive += 1
                max_consecutive = max(max_consecutive, current_consecutive)
            else:
                current_consecutive = 0
        
        return max_consecutive
    
    def _assess_data_quality(self, daily_df: pd.DataFrame, minute_df: pd.DataFrame) -> Dict[str, Any]:
        """데이터 품질 평가"""
        quality = {
            'daily_quality': 'good',
            'minute_quality': 'good',
            'issues': []
        }
        
        # 일봉 데이터 품질
        if daily_df.empty:
            quality['daily_quality'] = 'no_data'
            quality['issues'].append('일봉 데이터 없음')
        elif len(daily_df) < 5:
            quality['daily_quality'] = 'insufficient'
            quality['issues'].append('일봉 데이터 부족')
        
        # 분봉 데이터 품질
        if minute_df.empty:
            quality['minute_quality'] = 'no_data'
            quality['issues'].append('분봉 데이터 없음')
        elif len(minute_df) < 100:
            quality['minute_quality'] = 'insufficient'
            quality['issues'].append('분봉 데이터 부족')
        
        # 결측값 확인
        if not daily_df.empty:
            missing_daily = daily_df.isnull().sum().sum()
            if missing_daily > 0:
                quality['issues'].append(f'일봉 결측값: {missing_daily}개')
        
        if not minute_df.empty:
            missing_minute = minute_df.isnull().sum().sum()
            if missing_minute > 0:
                quality['issues'].append(f'분봉 결측값: {missing_minute}개')
        
        return quality
    
    def create_analysis_dataset(self, collected_data: Dict[str, Any]) -> pd.DataFrame:
        """
        수집된 데이터를 분석용 데이터셋으로 변환
        
        Args:
            collected_data: collect_analysis_data()의 결과
            
        Returns:
            pd.DataFrame: 분석용 데이터셋
        """
        try:
            analysis_records = []
            
            candidate_stocks = collected_data['candidate_stocks']
            daily_data = collected_data['daily_data']
            minute_data = collected_data['minute_data']
            
            for _, stock in candidate_stocks.iterrows():
                stock_code = stock['stock_code']
                stock_name = stock['stock_name']
                selection_date = stock['selection_date']
                score = stock['score']
                
                # 해당 종목의 데이터 준비
                stock_daily = daily_data.get(stock_code, {})
                stock_minute = minute_data.get(stock_code, {})
                
                # 분석용 데이터 생성
                stock_analysis = self.prepare_stock_data(stock_code, stock_name, stock_daily, stock_minute)
                
                # 분석 레코드 생성
                record = {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'selection_date': selection_date,
                    'score': score,
                    'reasons': stock['reasons'],
                    'status': stock['status']
                }
                
                # 기본 통계 추가
                if 'basic_stats' in stock_analysis:
                    stats = stock_analysis['basic_stats']
                    record.update({
                        'daily_count': stats.get('daily_count', 0),
                        'minute_count': stats.get('minute_count', 0),
                        'first_price': stats.get('price_stats', {}).get('first_price', 0),
                        'last_price': stats.get('price_stats', {}).get('last_price', 0),
                        'max_price': stats.get('price_stats', {}).get('max_price', 0),
                        'min_price': stats.get('price_stats', {}).get('min_price', 0),
                        'price_change': stats.get('price_stats', {}).get('price_change', 0),
                        'price_change_rate': stats.get('price_stats', {}).get('price_change_rate', 0),
                        'total_volume': stats.get('volume_stats', {}).get('total_volume', 0),
                        'avg_volume': stats.get('volume_stats', {}).get('avg_volume', 0)
                    })
                
                # 기술적 지표 추가
                if 'technical_indicators' in stock_analysis:
                    indicators = stock_analysis['technical_indicators']
                    record.update({
                        'ma5': indicators.get('ma5', 0),
                        'ma20': indicators.get('ma20', 0),
                        'volatility': indicators.get('volatility', 0),
                        'rsi': indicators.get('rsi', 50),
                        'minute_volatility': indicators.get('minute_volatility', 0)
                    })
                
                # 거래 패턴 추가
                if 'trading_patterns' in stock_analysis:
                    patterns = stock_analysis['trading_patterns']
                    if 'daily_patterns' in patterns:
                        daily_patterns = patterns['daily_patterns']
                        record.update({
                            'up_days': daily_patterns.get('up_days', 0),
                            'down_days': daily_patterns.get('down_days', 0),
                            'max_consecutive_up': daily_patterns.get('max_consecutive_up', 0),
                            'max_consecutive_down': daily_patterns.get('max_consecutive_down', 0)
                        })
                
                # 데이터 품질 추가
                if 'data_quality' in stock_analysis:
                    quality = stock_analysis['data_quality']
                    record.update({
                        'daily_quality': quality.get('daily_quality', 'unknown'),
                        'minute_quality': quality.get('minute_quality', 'unknown'),
                        'data_issues': '; '.join(quality.get('issues', []))
                    })
                
                analysis_records.append(record)
            
            # DataFrame 생성
            analysis_df = pd.DataFrame(analysis_records)
            
            self.logger.info(f"분석용 데이터셋 생성 완료: {len(analysis_df)}개 종목")
            return analysis_df
            
        except Exception as e:
            self.logger.error(f"분석용 데이터셋 생성 실패: {e}")
            return pd.DataFrame()


def main():
    """테스트 실행"""
    loader = AnalysisDataLoader()
    
    # 테스트용 더미 데이터
    test_daily_data = {
        '20250101': pd.DataFrame({
            'date': [pd.Timestamp('2025-01-01')],
            'open': [1000],
            'high': [1100],
            'low': [950],
            'close': [1050],
            'volume': [1000000]
        })
    }
    
    test_minute_data = {
        '20250101': pd.DataFrame({
            'datetime': pd.date_range('2025-01-01 09:00:00', periods=60, freq='1min'),
            'open': np.random.uniform(1000, 1100, 60),
            'high': np.random.uniform(1100, 1200, 60),
            'low': np.random.uniform(900, 1000, 60),
            'close': np.random.uniform(1000, 1100, 60),
            'volume': np.random.randint(1000, 10000, 60)
        })
    }
    
    # 종목 데이터 준비 테스트
    stock_analysis = loader.prepare_stock_data('005930', '삼성전자', test_daily_data, test_minute_data)
    
    print("종목 분석 데이터:")
    print(f"  종목코드: {stock_analysis['stock_code']}")
    print(f"  종목명: {stock_analysis['stock_name']}")
    print(f"  일봉 데이터: {len(stock_analysis['daily_data'])}건")
    print(f"  분봉 데이터: {len(stock_analysis['minute_data'])}건")
    print(f"  기본 통계: {stock_analysis['basic_stats']}")


if __name__ == "__main__":
    main()
