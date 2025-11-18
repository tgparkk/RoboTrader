"""
승률 60% 이상 조합 분석 스크립트
"""
import json
import glob
from pathlib import Path
from collections import defaultdict


def load_all_pattern_data():
    """모든 패턴 데이터 로드"""
    all_data = []
    pattern_files = glob.glob('pattern_data_log/pattern_data_*.jsonl')

    for file_path in sorted(pattern_files):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())
                        # trade_result가 있고 trade_executed가 True인 경우만
                        trade_result = data.get('trade_result')
                        if trade_result and trade_result.get('trade_executed'):
                            all_data.append(data)
                    except json.JSONDecodeError:
                        continue
        except FileNotFoundError:
            continue

    return all_data


def categorize_pattern(debug_info):
    """패턴을 카테고리로 분류"""
    categories = {}

    # 1단계: 상승 강도
    uptrend = debug_info.get('1_uptrend') or debug_info.get('uptrend', {})
    price_gain_str = uptrend.get('price_gain', '0%')
    try:
        uptrend_gain = float(price_gain_str.replace('%', ''))
    except (ValueError, AttributeError):
        uptrend_gain = 0.0

    if uptrend_gain < 4.0:
        categories['상승강도'] = '약함(<4%)'
    elif uptrend_gain < 6.0:
        categories['상승강도'] = '보통(4-6%)'
    else:
        categories['상승강도'] = '강함(>6%)'

    # 2단계: 하락 정도
    decline = debug_info.get('2_decline') or debug_info.get('decline', {})
    decline_pct_str = decline.get('decline_pct', '0%')
    try:
        decline_pct = float(decline_pct_str.replace('%', ''))
    except (ValueError, AttributeError):
        decline_pct = 0.0

    if decline_pct < 1.5:
        categories['하락정도'] = '얕음(<1.5%)'
    elif decline_pct < 2.5:
        categories['하락정도'] = '보통(1.5-2.5%)'
    else:
        categories['하락정도'] = '깊음(>2.5%)'

    # 3단계: 지지 길이
    support = debug_info.get('3_support') or debug_info.get('support', {})
    support_candles = support.get('candle_count', 0)

    if support_candles <= 2:
        categories['지지길이'] = '짧음(≤2)'
    elif support_candles <= 4:
        categories['지지길이'] = '보통(3-4)'
    else:
        categories['지지길이'] = '김(>4)'

    return categories


def analyze_combinations(min_trades=10):
    """조합별 통계 분석"""
    print("패턴 데이터 로딩 중...")
    all_data = load_all_pattern_data()
    print(f"총 {len(all_data)}건 로드 완료\n")

    # 조합별 데이터 집계
    combo_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'total_profit': 0.0, 'trades': []})

    for data in all_data:
        # trade_result에서 수익률 확인
        trade_result = data.get('trade_result', {})
        if not trade_result:
            continue

        profit = trade_result.get('profit_rate', 0)

        # pattern_stages에서 패턴 정보 추출
        pattern_stages = data.get('pattern_stages', {})
        if not pattern_stages:
            continue

        # 패턴 분류
        category = categorize_pattern(pattern_stages)
        combo_key = f"{category['상승강도']} + {category['하락정도']} + {category['지지길이']}"

        combo_stats[combo_key]['trades'].append(profit)
        combo_stats[combo_key]['total_profit'] += profit

        if profit > 0:
            combo_stats[combo_key]['wins'] += 1
        else:
            combo_stats[combo_key]['losses'] += 1

    # 통계 계산 및 필터링
    results = []
    for combo, stats in combo_stats.items():
        total_trades = len(stats['trades'])

        if total_trades < min_trades:
            continue

        win_rate = (stats['wins'] / total_trades * 100) if total_trades > 0 else 0
        avg_profit = stats['total_profit'] / total_trades if total_trades > 0 else 0

        results.append({
            'combination': combo,
            'trades': total_trades,
            'wins': stats['wins'],
            'losses': stats['losses'],
            'win_rate': win_rate,
            'total_profit': stats['total_profit'],
            'avg_profit': avg_profit
        })

    return results


