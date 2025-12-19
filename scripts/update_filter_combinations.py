#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
필터 조합 자동 업데이트 스크립트

사용법:
    python update_filter_combinations.py --min-trades 5

기능:
    1. 최신 패턴 데이터 분석
    2. 마이너스 조합 재계산
    3. pattern_combination_filter.py 자동 업데이트 (선택)
"""

import pandas as pd
import numpy as np
import json
import glob
from datetime import datetime
import argparse


def load_all_patterns():
    """모든 패턴 데이터 로드"""
    patterns = []

    for jsonl_file in glob.glob('pattern_data_log/*.jsonl'):
        with open(jsonl_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line)
                    if data.get('trade_result'):
                        patterns.append(data)
                except json.JSONDecodeError:
                    continue

    return patterns


def extract_features(data):
    """패턴 특징 추출"""
    stages = data['pattern_stages']

    # 1_uptrend 또는 uptrend 형식 지원
    uptrend = stages.get('1_uptrend') or stages.get('uptrend', {})
    decline = stages.get('2_decline') or stages.get('decline', {})
    support = stages.get('3_support') or stages.get('support', {})

    def clean_pct(value):
        if isinstance(value, str):
            return float(value.replace('%', '').replace(',', ''))
        return float(value)

    return {
        '상승률': clean_pct(uptrend.get('price_gain', 0)),
        '하락률': clean_pct(decline.get('decline_pct', 0)),
        '지지캔들수': support.get('candle_count', 0),
        '수익률': data['trade_result']['profit_pct'],
        '성공여부': 1 if data['trade_result']['profit_pct'] > 0 else 0
    }


def categorize_patterns(df):
    """패턴 카테고리화"""

    # 상승강도
    df['상승강도'] = pd.cut(
        df['상승률'],
        bins=[-np.inf, 4, 6, np.inf],
        labels=['약함(<4%)', '보통(4-6%)', '강함(>6%)']
    )

    # 하락정도
    df['하락정도'] = pd.cut(
        df['하락률'],
        bins=[-np.inf, 1.5, 2.5, np.inf],
        labels=['얕음(<1.5%)', '보통(1.5-2.5%)', '깊음(>2.5%)']
    )

    # 지지길이
    df['지지길이'] = pd.cut(
        df['지지캔들수'],
        bins=[-np.inf, 2, 4, np.inf],
        labels=['짧음(≤2)', '보통(3-4)', '김(>4)']
    )

    return df


def analyze_combinations(df, min_trades=1):
    """조합별 분석"""

    grouped = df.groupby(['상승강도', '하락정도', '지지길이'], observed=True)

    results = []
    for combo, group in grouped:
        if len(group) < min_trades:
            continue

        results.append({
            '상승강도': combo[0],
            '하락정도': combo[1],
            '지지길이': combo[2],
            '거래수': len(group),
            '승률': (group['성공여부'].sum() / len(group)) * 100,
            '총수익': group['수익률'].sum(),
            '평균수익': group['수익률'].mean()
        })

    return pd.DataFrame(results)


def find_negative_combinations(combo_df):
    """마이너스 조합 찾기"""
    negative = combo_df[combo_df['총수익'] < 0].sort_values('총수익')
    return negative


def print_analysis_report(df, combo_df, negative_combos):
    """분석 보고서 출력"""

    print("=" * 80)
    print("🔍 패턴 조합 분석 보고서")
    print("=" * 80)
    print(f"\n분석 기간: {datetime.now().strftime('%Y-%m-%d')}")
    print(f"총 패턴 수: {len(df):,}개")
    print(f"승률: {(df['성공여부'].sum() / len(df) * 100):.1f}%")
    print(f"총 수익: {df['수익률'].sum():.2f}%")
    print(f"평균 수익: {df['수익률'].mean():.3f}%")

    print(f"\n📊 조합 분석")
    print(f"총 조합 수: {len(combo_df)}개")
    print(f"양수 수익 조합: {len(combo_df[combo_df['총수익'] > 0])}개")
    print(f"마이너스 수익 조합: {len(negative_combos)}개")

    if len(negative_combos) > 0:
        print(f"\n🚫 마이너스 수익 조합 ({len(negative_combos)}개):")
        print("-" * 80)
        for idx, row in negative_combos.iterrows():
            print(f"{idx+1}. {row['상승강도']} + {row['하락정도']} + {row['지지길이']}")
            print(f"   거래: {int(row['거래수'])}건, 승률: {row['승률']:.1f}%, "
                  f"총손실: {row['총수익']:.2f}%, 평균: {row['평균수익']:.3f}%")

    print("\n" + "=" * 80)


def generate_filter_code(negative_combos):
    """필터 코드 생성"""

    code = "    NEGATIVE_PROFIT_COMBINATIONS = [\n"

    for idx, row in negative_combos.iterrows():
        code += f"        {{'상승강도': '{row['상승강도']}', "
        code += f"'하락정도': '{row['하락정도']}', "
        code += f"'지지길이': '{row['지지길이']}', "
        code += f"'총손실': {row['총수익']:.2f}}},\n"

    code += "    ]\n"

    return code


def main():
    parser = argparse.ArgumentParser(description='필터 조합 업데이트')
    parser.add_argument('--min-trades', type=int, default=1,
                       help='최소 거래 수 (기본값: 1)')
    parser.add_argument('--save-code', action='store_true',
                       help='필터 코드를 파일로 저장')

    args = parser.parse_args()

    print("📂 패턴 데이터 로딩 중...")
    patterns = load_all_patterns()

    if len(patterns) == 0:
        print("❌ 패턴 데이터가 없습니다.")
        return

    print(f"✅ {len(patterns):,}개 패턴 로드 완료")

    # 특징 추출
    print("🔄 특징 추출 중...")
    features = [extract_features(p) for p in patterns]
    df = pd.DataFrame(features)

    # 카테고리화
    print("📊 패턴 카테고리화 중...")
    df = categorize_patterns(df)

    # 조합별 분석
    print(f"🔍 조합별 분석 중 (최소 거래 수: {args.min_trades}건)...")
    combo_df = analyze_combinations(df, min_trades=args.min_trades)

    # 마이너스 조합 찾기
    negative_combos = find_negative_combinations(combo_df)

    # 보고서 출력
    print_analysis_report(df, combo_df, negative_combos)

    # 필터 코드 생성
    if args.save_code and len(negative_combos) > 0:
        filter_code = generate_filter_code(negative_combos)

        output_file = f'negative_combinations_{datetime.now().strftime("%Y%m%d_%H%M%S")}.txt'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("# 아래 코드를 pattern_combination_filter.py에 복사하세요\n\n")
            f.write(filter_code)

        print(f"\n💾 필터 코드 저장됨: {output_file}")
        print("이 코드를 core/indicators/pattern_combination_filter.py에 복사하세요.")

    # CSV 저장
    csv_file = f'combination_analysis_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
    combo_df.to_csv(csv_file, index=False, encoding='utf-8-sig')
    print(f"\n💾 상세 분석 저장됨: {csv_file}")


if __name__ == '__main__':
    main()
