#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
패턴 데이터에서 특징 추출
4단계 패턴의 세부 특징을 추출하여 분석 가능한 CSV 생성
"""

import json
import pandas as pd
from pathlib import Path


def extract_pattern_features():
    """패턴 데이터에서 분석 가능한 특징 추출"""

    print("패턴 특징 추출 중...")

    all_features = []
    pattern_dir = Path('pattern_data_log')

    for jsonl_file in sorted(pattern_dir.glob('pattern_data_*.jsonl')):
        print(f"  처리 중: {jsonl_file.name}")

        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())

                    # trade_result 체크
                    trade_result = data.get('trade_result')
                    if trade_result is None:
                        trade_result = {}

                    # 기본 정보
                    features = {
                        'pattern_id': data.get('pattern_id'),
                        'timestamp': data.get('timestamp'),
                        'stock_code': data.get('stock_code'),
                        'trade_executed': trade_result.get('trade_executed', False),
                        'profit_rate': trade_result.get('profit_rate', 0.0),
                        'sell_reason': trade_result.get('sell_reason', ''),
                    }

                    # pattern_stages 체크
                    pattern_stages = data.get('pattern_stages')
                    if pattern_stages is None:
                        pattern_stages = {}

                    # 1단계: 상승 (uptrend)
                    uptrend = pattern_stages.get('1_uptrend', {})
                    if uptrend and uptrend is not None:
                        # price_gain에서 % 제거하고 float로 변환
                        price_gain_str = uptrend.get('price_gain', '0%')
                        try:
                            features['uptrend_price_gain'] = float(price_gain_str.replace('%', ''))
                        except:
                            features['uptrend_price_gain'] = 0.0

                        features['uptrend_candle_count'] = uptrend.get('candle_count', 0)
                        features['uptrend_max_volume'] = uptrend.get('max_volume', '0').replace(',', '')

                    # 2단계: 하락 (decline)
                    decline = pattern_stages.get('2_decline', {})
                    if decline and decline is not None:
                        decline_pct_str = decline.get('decline_pct', '0%')
                        try:
                            features['decline_pct'] = float(decline_pct_str.replace('%', ''))
                        except:
                            features['decline_pct'] = 0.0

                        features['decline_candle_count'] = decline.get('candle_count', 0)

                    # 3단계: 지지 (support)
                    support = pattern_stages.get('3_support', {})
                    if support and support is not None:
                        features['support_candle_count'] = support.get('candle_count', 0)

                        # avg_volume_ratio 파싱
                        vol_ratio_str = support.get('avg_volume_ratio', '0%')
                        try:
                            features['support_avg_volume_ratio'] = float(vol_ratio_str.replace('%', ''))
                        except:
                            features['support_avg_volume_ratio'] = 0.0

                    # 4단계: 돌파 (breakout)
                    breakout = pattern_stages.get('4_breakout', {})
                    if breakout and breakout is not None:
                        # volume_ratio_vs_prev 파싱
                        vol_ratio = breakout.get('volume_ratio_vs_prev', 0)
                        if isinstance(vol_ratio, str):
                            try:
                                # "1.5배" -> 1.5
                                vol_ratio = float(vol_ratio.replace('배', '').replace('x', ''))
                            except:
                                vol_ratio = 0.0
                        features['breakout_volume_ratio_vs_prev'] = vol_ratio

                        # price_gain_pct 파싱
                        price_gain_str = breakout.get('price_gain_pct', '0%')
                        try:
                            features['breakout_price_gain'] = float(price_gain_str.replace('%', ''))
                        except:
                            features['breakout_price_gain'] = 0.0

                    # 신호 정보
                    signal_info = data.get('signal_info', {})
                    if signal_info:
                        features['signal_confidence'] = signal_info.get('confidence', 0)
                        features['signal_type'] = signal_info.get('signal_type', '')

                    all_features.append(features)

                except Exception as e:
                    print(f"    오류: {e}")
                    continue

    print(f"\n총 {len(all_features)}개 패턴 특징 추출 완료")

    # DataFrame 생성
    df = pd.DataFrame(all_features)

    # 저장
    output_file = 'all_patterns_analysis.csv'
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"저장 완료: {output_file}")

    # 기본 통계
    print(f"\n=== 기본 통계 ===")
    print(f"전체 패턴: {len(df)}개")
    print(f"거래 실행: {df['trade_executed'].sum()}개")
    print(f"거래 실행률: {df['trade_executed'].sum() / len(df) * 100:.1f}%")

    traded = df[df['trade_executed'] == True]
    if len(traded) > 0:
        wins = traded[traded['profit_rate'] > 0]
        print(f"\n거래 실행된 패턴:")
        print(f"  총 거래: {len(traded)}건")
        print(f"  승리: {len(wins)}건")
        print(f"  패배: {len(traded) - len(wins)}건")
        print(f"  승률: {len(wins) / len(traded) * 100:.1f}%")
        print(f"  평균 수익률: {traded['profit_rate'].mean():.3f}%")
        print(f"  총 수익률: {traded['profit_rate'].sum():.2f}%")

    print(f"\n추출된 주요 특징:")
    for col in sorted(df.columns):
        print(f"  - {col}")

    return df


if __name__ == '__main__':
    df = extract_pattern_features()
