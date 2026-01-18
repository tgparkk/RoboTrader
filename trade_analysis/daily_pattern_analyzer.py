"""
일봉 기반 승리/패배 패턴 분석기
분봉 데이터와 일봉 데이터를 결합하여 승리 확률을 높이는 패턴을 분석
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Any
from datetime import datetime, timedelta
import logging
from dataclasses import dataclass
from pathlib import Path
import pickle
import json
import re

from utils.logger import setup_logger
from utils.korean_time import now_kst
from utils.data_cache import DailyDataCache


@dataclass
class PatternFeature:
    """패턴 특성 데이터 클래스"""
    feature_name: str
    value: float
    weight: float = 1.0
    description: str = ""


@dataclass
class WinLossPattern:
    """승리/패배 패턴 데이터 클래스"""
    stock_code: str
    signal_date: str
    signal_time: str
    is_win: bool
    daily_features: Dict[str, float]
    minute_features: Dict[str, float]
    combined_score: float = 0.0


class DailyPatternAnalyzer:
    """일봉 기반 패턴 분석기"""
    
    def __init__(self, logger=None):
        self.logger = logger or setup_logger(__name__)
        self.patterns: List[WinLossPattern] = []
        self.feature_weights: Dict[str, float] = {}
        self.win_threshold: float = 0.6  # 승리 확률 임계값
        
    def load_signal_replay_logs(self, log_dir: str = "signal_replay_log") -> List[Dict]:
        """시뮬레이션 로그에서 승리/패배 데이터 로드"""
        try:
            log_path = Path(log_dir)
            if not log_path.exists():
                self.logger.warning(f"로그 디렉토리가 존재하지 않음: {log_dir}")
                return []
            
            logs = []
            for log_file in log_path.glob("*.txt"):
                try:
                    with open(log_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        logs.extend(self._parse_log_content(content, log_file.name))
                except Exception as e:
                    self.logger.warning(f"로그 파일 파싱 실패 {log_file}: {e}")
            
            self.logger.info(f"총 {len(logs)}개의 거래 로그 로드 완료")
            return logs
            
        except Exception as e:
            self.logger.error(f"로그 로드 실패: {e}")
            return []
    
    def _parse_log_content(self, content: str, filename: str) -> List[Dict]:
        """로그 내용 파싱"""
        logs = []
        lines = content.split('\n')
        
        # 파일명에서 날짜 추출
        date_match = re.search(r'(\d{8})', filename)
        signal_date = date_match.group(1) if date_match else now_kst().strftime("%Y%m%d")
        
        current_stock = None
        current_trades = []
        
        for line in lines:
            line = line.strip()
            
            # 종목코드 추출
            stock_match = re.search(r'=== (\d{6}) -', line)
            if stock_match:
                current_stock = stock_match.group(1)
                current_trades = []
                continue
            
            # 체결 시뮬레이션에서 거래 정보 추출
            if "체결 시뮬레이션:" in line:
                continue
            
            # 매수/매도 정보 추출
            trade_match = re.search(r'(\d{2}:\d{2}) 매수\[.*?\] @([\d,]+) → (\d{2}:\d{2}) 매도\[.*?\] @([\d,]+) \(([+-]?\d+\.\d+)%\)', line)
            if trade_match and current_stock:
                buy_time = trade_match.group(1)
                buy_price = float(trade_match.group(2).replace(',', ''))
                sell_time = trade_match.group(3)
                sell_price = float(trade_match.group(4).replace(',', ''))
                return_pct = float(trade_match.group(5))
                
                is_win = return_pct > 0
                
                log_data = {
                    'stock_code': current_stock,
                    'signal_date': signal_date,
                    'signal_time': buy_time,
                    'is_win': is_win,
                    'return_pct': return_pct,
                    'buy_price': buy_price,
                    'sell_price': sell_price,
                    'raw_line': line
                }
                
                logs.append(log_data)
        
        return logs
    
    def _extract_trade_info(self, line: str, is_win: bool) -> Optional[Dict]:
        """거래 정보 추출"""
        try:
            # 시간 정보 추출 (예: 09:03, 10:15 등)
            import re
            time_match = re.search(r'(\d{2}:\d{2})', line)
            if not time_match:
                return None
            
            signal_time = time_match.group(1)
            
            # 종목코드 추출 (예: 103840)
            stock_match = re.search(r'(\d{6})', line)
            if not stock_match:
                return None
            
            stock_code = stock_match.group(1)
            
            # 날짜는 파일명에서 추출 (예: signal_replay_20250901.txt)
            date_match = re.search(r'(\d{8})', line)
            signal_date = date_match.group(1) if date_match else now_kst().strftime("%Y%m%d")
            
            return {
                'stock_code': stock_code,
                'signal_date': signal_date,
                'signal_time': signal_time,
                'is_win': is_win,
                'raw_line': line
            }
            
        except Exception as e:
            self.logger.debug(f"거래 정보 추출 실패: {e}")
            return None
    
    def load_daily_data(self, stock_code: str, date_str: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드 (DuckDB)"""
        try:
            daily_cache = DailyDataCache()
            data = daily_cache.load_data(stock_code)

            if data is None or data.empty:
                return None
            
            # 컬럼명 정리 및 데이터 타입 변환
            if 'stck_bsop_date' in data.columns:
                data['date'] = pd.to_datetime(data['stck_bsop_date'])
            if 'stck_clpr' in data.columns:
                data['close'] = pd.to_numeric(data['stck_clpr'], errors='coerce')
            if 'stck_oprc' in data.columns:
                data['open'] = pd.to_numeric(data['stck_oprc'], errors='coerce')
            if 'stck_hgpr' in data.columns:
                data['high'] = pd.to_numeric(data['stck_hgpr'], errors='coerce')
            if 'stck_lwpr' in data.columns:
                data['low'] = pd.to_numeric(data['stck_lwpr'], errors='coerce')
            if 'acml_vol' in data.columns:
                data['volume'] = pd.to_numeric(data['acml_vol'], errors='coerce')
                
            return data.sort_values('date').reset_index(drop=True)
            
        except Exception as e:
            self.logger.debug(f"일봉 데이터 로드 실패 {stock_code}: {e}")
            return None
    
    def extract_daily_features(self, daily_data: pd.DataFrame, signal_date: str) -> Dict[str, float]:
        """일봉 데이터에서 특성 추출"""
        features = {}
        
        try:
            if daily_data is None or daily_data.empty:
                return features
            
            # 신호 날짜 이전 데이터만 사용
            signal_dt = pd.to_datetime(signal_date)
            historical_data = daily_data[daily_data['date'] < signal_dt].copy()
            
            if len(historical_data) < 5:
                return features
            
            # 최근 5일, 10일, 20일 데이터
            recent_5d = historical_data.tail(5)
            recent_10d = historical_data.tail(10)
            recent_20d = historical_data.tail(20)
            
            # 1. 가격 모멘텀 특성
            features['price_momentum_5d'] = self._calculate_price_momentum(recent_5d)
            features['price_momentum_10d'] = self._calculate_price_momentum(recent_10d)
            features['price_momentum_20d'] = self._calculate_price_momentum(recent_20d)
            
            # 2. 거래량 특성
            features['volume_ratio_5d'] = self._calculate_volume_ratio(recent_5d)
            features['volume_ratio_10d'] = self._calculate_volume_ratio(recent_10d)
            features['volume_ratio_20d'] = self._calculate_volume_ratio(recent_20d)
            
            # 3. 변동성 특성
            features['volatility_5d'] = self._calculate_volatility(recent_5d)
            features['volatility_10d'] = self._calculate_volatility(recent_10d)
            features['volatility_20d'] = self._calculate_volatility(recent_20d)
            
            # 4. 추세 특성
            features['trend_strength_5d'] = self._calculate_trend_strength(recent_5d)
            features['trend_strength_10d'] = self._calculate_trend_strength(recent_10d)
            features['trend_strength_20d'] = self._calculate_trend_strength(recent_20d)
            
            # 5. 지지/저항 특성
            features['support_resistance_ratio'] = self._calculate_support_resistance_ratio(historical_data)
            
            # 6. 연속 상승/하락 특성
            features['consecutive_up_days'] = self._calculate_consecutive_days(recent_10d, 'up')
            features['consecutive_down_days'] = self._calculate_consecutive_days(recent_10d, 'down')
            
            # 7. 갭 특성
            features['gap_frequency'] = self._calculate_gap_frequency(recent_10d)
            features['gap_magnitude'] = self._calculate_gap_magnitude(recent_10d)
            
        except Exception as e:
            self.logger.debug(f"일봉 특성 추출 실패: {e}")
        
        return features
    
    def _calculate_price_momentum(self, data: pd.DataFrame) -> float:
        """가격 모멘텀 계산"""
        if len(data) < 2:
            return 0.0
        
        start_price = data['close'].iloc[0]
        end_price = data['close'].iloc[-1]
        
        if start_price == 0:
            return 0.0
        
        return (end_price - start_price) / start_price * 100
    
    def _calculate_volume_ratio(self, data: pd.DataFrame) -> float:
        """거래량 비율 계산 (평균 대비)"""
        if len(data) < 2:
            return 1.0
        
        recent_volume = data['volume'].iloc[-1]
        avg_volume = data['volume'].mean()
        
        if avg_volume == 0:
            return 1.0
        
        return recent_volume / avg_volume
    
    def _calculate_volatility(self, data: pd.DataFrame) -> float:
        """변동성 계산 (일일 수익률의 표준편차)"""
        if len(data) < 2:
            return 0.0
        
        returns = data['close'].pct_change().dropna()
        return returns.std() * 100
    
    def _calculate_trend_strength(self, data: pd.DataFrame) -> float:
        """추세 강도 계산 (선형 회귀 기울기)"""
        if len(data) < 3:
            return 0.0
        
        x = np.arange(len(data))
        y = data['close'].values
        
        # 선형 회귀
        coeffs = np.polyfit(x, y, 1)
        slope = coeffs[0]
        
        # 정규화 (가격 대비)
        avg_price = data['close'].mean()
        if avg_price == 0:
            return 0.0
        
        return (slope / avg_price) * 100
    
    def _calculate_support_resistance_ratio(self, data: pd.DataFrame) -> float:
        """지지/저항 비율 계산"""
        if len(data) < 10:
            return 0.5
        
        recent_20d = data.tail(20)
        current_price = recent_20d['close'].iloc[-1]
        
        # 최근 20일 고가/저가 범위에서 현재가 위치
        high_20d = recent_20d['high'].max()
        low_20d = recent_20d['low'].min()
        
        if high_20d == low_20d:
            return 0.5
        
        return (current_price - low_20d) / (high_20d - low_20d)
    
    def _calculate_consecutive_days(self, data: pd.DataFrame, direction: str) -> int:
        """연속 상승/하락 일수 계산"""
        if len(data) < 2:
            return 0
        
        consecutive = 0
        for i in range(len(data) - 1, 0, -1):
            if direction == 'up' and data['close'].iloc[i] > data['close'].iloc[i-1]:
                consecutive += 1
            elif direction == 'down' and data['close'].iloc[i] < data['close'].iloc[i-1]:
                consecutive += 1
            else:
                break
        
        return consecutive
    
    def _calculate_gap_frequency(self, data: pd.DataFrame) -> float:
        """갭 빈도 계산"""
        if len(data) < 2:
            return 0.0
        
        gaps = 0
        for i in range(1, len(data)):
            prev_close = data['close'].iloc[i-1]
            curr_open = data['open'].iloc[i]
            
            # 갭 크기가 1% 이상인 경우
            if abs(curr_open - prev_close) / prev_close > 0.01:
                gaps += 1
        
        return gaps / (len(data) - 1)
    
    def _calculate_gap_magnitude(self, data: pd.DataFrame) -> float:
        """갭 크기 계산"""
        if len(data) < 2:
            return 0.0
        
        gap_magnitudes = []
        for i in range(1, len(data)):
            prev_close = data['close'].iloc[i-1]
            curr_open = data['open'].iloc[i]
            
            if prev_close != 0:
                gap_mag = (curr_open - prev_close) / prev_close * 100
                gap_magnitudes.append(gap_mag)
        
        return np.mean(gap_magnitudes) if gap_magnitudes else 0.0
    
    def analyze_patterns(self, log_dir: str = "signal_replay_log") -> Dict[str, Any]:
        """승리/패배 패턴 분석"""
        try:
            self.logger.info("🔍 승리/패배 패턴 분석 시작...")
            
            # 1. 로그 데이터 로드
            logs = self.load_signal_replay_logs(log_dir)
            if not logs:
                self.logger.warning("분석할 로그 데이터가 없습니다.")
                return {}
            
            # 2. 각 거래에 대해 일봉 특성 추출
            patterns = []
            for log in logs:
                stock_code = log['stock_code']
                signal_date = log['signal_date']
                
                # 일봉 데이터 로드
                daily_data = self.load_daily_data(stock_code, signal_date)
                if daily_data is None:
                    continue
                
                # 일봉 특성 추출
                daily_features = self.extract_daily_features(daily_data, signal_date)
                
                # 패턴 객체 생성
                pattern = WinLossPattern(
                    stock_code=stock_code,
                    signal_date=signal_date,
                    signal_time=log['signal_time'],
                    is_win=log['is_win'],
                    daily_features=daily_features,
                    minute_features={},  # 분봉 특성은 나중에 추가
                    combined_score=0.0
                )
                
                patterns.append(pattern)
            
            self.patterns = patterns
            self.logger.info(f"✅ {len(patterns)}개 패턴 분석 완료")
            
            # 3. 특성별 승리/패배 차이 분석
            analysis_result = self._analyze_feature_differences(patterns)
            
            return analysis_result
            
        except Exception as e:
            self.logger.error(f"패턴 분석 실패: {e}")
            return {}
    
    def _analyze_feature_differences(self, patterns: List[WinLossPattern]) -> Dict[str, Any]:
        """특성별 승리/패배 차이 분석"""
        try:
            if not patterns:
                return {}
            
            # 승리/패배 그룹 분리
            win_patterns = [p for p in patterns if p.is_win]
            loss_patterns = [p for p in patterns if not p.is_win]
            
            self.logger.info(f"승리 패턴: {len(win_patterns)}개, 패배 패턴: {len(loss_patterns)}개")
            
            # 모든 특성 수집
            all_features = set()
            for pattern in patterns:
                all_features.update(pattern.daily_features.keys())
            
            # 특성별 분석
            feature_analysis = {}
            for feature in all_features:
                win_values = [p.daily_features.get(feature, 0) for p in win_patterns]
                loss_values = [p.daily_features.get(feature, 0) for p in loss_patterns]
                
                if not win_values or not loss_values:
                    continue
                
                win_mean = np.mean(win_values)
                loss_mean = np.mean(loss_values)
                win_std = np.std(win_values)
                loss_std = np.std(loss_values)
                
                # 통계적 유의성 검정 (간단한 t-test)
                t_stat, p_value = self._simple_t_test(win_values, loss_values)
                
                # 특성 가중치 계산 (승리와 패배의 차이가 클수록 높은 가중치)
                weight = abs(win_mean - loss_mean) / (win_std + loss_std + 1e-8)
                
                feature_analysis[feature] = {
                    'win_mean': win_mean,
                    'loss_mean': loss_mean,
                    'win_std': win_std,
                    'loss_std': loss_std,
                    'difference': win_mean - loss_mean,
                    'weight': weight,
                    't_stat': t_stat,
                    'p_value': p_value,
                    'significance': p_value < 0.05
                }
            
            # 가중치 정규화
            max_weight = max([fa['weight'] for fa in feature_analysis.values()])
            for feature in feature_analysis:
                feature_analysis[feature]['normalized_weight'] = feature_analysis[feature]['weight'] / max_weight
            
            # 결과 정리
            result = {
                'total_patterns': len(patterns),
                'win_patterns': len(win_patterns),
                'loss_patterns': len(loss_patterns),
                'win_rate': len(win_patterns) / len(patterns) if patterns else 0,
                'feature_analysis': feature_analysis,
                'top_features': self._get_top_features(feature_analysis)
            }
            
            return result
            
        except Exception as e:
            self.logger.error(f"특성 차이 분석 실패: {e}")
            return {}
    
    def _simple_t_test(self, group1: List[float], group2: List[float]) -> Tuple[float, float]:
        """간단한 t-test 구현"""
        try:
            n1, n2 = len(group1), len(group2)
            if n1 < 2 or n2 < 2:
                return 0.0, 1.0
            
            mean1, mean2 = np.mean(group1), np.mean(group2)
            var1, var2 = np.var(group1, ddof=1), np.var(group2, ddof=1)
            
            # 풀드 분산
            pooled_var = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
            
            # 표준 오차
            se = np.sqrt(pooled_var * (1/n1 + 1/n2))
            
            if se == 0:
                return 0.0, 1.0
            
            # t-통계량
            t_stat = (mean1 - mean2) / se
            
            # 자유도
            df = n1 + n2 - 2
            
            # p-value (근사치)
            p_value = 2 * (1 - self._t_cdf(abs(t_stat), df))
            
            return t_stat, p_value
            
        except Exception as e:
            self.logger.debug(f"t-test 계산 실패: {e}")
            return 0.0, 1.0
    
    def _t_cdf(self, t: float, df: int) -> float:
        """t-분포 누적분포함수 근사"""
        # 간단한 근사치 (정확한 계산은 scipy.stats.t.cdf 사용 권장)
        if df > 30:
            # 정규분포로 근사
            return 0.5 * (1 + np.tanh(t / np.sqrt(2)))
        else:
            # 자유도가 작을 때의 근사
            return 0.5 * (1 + np.tanh(t / np.sqrt(df / (df - 2))))
    
    def _get_top_features(self, feature_analysis: Dict[str, Any], top_n: int = 10) -> List[Dict[str, Any]]:
        """상위 특성 추출"""
        sorted_features = sorted(
            feature_analysis.items(),
            key=lambda x: x[1]['normalized_weight'],
            reverse=True
        )
        
        return [
            {
                'feature': feature,
                'analysis': analysis
            }
            for feature, analysis in sorted_features[:top_n]
        ]
    
    def save_analysis_results(self, results: Dict[str, Any], output_file: str = "daily_pattern_analysis.json"):
        """분석 결과 저장"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2, default=str)
            
            self.logger.info(f"✅ 분석 결과가 {output_file}에 저장되었습니다.")
            
        except Exception as e:
            self.logger.error(f"분석 결과 저장 실패: {e}")
    
    def generate_filter_rules(self, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        """필터 규칙 생성"""
        try:
            if not analysis_results or 'feature_analysis' not in analysis_results:
                return {}
            
            feature_analysis = analysis_results['feature_analysis']
            top_features = analysis_results.get('top_features', [])
            
            # 상위 특성들을 기반으로 필터 규칙 생성
            filter_rules = {}
            
            for feature_info in top_features[:5]:  # 상위 5개 특성만 사용
                feature = feature_info['feature']
                analysis = feature_info['analysis']
                
                if not analysis['significance']:
                    continue
                
                # 승리 패턴의 평균값을 기준으로 필터 생성
                win_mean = analysis['win_mean']
                win_std = analysis['win_std']
                
                # 임계값 설정 (평균 ± 0.5 * 표준편차)
                threshold_low = win_mean - 0.5 * win_std
                threshold_high = win_mean + 0.5 * win_std
                
                filter_rules[feature] = {
                    'threshold_low': threshold_low,
                    'threshold_high': threshold_high,
                    'weight': analysis['normalized_weight'],
                    'description': f"{feature}: {threshold_low:.3f} ~ {threshold_high:.3f}"
                }
            
            return filter_rules
            
        except Exception as e:
            self.logger.error(f"필터 규칙 생성 실패: {e}")
            return {}


def main():
    """메인 실행 함수"""
    analyzer = DailyPatternAnalyzer()
    
    # 패턴 분석 실행
    results = analyzer.analyze_patterns()
    
    if results:
        # 결과 저장
        analyzer.save_analysis_results(results)
        
        # 필터 규칙 생성
        filter_rules = analyzer.generate_filter_rules(results)
        
        # 결과 출력
        print("\n" + "="*80)
        print("📊 일봉 기반 승리/패배 패턴 분석 결과")
        print("="*80)
        print(f"총 패턴 수: {results['total_patterns']}")
        print(f"승리 패턴: {results['win_patterns']}")
        print(f"패배 패턴: {results['loss_patterns']}")
        print(f"전체 승률: {results['win_rate']:.1%}")
        print("\n🔝 상위 특성:")
        
        for i, feature_info in enumerate(results['top_features'][:10], 1):
            feature = feature_info['feature']
            analysis = feature_info['analysis']
            print(f"{i:2d}. {feature}")
            print(f"    승리 평균: {analysis['win_mean']:.3f}")
            print(f"    패배 평균: {analysis['loss_mean']:.3f}")
            print(f"    차이: {analysis['difference']:+.3f}")
            print(f"    가중치: {analysis['normalized_weight']:.3f}")
            print(f"    유의성: {'✅' if analysis['significance'] else '❌'}")
            print()
        
        print("\n🎯 생성된 필터 규칙:")
        for feature, rule in filter_rules.items():
            print(f"• {rule['description']} (가중치: {rule['weight']:.3f})")
    
    else:
        print("❌ 분석할 데이터가 없습니다.")


if __name__ == "__main__":
    main()
