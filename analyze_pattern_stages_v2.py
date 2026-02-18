"""
pattern_stages 변수와 승률 상관관계 분석 (v2)
3분봉 기반 특성(연속양봉, 가격위치) 포함
"""

import json
import os
from collections import defaultdict
from datetime import datetime
import statistics

PATTERN_LOG_DIR = "pattern_data_log"
OUTPUT_FILE = "pattern_stages_analysis_report_v2.txt"


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
                    if data.get('trade_result') and isinstance(data['trade_result'], dict):
                        if 'profit_rate' in data['trade_result']:
                            trades.append(data)
                except json.JSONDecodeError:
                    continue

    return trades


def get_all_candles_from_stages(stages):
    """pattern_stages에서 모든 캔들을 시간순으로 추출"""
    all_candles = []

    for stage_name in ['1_uptrend', '2_decline', '3_support']:
        stage = stages.get(stage_name, {})
        candles = stage.get('candles', [])
        all_candles.extend(candles)

    # 4_breakout은 단일 캔들
    breakout = stages.get('4_breakout', {})
    breakout_candle = breakout.get('candle')
    if breakout_candle:
        all_candles.append(breakout_candle)

    # 시간순 정렬
    all_candles.sort(key=lambda x: x.get('datetime', ''))

    return all_candles


def extract_3min_features(candles):
    """3분봉 캔들에서 연속양봉, 가격위치 등 추출"""
    if len(candles) < 5:
        return {}

    # 마지막 5개 캔들 사용
    recent = candles[-5:]

    # 연속 양봉 수 (뒤에서부터)
    consecutive_bullish = 0
    for candle in reversed(recent):
        body = candle.get('close', 0) - candle.get('open', 0)
        if body > 0:
            consecutive_bullish += 1
        else:
            break

    # 가격 위치 (최근 5봉 범위 내)
    highs = [c.get('high', c.get('close', 0)) for c in recent]
    lows = [c.get('low', c.get('close', 0)) for c in recent]
    closes = [c.get('close', 0) for c in recent]

    high_5 = max(highs)
    low_5 = min(lows)
    current_close = closes[-1]

    if high_5 > low_5:
        price_position = (current_close - low_5) / (high_5 - low_5)
    else:
        price_position = 0.5

    # 윗꼬리 비율 (마지막 캔들)
    last = recent[-1]
    last_high = last.get('high', 0)
    last_low = last.get('low', 0)
    last_open = last.get('open', 0)
    last_close = last.get('close', 0)
    last_range = last_high - last_low

    if last_range > 0:
        upper_wick = last_high - max(last_open, last_close)
        upper_wick_ratio = upper_wick / last_range
    else:
        upper_wick_ratio = 0

    # 거래량 비율 (마지막 vs 이전 4개 평균)
    volumes = [c.get('volume', 0) for c in recent]
    avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    if avg_vol > 0:
        volume_ratio = volumes[-1] / avg_vol
    else:
        volume_ratio = 1.0

    # 캔들 바디 크기 추세 (축소 → 확대)
    bodies = [abs(c.get('close', 0) - c.get('open', 0)) for c in recent]
    if len(bodies) >= 3:
        early_avg = sum(bodies[:2]) / 2
        late_avg = sum(bodies[-2:]) / 2
        if early_avg > 0:
            body_expansion = late_avg / early_avg
        else:
            body_expansion = 1.0
    else:
        body_expansion = 1.0

    return {
        'consecutive_bullish': consecutive_bullish,
        'price_position': price_position,
        'upper_wick_ratio': upper_wick_ratio,
        'volume_ratio': volume_ratio,
        'body_expansion': body_expansion,
    }


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
    features['uptrend_price_gain'] = uptrend.get('price_gain', 0) * 100

    # 2_decline 특성
    decline = stages.get('2_decline', {})
    features['decline_candle_count'] = decline.get('candle_count', 0)
    features['decline_pct'] = decline.get('decline_pct', 0)

    # 3_support 특성
    support = stages.get('3_support', {})
    features['support_candle_count'] = support.get('candle_count', 0)

    # 상승/하락 비율
    if features['decline_pct'] > 0:
        features['rise_decline_ratio'] = features['uptrend_price_gain'] / features['decline_pct']
    else:
        features['rise_decline_ratio'] = 0

    # 3분봉 기반 특성 추출
    all_candles = get_all_candles_from_stages(stages)
    candle_features = extract_3min_features(all_candles)
    features.update(candle_features)

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

        if len(passed) >= 10:
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


