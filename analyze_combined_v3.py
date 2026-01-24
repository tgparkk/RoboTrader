"""
signal_replay_log + pattern_data_log 통합 분석 (v3)
- signal_replay_log: 거래 정보 + DuckDB 3분봉 특성
- pattern_data_log: pattern_stages 정보 (상승폭, 하락폭, 지지캔들 등)
"""

import json
import os
import re
import duckdb
from datetime import datetime, timedelta
from collections import defaultdict
import statistics

SIGNAL_LOG_DIR = "signal_replay_log"
PATTERN_LOG_DIR = "pattern_data_log"
DUCKDB_PATH = "cache/market_data_v2.duckdb"
OUTPUT_FILE = "analysis_combined_v3_report.txt"


def parse_trade_from_simulation(line):
    """체결 시뮬레이션 라인에서 거래 정보 추출"""
    pattern = r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([+-]?\d+\.?\d*)%\)'
    match = re.search(pattern, line)
    if match:
        return {
            'buy_time': match.group(1),
            'buy_signal': match.group(2),
            'buy_price': int(match.group(3).replace(',', '')),
            'sell_time': match.group(4),
            'sell_signal': match.group(5),
            'sell_price': int(match.group(6).replace(',', '')),
            'profit_pct': float(match.group(7))
        }
    return None


def extract_trades_from_signal_log():
    """signal_replay_log에서 모든 거래 추출"""
    trades = []

    for filename in sorted(os.listdir(SIGNAL_LOG_DIR)):
        if not filename.startswith('signal_new2_replay_') or not filename.endswith('.txt'):
            continue

        date_match = re.search(r'(\d{8})', filename)
        if not date_match:
            continue

        date_str = date_match.group(1)
        filepath = os.path.join(SIGNAL_LOG_DIR, filename)

        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.read().split('\n')

        current_stock = None
        in_simulation_section = False

        for line in lines:
            line = line.strip()

            stock_match = re.match(r'=== (\d{6}) - \d{8} 눌림목\(3분\) 신호 재현 ===', line)
            if stock_match:
                current_stock = stock_match.group(1)
                in_simulation_section = False
                continue

            if '체결 시뮬레이션:' in line:
                in_simulation_section = True
                continue

            if in_simulation_section and '매수' in line and '매도' in line and current_stock:
                trade = parse_trade_from_simulation(line)
                if trade:
                    trade['stock_code'] = current_stock
                    trade['date'] = date_str
                    trade['is_win'] = trade['profit_pct'] > 0
                    trades.append(trade)

            if line.startswith('매수 못한 기회:'):
                in_simulation_section = False

    return trades


def load_pattern_data():
    """pattern_data_log에서 pattern_stages 정보 로드"""
    pattern_data = {}  # key: (stock_code, date, buy_time_approx) -> pattern_stages

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
                    stock_code = data.get('stock_code', '')
                    signal_time = data.get('signal_time', '')
                    stages = data.get('pattern_stages', {})

                    if stock_code and signal_time and stages:
                        # signal_time: "2025-10-01 09:21:00"
                        dt = datetime.strptime(signal_time, "%Y-%m-%d %H:%M:%S")
                        date_str = dt.strftime("%Y%m%d")
                        time_str = dt.strftime("%H:%M")

                        key = (stock_code, date_str, time_str)
                        pattern_data[key] = stages

                except (json.JSONDecodeError, ValueError):
                    continue

    return pattern_data


def load_3min_data(conn, stock_code, date_str):
    """DuckDB에서 3분봉 데이터 로드"""
    import pandas as pd
    table_name = f"minute_{stock_code}"

    try:
        tables = conn.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]

        if table_name not in table_names:
            return None

        date_formatted = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]}"

        query = f"""
        SELECT datetime, open, high, low, close, volume
        FROM {table_name}
        WHERE DATE(datetime) = '{date_formatted}'
        ORDER BY datetime
        """

        df = conn.execute(query).fetchdf()

        if df.empty:
            return None

        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)

        # 3분봉으로 리샘플링
        if len(df) > 100:
            df_3min = df.resample('3min').agg({
                'open': 'first',
                'high': 'max',
                'low': 'min',
                'close': 'last',
                'volume': 'sum'
            }).dropna()
            return df_3min
        else:
            return df

    except Exception as e:
        return None


