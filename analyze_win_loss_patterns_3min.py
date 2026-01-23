"""
3분봉 기준 승/패 패턴 분석
DuckDB 캐시에서 3분봉 데이터를 로드하여 필터 최적 임계값 도출

실행:
    python analyze_win_loss_patterns_3min.py
"""

import os
import re
import duckdb
from datetime import datetime, timedelta
from collections import defaultdict
import pandas as pd

# 경로 설정
SIGNAL_LOG_DIR = "D:/GIT/RoboTrader/signal_replay_log"
DUCKDB_PATH = "D:/GIT/RoboTrader/cache/market_data_v2.duckdb"
OUTPUT_FILE = "analysis_3min_filter_report.txt"


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


def extract_trades_from_file(filepath, date_str):
    """파일에서 모든 거래 추출"""
    trades = []

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


def load_3min_data_from_duckdb(conn, stock_code, date_str):
    """DuckDB에서 특정 종목의 3분봉 데이터 로드"""
    table_name = f"minute_{stock_code}"

    try:
        # 테이블 존재 여부 확인
        tables = conn.execute("SHOW TABLES").fetchall()
        table_names = [t[0] for t in tables]

        if table_name not in table_names:
            return None

        # 해당 날짜의 3분봉 데이터 로드
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

        # datetime을 인덱스로 설정
        df['datetime'] = pd.to_datetime(df['datetime'])
        df.set_index('datetime', inplace=True)

        # 3분봉으로 리샘플링 (이미 분봉 데이터가 3분봉일 수 있음)
        # 1분봉이면 3분봉으로 변환
        if len(df) > 100:  # 아마도 1분봉
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
        print(f"  ⚠️ {stock_code} 데이터 로드 실패: {e}")
        return None


def extract_ohlcv_features(df_3min, buy_time_str, date_str):
    """매수 시점 기준 최근 5개 3분봉의 특징 추출"""
    if df_3min is None or df_3min.empty:
        return None

    try:
        # 매수 시간 파싱
        buy_dt = datetime.strptime(f"{date_str} {buy_time_str}", "%Y%m%d %H:%M")

        # 매수 시점 이전의 데이터만 사용
        df_before = df_3min[df_3min.index <= buy_dt]

        if len(df_before) < 5:
            return None

        # 최근 5개 봉
        recent = df_before.tail(5)

        # 캔들 데이터
        candle_bodies = []
        volumes = []
        closes = []

        for _, row in recent.iterrows():
            o = row['open']
            c = row['close']
            candle_bodies.append(c - o)
            volumes.append(row['volume'])
            closes.append(c)

        # 연속 양봉 수
        consecutive_bullish = 0
        for body in reversed(candle_bodies):
            if body > 0:
                consecutive_bullish += 1
            else:
                break

        # 거래량 비율 (최근 1봉 vs 이전 4봉 평균)
        avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
        volume_vs_avg = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

        # 가격 위치 (최근 5봉 범위 내)
        high_5 = recent['high'].max()
        low_5 = recent['low'].min()
        price_position = (closes[-1] - low_5) / (high_5 - low_5) if high_5 > low_5 else 0.5

        # 윗꼬리 비율 (마지막 봉)
        last = recent.iloc[-1]
        last_range = last['high'] - last['low']

        if last_range > 0:
            upper_wick = last['high'] - max(last['open'], last['close'])
            upper_wick_ratio = upper_wick / last_range
        else:
            upper_wick_ratio = 0

        return {
            'consecutive_bullish': consecutive_bullish,
            'volume_vs_avg': volume_vs_avg,
            'price_position': price_position,
            'upper_wick_ratio': upper_wick_ratio,
        }

    except Exception as e:
        return None


def analyze_feature_distribution(trades, feature_name, feature_key, thresholds):
    """특정 특징의 임계값별 승률 분석"""
    results = []

    for threshold in thresholds:
        passed = [t for t in trades if t.get('ohlcv_features', {}).get(feature_key, 0) >= threshold]
        if passed:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            results.append({
                'threshold': threshold,
                'trades': len(passed),
                'wins': wins,
                'winrate': winrate
            })

    return results