def main():
    print("=" * 70)
    print("pattern_stages + 3분봉 특성 분석 (v2)")
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
        f.write("pattern_stages + 3분봉 특성 분석 보고서 (v2)\n")
        f.write(f"분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"총 거래: {len(trades_features)}건 ({wins}승 {losses}패)\n")
        f.write(f"기본 승률: {base_winrate:.1f}%\n")
        f.write(f"평균 수익률: {avg_profit:.2f}%\n\n")

        # ===== 3분봉 기반 특성 분석 =====
        f.write("=" * 80 + "\n")
        f.write("A. 3분봉 기반 특성 분석 (기존 어드밴스필터 기준)\n")
        f.write("=" * 80 + "\n")

        # 연속 양봉
        f.write("\nA-1. 연속 양봉 수 (3분봉):\n")
        for min_count in range(0, 6):
            passed = [t for t in trades_features if t.get('consecutive_bullish', 0) >= min_count]
            if len(passed) >= 10:
                wins_count = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins_count / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  >= {min_count}개: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 가격 위치
        f.write("\nA-2. 가격 위치 (3분봉, 최근 5봉 기준):\n")
        for threshold in [0.5, 0.6, 0.7, 0.8, 0.9]:
            passed = [t for t in trades_features if t.get('price_position', 0) >= threshold]
            if len(passed) >= 10:
                wins_count = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins_count / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  >= {threshold*100:.0f}%: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 윗꼬리 비율
        f.write("\nA-3. 윗꼬리 비율 (3분봉):\n")
        for threshold in [0.05, 0.10, 0.15, 0.20, 0.30]:
            passed = [t for t in trades_features if t.get('upper_wick_ratio', 1) <= threshold]
            if len(passed) >= 10:
                wins_count = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins_count / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  <= {threshold*100:.0f}%: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 거래량 비율
        f.write("\nA-4. 거래량 비율 (마지막봉 vs 이전4봉 평균):\n")
        results = analyze_range(trades_features, 'volume_ratio', [(0,0.5), (0.5,1.0), (1.0,1.5), (1.5,2.0), (2.0,3.0), (3.0,10)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}x: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # 캔들 바디 확대
        f.write("\nA-5. 캔들 바디 확대율 (후반2봉/전반2봉):\n")
        results = analyze_range(trades_features, 'body_expansion', [(0,0.5), (0.5,1.0), (1.0,1.5), (1.5,2.0), (2.0,5.0)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}x: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # ===== pattern_stages 분석 =====
        f.write("\n" + "=" * 80 + "\n")
        f.write("B. pattern_stages 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\nB-1. 상승폭 (uptrend_price_gain %):\n")
        results = analyze_range(trades_features, 'uptrend_price_gain', [(0,3), (3,5), (5,10), (10,15), (15,30)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}%: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\nB-2. 하락폭 (decline_pct %):\n")
        results = analyze_range(trades_features, 'decline_pct', [(0,2), (2,3), (3,4), (4,5), (5,10)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}%: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\nB-3. 지지구간 캔들 수:\n")
        results = analyze_range(trades_features, 'support_candle_count', [(1,2), (2,3), (3,4), (4,10)])
        for r in results:
            improvement = r['winrate'] - base_winrate
            f.write(f"  {r['range']}개: {r['trades']}건, 승률 {r['winrate']:.1f}% ({improvement:+.1f}%p)\n")

        # ===== 시간/요일 =====
        f.write("\n" + "=" * 80 + "\n")
        f.write("C. 시간/요일 분석\n")
        f.write("=" * 80 + "\n")

        f.write("\nC-1. 요일별:\n")
        day_names = ['월', '화', '수', '목', '금']
        for weekday in range(5):
            day_trades = [t for t in trades_features if t.get('weekday') == weekday]
            if len(day_trades) >= 10:
                wins_count = sum(1 for t in day_trades if t['is_win'])
                winrate = 100 * wins_count / len(day_trades)
                improvement = winrate - base_winrate
                f.write(f"  {day_names[weekday]}요일: {len(day_trades)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # ===== 복합 조건 =====
        f.write("\n" + "=" * 80 + "\n")
        f.write("D. 복합 조건 탐색\n")
        f.write("=" * 80 + "\n")

        conditions = [
            # 3분봉 기반
            ('연속양봉>=1', lambda t: t.get('consecutive_bullish', 0) >= 1),
            ('연속양봉>=2', lambda t: t.get('consecutive_bullish', 0) >= 2),
            ('연속양봉>=3', lambda t: t.get('consecutive_bullish', 0) >= 3),
            ('가격위치>=70%', lambda t: t.get('price_position', 0) >= 0.7),
            ('가격위치>=80%', lambda t: t.get('price_position', 0) >= 0.8),
            ('가격위치>=90%', lambda t: t.get('price_position', 0) >= 0.9),
            ('윗꼬리<=10%', lambda t: t.get('upper_wick_ratio', 1) <= 0.1),
            ('거래량>=1.5x', lambda t: t.get('volume_ratio', 0) >= 1.5),
            ('바디확대>=1.5x', lambda t: t.get('body_expansion', 0) >= 1.5),
            # pattern_stages 기반
            ('상승폭<10%', lambda t: t.get('uptrend_price_gain', 100) < 10),
            ('상승폭<15%', lambda t: t.get('uptrend_price_gain', 100) < 15),
            ('하락폭<3%', lambda t: t.get('decline_pct', 100) < 3),
            ('하락폭<5%', lambda t: t.get('decline_pct', 100) < 5),
            ('지지캔들<=2', lambda t: t.get('support_candle_count', 100) <= 2),
            # 시간/요일
            ('화요일제외', lambda t: t.get('weekday', -1) != 1),
            ('월요일', lambda t: t.get('weekday', -1) == 0),
        ]

        f.write("\nD-1. 개별 조건:\n")
        for name, cond in conditions:
            passed = [t for t in trades_features if cond(t)]
            if len(passed) >= 20:
                wins_count = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins_count / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  {name}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 2개 조합
        f.write("\nD-2. 2개 조합 (승률 52% 이상, 30건 이상):\n")
        combos_2 = []
        for i, (name1, cond1) in enumerate(conditions):
            for name2, cond2 in conditions[i+1:]:
                passed = [t for t in trades_features if cond1(t) and cond2(t)]
                if len(passed) >= 30:
                    wins_count = sum(1 for t in passed if t['is_win'])
                    winrate = 100 * wins_count / len(passed)
                    if winrate >= 52:
                        improvement = winrate - base_winrate
                        combos_2.append((f"{name1} & {name2}", len(passed), winrate, improvement))

        combos_2.sort(key=lambda x: -x[2])  # 승률 순 정렬
        for name, count, winrate, improvement in combos_2[:20]:
            f.write(f"  {name}: {count}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 3개 조합
        f.write("\nD-3. 3개 조합 (승률 55% 이상, 30건 이상):\n")
        combos_3 = []
        for i, (name1, cond1) in enumerate(conditions):
            for j, (name2, cond2) in enumerate(conditions[i+1:], i+1):
                for name3, cond3 in conditions[j+1:]:
                    passed = [t for t in trades_features if cond1(t) and cond2(t) and cond3(t)]
                    if len(passed) >= 30:
                        wins_count = sum(1 for t in passed if t['is_win'])
                        winrate = 100 * wins_count / len(passed)
                        if winrate >= 55:
                            improvement = winrate - base_winrate
                            combos_3.append((f"{name1} & {name2} & {name3}", len(passed), winrate, improvement))

        combos_3.sort(key=lambda x: -x[2])
        for name, count, winrate, improvement in combos_3[:20]:
            f.write(f"  {name}: {count}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 4개 조합
        f.write("\nD-4. 4개 조합 (승률 58% 이상, 20건 이상):\n")
        combos_4 = []
        for i, (name1, cond1) in enumerate(conditions):
            for j, (name2, cond2) in enumerate(conditions[i+1:], i+1):
                for k, (name3, cond3) in enumerate(conditions[j+1:], j+1):
                    for name4, cond4 in conditions[k+1:]:
                        passed = [t for t in trades_features if cond1(t) and cond2(t) and cond3(t) and cond4(t)]
                        if len(passed) >= 20:
                            wins_count = sum(1 for t in passed if t['is_win'])
                            winrate = 100 * wins_count / len(passed)
                            if winrate >= 58:
                                improvement = winrate - base_winrate
                                combos_4.append((f"{name1} & {name2} & {name3} & {name4}", len(passed), winrate, improvement))

        combos_4.sort(key=lambda x: -x[2])
        for name, count, winrate, improvement in combos_4[:15]:
            f.write(f"  {name}: {count}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("분석 완료\n")
        f.write("=" * 80 + "\n")

    print(f"\n분석 완료! 결과 파일: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