def extract_3min_features(df_3min, buy_time_str, date_str):
    """매수 시점 기준 최근 5개 3분봉 특성 추출"""
    if df_3min is None or df_3min.empty:
        return None

    try:
        buy_dt = datetime.strptime(f"{date_str} {buy_time_str}", "%Y%m%d %H:%M")
        df_before = df_3min[df_3min.index <= buy_dt]

        if len(df_before) < 5:
            return None

        recent = df_before.tail(5)

        # 연속 양봉
        candle_bodies = []
        for _, row in recent.iterrows():
            candle_bodies.append(row['close'] - row['open'])

        consecutive_bullish = 0
        for body in reversed(candle_bodies):
            if body > 0:
                consecutive_bullish += 1
            else:
                break

        # 가격 위치
        high_5 = recent['high'].max()
        low_5 = recent['low'].min()
        current_close = recent.iloc[-1]['close']
        price_position = (current_close - low_5) / (high_5 - low_5) if high_5 > low_5 else 0.5

        # 거래량 비율
        volumes = recent['volume'].tolist()
        avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
        volume_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

        return {
            'consecutive_bullish': consecutive_bullish,
            'price_position': price_position,
            'volume_ratio': volume_ratio,
        }

    except Exception as e:
        return None


def extract_pattern_features(stages):
    """pattern_stages에서 특성 추출"""
    if not stages:
        return {}

    features = {}

    # 1_uptrend
    uptrend = stages.get('1_uptrend', {})
    features['uptrend_candle_count'] = uptrend.get('candle_count', 0)
    features['uptrend_price_gain'] = uptrend.get('price_gain', 0) * 100

    # 2_decline
    decline = stages.get('2_decline', {})
    features['decline_candle_count'] = decline.get('candle_count', 0)
    features['decline_pct'] = decline.get('decline_pct', 0)

    # 3_support
    support = stages.get('3_support', {})
    features['support_candle_count'] = support.get('candle_count', 0)

    # 상승/하락 비율
    if features['decline_pct'] > 0:
        features['rise_decline_ratio'] = features['uptrend_price_gain'] / features['decline_pct']
    else:
        features['rise_decline_ratio'] = 0

    return features


def analyze_range(trades, feature_name, ranges, base_winrate):
    """구간별 승률 분석"""
    results = []

    for low, high in ranges:
        passed = [t for t in trades if low <= t.get(feature_name, -999) < high]

        if len(passed) >= 15:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            improvement = winrate - base_winrate
            results.append({
                'range': f"{low}~{high}",
                'trades': len(passed),
                'winrate': winrate,
                'improvement': improvement
            })

    return results


