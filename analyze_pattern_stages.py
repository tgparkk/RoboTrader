"""
pattern_stages 변수와 승률 상관관계 분석
데이터 기반으로 어떤 특성이 승률과 연관되는지 발견
"""

import json
import os
from collections import defaultdict
from datetime import datetime
import statistics

PATTERN_LOG_DIR = "pattern_data_log"
OUTPUT_FILE = "pattern_stages_analysis_report.txt"


def load_all_trades():
    """모든 거래 데이터 로드"""
    trades = []

    for filename in sorted(os.listdir(PATTERN_LOG_DIR)):
        if not filename.endswith('.jsonl'):
            continue

        filepath = os.path.join(PATTERN_LOG_DIR, filename)
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    # trade_result가 있는 것만
                    if data.get('trade_result') and isinstance(data['trade_result'], dict):
                        if 'profit_rate' in data['trade_result']:
                            trades.append(data)
                except json.JSONDecodeError:
                    continue

    return trades


def extract_features(trade):
    """거래에서 분석할 특성 추출"""
    features = {}

    stages = trade.get('pattern_stages', {})
    signal_info = trade.get('signal_info', {})
    trade_result = trade.get('trade_result', {})

    # 결과
    profit_rate = trade_result.get('profit_rate', 0)
    features['is_win'] = profit_rate > 0
    features['profit_rate'] = profit_rate

    # 신호 정보
    features['confidence'] = signal_info.get('confidence', 0)

    # 1_uptrend 특성
    uptrend = stages.get('1_uptrend', {})
    features['uptrend_candle_count'] = uptrend.get('candle_count', 0)
    features['uptrend_price_gain'] = uptrend.get('price_gain', 0) * 100  # %로 변환
    features['uptrend_max_volume'] = uptrend.get('max_volume', 0)
    features['uptrend_volume_avg'] = uptrend.get('volume_avg', 0)

    # 2_decline 특성
    decline = stages.get('2_decline', {})
    features['decline_candle_count'] = decline.get('candle_count', 0)
    features['decline_pct'] = decline.get('decline_pct', 0)
    features['decline_avg_volume'] = decline.get('avg_volume', 0)

    # 3_support 특성
    support = stages.get('3_support', {})
    features['support_candle_count'] = support.get('candle_count', 0)
    features['support_avg_volume'] = support.get('avg_volume', 0)
    features['support_avg_volume_ratio'] = support.get('avg_volume_ratio', 0)

    # 4_breakout 특성
    breakout = stages.get('4_breakout', {})
    features['breakout_volume'] = breakout.get('volume', 0)
    features['breakout_body_size'] = breakout.get('body_size', 0)

    # 파생 특성
    # 상승/하락 비율
    if features['decline_pct'] > 0:
        features['rise_decline_ratio'] = features['uptrend_price_gain'] / features['decline_pct']
    else:
        features['rise_decline_ratio'] = 0

    # 거래량 변화 패턴
    if features['uptrend_volume_avg'] > 0:
        features['decline_vol_ratio'] = features['decline_avg_volume'] / features['uptrend_volume_avg']
        features['support_vol_ratio'] = features['support_avg_volume'] / features['uptrend_volume_avg']
        features['breakout_vol_ratio'] = features['breakout_volume'] / features['uptrend_volume_avg']
    else:
        features['decline_vol_ratio'] = 0
        features['support_vol_ratio'] = 0
        features['breakout_vol_ratio'] = 0

    # 거래량 V자형 패턴 (support < decline 이고 breakout > support)
    features['volume_v_pattern'] = (
        features['support_avg_volume'] < features['decline_avg_volume'] and
        features['breakout_volume'] > features['support_avg_volume']
    )

    # 시간 정보
    signal_time = trade.get('signal_time', '')
    if signal_time:
        try:
            dt = datetime.strptime(signal_time, "%Y-%m-%d %H:%M:%S")
            features['hour'] = dt.hour
            features['weekday'] = dt.weekday()
        except:
            features['hour'] = -1
            features['weekday'] = -1

    return features


def analyze_threshold(trades_features, feature_name, thresholds, is_less_than=False):
    """임계값별 승률 분석"""
    results = []

    for threshold in thresholds:
        if is_less_than:
            passed = [t for t in trades_features if t.get(feature_name, float('inf')) <= threshold]
        else:
            passed = [t for t in trades_features if t.get(feature_name, 0) >= threshold]

        if len(passed) >= 10:  # 최소 10건 이상
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            avg_profit = statistics.mean([t['profit_rate'] for t in passed])
            results.append({
                'threshold': threshold,
                'trades': len(passed),
                'wins': wins,
                'winrate': winrate,
                'avg_profit': avg_profit
            })

    return results