def main():
    print("="*80)
    print("승률 60% 이상 조합 분석")
    print("="*80)
    print()

    # 최소 10건 이상 거래된 조합 분석
    results = analyze_combinations(min_trades=10)

    # 승률 순 정렬
    results.sort(key=lambda x: x['win_rate'], reverse=True)

    # 승률 60% 이상 필터링
    high_winrate = [r for r in results if r['win_rate'] >= 60.0]

    print(f"\n[+] 전체 조합: {len(results)}개 (최소 10건 이상)")
    print(f"[+] 승률 60% 이상: {len(high_winrate)}개\n")

    print("="*80)
    print("[WIN 60%+] 승률 60% 이상 조합")
    print("="*80)
    print(f"{'조합':<50} {'거래수':>8} {'승률':>8} {'총수익':>10} {'평균':>8}")
    print("-"*80)

    total_trades_60 = 0
    total_profit_60 = 0

    for r in high_winrate:
        print(f"{r['combination']:<50} {r['trades']:>8} {r['win_rate']:>7.1f}% {r['total_profit']:>9.2f}% {r['avg_profit']:>7.2f}%")
        total_trades_60 += r['trades']
        total_profit_60 += r['total_profit']

    print("-"*80)
    print(f"{'합계':<50} {total_trades_60:>8} {'-':>8} {total_profit_60:>9.2f}% {total_profit_60/total_trades_60 if total_trades_60 > 0 else 0:>7.2f}%")
    print()

    # 전체 대비 비교
    all_trades = sum(r['trades'] for r in results)
    all_profit = sum(r['total_profit'] for r in results)

    print("="*80)
    print("[COMPARE] 전략 비교")
    print("="*80)
    print()
    print(f"[현재 전략] 마이너스 조합 제외 (블랙리스트)")
    print(f"  - 전체 거래: {all_trades}건")
    print(f"  - 전체 수익: {all_profit:.2f}%")
    print(f"  - 평균 수익: {all_profit/all_trades if all_trades > 0 else 0:.2f}%")
    print()
    print(f"[제안 전략] 승률 60% 이상만 허용 (화이트리스트)")
    print(f"  - 거래 수: {total_trades_60}건 ({total_trades_60/all_trades*100 if all_trades > 0 else 0:.1f}%)")
    print(f"  - 총 수익: {total_profit_60:.2f}%")
    print(f"  - 평균 수익: {total_profit_60/total_trades_60 if total_trades_60 > 0 else 0:.2f}%")
    print()
    print(f"[RESULT] 개선 효과:")
    print(f"  - 거래 감소: {all_trades - total_trades_60}건 ({(all_trades - total_trades_60)/all_trades*100 if all_trades > 0 else 0:.1f}%)")
    print(f"  - 수익 변화: {total_profit_60 - all_profit:+.2f}%")
    print(f"  - 평균 수익 개선: {(total_profit_60/total_trades_60 if total_trades_60 > 0 else 0) - (all_profit/all_trades if all_trades > 0 else 0):+.2f}%p")
    print()

    # 월별 분석
    print("="*80)
    print("[LIST] 승률 60% 이상 조합 목록")
    print("="*80)
    print()
    for i, r in enumerate(high_winrate, 1):
        parts = r['combination'].split(' + ')
        print(f"{i}. {r['combination']}")
        print(f"   거래: {r['trades']}건 | 승: {r['wins']}건 | 패: {r['losses']}건")
        print(f"   승률: {r['win_rate']:.1f}% | 총수익: {r['total_profit']:.2f}% | 평균: {r['avg_profit']:.2f}%")
        print()


if __name__ == '__main__':
    main()