def main():
    print("=" * 70)
    print("signal_replay_log + pattern_data_log 통합 분석 (v3)")
    print("=" * 70)

    # 1. signal_replay_log에서 거래 추출
    print("\n1. signal_replay_log 거래 로딩...")
    trades = extract_trades_from_signal_log()
    print(f"   거래 수: {len(trades)}")

    # 2. pattern_data_log 로드
    print("\n2. pattern_data_log 로딩...")
    pattern_data = load_pattern_data()
    print(f"   패턴 수: {len(pattern_data)}")

    # 3. DuckDB 연결
    print("\n3. DuckDB 연결...")
    if not os.path.exists(DUCKDB_PATH):
        print(f"   ❌ DuckDB 파일 없음: {DUCKDB_PATH}")
        return
    conn = duckdb.connect(DUCKDB_PATH, read_only=True)

    # 4. 데이터 캐싱 및 특성 추출
    print("\n4. 특성 추출 중...")
    stock_data_cache = {}
    matched = 0
    unmatched = 0

    for i, trade in enumerate(trades):
        stock_code = trade['stock_code']
        date_str = trade['date']
        buy_time = trade['buy_time']

        # DuckDB 3분봉 특성
        cache_key = f"{stock_code}_{date_str}"
        if cache_key not in stock_data_cache:
            stock_data_cache[cache_key] = load_3min_data(conn, stock_code, date_str)

        df_3min = stock_data_cache[cache_key]
        features_3min = extract_3min_features(df_3min, buy_time, date_str)

        if features_3min:
            trade.update(features_3min)

        # pattern_stages 매칭 (시간 ±3분 허용)
        pattern_key = (stock_code, date_str, buy_time)
        stages = pattern_data.get(pattern_key)

        if not stages:
            # ±3분 범위 탐색
            buy_dt = datetime.strptime(f"{date_str} {buy_time}", "%Y%m%d %H:%M")
            for delta in [-3, 3, -6, 6]:
                alt_dt = buy_dt + timedelta(minutes=delta)
                alt_time = alt_dt.strftime("%H:%M")
                alt_key = (stock_code, date_str, alt_time)
                stages = pattern_data.get(alt_key)
                if stages:
                    break

        if stages:
            pattern_features = extract_pattern_features(stages)
            trade.update(pattern_features)
            matched += 1
        else:
            unmatched += 1

        if (i + 1) % 200 == 0:
            print(f"   진행: {i+1}/{len(trades)}")

    conn.close()
    print(f"\n   매칭: {matched}건, 미매칭: {unmatched}건")

    # 5. 분석
    # 3분봉 특성 있는 거래만
    trades_with_3min = [t for t in trades if 'consecutive_bullish' in t]
    # pattern_stages 특성도 있는 거래
    trades_with_both = [t for t in trades_with_3min if 'uptrend_price_gain' in t]

    print(f"\n분석 대상:")
    print(f"   3분봉 특성 있음: {len(trades_with_3min)}건")
    print(f"   pattern_stages도 있음: {len(trades_with_both)}건")

    if not trades_with_3min:
        print("분석할 데이터가 없습니다.")
        return

    # 기본 통계
    wins = sum(1 for t in trades_with_3min if t['is_win'])
    base_winrate = 100 * wins / len(trades_with_3min)

    print(f"\n기본 통계 (3분봉 특성 있는 거래):")
    print(f"   거래: {len(trades_with_3min)}건 ({wins}승 {len(trades_with_3min)-wins}패)")
    print(f"   승률: {base_winrate:.1f}%")

    # 결과 파일 작성
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("signal_replay_log + pattern_data_log 통합 분석 보고서 (v3)\n")
        f.write(f"분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"총 거래: {len(trades_with_3min)}건 ({wins}승 {len(trades_with_3min)-wins}패)\n")
        f.write(f"기본 승률: {base_winrate:.1f}%\n")
        f.write(f"pattern_stages 매칭: {len(trades_with_both)}건\n\n")

        # A. 3분봉 기반 분석 (기존)
        f.write("=" * 80 + "\n")
        f.write("A. 3분봉 기반 분석 (DuckDB)\n")
        f.write("=" * 80 + "\n")

        f.write("\nA-1. 연속 양봉:\n")
        for min_count in range(0, 6):
            passed = [t for t in trades_with_3min if t.get('consecutive_bullish', 0) >= min_count]
            if len(passed) >= 10:
                wins_c = sum(1 for t in passed if t['is_win'])
                wr = 100 * wins_c / len(passed)
                f.write(f"  >= {min_count}: {len(passed)}건, 승률 {wr:.1f}% ({wr-base_winrate:+.1f}%p)\n")

        f.write("\nA-2. 가격 위치:\n")
        for threshold in [0.5, 0.6, 0.7, 0.8, 0.9]:
            passed = [t for t in trades_with_3min if t.get('price_position', 0) >= threshold]
            if len(passed) >= 10:
                wins_c = sum(1 for t in passed if t['is_win'])
                wr = 100 * wins_c / len(passed)
                f.write(f"  >= {threshold*100:.0f}%: {len(passed)}건, 승률 {wr:.1f}% ({wr-base_winrate:+.1f}%p)\n")

        # B. pattern_stages 분석
        if trades_with_both:
            base_winrate_both = 100 * sum(1 for t in trades_with_both if t['is_win']) / len(trades_with_both)

            f.write("\n" + "=" * 80 + "\n")
            f.write(f"B. pattern_stages 분석 ({len(trades_with_both)}건, 기본승률 {base_winrate_both:.1f}%)\n")
            f.write("=" * 80 + "\n")

            f.write("\nB-1. 상승폭 (uptrend_price_gain %):\n")
            results = analyze_range(trades_with_both, 'uptrend_price_gain',
                                   [(0,3), (3,5), (5,10), (10,15), (15,30)], base_winrate_both)
            for r in results:
                f.write(f"  {r['range']}%: {r['trades']}건, 승률 {r['winrate']:.1f}% ({r['improvement']:+.1f}%p)\n")

            f.write("\nB-2. 하락폭 (decline_pct %):\n")
            results = analyze_range(trades_with_both, 'decline_pct',
                                   [(0,2), (2,3), (3,4), (4,5), (5,10)], base_winrate_both)
            for r in results:
                f.write(f"  {r['range']}%: {r['trades']}건, 승률 {r['winrate']:.1f}% ({r['improvement']:+.1f}%p)\n")

            f.write("\nB-3. 지지구간 캔들 수:\n")
            results = analyze_range(trades_with_both, 'support_candle_count',
                                   [(1,2), (2,3), (3,4), (4,10)], base_winrate_both)
            for r in results:
                f.write(f"  {r['range']}개: {r['trades']}건, 승률 {r['winrate']:.1f}% ({r['improvement']:+.1f}%p)\n")

            f.write("\nB-4. 상승/하락 비율:\n")
            results = analyze_range(trades_with_both, 'rise_decline_ratio',
                                   [(0,1), (1,2), (2,3), (3,5), (5,10), (10,100)], base_winrate_both)
            for r in results:
                f.write(f"  {r['range']}: {r['trades']}건, 승률 {r['winrate']:.1f}% ({r['improvement']:+.1f}%p)\n")

        # C. 복합 조건 탐색
        f.write("\n" + "=" * 80 + "\n")
        f.write("C. 복합 조건 탐색\n")
        f.write("=" * 80 + "\n")

        conditions = [
            # 3분봉 기반
            ('연속양봉>=1', lambda t: t.get('consecutive_bullish', 0) >= 1),
            ('연속양봉>=2', lambda t: t.get('consecutive_bullish', 0) >= 2),
            ('가격위치>=70%', lambda t: t.get('price_position', 0) >= 0.7),
            ('가격위치>=80%', lambda t: t.get('price_position', 0) >= 0.8),
            ('가격위치>=90%', lambda t: t.get('price_position', 0) >= 0.9),
            ('거래량>=1.5x', lambda t: t.get('volume_ratio', 0) >= 1.5),
            # pattern_stages 기반
            ('상승폭<10%', lambda t: t.get('uptrend_price_gain', 100) < 10),
            ('상승폭<15%', lambda t: t.get('uptrend_price_gain', 100) < 15),
            ('하락폭<3%', lambda t: t.get('decline_pct', 100) < 3),
            ('하락폭<5%', lambda t: t.get('decline_pct', 100) < 5),
            ('지지캔들<=2', lambda t: t.get('support_candle_count', 100) <= 2),
            ('지지캔들!=3', lambda t: t.get('support_candle_count', 0) != 3),
        ]

        # pattern_stages 있는 데이터로 분석
        analysis_data = trades_with_both if trades_with_both else trades_with_3min
        base_wr = 100 * sum(1 for t in analysis_data if t['is_win']) / len(analysis_data)

        f.write(f"\n분석 대상: {len(analysis_data)}건 (기본승률 {base_wr:.1f}%)\n")

        f.write("\nC-1. 개별 조건:\n")
        for name, cond in conditions:
            passed = [t for t in analysis_data if cond(t)]
            if len(passed) >= 20:
                wins_c = sum(1 for t in passed if t['is_win'])
                wr = 100 * wins_c / len(passed)
                f.write(f"  {name}: {len(passed)}건, 승률 {wr:.1f}% ({wr-base_wr:+.1f}%p)\n")

        # 2개 조합
        f.write("\nC-2. 2개 조합 (승률 55% 이상, 20건 이상):\n")
        combos = []
        for i, (name1, cond1) in enumerate(conditions):
            for name2, cond2 in conditions[i+1:]:
                passed = [t for t in analysis_data if cond1(t) and cond2(t)]
                if len(passed) >= 20:
                    wins_c = sum(1 for t in passed if t['is_win'])
                    wr = 100 * wins_c / len(passed)
                    if wr >= 55:
                        combos.append((f"{name1} & {name2}", len(passed), wr, wr-base_wr))

        combos.sort(key=lambda x: -x[2])
        for name, count, wr, imp in combos[:15]:
            f.write(f"  {name}: {count}건, 승률 {wr:.1f}% ({imp:+.1f}%p)\n")

        # 3개 조합
        f.write("\nC-3. 3개 조합 (승률 60% 이상, 20건 이상):\n")
        combos = []
        for i, (name1, cond1) in enumerate(conditions):
            for j, (name2, cond2) in enumerate(conditions[i+1:], i+1):
                for name3, cond3 in conditions[j+1:]:
                    passed = [t for t in analysis_data if cond1(t) and cond2(t) and cond3(t)]
                    if len(passed) >= 20:
                        wins_c = sum(1 for t in passed if t['is_win'])
                        wr = 100 * wins_c / len(passed)
                        if wr >= 60:
                            combos.append((f"{name1} & {name2} & {name3}", len(passed), wr, wr-base_wr))

        combos.sort(key=lambda x: -x[2])
        for name, count, wr, imp in combos[:15]:
            f.write(f"  {name}: {count}건, 승률 {wr:.1f}% ({imp:+.1f}%p)\n")

        # 4개 조합
        f.write("\nC-4. 4개 조합 (승률 65% 이상, 15건 이상):\n")
        combos = []
        for i, (name1, cond1) in enumerate(conditions):
            for j, (name2, cond2) in enumerate(conditions[i+1:], i+1):
                for k, (name3, cond3) in enumerate(conditions[j+1:], j+1):
                    for name4, cond4 in conditions[k+1:]:
                        passed = [t for t in analysis_data if cond1(t) and cond2(t) and cond3(t) and cond4(t)]
                        if len(passed) >= 15:
                            wins_c = sum(1 for t in passed if t['is_win'])
                            wr = 100 * wins_c / len(passed)
                            if wr >= 65:
                                combos.append((f"{name1} & {name2} & {name3} & {name4}", len(passed), wr, wr-base_wr))

        combos.sort(key=lambda x: -x[2])
        for name, count, wr, imp in combos[:10]:
            f.write(f"  {name}: {count}건, 승률 {wr:.1f}% ({imp:+.1f}%p)\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("분석 완료\n")
        f.write("=" * 80 + "\n")

    print(f"\n분석 완료! 결과 파일: {OUTPUT_FILE}")


if __name__ == '__main__':
    main()
