"""
눌림목 4단계 패턴 상세 분석
- 승리 거래와 패배 거래의 4단계별 차이점 분석
"""

import pandas as pd
import numpy as np
from pathlib import Path
import pickle
from datetime import datetime
import re
from typing import Dict, List
import json

# 전략 모듈 임포트
from core.indicators.pullback_candle_pattern import PullbackCandlePattern
from core.indicators.bisector_line import BisectorLine
from core.indicators.pullback_utils import PullbackUtils
from core.timeframe_converter import TimeFrameConverter


class FourStagePatternAnalyzer:
    """4단계 패턴 분석기"""

    def __init__(self, signal_log_dir: str = "signal_replay_log",
                 minute_data_dir: str = "cache/minute_data"):
        self.signal_log_dir = Path(signal_log_dir)
        self.minute_data_dir = Path(minute_data_dir)
        self.trade_data = []

    def parse_signal_log(self, file_path: Path) -> List[Dict]:
        """신호 로그 파일 파싱"""
        trades = []

        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except:
            return trades

        # 날짜 추출
        date_match = re.search(r'signal_new2_replay_(\d{8})_', file_path.name)
        if not date_match:
            return trades
        trade_date = date_match.group(1)

        # 개별 종목 섹션 파싱
        stock_sections = re.findall(
            r'=== (\d{6}) - .*?체결 시뮬레이션:(.*?)(?:매수 못한 기회:|$)',
            content,
            re.DOTALL
        )

        for stock_code, simulation_text in stock_sections:
            trade_matches = re.findall(
                r'(\d{2}:\d{2})\s+매수.*?→.*?매도.*?\(([\+\-]\d+\.\d+)%\)',
                simulation_text
            )

            for trade_time, profit_str in trade_matches:
                profit_pct = float(profit_str)
                is_win = profit_pct > 0

                trades.append({
                    'date': trade_date,
                    'stock_code': stock_code,
                    'time': trade_time,
                    'is_win': is_win,
                    'profit_pct': profit_pct
                })

        return trades

    def load_all_trades(self, start_date: str = "20250901", end_date: str = "20251031"):
        """모든 거래 로그 로드"""
        print(f"\n[+] 거래 로그 로딩 중... ({start_date} ~ {end_date})")

        log_files = sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt"))

        for log_file in log_files:
            date_match = re.search(r'(\d{8})', log_file.name)
            if date_match:
                file_date = date_match.group(1)
                if start_date <= file_date <= end_date:
                    trades = self.parse_signal_log(log_file)
                    self.trade_data.extend(trades)

        print(f"[OK] 총 {len(self.trade_data)}개 거래 로드 완료")
        return len(self.trade_data)

    def load_minute_data(self, stock_code: str, date: str) -> pd.DataFrame:
        """분봉 데이터 로드 및 3분봉 변환"""
        possible_patterns = [
            f"{stock_code}_{date}.pkl",
            f"{stock_code}_3min_{date}.pkl",
            f"{stock_code}_{date}_3min.pkl",
        ]

        for pattern in possible_patterns:
            file_path = self.minute_data_dir / pattern
            if file_path.exists():
                try:
                    with open(file_path, 'rb') as f:
                        data = pickle.load(f)
                    if isinstance(data, pd.DataFrame) and len(data) > 0:
                        # 1분봉 데이터를 3분봉으로 변환
                        data_3min = TimeFrameConverter.convert_to_timeframe(data, 3)
                        if data_3min is not None and len(data_3min) > 0:
                            return data_3min
                        return None
                except Exception as e:
                    continue

        return None

    def analyze_4stage_pattern(self, data: pd.DataFrame, buy_time: str) -> Dict:
        """4단계 패턴 상세 분석

        1단계: 상승 (uptrend)
        2단계: 하락 (decline)
        3단계: 지지 (support)
        4단계: 돌파 (breakout)
        """
        if data is None or len(data) < 5:
            return None

        # buy_time 시점 찾기 (매수 신호 발생 시점)
        if 'datetime' in data.columns:
            data['datetime'] = pd.to_datetime(data['datetime'])
            # buy_time 형식: "10:45"
            buy_hour, buy_minute = map(int, buy_time.split(':'))

            # 해당 시간의 3분봉 찾기 (3분봉이므로 정확한 시간 매칭)
            for idx, row in data.iterrows():
                candle_time = pd.to_datetime(row['datetime'])
                if candle_time.hour == buy_hour and candle_time.minute == buy_minute:
                    buy_idx = idx
                    break
            else:
                # 정확한 시간을 찾지 못하면 가장 가까운 시간 사용
                target_time = pd.to_datetime(f"{data['datetime'].iloc[0].date()} {buy_time}")
                time_diffs = abs((data['datetime'] - target_time).dt.total_seconds())
                buy_idx = time_diffs.idxmin()
        else:
            buy_idx = len(data) - 1

        # 매수 시점까지의 데이터만 사용 (매수 시점 포함)
        data_until_buy = data.loc[:buy_idx].copy()

        if len(data_until_buy) < 5:
            return None

        try:
            # 4단계 패턴 분석 실행 (debug=True로 debug_info 포함)
            pattern_info = PullbackCandlePattern.analyze_support_pattern(data_until_buy, debug=True)

            if not pattern_info or not isinstance(pattern_info, dict):
                return None

            # debug_info에서 4단계 정보 추출
            debug_info = pattern_info.get('debug_info', {})

            # 기본 정보
            result = {
                'has_pattern': pattern_info.get('has_support_pattern', False),
                'confidence': pattern_info.get('confidence', 0.0),
                'stage_count': 0
            }

            # uptrend (상승 구간)
            if 'uptrend' in debug_info:
                uptrend = debug_info['uptrend']
                result['uptrend_exists'] = True
                result['stage_count'] += 1
                result['uptrend_start'] = uptrend['start_idx']
                result['uptrend_end'] = uptrend['end_idx']
                result['uptrend_candles'] = uptrend['end_idx'] - uptrend['start_idx'] + 1

                # 상승 구간 분석
                uptrend_data = data_until_buy.iloc[uptrend['start_idx']:uptrend['end_idx']+1]
                result['uptrend_price_gain'] = float(uptrend['price_gain'].strip('%')) if isinstance(uptrend.get('price_gain'), str) else 0
                result['uptrend_max_volume'] = float(uptrend['max_volume'].replace(',', '')) if isinstance(uptrend.get('max_volume'), str) else 0
                result['uptrend_avg_volume'] = uptrend_data['volume'].mean() if len(uptrend_data) > 0 else 0

                # 거래량 추세 (초반 vs 후반)
                if len(uptrend_data) >= 2:
                    mid = len(uptrend_data) // 2
                    first_half_vol = uptrend_data['volume'].iloc[:mid].mean()
                    second_half_vol = uptrend_data['volume'].iloc[mid:].mean()
                    result['uptrend_volume_trend'] = (second_half_vol - first_half_vol) / first_half_vol if first_half_vol > 0 else 0
                else:
                    result['uptrend_volume_trend'] = 0
            else:
                result['uptrend_exists'] = False

            # decline (하락 구간)
            if 'decline' in debug_info:
                decline = debug_info['decline']
                result['decline_exists'] = True
                result['stage_count'] += 1
                result['decline_start'] = decline['start_idx']
                result['decline_end'] = decline['end_idx']
                result['decline_candles'] = decline['candle_count']

                # 하락 구간 분석
                decline_data = data_until_buy.iloc[decline['start_idx']:decline['end_idx']+1]
                result['decline_price_drop'] = float(decline['decline_pct'].strip('%')) if isinstance(decline.get('decline_pct'), str) else 0
                result['decline_avg_volume'] = decline_data['volume'].mean() if len(decline_data) > 0 else 0
                result['decline_min_volume'] = decline_data['volume'].min() if len(decline_data) > 0 else 0

                if len(decline_data) > 0:
                    max_vol = decline_data['volume'].max()
                    min_vol = decline_data['volume'].min()
                    result['decline_volume_decrease_ratio'] = min_vol / max_vol if max_vol > 0 else 0
                else:
                    result['decline_volume_decrease_ratio'] = 0
            else:
                result['decline_exists'] = False

            # support (지지 구간)
            if 'support' in debug_info:
                support = debug_info['support']
                result['support_exists'] = True
                result['stage_count'] += 1
                result['support_start'] = support['start_idx']
                result['support_end'] = support['end_idx']
                result['support_candles'] = support['candle_count']

                # 지지 구간 분석
                support_data = data_until_buy.iloc[support['start_idx']:support['end_idx']+1]
                result['support_avg_volume_ratio'] = float(support['avg_volume_ratio'].strip('%')) if isinstance(support.get('avg_volume_ratio'), str) else 0
                result['support_price_volatility'] = float(support['price_volatility'].strip('%')) if isinstance(support.get('price_volatility'), str) else 0

                if len(support_data) > 0:
                    result['support_price_range'] = (support_data['high'].max() - support_data['low'].min()) / support_data['close'].mean() * 100
                    result['support_avg_volume'] = support_data['volume'].mean()
                    result['support_volume_stability'] = support_data['volume'].std() / support_data['volume'].mean() if support_data['volume'].mean() > 0 else 0
                    result['support_low_stability'] = support_data['low'].std() / support_data['low'].mean() * 100 if support_data['low'].mean() > 0 else 0
                else:
                    result['support_price_range'] = 0
                    result['support_avg_volume'] = 0
                    result['support_volume_stability'] = 0
                    result['support_low_stability'] = 0
            else:
                result['support_exists'] = False

            # breakout (돌파 구간)
            if 'breakout' in debug_info:
                breakout = debug_info['breakout']
                result['breakout_exists'] = True
                result['stage_count'] += 1
                result['breakout_idx'] = breakout['idx']

                # 돌파봉 특성
                result['breakout_body_increase'] = float(breakout['body_increase'].strip('%')) if isinstance(breakout.get('body_increase'), str) else 0
                result['breakout_volume_increase'] = float(breakout['volume_increase'].strip('%')) if isinstance(breakout.get('volume_increase'), str) else 0

                # 돌파봉 데이터
                breakout_candle = data_until_buy.iloc[breakout['idx']]
                result['breakout_body_pct'] = abs(breakout_candle['close'] - breakout_candle['open']) / breakout_candle['open'] * 100
                result['breakout_volume'] = breakout_candle['volume']

                # 돌파봉 vs 지지 구간 평균 거래량
                if 'support_avg_volume' in result and result['support_avg_volume'] > 0:
                    result['breakout_vs_support_volume'] = breakout_candle['volume'] / result['support_avg_volume']
                else:
                    result['breakout_vs_support_volume'] = 0
            else:
                result['breakout_exists'] = False

            # 전체 패턴 특성 계산
            if result['has_pattern']:
                # 하락 대비 상승 비율
                if 'uptrend_price_gain' in result and 'decline_price_drop' in result and result['uptrend_price_gain'] != 0:
                    result['decline_to_uptrend_ratio'] = abs(result['decline_price_drop']) / result['uptrend_price_gain']
                else:
                    result['decline_to_uptrend_ratio'] = 0

                # 상승 거래량 대비 지지 거래량
                if 'uptrend_avg_volume' in result and 'support_avg_volume' in result and result['uptrend_avg_volume'] > 0:
                    result['support_to_uptrend_volume'] = result['support_avg_volume'] / result['uptrend_avg_volume']
                else:
                    result['support_to_uptrend_volume'] = 0

            return result

        except Exception as e:
            print(f"  [WARNING] 4단계 패턴 분석 오류: {e}")
            import traceback
            traceback.print_exc()
            return None

    def analyze_differences(self):
        """승패 거래의 4단계 패턴 차이 분석"""
        print("\n" + "="*80)
        print("[*] 4단계 패턴 승패 비교 분석")
        print("="*80)

        df = pd.DataFrame(self.trade_data)

        print(f"\n[*] 기본 통계:")
        print(f"  총 거래: {len(df)}개")
        wins = df[df['is_win'] == True]
        losses = df[df['is_win'] == False]
        print(f"  승리: {len(wins)}개 ({len(wins)/len(df)*100:.1f}%)")
        print(f"  패배: {len(losses)}개 ({len(losses)/len(df)*100:.1f}%)")

        # 4단계 패턴 분석
        print(f"\n[*] 4단계 패턴 분석 중...")

        win_patterns = []
        loss_patterns = []

        total_trades = len(df)
        debug_count = 0
        for idx, trade in df.iterrows():
            if (idx + 1) % 50 == 0:
                print(f"  진행률: {idx+1}/{total_trades} ({(idx+1)/total_trades*100:.1f}%)")

            data = self.load_minute_data(trade['stock_code'], trade['date'])
            if data is None:
                if debug_count < 3:
                    print(f"  [DEBUG] No data for {trade['stock_code']} on {trade['date']}")
                    debug_count += 1
                continue

            pattern = self.analyze_4stage_pattern(data, trade['time'])
            if not pattern:
                if debug_count < 3:
                    print(f"  [DEBUG] No pattern for {trade['stock_code']} on {trade['date']} at {trade['time']}")
                    print(f"           Data length: {len(data)}, Win: {trade['is_win']}")
                    debug_count += 1
                continue

            # 첫 3개 패턴 디버그
            if debug_count < 3:
                print(f"  [DEBUG] Found pattern for {trade['stock_code']} on {trade['date']} at {trade['time']}")
                print(f"           has_pattern={pattern.get('has_pattern')}, confidence={pattern.get('confidence')}")
                print(f"           stage_count={pattern.get('stage_count')}")
                debug_count += 1

            pattern['profit_pct'] = trade['profit_pct']

            if trade['is_win']:
                win_patterns.append(pattern)
            else:
                loss_patterns.append(pattern)

        print(f"[OK] 수집 완료: 승리 {len(win_patterns)}개, 패배 {len(loss_patterns)}개")

        # 패턴 비교
        if len(win_patterns) > 0 and len(loss_patterns) > 0:
            self._compare_patterns(win_patterns, loss_patterns)

        # 결과 저장
        self._save_results(win_patterns, loss_patterns)

    def _compare_patterns(self, win_patterns: List[Dict], loss_patterns: List[Dict]):
        """패턴 비교 분석"""
        print("\n" + "="*80)
        print("[*] 4단계 패턴 비교")
        print("="*80)

        win_df = pd.DataFrame(win_patterns)
        loss_df = pd.DataFrame(loss_patterns)

        # 4단계 완성도 비교
        print(f"\n[*] 4단계 패턴 완성도:")
        win_has_pattern = win_df['has_pattern'].sum() / len(win_df) * 100
        loss_has_pattern = loss_df['has_pattern'].sum() / len(loss_df) * 100
        print(f"  승리: {win_has_pattern:.1f}% ({win_df['has_pattern'].sum()}개/{len(win_df)}개)")
        print(f"  패배: {loss_has_pattern:.1f}% ({loss_df['has_pattern'].sum()}개/{len(loss_df)}개)")
        print(f"  차이: {win_has_pattern - loss_has_pattern:+.1f}%p")

        # 단계별 존재 비율
        print(f"\n[*] 단계별 존재 비율:")
        stages = ['uptrend', 'decline', 'support', 'breakout']
        for stage in stages:
            col = f'{stage}_exists'
            if col in win_df.columns and col in loss_df.columns:
                win_pct = win_df[col].sum() / len(win_df) * 100
                loss_pct = loss_df[col].sum() / len(loss_df) * 100
                print(f"  {stage:10s}: 승리 {win_pct:5.1f}% / 패배 {loss_pct:5.1f}% (차이: {win_pct-loss_pct:+.1f}%p)")

        # 수치형 특징 비교
        numeric_features = [
            'uptrend_price_gain', 'uptrend_avg_volume', 'uptrend_volume_trend', 'uptrend_max_volume',
            'decline_price_drop', 'decline_avg_volume', 'decline_volume_decrease_ratio', 'decline_candles',
            'support_price_range', 'support_avg_volume', 'support_volume_stability', 'support_low_stability',
            'support_avg_volume_ratio', 'support_price_volatility', 'support_candles',
            'breakout_body_pct', 'breakout_volume', 'breakout_vs_support_volume',
            'breakout_body_increase', 'breakout_volume_increase',
            'decline_to_uptrend_ratio', 'support_to_uptrend_volume',
            'confidence', 'stage_count'
        ]

        print(f"\n{'특징':<35} {'승리 평균':>12} {'패배 평균':>12} {'차이':>12} {'유의성':>8}")
        print("-" * 85)

        significant_features = []

        for feature in numeric_features:
            if feature in win_df.columns and feature in loss_df.columns:
                win_mean = win_df[feature].dropna().mean()
                loss_mean = loss_df[feature].dropna().mean()
                diff = win_mean - loss_mean

                # 표준편차 기반 유의성
                win_std = win_df[feature].dropna().std()
                loss_std = loss_df[feature].dropna().std()

                is_significant = abs(diff) > (win_std + loss_std) * 0.15
                significance = "[*]" if is_significant else ""

                print(f"{feature:<35} {win_mean:>12.2f} {loss_mean:>12.2f} {diff:>12.2f} {significance:>8}")

                if is_significant:
                    significant_features.append({
                        'feature': feature,
                        'win_mean': win_mean,
                        'loss_mean': loss_mean,
                        'diff': diff
                    })

        # 유의미한 특징 요약
        if significant_features:
            print("\n" + "="*80)
            print("[*] 유의미한 차이를 보이는 특징 (중요도 순)")
            print("="*80)

            significant_features.sort(key=lambda x: abs(x['diff']), reverse=True)

            for i, feat in enumerate(significant_features[:10], 1):
                direction = "높음" if feat['diff'] > 0 else "낮음"
                print(f"\n{i}. {feat['feature']}")
                print(f"   승리: {feat['win_mean']:.2f} / 패배: {feat['loss_mean']:.2f}")
                print(f"   → 승리 종목이 {abs(feat['diff']):.2f} {direction}")

    def _save_results(self, win_patterns: List[Dict], loss_patterns: List[Dict]):
        """결과 저장"""
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        results = {
            'win_patterns': win_patterns,
            'loss_patterns': loss_patterns,
            'win_summary': pd.DataFrame(win_patterns).describe().to_dict() if win_patterns else {},
            'loss_summary': pd.DataFrame(loss_patterns).describe().to_dict() if loss_patterns else {},
            'timestamp': timestamp
        }

        json_path = f"4stage_pattern_analysis_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[*] 분석 결과 저장: {json_path}")


def main():
    """메인 실행"""
    analyzer = FourStagePatternAnalyzer()

    # 거래 로그 로드
    analyzer.load_all_trades(start_date="20250901", end_date="20251031")

    if len(analyzer.trade_data) == 0:
        print("[!] 거래 데이터가 없습니다.")
        return

    # 4단계 패턴 분석
    analyzer.analyze_differences()

    print("\n" + "="*80)
    print("[OK] 분석 완료!")
    print("="*80)


if __name__ == "__main__":
    main()