def analyze_range(trades_features, feature_name, ranges):
    """구간별 승률 분석"""
    results = []

    for low, high in ranges:
        passed = [t for t in trades_features
                 if low <= t.get(feature_name, -999) < high]

        if len(passed) >= 10:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            avg_profit = statistics.mean([t['profit_rate'] for t in passed])
            results.append({
                'range': f"{low}~{high}",
                'trades': len(passed),
                'wins': wins,
                'winrate': winrate,
                'avg_profit': avg_profit
            })

    return results


def analyze_boolean(trades_features, feature_name):
    """불리언 특성 분석"""
    true_trades = [t for t in trades_features if t.get(feature_name, False)]
    false_trades = [t for t in trades_features if not t.get(feature_name, False)]

    results = []

    if len(true_trades) >= 10:
        wins = sum(1 for t in true_trades if t['is_win'])
        winrate = 100 * wins / len(true_trades)
        avg_profit = statistics.mean([t['profit_rate'] for t in true_trades])
        results.append({
            'value': 'True',
            'trades': len(true_trades),
            'wins': wins,
            'winrate': winrate,
            'avg_profit': avg_profit
        })

    if len(false_trades) >= 10:
        wins = sum(1 for t in false_trades if t['is_win'])
        winrate = 100 * wins / len(false_trades)
        avg_profit = statistics.mean([t['profit_rate'] for t in false_trades])
        results.append({
            'value': 'False',
            'trades': len(false_trades),
            'wins': wins,
            'winrate': winrate,
            'avg_profit': avg_profit
        })

    return results