def main():
    print("=" * 70)
    print("3분봉 기준 승/패 패턴 분석")
    print("=" * 70)

    # DuckDB 연결
    print("\nDuckDB 연결 중...")
    if not os.path.exists(DUCKDB_PATH):
        print(f"❌ DuckDB 파일이 없습니다: {DUCKDB_PATH}")
        return

    conn = duckdb.connect(DUCKDB_PATH, read_only=True)

    # 모든 거래 로드
    print("\n거래 데이터 로딩 중...")
    all_trades = []

    for filename in sorted(os.listdir(SIGNAL_LOG_DIR)):
        if filename.startswith('signal_new2_replay_') and filename.endswith('.txt'):
            date_match = re.search(r'(\d{8})', filename)
            if date_match:
                date_str = date_match.group(1)
                filepath = os.path.join(SIGNAL_LOG_DIR, filename)
                trades = extract_trades_from_file(filepath, date_str)
                all_trades.extend(trades)

    print(f"총 거래 수: {len(all_trades)}")

    if not all_trades:
        print("❌ 거래 데이터가 없습니다.")
        conn.close()
        return

    # 3분봉 특징 추출
    print("\n3분봉 특징 추출 중...")
    processed = 0
    failed = 0

    # 종목별로 데이터 캐싱
    stock_data_cache = {}

    for i, trade in enumerate(all_trades):
        stock_code = trade['stock_code']
        date_str = trade['date']
        cache_key = f"{stock_code}_{date_str}"

        # 캐시에서 데이터 가져오기
        if cache_key not in stock_data_cache:
            stock_data_cache[cache_key] = load_3min_data_from_duckdb(conn, stock_code, date_str)

        df_3min = stock_data_cache[cache_key]

        if df_3min is not None:
            features = extract_ohlcv_features(df_3min, trade['buy_time'], date_str)
            if features:
                trade['ohlcv_features'] = features
                processed += 1
            else:
                failed += 1
        else:
            failed += 1

        if (i + 1) % 100 == 0:
            print(f"  진행: {i+1}/{len(all_trades)} ({processed} 성공, {failed} 실패)")

    conn.close()

    print(f"\n특징 추출 완료: {processed}건 성공, {failed}건 실패")

    # 특징이 있는 거래만 필터링
    trades_with_features = [t for t in all_trades if 'ohlcv_features' in t]

    if not trades_with_features:
        print("❌ 특징 추출된 거래가 없습니다.")
        return

    # 기본 통계
    total_wins = sum(1 for t in trades_with_features if t['is_win'])
    total_losses = len(trades_with_features) - total_wins
    base_winrate = 100 * total_wins / len(trades_with_features)

    print(f"\n기본 통계 (3분봉 특징 있는 거래):")
    print(f"  거래: {len(trades_with_features)}건 ({total_wins}승 {total_losses}패)")
    print(f"  승률: {base_winrate:.1f}%")

    # 결과 파일 작성
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("3분봉 기준 필터 최적화 분석 보고서\n")
        f.write(f"분석 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"총 거래: {len(trades_with_features)}건 ({total_wins}승 {total_losses}패)\n")
        f.write(f"기본 승률: {base_winrate:.1f}%\n\n")

        # 1. 연속 양봉 분석
        f.write("=" * 80 + "\n")
        f.write("1. 연속 양봉 필터 분석 (3분봉 기준)\n")
        f.write("=" * 80 + "\n")

        for min_count in range(0, 6):
            passed = [t for t in trades_with_features
                     if t['ohlcv_features'].get('consecutive_bullish', 0) >= min_count]
            if passed:
                wins = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  연속양봉 >= {min_count}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 2. 가격 위치 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("2. 가격 위치 필터 분석 (3분봉 기준)\n")
        f.write("=" * 80 + "\n")

        for threshold in [0.5, 0.6, 0.7, 0.8, 0.9]:
            passed = [t for t in trades_with_features
                     if t['ohlcv_features'].get('price_position', 0) >= threshold]
            if passed:
                wins = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  가격위치 >= {threshold*100:.0f}%: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 3. 윗꼬리 비율 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("3. 윗꼬리 비율 필터 분석 (3분봉 기준)\n")
        f.write("=" * 80 + "\n")

        for threshold in [0.05, 0.10, 0.15, 0.20, 0.30]:
            passed = [t for t in trades_with_features
                     if t['ohlcv_features'].get('upper_wick_ratio', 1) <= threshold]
            if passed:
                wins = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  윗꼬리 <= {threshold*100:.0f}%: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 4. 거래량 비율 분석
        f.write("\n" + "=" * 80 + "\n")
        f.write("4. 거래량 비율 필터 분석 (3분봉 기준)\n")
        f.write("=" * 80 + "\n")

        vol_ranges = [(0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 3.0), (3.0, float('inf'))]
        for low, high in vol_ranges:
            if high == float('inf'):
                passed = [t for t in trades_with_features
                         if t['ohlcv_features'].get('volume_vs_avg', 0) >= low]
                label = f">= {low}x"
            else:
                passed = [t for t in trades_with_features
                         if low <= t['ohlcv_features'].get('volume_vs_avg', 0) < high]
                label = f"{low}-{high}x"

            if passed:
                wins = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  거래량 {label}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 5. 복합 필터 테스트
        f.write("\n" + "=" * 80 + "\n")
        f.write("5. 복합 필터 테스트 (3분봉 기준)\n")
        f.write("=" * 80 + "\n")

        # 다양한 조합 테스트
        filter_combinations = [
            {'name': '연속양봉1+', 'filter': lambda t: t['ohlcv_features'].get('consecutive_bullish', 0) >= 1},
            {'name': '가격위치70%+', 'filter': lambda t: t['ohlcv_features'].get('price_position', 0) >= 0.7},
            {'name': '가격위치80%+', 'filter': lambda t: t['ohlcv_features'].get('price_position', 0) >= 0.8},
            {'name': '윗꼬리10%이하', 'filter': lambda t: t['ohlcv_features'].get('upper_wick_ratio', 1) <= 0.1},
            {'name': '거래량1.5x이상', 'filter': lambda t: t['ohlcv_features'].get('volume_vs_avg', 0) >= 1.5},
        ]

        # 개별 필터
        f.write("\n개별 필터 효과:\n")
        for fc in filter_combinations:
            passed = [t for t in trades_with_features if fc['filter'](t)]
            if passed:
                wins = sum(1 for t in passed if t['is_win'])
                winrate = 100 * wins / len(passed)
                improvement = winrate - base_winrate
                f.write(f"  {fc['name']}: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 조합 필터
        f.write("\n조합 필터 효과:\n")

        # 연속양봉1+ + 가격위치70%+
        passed = [t for t in trades_with_features
                 if t['ohlcv_features'].get('consecutive_bullish', 0) >= 1
                 and t['ohlcv_features'].get('price_position', 0) >= 0.7]
        if passed:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            improvement = winrate - base_winrate
            f.write(f"  연속양봉1+ & 가격위치70%+: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 연속양봉1+ + 가격위치80%+
        passed = [t for t in trades_with_features
                 if t['ohlcv_features'].get('consecutive_bullish', 0) >= 1
                 and t['ohlcv_features'].get('price_position', 0) >= 0.8]
        if passed:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            improvement = winrate - base_winrate
            f.write(f"  연속양봉1+ & 가격위치80%+: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 연속양봉2+ + 가격위치70%+
        passed = [t for t in trades_with_features
                 if t['ohlcv_features'].get('consecutive_bullish', 0) >= 2
                 and t['ohlcv_features'].get('price_position', 0) >= 0.7]
        if passed:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            improvement = winrate - base_winrate
            f.write(f"  연속양봉2+ & 가격위치70%+: {len(passed)}건, 승률 {winrate:.1f}% ({improvement:+.1f}%p)\n")

        # 6. 추천 설정
        f.write("\n" + "=" * 80 + "\n")
        f.write("6. 3분봉 기준 추천 설정\n")
        f.write("=" * 80 + "\n")
        f.write("\n위 분석 결과를 바탕으로 config/advanced_filter_settings.py를 업데이트하세요.\n")
        f.write("승률 개선이 가장 높은 임계값을 선택하되, 거래 수가 너무 적지 않도록 균형을 맞추세요.\n")

    print(f"\n분석 완료! 결과 파일: {OUTPUT_FILE}")
    print("\n주요 결과 미리보기:")

    # 콘솔 출력
    print("\n연속 양봉 필터 (3분봉):")
    for min_count in [1, 2, 3]:
        passed = [t for t in trades_with_features
                 if t['ohlcv_features'].get('consecutive_bullish', 0) >= min_count]
        if passed:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            print(f"  >= {min_count}개: {len(passed)}건, 승률 {winrate:.1f}%")

    print("\n가격 위치 필터 (3분봉):")
    for threshold in [0.6, 0.7, 0.8]:
        passed = [t for t in trades_with_features
                 if t['ohlcv_features'].get('price_position', 0) >= threshold]
        if passed:
            wins = sum(1 for t in passed if t['is_win'])
            winrate = 100 * wins / len(passed)
            print(f"  >= {threshold*100:.0f}%: {len(passed)}건, 승률 {winrate:.1f}%")


if __name__ == '__main__':
    main()
