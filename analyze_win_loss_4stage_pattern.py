#!/usr/bin/env python3
"""
4단계 패턴 승패 분석 스크립트 (개선 버전)

매매당 4단계 조합의 차이점을 상세히 분석:
- 거래량 패턴 (각 구간별 절대값 + 비율)
- 봉의 크기 패턴 (몸통, 꼬리, 전체 크기)
- 봉의 흐름 패턴 (연속성, 변화율, 추세)
- 시간대별 특성
- 종합 패턴 점수
"""

import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any
import sys


class FourStagePatternAnalyzer:
    """4단계 패턴 승패 분석기"""

    def __init__(self, log_dir: str = "pattern_data_log"):
        self.log_dir = Path(log_dir)
        self.patterns = []
        self.wins = []
        self.losses = []

    def load_data(self, start_date: str = None, end_date: str = None):
        """기간별 데이터 로드"""

        if start_date and end_date:
            # 날짜 범위 지정
            dates = pd.date_range(start_date, end_date, freq='D')
            date_strs = [d.strftime('%Y%m%d') for d in dates]
        else:
            # 모든 파일 로드
            date_strs = [f.stem.replace('pattern_data_', '') for f in self.log_dir.glob('pattern_data_*.jsonl')]

        print(f"\n{'='*80}")
        print(f"[데이터 로딩]")
        print(f"{'='*80}")

        for date_str in sorted(date_strs):
            log_file = self.log_dir / f"pattern_data_{date_str}.jsonl"
            if log_file.exists():
                count = self._load_single_file(log_file)
                print(f"  {date_str}: {count}개 패턴")

        print(f"\n총 로드: {len(self.patterns)}개 패턴")

        # 승패 분류
        self._classify_win_loss()

    def _load_single_file(self, log_file: Path) -> int:
        """단일 파일 로드"""
        count = 0
        with open(log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        pattern = json.loads(line)
                        self.patterns.append(pattern)
                        count += 1
                    except json.JSONDecodeError:
                        continue
        return count

    def _classify_win_loss(self):
        """승패 분류"""
        for pattern in self.patterns:
            trade_result = pattern.get('trade_result')
            if trade_result and trade_result.get('trade_executed'):
                profit_rate = trade_result.get('profit_rate', 0)
                if profit_rate > 0:
                    self.wins.append(pattern)
                else:
                    self.losses.append(pattern)

        print(f"\n매매 실행: {len(self.wins) + len(self.losses)}개")
        print(f"  승리: {len(self.wins)}개")
        print(f"  패배: {len(self.losses)}개")
        if len(self.wins) + len(self.losses) > 0:
            win_rate = len(self.wins) / (len(self.wins) + len(self.losses)) * 100
            print(f"  승률: {win_rate:.1f}%")

    def analyze_volume_patterns(self):
        """거래량 패턴 분석"""
        print(f"\n{'='*80}")
        print(f"[1. 거래량 패턴 분석]")
        print(f"{'='*80}")

        # 1-1. 상승구간 거래량
        print(f"\n[1-1. 상승구간 거래량]")
        self._compare_metric_advanced(
            '1_uptrend', 'max_volume', '최대 거래량',
            analysis_type='distribution'
        )
        self._compare_metric_advanced(
            '1_uptrend', 'volume_avg', '평균 거래량',
            analysis_type='distribution'
        )

        # 1-2. 하락구간 거래량 비율
        print(f"\n[1-2. 하락구간 거래량 (기준 대비)]")
        self._compare_metric_advanced(
            '2_decline', 'avg_volume_ratio', '평균 거래량 비율',
            multiplier=100, analysis_type='distribution'
        )

        # 1-3. 지지구간 거래량 비율
        print(f"\n[1-3. 지지구간 거래량 (기준 대비)]")
        self._compare_metric_advanced(
            '3_support', 'avg_volume_ratio', '평균 거래량 비율',
            multiplier=100, analysis_type='distribution'
        )

        # 1-4. 돌파양봉 거래량
        print(f"\n[1-4. 돌파양봉 거래량]")
        self._compare_metric_advanced(
            '4_breakout', 'volume', '거래량',
            analysis_type='distribution'
        )
        self._compare_metric_advanced(
            '4_breakout', 'volume_ratio_vs_prev', '직전봉 대비 비율',
            multiplier=100, analysis_type='distribution'
        )

    def analyze_candle_size_patterns(self):
        """봉 크기 패턴 분석"""
        print(f"\n{'='*80}")
        print(f"[2. 봉 크기 패턴 분석]")
        print(f"{'='*80}")

        # 2-1. 상승구간 봉 크기
        print(f"\n[2-1. 상승구간 평균 봉 크기]")
        self._analyze_candle_sizes('1_uptrend')

        # 2-2. 하락구간 봉 크기
        print(f"\n[2-2. 하락구간 평균 봉 크기]")
        self._analyze_candle_sizes('2_decline')

        # 2-3. 지지구간 봉 크기
        print(f"\n[2-3. 지지구간 평균 봉 크기]")
        self._analyze_candle_sizes('3_support')

        # 2-4. 돌파양봉 크기
        print(f"\n[2-4. 돌파양봉 크기]")
        self._compare_metric_advanced(
            '4_breakout', 'body_size', '몸통 크기',
            analysis_type='distribution'
        )
        self._compare_metric_advanced(
            '4_breakout', 'body_increase_vs_support', '지지구간 대비 몸통 증가율',
            multiplier=100, analysis_type='distribution'
        )

    def analyze_flow_patterns(self):
        """봉 흐름 패턴 분석"""
        print(f"\n{'='*80}")
        print(f"[3. 봉 흐름 패턴 분석]")
        print(f"{'='*80}")

        # 3-1. 각 구간의 캔들 개수
        print(f"\n[3-1. 구간별 캔들 개수]")
        for stage_key, stage_name in [
            ('1_uptrend', '상승구간'),
            ('2_decline', '하락구간'),
            ('3_support', '지지구간')
        ]:
            self._compare_metric_advanced(
                stage_key, 'candle_count', f'{stage_name} 캔들 개수',
                analysis_type='distribution'
            )

        # 3-2. 상승/하락률
        print(f"\n[3-2. 가격 변화율]")
        self._compare_metric_advanced(
            '1_uptrend', 'price_gain', '상승률',
            multiplier=100, analysis_type='distribution'
        )
        self._compare_metric_advanced(
            '2_decline', 'decline_pct', '하락률',
            multiplier=100, analysis_type='distribution'
        )

        # 3-3. 지지구간 가격 변동성
        print(f"\n[3-3. 지지구간 안정성]")
        self._compare_metric_advanced(
            '3_support', 'price_volatility', '가격 변동성',
            multiplier=100, analysis_type='distribution'
        )

    def analyze_time_patterns(self):
        """시간대별 패턴 분석"""
        print(f"\n{'='*80}")
        print(f"[4. 시간대별 패턴 분석]")
        print(f"{'='*80}")

        # 시간대별 승패 분류
        time_groups = {
            '09시대': [],
            '10시대': [],
            '11시대': [],
            '12시대': [],
            '13시대': [],
            '14시대': []
        }

        for pattern_list, result_type in [(self.wins, 'win'), (self.losses, 'loss')]:
            for pattern in pattern_list:
                timestamp = pattern.get('timestamp', '')
                if timestamp:
                    hour = int(timestamp.split(' ')[1].split(':')[0])
                    time_key = f'{hour:02d}시대'
                    if time_key in time_groups:
                        time_groups[time_key].append(result_type)

        # 시간대별 통계
        print(f"\n{'시간대':^10} | {'총건수':^8} | {'승':^6} | {'패':^6} | {'승률':^8}")
        print(f"{'-'*60}")

        for time_key in sorted(time_groups.keys()):
            results = time_groups[time_key]
            total = len(results)
            wins = results.count('win')
            losses = results.count('loss')
            win_rate = wins / total * 100 if total > 0 else 0

            print(f"{time_key:^10} | {total:^8d} | {wins:^6d} | {losses:^6d} | {win_rate:^7.1f}%")

    def find_winning_patterns(self):
        """승리 패턴의 공통 특성 찾기"""
        print(f"\n{'='*80}")
        print(f"[5. 승리 패턴의 공통 특성]")
        print(f"{'='*80}")

        if not self.wins:
            print("  승리 데이터 없음")
            return

        # 고승률 조건 찾기
        conditions = []

        # 조건 1: 상승구간 적정 범위 (3-5%)
        uptrend_gains = self._extract_values(self.wins, '1_uptrend', 'price_gain')
        optimal_gains = [g for g in uptrend_gains if 0.03 <= g <= 0.05]
        if uptrend_gains and len(optimal_gains) / len(uptrend_gains) > 0.5:
            conditions.append("[O] 상승률 3-5% 구간에서 승률 높음")

        # 조건 2: 하락구간 낮은 거래량 (25% 이하)
        decline_vols = self._extract_values(self.wins, '2_decline', 'avg_volume_ratio')
        low_vol_declines = [v for v in decline_vols if v <= 0.25]
        if decline_vols and len(low_vol_declines) / len(decline_vols) > 0.6:
            conditions.append("[O] 하락구간 거래량 25% 이하에서 승률 높음")

        # 조건 3: 지지구간 안정성 (변동성 1.5% 이하)
        support_vols = self._extract_values(self.wins, '3_support', 'price_volatility')
        stable_supports = [v for v in support_vols if v <= 0.015]
        if support_vols and len(stable_supports) / len(support_vols) > 0.5:
            conditions.append("[O] 지지구간 변동성 1.5% 이하에서 승률 높음")

        # 조건 4: 돌파양봉 적정 크기 (30-60% 증가)
        breakout_increases = self._extract_values(self.wins, '4_breakout', 'body_increase_vs_support')
        optimal_increases = [b for b in breakout_increases if 0.3 <= b <= 0.6]
        if breakout_increases and len(optimal_increases) / len(breakout_increases) > 0.5:
            conditions.append("[O] 돌파양봉 몸통 30-60% 증가에서 승률 높음")

        if conditions:
            print("\n발견된 승리 패턴:")
            for i, cond in enumerate(conditions, 1):
                print(f"  {i}. {cond}")
        else:
            print("  명확한 공통 패턴을 찾지 못했습니다.")

    def find_losing_patterns(self):
        """패배 패턴의 공통 특성 찾기"""
        print(f"\n{'='*80}")
        print(f"[6. 패배 패턴의 공통 특성 (차단 조건)]")
        print(f"{'='*80}")

        if not self.losses:
            print("  패배 데이터 없음")
            return

        # 위험 신호 찾기
        warnings = []

        # 위험 1: 과도한 상승 (7% 이상)
        uptrend_gains = self._extract_values(self.losses, '1_uptrend', 'price_gain')
        excessive_gains = [g for g in uptrend_gains if g >= 0.07]
        if uptrend_gains and len(excessive_gains) / len(uptrend_gains) > 0.3:
            warnings.append("[!] 상승률 7% 이상 과열 구간에서 패배 많음")

        # 위험 2: 하락구간 높은 거래량 (35% 이상)
        decline_vols = self._extract_values(self.losses, '2_decline', 'avg_volume_ratio')
        high_vol_declines = [v for v in decline_vols if v >= 0.35]
        if decline_vols and len(high_vol_declines) / len(decline_vols) > 0.3:
            warnings.append("[!] 하락구간 거래량 35% 이상에서 패배 많음 (악성매물)")

        # 위험 3: 지지구간 불안정 (변동성 2.5% 이상)
        support_vols = self._extract_values(self.losses, '3_support', 'price_volatility')
        unstable_supports = [v for v in support_vols if v >= 0.025]
        if support_vols and len(unstable_supports) / len(support_vols) > 0.3:
            warnings.append("[!] 지지구간 변동성 2.5% 이상에서 패배 많음")

        # 위험 4: 돌파양봉 과도한 급등 (80% 이상)
        breakout_increases = self._extract_values(self.losses, '4_breakout', 'body_increase_vs_support')
        excessive_increases = [b for b in breakout_increases if b >= 0.8]
        if breakout_increases and len(excessive_increases) / len(breakout_increases) > 0.3:
            warnings.append("[!] 돌파양봉 80% 이상 급등에서 패배 많음 (과열)")

        if warnings:
            print("\n발견된 패배 패턴 (차단 권장):")
            for i, warn in enumerate(warnings, 1):
                print(f"  {i}. {warn}")
        else:
            print("  명확한 위험 패턴을 찾지 못했습니다.")

    def export_detailed_csv(self, output_file: str = "4stage_pattern_detailed_analysis.csv"):
        """상세 분석 결과를 CSV로 내보내기"""
        print(f"\n{'='*80}")
        print(f"[7. 상세 데이터 내보내기]")
        print(f"{'='*80}")

        records = []
        for pattern in self.patterns:
            trade_result = pattern.get('trade_result') or {}
            if not trade_result.get('trade_executed'):
                continue

            stages = pattern.get('pattern_stages', {})

            record = {
                'pattern_id': pattern['pattern_id'],
                'timestamp': pattern['timestamp'],
                'stock_code': pattern['stock_code'],
                'signal_type': pattern['signal_info']['signal_type'],
                'confidence': pattern['signal_info']['confidence'],
                'profit_rate': trade_result.get('profit_rate', 0),
                'result': 'WIN' if trade_result.get('profit_rate', 0) > 0 else 'LOSS',

                # 상승구간
                'uptrend_candles': stages.get('1_uptrend', {}).get('candle_count'),
                'uptrend_gain_pct': self._parse_pct(stages.get('1_uptrend', {}).get('price_gain')),
                'uptrend_max_vol': stages.get('1_uptrend', {}).get('max_volume'),
                'uptrend_avg_vol': stages.get('1_uptrend', {}).get('volume_avg'),

                # 하락구간
                'decline_candles': stages.get('2_decline', {}).get('candle_count'),
                'decline_pct': self._parse_pct(stages.get('2_decline', {}).get('decline_pct')),
                'decline_vol_ratio': self._parse_pct(stages.get('2_decline', {}).get('avg_volume_ratio')),

                # 지지구간
                'support_candles': stages.get('3_support', {}).get('candle_count'),
                'support_volatility': self._parse_pct(stages.get('3_support', {}).get('price_volatility')),
                'support_vol_ratio': self._parse_pct(stages.get('3_support', {}).get('avg_volume_ratio')),

                # 돌파양봉
                'breakout_body': stages.get('4_breakout', {}).get('body_size'),
                'breakout_volume': stages.get('4_breakout', {}).get('volume'),
                'breakout_vol_vs_prev': stages.get('4_breakout', {}).get('volume_ratio_vs_prev'),
                'breakout_body_increase': stages.get('4_breakout', {}).get('body_increase_vs_support'),
            }

            records.append(record)

        df = pd.DataFrame(records)
        df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"  파일 저장: {output_file}")
        print(f"  총 레코드: {len(df)}개")

        return df

    def _compare_metric_advanced(self, stage_key, metric_key, metric_name, multiplier=1, analysis_type='simple'):
        """고급 지표 비교 (분포 분석 포함)"""

        win_values = self._extract_values(self.wins, stage_key, metric_key)
        loss_values = self._extract_values(self.losses, stage_key, metric_key)

        if not win_values and not loss_values:
            return

        win_values = [v * multiplier for v in win_values]
        loss_values = [v * multiplier for v in loss_values]

        # 기본 통계
        win_avg = np.mean(win_values) if win_values else 0
        loss_avg = np.mean(loss_values) if loss_values else 0

        print(f"\n  {metric_name}:")
        print(f"    승리 평균: {win_avg:.2f}")
        print(f"    패배 평균: {loss_avg:.2f}")
        print(f"    차이: {win_avg - loss_avg:+.2f}")

        if analysis_type == 'distribution':
            # 분포 분석 (사분위수)
            if win_values:
                win_q1, win_median, win_q3 = np.percentile(win_values, [25, 50, 75])
                print(f"    승리 분포: Q1={win_q1:.2f}, 중앙={win_median:.2f}, Q3={win_q3:.2f}")

            if loss_values:
                loss_q1, loss_median, loss_q3 = np.percentile(loss_values, [25, 50, 75])
                print(f"    패배 분포: Q1={loss_q1:.2f}, 중앙={loss_median:.2f}, Q3={loss_q3:.2f}")

    def _analyze_candle_sizes(self, stage_key):
        """캔들 크기 분석 (몸통, 꼬리, 전체)"""

        win_candles = self._extract_candles(self.wins, stage_key)
        loss_candles = self._extract_candles(self.losses, stage_key)

        if not win_candles and not loss_candles:
            print("  데이터 없음")
            return

        # 평균 몸통 크기
        win_avg_body = self._calc_avg_body_size(win_candles) if win_candles else 0
        loss_avg_body = self._calc_avg_body_size(loss_candles) if loss_candles else 0

        # 평균 전체 크기 (고가-저가)
        win_avg_range = self._calc_avg_range(win_candles) if win_candles else 0
        loss_avg_range = self._calc_avg_range(loss_candles) if loss_candles else 0

        print(f"  평균 몸통 크기:")
        print(f"    승리: {win_avg_body:.2f}")
        print(f"    패배: {loss_avg_body:.2f}")
        print(f"    차이: {win_avg_body - loss_avg_body:+.2f}")

        print(f"  평균 전체 크기 (고가-저가):")
        print(f"    승리: {win_avg_range:.2f}")
        print(f"    패배: {loss_avg_range:.2f}")
        print(f"    차이: {win_avg_range - loss_avg_range:+.2f}")

    def _extract_values(self, patterns, stage_key, metric_key):
        """패턴에서 특정 지표 값 추출"""
        values = []
        for pattern in patterns:
            stage = pattern.get('pattern_stages', {}).get(stage_key, {})
            value = stage.get(metric_key)
            parsed = self._parse_value(value)
            if parsed is not None:
                values.append(parsed)
        return values

    def _extract_candles(self, patterns, stage_key):
        """패턴에서 캔들 데이터 추출"""
        all_candles = []
        for pattern in patterns:
            stage = pattern.get('pattern_stages', {}).get(stage_key, {})
            candles = stage.get('candles', [])
            all_candles.extend(candles)
        return all_candles

    def _calc_avg_body_size(self, candles):
        """평균 몸통 크기 계산"""
        bodies = [abs(c['close'] - c['open']) for c in candles if c.get('close') and c.get('open')]
        return np.mean(bodies) if bodies else 0

    def _calc_avg_range(self, candles):
        """평균 전체 크기 (고가-저가) 계산"""
        ranges = [c['high'] - c['low'] for c in candles if c.get('high') and c.get('low')]
        return np.mean(ranges) if ranges else 0

    def _parse_value(self, val):
        """문자열 값을 숫자로 변환"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            val = val.replace('%', '').replace(',', '').strip()
            try:
                return float(val)
            except ValueError:
                return None
        return None

    def _parse_pct(self, val):
        """퍼센트 문자열을 float로 변환"""
        parsed = self._parse_value(val)
        if parsed is not None:
            # 이미 % 형식으로 저장되어 있으면 그대로, 아니면 100 곱하기
            if isinstance(val, str) and '%' in val:
                return parsed
            return parsed * 100
        return None


def main():
    """메인 실행"""

    analyzer = FourStagePatternAnalyzer()

    # 날짜 범위 인자 처리
    if len(sys.argv) >= 3:
        start_date = sys.argv[1]
        end_date = sys.argv[2]
        print(f"[분석 기간] {start_date} ~ {end_date}")
        analyzer.load_data(start_date, end_date)
    else:
        print(f"[분석 기간] 전체")
        analyzer.load_data()

    if not analyzer.wins and not analyzer.losses:
        print("\n[오류] 분석할 매매 데이터가 없습니다.")
        print("  - pattern_data_log/*.jsonl 파일을 확인하세요")
        print("  - trade_result 필드가 있는지 확인하세요")
        return

    # 분석 실행
    analyzer.analyze_volume_patterns()
    analyzer.analyze_candle_size_patterns()
    analyzer.analyze_flow_patterns()
    analyzer.analyze_time_patterns()
    analyzer.find_winning_patterns()
    analyzer.find_losing_patterns()

    # CSV 내보내기
    analyzer.export_detailed_csv()

    print(f"\n{'='*80}")
    print(f"[분석 완료]")
    print(f"{'='*80}")
    print("다음 단계:")
    print("  1. CSV 파일을 엑셀로 열어서 피벗 테이블로 심층 분석")
    print("  2. 승리 패턴의 조건을 코드에 반영")
    print("  3. 패배 패턴의 차단 조건 추가")
    print(f"{'='*80}\n")


if __name__ == "__main__":
    main()