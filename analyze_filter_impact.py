"""
필터별 효과 측정 스크립트
- 각 필터가 차단하는 거래의 승률/수익 분석
- 총 수익 변화 시뮬레이션
- 승률 vs 거래 기회 vs 총 수익의 최적 밸런스 찾기
"""

import pandas as pd
import numpy as np
from pathlib import Path
import json
from typing import Dict, List, Tuple
from analyze_win_loss_pattern import WinLossAnalyzer


class FilterImpactAnalyzer:
    """필터 영향도 분석기"""

    def __init__(self, analyzer: WinLossAnalyzer):
        self.analyzer = analyzer
        self.trade_features = []

    def collect_all_features(self, morning_only=True):
        """모든 거래의 특징 수집"""
        print("\n[*] 모든 거래의 특징 수집 중...")

        df = pd.DataFrame(self.analyzer.trade_data)

        if morning_only:
            df['hour'] = df['time'].str[:2].astype(int)
            df = df[df['hour'] < 12].copy()
            print(f"    12시 이전 거래: {len(df)}개")

        total_trades = len(df)
        for idx, trade in df.iterrows():
            if (idx + 1) % 50 == 0:
                print(f"    진행률: {idx+1}/{total_trades} ({(idx+1)/total_trades*100:.1f}%)")

            data = self.analyzer.load_minute_data(trade['stock_code'], trade['date'])
            if data is None:
                continue

            features = self.analyzer.calculate_technical_features(data, trade['time'])
            if not features:
                continue

            # 거래 정보 추가
            features['is_win'] = trade['is_win']
            features['profit_pct'] = trade['profit_pct']
            features['confidence'] = trade['confidence']
            features['stock_code'] = trade['stock_code']
            features['date'] = trade['date']
            features['time'] = trade['time']

            self.trade_features.append(features)

        print(f"[OK] 수집 완료: {len(self.trade_features)}개")
        return pd.DataFrame(self.trade_features)

    def analyze_filter(self, df: pd.DataFrame, filter_name: str,
                      filter_condition: callable) -> Dict:
        """단일 필터의 영향 분석

        Args:
            df: 전체 거래 DataFrame
            filter_name: 필터 이름
            filter_condition: 필터 조건 함수 (True면 차단)

        Returns:
            필터 영향 분석 결과
        """
        print(f"\n{'='*80}")
        print(f"[*] {filter_name} 분석")
        print(f"{'='*80}")

        # 필터 적용
        df['blocked'] = df.apply(filter_condition, axis=1)

        blocked = df[df['blocked'] == True]
        passed = df[df['blocked'] == False]

        # 기본 통계
        print(f"\n[기본 통계]")
        print(f"  전체 거래: {len(df)}개")
        print(f"  차단된 거래: {len(blocked)}개 ({len(blocked)/len(df)*100:.1f}%)")
        print(f"  통과한 거래: {len(passed)}개 ({len(passed)/len(df)*100:.1f}%)")

        # 차단된 거래 분석
        if len(blocked) > 0:
            blocked_wins = blocked[blocked['is_win'] == True]
            blocked_win_rate = len(blocked_wins) / len(blocked) * 100
            blocked_avg_profit = blocked['profit_pct'].mean()

            print(f"\n[차단된 거래 분석]")
            print(f"  승률: {blocked_win_rate:.1f}% ({len(blocked_wins)}승 {len(blocked)-len(blocked_wins)}패)")
            print(f"  평균 수익률: {blocked_avg_profit:+.2f}%")

            if blocked_win_rate < 50:
                print(f"  -> 차단된 거래가 손실 구간! (좋은 필터)")
            elif blocked_win_rate > 55:
                print(f"  -> 차단된 거래가 수익 구간! (나쁜 필터)")
            else:
                print(f"  -> 차단된 거래가 손익분기점")

        # 통과한 거래 분석
        if len(passed) > 0:
            passed_wins = passed[passed['is_win'] == True]
            passed_win_rate = len(passed_wins) / len(passed) * 100
            passed_avg_profit = passed['profit_pct'].mean()

            print(f"\n[통과한 거래 분석]")
            print(f"  승률: {passed_win_rate:.1f}% ({len(passed_wins)}승 {len(passed)-len(passed_wins)}패)")
            print(f"  평균 수익률: {passed_avg_profit:+.2f}%")

        # 총 수익 비교 (거래당 평균 기준)
        original_win_rate = len(df[df['is_win']]) / len(df) * 100
        original_avg_profit = df['profit_pct'].mean()

        print(f"\n[총 수익 비교]")
        print(f"  원래 승률: {original_win_rate:.1f}%")
        print(f"  원래 평균 수익: {original_avg_profit:+.2f}%")

        if len(passed) > 0:
            print(f"  필터 후 승률: {passed_win_rate:.1f}% (변화: {passed_win_rate-original_win_rate:+.1f}%p)")
            print(f"  필터 후 평균 수익: {passed_avg_profit:+.2f}% (변화: {passed_avg_profit-original_avg_profit:+.2f}%p)")

            # 총 수익 시뮬레이션 (100만원 기준)
            capital = 1000000
            original_total = capital * len(df) * (original_avg_profit / 100)
            filtered_total = capital * len(passed) * (passed_avg_profit / 100)

            print(f"\n[총 수익 시뮬레이션 (100만원 x 각 거래)]")
            print(f"  원래 총 수익: {original_total:,.0f}원 ({len(df)}개 거래)")
            print(f"  필터 후 총 수익: {filtered_total:,.0f}원 ({len(passed)}개 거래)")
            print(f"  총 수익 변화: {filtered_total-original_total:+,.0f}원 ({(filtered_total-original_total)/original_total*100:+.1f}%)")

            if filtered_total > original_total:
                print(f"  -> 총 수익 증가! (좋은 필터)")
            else:
                print(f"  -> 총 수익 감소! (필터 재검토 필요)")

        return {
            'filter_name': filter_name,
            'total_trades': len(df),
            'blocked_count': len(blocked),
            'blocked_win_rate': blocked_win_rate if len(blocked) > 0 else None,
            'blocked_avg_profit': blocked_avg_profit if len(blocked) > 0 else None,
            'passed_count': len(passed),
            'passed_win_rate': passed_win_rate if len(passed) > 0 else None,
            'passed_avg_profit': passed_avg_profit if len(passed) > 0 else None,
            'original_win_rate': original_win_rate,
            'original_avg_profit': original_avg_profit,
            'win_rate_change': passed_win_rate - original_win_rate if len(passed) > 0 else None,
            'avg_profit_change': passed_avg_profit - original_avg_profit if len(passed) > 0 else None,
            'total_profit_change_pct': ((filtered_total - original_total) / original_total * 100) if len(passed) > 0 else None
        }

    def test_all_filters(self, df: pd.DataFrame):
        """모든 후보 필터 테스트"""
        results = []

        # 필터 1: 돌파봉 몸통 크기 제한
        print("\n" + "="*80)
        print("[1/6] 돌파봉 몸통 크기 제한 필터")
        print("="*80)

        for threshold in [0.4, 0.5, 0.6]:
            result = self.analyze_filter(
                df,
                f"돌파봉 몸통 >= {threshold}% 차단",
                lambda row: row.get('breakout_body_pct', 0) >= threshold if pd.notna(row.get('breakout_body_pct')) else False
            )
            results.append(result)

        # 필터 2: 눌림목 거래량 안정성
        print("\n" + "="*80)
        print("[2/6] 눌림목 거래량 안정성 필터")
        print("="*80)

        for threshold in [25000, 30000, 35000]:
            result = self.analyze_filter(
                df,
                f"눌림목 거래량 표준편차 > {threshold} 차단",
                lambda row, t=threshold: row.get('pre_volume_std', 0) > t if pd.notna(row.get('pre_volume_std')) else False
            )
            results.append(result)

        # 필터 3: 돌파봉 거래량 검증
        print("\n" + "="*80)
        print("[3/6] 돌파봉 거래량 검증 필터")
        print("="*80)

        for threshold in [1.2, 1.3, 1.4]:
            result = self.analyze_filter(
                df,
                f"돌파봉 거래량 < {threshold}배 차단",
                lambda row, t=threshold: row.get('breakout_volume_vs_prev', 0) < t if pd.notna(row.get('breakout_volume_vs_prev')) else False
            )
            results.append(result)

        # 필터 4: RSI 모멘텀
        print("\n" + "="*80)
        print("[4/6] RSI 모멘텀 필터")
        print("="*80)

        for threshold in [45, 50, 55]:
            result = self.analyze_filter(
                df,
                f"RSI < {threshold} 차단",
                lambda row, t=threshold: row.get('rsi', 100) < t if pd.notna(row.get('rsi')) else False
            )
            results.append(result)

        # 필터 5: 상승 구간 거래량 추세
        print("\n" + "="*80)
        print("[5/6] 상승 구간 거래량 추세 필터")
        print("="*80)

        for threshold in [-0.05, -0.10, -0.15]:
            result = self.analyze_filter(
                df,
                f"상승 구간 거래량 추세 > {threshold} 차단",
                lambda row, t=threshold: row.get('uptrend_volume_trend', 0) > t if pd.notna(row.get('uptrend_volume_trend')) else False
            )
            results.append(result)

        # 필터 6: 상승 구간 평균 거래량
        print("\n" + "="*80)
        print("[6/6] 상승 구간 평균 거래량 필터")
        print("="*80)

        for threshold in [40000, 45000, 50000]:
            result = self.analyze_filter(
                df,
                f"상승 구간 평균 거래량 > {threshold} 차단",
                lambda row, t=threshold: row.get('uptrend_avg_volume', 0) > t if pd.notna(row.get('uptrend_avg_volume')) else False
            )
            results.append(result)

        return results

    def find_best_combination(self, df: pd.DataFrame, results: List[Dict]):
        """최적 필터 조합 찾기"""
        print("\n" + "="*80)
        print("[*] 최적 필터 조합 찾기")
        print("="*80)

        # 총 수익이 증가하는 필터만 선택
        good_filters = [r for r in results if r['total_profit_change_pct'] is not None and r['total_profit_change_pct'] > 0]

        if not good_filters:
            print("\n[!] 총 수익을 증가시키는 필터가 없습니다!")
            return

        # 총 수익 증가율 기준 정렬
        good_filters.sort(key=lambda x: x['total_profit_change_pct'], reverse=True)

        print(f"\n[총 수익 증가 필터 TOP 5]")
        print(f"\n{'순위':<5} {'필터명':<40} {'총수익변화':<12} {'승률변화':<12} {'거래감소':<12}")
        print("-" * 80)

        for i, r in enumerate(good_filters[:5], 1):
            print(f"{i:<5} {r['filter_name']:<40} {r['total_profit_change_pct']:>+10.1f}% {r['win_rate_change']:>+10.1f}%p {r['blocked_count']:>10}개")

        # 복합 필터 테스트 (상위 2개 조합)
        if len(good_filters) >= 2:
            print(f"\n{'='*80}")
            print(f"[*] 상위 2개 필터 조합 테스트")
            print(f"{'='*80}")

            filter1 = good_filters[0]
            filter2 = good_filters[1]

            print(f"\n필터 1: {filter1['filter_name']}")
            print(f"필터 2: {filter2['filter_name']}")

            # TODO: 복합 필터 구현 (조합 효과 측정)
            print(f"\n[참고] 복합 필터는 개별 효과의 단순 합이 아닙니다.")
            print(f"      정확한 측정을 위해서는 두 필터를 동시에 적용한 백테스트가 필요합니다.")

    def save_results(self, results: List[Dict]):
        """결과 저장"""
        from datetime import datetime
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')

        # DataFrame으로 변환
        results_df = pd.DataFrame(results)

        # CSV 저장
        csv_path = f"filter_impact_analysis_{timestamp}.csv"
        results_df.to_csv(csv_path, index=False, encoding='utf-8-sig')
        print(f"\n[*] 결과 저장: {csv_path}")

        # JSON 저장
        json_path = f"filter_impact_analysis_{timestamp}.json"
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"[*] 결과 저장: {json_path}")


def main():
    """메인 실행"""
    print("="*80)
    print("[*] 필터별 영향도 분석 시작")
    print("="*80)

    # 1. 기본 분석기 초기화
    analyzer = WinLossAnalyzer()
    analyzer.load_all_trades(start_date="20250901", end_date="20251031")

    if len(analyzer.trade_data) == 0:
        print("[!] 거래 데이터가 없습니다.")
        return

    # 2. 필터 영향도 분석기 초기화
    filter_analyzer = FilterImpactAnalyzer(analyzer)

    # 3. 모든 거래의 특징 수집
    df = filter_analyzer.collect_all_features(morning_only=True)

    if len(df) == 0:
        print("[!] 특징 데이터를 수집할 수 없습니다.")
        return

    # 4. 모든 필터 테스트
    results = filter_analyzer.test_all_filters(df)

    # 5. 최적 조합 찾기
    filter_analyzer.find_best_combination(df, results)

    # 6. 결과 저장
    filter_analyzer.save_results(results)

    print("\n" + "="*80)
    print("[OK] 분석 완료!")
    print("="*80)


if __name__ == "__main__":
    main()