def main():
    print("=" * 70)
    print("pattern_stages 변수와 승률 상관관계 분석")
    print("=" * 70)

    # 데이터 로드
    print("\n데이터 로딩 중...")
    trades = load_all_trades()
    print(f"총 거래 수: {len(trades)}")

    if not trades:
        print("거래 데이터가 없습니다.")
        return

    # 특성 추출
    print("특성 추출 중...")
    trades_features = [extract_features(t) for t in trades]

    # 기본 통계
    wins = sum(1 for t in trades_features if t['is_win'])
    losses = len(trades_features) - wins
    base_winrate = 100 * wins / len(trades_features)
    avg_profit = statistics.mean([t['profit_rate'] for t in trades_features])

    print(f"\n기본 통계:")
    print(f"  거래: {len(trades_features)}건 ({wins}승 {losses}패)")
    print(f"  승률: {base_winrate:.1f}%")
    print(f"  평균 수익률: {avg_profit:.2f}%")

    # 결과 파일 작성
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("pattern_stages 변수와 승률 상관관계 분석 보고서\n")
        f.write(f"분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"총 거래: {len(trades_features)}건 ({wins}승 {losses}패)\n")
        f.write(f"기본 승률: {base_winrate:.1f}%\n")
        f.write(f"평균 수익률: {avg_profit:.2f}%\n\n")

        # 1. confidence 분석
        f.write("=" * 80 + "\n")
        f.write("1. 신호 신뢰도 (confidence) 분석\n")
        f.write("=" * 80 + "\n")
        results = analyze_threshold(trades_features, 'confidence', [70, 80, 85, 90, 95])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  >= {r['threshold']}: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p), 평균수익 {r['avg_profit']:.2f}%\n")

        # 2. uptrend 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("2. 상승구간 (1_uptrend) 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\n2-1. 상승구간 캔들 수:\n")
        results = analyze_range(trades_features, 'uptrend_candle_count', [(1,3), (3,5), (5,7), (7,10), (10,20)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}개: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n2-2. 상승폭 (price_gain %):\n")
        results = analyze_range(trades_features, 'uptrend_price_gain', [(0,3), (3,5), (5,10), (10,15), (15,30)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}%: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # 3. decline 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("3. 하락구간 (2_decline) 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\n3-1. 하락구간 캔들 수:\n")
        results = analyze_range(trades_features, 'decline_candle_count', [(1,2), (2,3), (3,4), (4,6), (6,10)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}개: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n3-2. 하락폭 (decline_pct %):\n")
        results = analyze_range(trades_features, 'decline_pct', [(0,2), (2,3), (3,4), (4,5), (5,10)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}%: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # 4. support 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("4. 지지구간 (3_support) 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\n4-1. 지지구간 캔들 수:\n")
        results = analyze_range(trades_features, 'support_candle_count', [(1,2), (2,3), (3,4), (4,6), (6,10)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}개: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # 5. 상승/하락 비율 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("5. 상승폭/하락폭 비율 분석\n")
        f.write("=" * 80 + "\n")
        results = analyze_range(trades_features, 'rise_decline_ratio', [(0,1), (1,2), (2,3), (3,5), (5,10), (10,100)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  비율 {r['range']}: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # 6. 거래량 패턴 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("6. 거래량 패턴 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\n6-1. 하락구간 거래량 비율 (vs 상승구간):\n")
        results = analyze_range(trades_features, 'decline_vol_ratio', [(0,0.3), (0.3,0.5), (0.5,0.7), (0.7,1.0), (1.0,2.0)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}x: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n6-2. 지지구간 거래량 비율 (vs 상승구간):\n")
        results = analyze_range(trades_features, 'support_vol_ratio', [(0,0.2), (0.2,0.4), (0.4,0.6), (0.6,0.8), (0.8,1.0), (1.0,2.0)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}x: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n6-3. 돌파봉 거래량 비율 (vs 상승구간):\n")
        results = analyze_range(trades_features, 'breakout_vol_ratio', [(0,0.2), (0.2,0.4), (0.4,0.6), (0.6,0.8), (0.8,1.0), (1.0,2.0)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}x: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n6-4. 거래량 V자형 패턴 (support<decline & breakout>support):\n")
        results = analyze_boolean(trades_features, 'volume_v_pattern')
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['value']}: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # 7. 요일/시간 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("7. 시간/요일 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\n7-1. 시간대별:\n")
        for hour in range(9, 16):
            hour_trades = [t for t in trades_features if t.get('hour') == hour]
            if len(hour_trades) >= 10:
                wins = sum(1 for t in hour_trades if t['is_win'])
                winrate = 100 * wins / len(hour_trades)
                improvement = winrate - base_winrate
                f.write(f"  {hour}시: {len(hour_trades)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n7-2. 요일별:\n")
        day_names = ['월', '화', '수', '목', '금']
        for weekday in range(5):
            day_trades = [t for t in trades_features if t.get('weekday') == weekday]
            if len(day_trades) >= 10:
                wins = sum(1 for t in day_trades if t['is_win'])
                winrate = 100 * wins / len(day_trades)
                improvement = winrate - base_winrate
                f.write(f"  {day_names[weekday]}요일: {len(day_trades)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 8. 복합 조건 테스트
        f.write("\n" + "=" * 80 + "\n")
        f.write("8. 유의미한 조합 탐색\n")
        f.write("=" * 80 + "\n")

        # 상위 조건들을 조합해서 테스트
        conditions = [
            ('confidence>=85', lambda t: t.get('confidence', 0) >= 85),
            ('confidence>=90', lambda t: t.get('confidence', 0) >= 90),
            ('uptrend_gain>=5%', lambda t: t.get('uptrend_price_gain', 0) >= 5),
            ('uptrend_gain>=10%', lambda t: t.get('uptrend_price_gain', 0) >= 10),
            ('decline<=3%', lambda t: t.get('decline_pct', 100) <= 3),
            ('decline<=4%', lambda t: t.get('decline_pct', 100) <= 4),
            ('support_candle<=2', lambda t: t.get('support_candle_count', 100) <= 2),
            ('rise_decline_ratio>=2', lambda t: t.get('rise_decline_ratio', 0) >= 2),
            ('rise_decline_ratio>=3', lambda t: t.get('rise_decline_ratio', 0) >= 3),
            ('volume_v_pattern', lambda t: t.get('volume_v_pattern', False)),
            ('support_vol<=0.5x', lambda t: t.get('support_vol_ratio', 100) <= 0.5),
            ('not_tuesday', lambda t: t.get('weekday', -1) != 1),
        ]

        f.write("\n개별 조건:\n")
        for name, cond in conditions:
            passed = [t for t in trades_features if cond(t)]
            if len(passed) >= 20:
                wins = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  {name}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 2개 조합
        f.write("\n2개 조합 (승률 55% 이상만 표시):\n")
        for i, (name1, cond1) in enumerate(conditions):
            for name2, cond2 in conditions[i+1:]:
                passed = [t for t in trades_features if cond1(t) and cond2(t)]
                if len(passed) >= 20:
                    wins = sum(1 for t in passed if t['is_win'])
                    winrate = 100 * wins / len(passed)
                    if winrate >= 55:
                        improvement = winrate - base_winrate
                        f.write(f"  {name1} & {name2}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 3개 조합
        f.write("\n3개 조합 (승률 60% 이상만 표시):\n")
        for i, (name1, cond1) in enumerate(conditions):
            for j, (name2, cond2) in enumerate(conditions[i+1:], i+1):
                for name3, cond3 in conditions[j+1:]:
                    passed = [t for t in trades_features if cond1(t) and cond2(t) and cond3(t)]
                    if len(passed) >= 20:
                        wins = sum(1 for t in passed if t['is_win'])
                        winrate = 100 * wins / len(passed)
                        if winrate >= 60:
                            improvement = winrate - base_winrate
                            f.write(f"  {name1} & {name2} & {name3}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("분석 완료\n")
        f.write("=" * 80 + "\n")

    print(f"\n분석 완료! 결과 파일: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
