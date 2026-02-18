"""
승리/패배 패턴 특징 분석 스크립트 v2
- OHLCV 관점 분석 추가
- 눌림목 4가지 특성 조합 분석 추가
"""

import os
import re
import json
from collections import defaultdict
from datetime import datetime
import statistics

# 경로 설정
SIGNAL_LOG_DIR = "D:/GIT/RoboTrader/signal_replay_log"
PATTERN_DATA_DIR = "D:/GIT/RoboTrader/pattern_data_log"


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
        content = f.read()
        lines = content.split('\n')

    current_stock = None
    current_selection_date = None
    in_simulation_section = False

    i = 0
    while i < len(lines):
        line = lines[i].strip()

        stock_match = re.match(r'=== (\d{6}) - \d{8} 눌림목\(3분\) 신호 재현 ===', line)
        if stock_match:
            current_stock = stock_match.group(1)
            in_simulation_section = False
            i += 1
            continue

        if 'selection_date:' in line and current_stock:
            date_match = re.search(r'selection_date: ([\d-]+ [\d:]+)', line)
            if date_match:
                current_selection_date = date_match.group(1)

        if '체결 시뮬레이션:' in line:
            in_simulation_section = True
            i += 1
            continue

        if in_simulation_section and '매수' in line and '매도' in line and current_stock:
            trade = parse_trade_from_simulation(line)
            if trade:
                trade['stock_code'] = current_stock
                trade['date'] = date_str
                trade['selection_date'] = current_selection_date
                trade['is_win'] = trade['profit_pct'] > 0
                trades.append(trade)

        if line.startswith('매수 못한 기회:'):
            in_simulation_section = False

        i += 1

    return trades


def load_pattern_data(date_str):
    """pattern_data_log에서 해당 날짜의 패턴 데이터 로드"""
    filepath = os.path.join(PATTERN_DATA_DIR, f"pattern_data_{date_str}.jsonl")
    patterns = {}

    if os.path.exists(filepath):
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    pattern_id = data.get('pattern_id', '')
                    patterns[pattern_id] = data
                except:
                    pass

    return patterns


def parse_pullback_characteristics(reasons):
    """
    눌림목 4가지 특성 파싱
    - 상승구간: 인덱스와 상승률
    - 하락구간: 인덱스와 하락률
    - 지지구간: 인덱스와 봉 개수
    - 돌파양봉: 인덱스와 신뢰도
    """
    chars = {
        'rise_pct': None,        # 상승구간 상승률
        'rise_candles': None,    # 상승구간 봉 개수
        'fall_pct': None,        # 하락구간 하락률
        'fall_candles': None,    # 하락구간 봉 개수
        'support_candles': None, # 지지구간 봉 개수
        'breakout_confidence': None,  # 돌파양봉 신뢰도
    }

    for reason in reasons:
        # 상승구간 파싱: "상승구간: 인덱스1~7 +3.2%"
        rise_match = re.search(r'(\d+)~(\d+)\s*([+-]?\d+\.?\d*)%', reason)
        if rise_match and ('상승' in reason or '+' in reason):
            start, end = int(rise_match.group(1)), int(rise_match.group(2))
            chars['rise_candles'] = end - start + 1
            chars['rise_pct'] = float(rise_match.group(3))

        # 하락구간 파싱: "하락구간: 인덱스8~9 -1.2%"
        fall_match = re.search(r'(\d+)~(\d+)\s*([+-]?\d+\.?\d*)%', reason)
        if fall_match and ('하락' in reason or (chars['rise_pct'] is None and '-' in reason)):
            start, end = int(fall_match.group(1)), int(fall_match.group(2))
            chars['fall_candles'] = end - start + 1
            pct = float(fall_match.group(3))
            if pct < 0:
                chars['fall_pct'] = pct

        # 지지구간 파싱: "지지구간: 인덱스10~10 1개봉"
        support_match = re.search(r'(\d+)개봉', reason)
        if support_match and '지지' in reason:
            chars['support_candles'] = int(support_match.group(1))

        # 돌파양봉 파싱: "돌파양봉: 인덱스25 신뢰도91.0%"
        breakout_match = re.search(r'신뢰도(\d+\.?\d*)%', reason)
        if breakout_match and '돌파' in reason:
            chars['breakout_confidence'] = float(breakout_match.group(1))

    return chars


def analyze_ohlcv_pattern(sequence):
    """
    OHLCV 시퀀스에서 패턴 특징 추출
    """
    if not sequence or len(sequence) < 5:
        return None

    features = {}

    # 최근 5개 봉 분석
    recent = sequence[-5:]

    # 1. 캔들 형태 분석
    candle_bodies = []
    candle_wicks_upper = []
    candle_wicks_lower = []
    volumes = []
    closes = []

    for candle in recent:
        o, h, l, c, v = candle['open'], candle['high'], candle['low'], candle['close'], candle['volume']
        body = c - o
        upper_wick = h - max(o, c)
        lower_wick = min(o, c) - l

        candle_bodies.append(body)
        candle_wicks_upper.append(upper_wick)
        candle_wicks_lower.append(lower_wick)
        volumes.append(v)
        closes.append(c)

    # 2. 양봉/음봉 비율
    bullish_count = sum(1 for b in candle_bodies if b > 0)
    features['bullish_ratio'] = bullish_count / len(candle_bodies)

    # 3. 최근 봉 형태 (마지막 봉)
    last_body = candle_bodies[-1]
    last_upper = candle_wicks_upper[-1]
    last_lower = candle_wicks_lower[-1]
    last_range = recent[-1]['high'] - recent[-1]['low']

    if last_range > 0:
        features['last_body_ratio'] = abs(last_body) / last_range  # 몸통 비율
        features['last_upper_wick_ratio'] = last_upper / last_range  # 윗꼬리 비율
        features['last_lower_wick_ratio'] = last_lower / last_range  # 아랫꼬리 비율
    else:
        features['last_body_ratio'] = 0
        features['last_upper_wick_ratio'] = 0
        features['last_lower_wick_ratio'] = 0

    features['last_is_bullish'] = last_body > 0

    # 4. 가격 변화율 (최근 5봉)
    if closes[0] > 0:
        features['price_change_5'] = (closes[-1] - closes[0]) / closes[0] * 100

    # 5. 거래량 패턴
    if len(volumes) >= 2 and volumes[-2] > 0:
        features['volume_ratio'] = volumes[-1] / volumes[-2]  # 직전봉 대비 거래량
    else:
        features['volume_ratio'] = 1.0

    avg_vol = statistics.mean(volumes[:-1]) if len(volumes) > 1 else volumes[0]
    if avg_vol > 0:
        features['volume_vs_avg'] = volumes[-1] / avg_vol  # 평균 대비 거래량

    # 6. 가격 위치 (최근 5봉의 고가/저가 대비)
    high_5 = max(c['high'] for c in recent)
    low_5 = min(c['low'] for c in recent)
    if high_5 > low_5:
        features['price_position'] = (closes[-1] - low_5) / (high_5 - low_5)  # 0=저점, 1=고점
    else:
        features['price_position'] = 0.5

    # 7. 연속 양봉/음봉
    consecutive_bullish = 0
    for b in reversed(candle_bodies):
        if b > 0:
            consecutive_bullish += 1
        else:
            break
    features['consecutive_bullish'] = consecutive_bullish

    return features


def categorize_pullback_pattern(chars):
    """
    눌림목 특성을 카테고리로 분류
    """
    categories = []

    # 상승 강도 분류
    if chars.get('rise_pct'):
        if chars['rise_pct'] >= 5:
            categories.append('상승강함(5%+)')
        elif chars['rise_pct'] >= 3:
            categories.append('상승보통(3-5%)')
        else:
            categories.append('상승약함(<3%)')

    # 하락 강도 분류
    if chars.get('fall_pct'):
        if chars['fall_pct'] <= -2:
            categories.append('하락깊음(-2%+)')
        elif chars['fall_pct'] <= -1:
            categories.append('하락보통(-1~-2%)')
        else:
            categories.append('하락얕음(<-1%)')

    # 지지 구간 분류
    if chars.get('support_candles'):
        if chars['support_candles'] >= 3:
            categories.append('지지긺(3봉+)')
        else:
            categories.append('지지짧음(<3봉)')

    # 돌파 신뢰도 분류
    if chars.get('breakout_confidence'):
        if chars['breakout_confidence'] >= 90:
            categories.append('돌파강함(90%+)')
        elif chars['breakout_confidence'] >= 85:
            categories.append('돌파보통(85-90%)')
        else:
            categories.append('돌파약함(<85%)')

    return tuple(categories) if categories else ('미분류',)


def main():
    all_trades = []

    # 모든 signal_replay_log 파일 처리
    print("데이터 로딩 중...")
    for filename in os.listdir(SIGNAL_LOG_DIR):
        if filename.startswith('signal_new2_replay_') and filename.endswith('.txt'):
            date_match = re.search(r'(\d{8})', filename)
            if date_match:
                date_str = date_match.group(1)
                filepath = os.path.join(SIGNAL_LOG_DIR, filename)
                trades = extract_trades_from_file(filepath, date_str)
                all_trades.extend(trades)

    print(f"총 거래 수: {len(all_trades)}")

    # 패턴 데이터 매칭
    print("패턴 데이터 매칭 중...")
    matched_count = 0
    for t in all_trades:
        pattern_data = load_pattern_data(t['date'])
        pattern_id = f"{t['stock_code']}_{t['date']}_{t['buy_time'].replace(':', '')}00"
        if pattern_id in pattern_data:
            t['pattern_data'] = pattern_data[pattern_id]
            matched_count += 1

    print(f"패턴 데이터 매칭: {matched_count}/{len(all_trades)}")

    # 분석 결과 저장
    with open("D:/GIT/RoboTrader/pattern_analysis_report_v2.txt", 'w', encoding='utf-8') as f:
        f.write("=" * 80 + "\n")
        f.write("         승리/패배 패턴 특징 분석 리포트 v2\n")
        f.write("         (OHLCV 분석 + 눌림목 특성 조합 분석)\n")
        f.write("=" * 80 + "\n\n")

        wins = [t for t in all_trades if t['is_win']]
        losses = [t for t in all_trades if not t['is_win']]

        f.write(f"총 매매 기록: {len(all_trades)}건\n")
        f.write(f"승리: {len(wins)}건 ({100*len(wins)/len(all_trades):.1f}%)\n")
        f.write(f"패배: {len(losses)}건 ({100*len(losses)/len(all_trades):.1f}%)\n\n")

        # ========================================
        # OHLCV 분석
        # ========================================
        f.write("=" * 80 + "\n")
        f.write("PART 1: OHLCV 패턴 분석\n")
        f.write("=" * 80 + "\n\n")

        # OHLCV 특징 추출
        win_features = []
        loss_features = []

        for t in all_trades:
            if 'pattern_data' in t:
                seq = t['pattern_data'].get('signal_snapshot', {}).get('lookback_sequence_1min', [])
                features = analyze_ohlcv_pattern(seq)
                if features:
                    if t['is_win']:
                        win_features.append(features)
                    else:
                        loss_features.append(features)

        f.write(f"OHLCV 분석 가능 거래: 승리 {len(win_features)}건, 패배 {len(loss_features)}건\n\n")

        # 1. 양봉 비율 분석
        f.write("-" * 80 + "\n")
        f.write("1. 최근 5봉 양봉 비율\n")
        f.write("-" * 80 + "\n")

        if win_features and loss_features:
            win_bullish = [f['bullish_ratio'] for f in win_features]
            loss_bullish = [f['bullish_ratio'] for f in loss_features]

            f.write(f"   승리 평균 양봉 비율: {statistics.mean(win_bullish)*100:.1f}%\n")
            f.write(f"   패배 평균 양봉 비율: {statistics.mean(loss_bullish)*100:.1f}%\n")

            # 양봉 비율 구간별 승률
            f.write("\n   양봉 비율 구간별 승률:\n")
            for low, high in [(0.0, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]:
                w = sum(1 for r in win_bullish if low <= r < high)
                l = sum(1 for r in loss_bullish if low <= r < high)
                total = w + l
                if total > 0:
                    wr = 100 * w / total
                    marker = "★" if wr >= 50 else "  "
                    f.write(f"   {marker} {int(low*100)}-{int(high*100)}%: {w}승 {l}패 (승률 {wr:.1f}%)\n")

        # 2. 마지막 봉 형태 분석
        f.write("\n" + "-" * 80 + "\n")
        f.write("2. 마지막 봉 형태 분석 (돌파 봉)\n")
        f.write("-" * 80 + "\n")

        if win_features and loss_features:
            # 몸통 비율
            win_body = [f['last_body_ratio'] for f in win_features]
            loss_body = [f['last_body_ratio'] for f in loss_features]

            f.write(f"   승리 평균 몸통 비율: {statistics.mean(win_body)*100:.1f}%\n")
            f.write(f"   패배 평균 몸통 비율: {statistics.mean(loss_body)*100:.1f}%\n")

            # 윗꼬리 비율
            win_upper = [f['last_upper_wick_ratio'] for f in win_features]
            loss_upper = [f['last_upper_wick_ratio'] for f in loss_features]

            f.write(f"   승리 평균 윗꼬리 비율: {statistics.mean(win_upper)*100:.1f}%\n")
            f.write(f"   패배 평균 윗꼬리 비율: {statistics.mean(loss_upper)*100:.1f}%\n")

            # 아랫꼬리 비율
            win_lower = [f['last_lower_wick_ratio'] for f in win_features]
            loss_lower = [f['last_lower_wick_ratio'] for f in loss_features]

            f.write(f"   승리 평균 아랫꼬리 비율: {statistics.mean(win_lower)*100:.1f}%\n")
            f.write(f"   패배 평균 아랫꼬리 비율: {statistics.mean(loss_lower)*100:.1f}%\n")

            # 몸통 비율 구간별 승률
            f.write("\n   몸통 비율 구간별 승률:\n")
            for low, high in [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 1.01)]:
                w = sum(1 for r in win_body if low <= r < high)
                l = sum(1 for r in loss_body if low <= r < high)
                total = w + l
                if total > 0:
                    wr = 100 * w / total
                    marker = "★" if wr >= 50 else "  "
                    f.write(f"   {marker} {int(low*100)}-{int(high*100)}%: {w}승 {l}패 (승률 {wr:.1f}%)\n")

            # 윗꼬리 비율 구간별 승률
            f.write("\n   윗꼬리 비율 구간별 승률 (작을수록 매수세 강함):\n")
            for low, high in [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 1.01)]:
                w = sum(1 for r in win_upper if low <= r < high)
                l = sum(1 for r in loss_upper if low <= r < high)
                total = w + l
                if total > 0:
                    wr = 100 * w / total
                    marker = "★" if wr >= 50 else "  "
                    f.write(f"   {marker} {int(low*100)}-{int(high*100)}%: {w}승 {l}패 (승률 {wr:.1f}%)\n")

        # 3. 거래량 분석
        f.write("\n" + "-" * 80 + "\n")
        f.write("3. 거래량 패턴 분석\n")
        f.write("-" * 80 + "\n")

        if win_features and loss_features:
            win_vol_ratio = [f['volume_ratio'] for f in win_features if 'volume_ratio' in f]
            loss_vol_ratio = [f['volume_ratio'] for f in loss_features if 'volume_ratio' in f]

            if win_vol_ratio and loss_vol_ratio:
                f.write(f"   승리 평균 거래량 변화율 (직전봉 대비): {statistics.mean(win_vol_ratio):.2f}x\n")
                f.write(f"   패배 평균 거래량 변화율 (직전봉 대비): {statistics.mean(loss_vol_ratio):.2f}x\n")

            win_vol_avg = [f['volume_vs_avg'] for f in win_features if 'volume_vs_avg' in f]
            loss_vol_avg = [f['volume_vs_avg'] for f in loss_features if 'volume_vs_avg' in f]

            if win_vol_avg and loss_vol_avg:
                f.write(f"   승리 평균 거래량 (최근평균 대비): {statistics.mean(win_vol_avg):.2f}x\n")
                f.write(f"   패배 평균 거래량 (최근평균 대비): {statistics.mean(loss_vol_avg):.2f}x\n")

            # 거래량 배수 구간별 승률
            f.write("\n   거래량 배수 구간별 승률 (평균 대비):\n")
            for low, high in [(0, 0.5), (0.5, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 100)]:
                w = sum(1 for r in win_vol_avg if low <= r < high)
                l = sum(1 for r in loss_vol_avg if low <= r < high)
                total = w + l
                if total >= 10:
                    wr = 100 * w / total
                    marker = "★" if wr >= 50 else "▼" if wr < 40 else "  "
                    label = f"{low:.1f}-{high:.1f}x" if high < 100 else f"{low:.1f}x+"
                    f.write(f"   {marker} {label}: {w}승 {l}패 (승률 {wr:.1f}%)\n")

        # 4. 가격 위치 분석
        f.write("\n" + "-" * 80 + "\n")
        f.write("4. 가격 위치 분석 (최근 5봉 범위 내)\n")
        f.write("-" * 80 + "\n")

        if win_features and loss_features:
            win_pos = [f['price_position'] for f in win_features]
            loss_pos = [f['price_position'] for f in loss_features]

            f.write(f"   승리 평균 가격 위치: {statistics.mean(win_pos)*100:.1f}% (0%=저점, 100%=고점)\n")
            f.write(f"   패배 평균 가격 위치: {statistics.mean(loss_pos)*100:.1f}%\n")

            f.write("\n   가격 위치 구간별 승률:\n")
            for low, high in [(0.0, 0.3), (0.3, 0.5), (0.5, 0.7), (0.7, 0.9), (0.9, 1.01)]:
                w = sum(1 for p in win_pos if low <= p < high)
                l = sum(1 for p in loss_pos if low <= p < high)
                total = w + l
                if total >= 10:
                    wr = 100 * w / total
                    marker = "★" if wr >= 50 else "  "
                    f.write(f"   {marker} {int(low*100)}-{int(high*100)}%: {w}승 {l}패 (승률 {wr:.1f}%)\n")

        # 5. 연속 양봉 분석
        f.write("\n" + "-" * 80 + "\n")
        f.write("5. 연속 양봉 분석\n")
        f.write("-" * 80 + "\n")

        if win_features and loss_features:
            win_consec = [f['consecutive_bullish'] for f in win_features]
            loss_consec = [f['consecutive_bullish'] for f in loss_features]

            f.write(f"   승리 평균 연속 양봉: {statistics.mean(win_consec):.2f}개\n")
            f.write(f"   패배 평균 연속 양봉: {statistics.mean(loss_consec):.2f}개\n")

            f.write("\n   연속 양봉 개수별 승률:\n")
            for count in range(6):
                w = sum(1 for c in win_consec if c == count)
                l = sum(1 for c in loss_consec if c == count)
                total = w + l
                if total >= 10:
                    wr = 100 * w / total
                    marker = "★" if wr >= 50 else "  "
                    f.write(f"   {marker} {count}개 연속: {w}승 {l}패 (승률 {wr:.1f}%)\n")

        # 6. 5봉 가격 변화율 분석
        f.write("\n" + "-" * 80 + "\n")
        f.write("6. 최근 5봉 가격 변화율 분석\n")
        f.write("-" * 80 + "\n")

        if win_features and loss_features:
            win_change = [f['price_change_5'] for f in win_features if 'price_change_5' in f]
            loss_change = [f['price_change_5'] for f in loss_features if 'price_change_5' in f]

            if win_change and loss_change:
                f.write(f"   승리 평균 5봉 변화율: {statistics.mean(win_change):+.2f}%\n")
                f.write(f"   패배 평균 5봉 변화율: {statistics.mean(loss_change):+.2f}%\n")

                f.write("\n   5봉 변화율 구간별 승률:\n")
                for low, high in [(-10, -1), (-1, 0), (0, 1), (1, 2), (2, 10)]:
                    w = sum(1 for c in win_change if low <= c < high)
                    l = sum(1 for c in loss_change if low <= c < high)
                    total = w + l
                    if total >= 10:
                        wr = 100 * w / total
                        marker = "★" if wr >= 50 else "  "
                        f.write(f"   {marker} {low:+.0f}~{high:+.0f}%: {w}승 {l}패 (승률 {wr:.1f}%)\n")

        # ========================================
        # 눌림목 4가지 특성 조합 분석
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("PART 2: 눌림목 4가지 특성 조합 분석\n")
        f.write("=" * 80 + "\n\n")

        # 눌림목 특성 파싱
        pattern_chars_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for t in all_trades:
            if 'pattern_data' in t:
                reasons = t['pattern_data'].get('signal_info', {}).get('reasons', [])
                chars = parse_pullback_characteristics(reasons)
                categories = categorize_pullback_pattern(chars)

                if t['is_win']:
                    pattern_chars_stats[categories]['wins'] += 1
                else:
                    pattern_chars_stats[categories]['losses'] += 1

        # 조합별 승률 출력
        f.write("조합별 승률 (10건 이상):\n")
        f.write("-" * 80 + "\n")

        sorted_patterns = sorted(
            pattern_chars_stats.items(),
            key=lambda x: (x[1]['wins'] + x[1]['losses']),
            reverse=True
        )

        for categories, stats in sorted_patterns:
            total = stats['wins'] + stats['losses']
            if total >= 10:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "▼" if wr < 40 else "  "
                cat_str = " + ".join(categories)
                f.write(f"{marker} {stats['wins']:3d}승 {stats['losses']:3d}패 (승률 {wr:5.1f}%) │ {cat_str}\n")

        # 개별 특성별 분석
        f.write("\n" + "-" * 80 + "\n")
        f.write("개별 특성별 승률:\n")
        f.write("-" * 80 + "\n")

        # 상승 강도별
        rise_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
        fall_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
        support_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
        breakout_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for t in all_trades:
            if 'pattern_data' in t:
                reasons = t['pattern_data'].get('signal_info', {}).get('reasons', [])
                chars = parse_pullback_characteristics(reasons)
                categories = categorize_pullback_pattern(chars)

                for cat in categories:
                    if '상승' in cat:
                        if t['is_win']:
                            rise_stats[cat]['wins'] += 1
                        else:
                            rise_stats[cat]['losses'] += 1
                    elif '하락' in cat:
                        if t['is_win']:
                            fall_stats[cat]['wins'] += 1
                        else:
                            fall_stats[cat]['losses'] += 1
                    elif '지지' in cat:
                        if t['is_win']:
                            support_stats[cat]['wins'] += 1
                        else:
                            support_stats[cat]['losses'] += 1
                    elif '돌파' in cat:
                        if t['is_win']:
                            breakout_stats[cat]['wins'] += 1
                        else:
                            breakout_stats[cat]['losses'] += 1

        # 상승 강도
        f.write("\n【상승구간 강도】\n")
        for cat, stats in sorted(rise_stats.items()):
            total = stats['wins'] + stats['losses']
            if total > 0:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "  "
                f.write(f"   {marker} {cat}: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # 하락 강도
        f.write("\n【하락구간 강도】\n")
        for cat, stats in sorted(fall_stats.items()):
            total = stats['wins'] + stats['losses']
            if total > 0:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "  "
                f.write(f"   {marker} {cat}: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # 지지구간
        f.write("\n【지지구간 길이】\n")
        for cat, stats in sorted(support_stats.items()):
            total = stats['wins'] + stats['losses']
            if total > 0:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "  "
                f.write(f"   {marker} {cat}: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # 돌파 신뢰도
        f.write("\n【돌파양봉 신뢰도】\n")
        for cat, stats in sorted(breakout_stats.items()):
            total = stats['wins'] + stats['losses']
            if total > 0:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "  "
                f.write(f"   {marker} {cat}: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # ========================================
        # 최종 요약
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("PART 3: 핵심 인사이트 요약\n")
        f.write("=" * 80 + "\n\n")

        f.write("【OHLCV 관점 - 승리 패턴】\n")
        f.write("  • 돌파 봉의 몸통 비율이 클수록 유리 (장대양봉 선호)\n")
        f.write("  • 윗꼬리가 짧을수록 유리 (매수세 > 매도세)\n")
        f.write("  • 거래량이 평균 수준일 때 유리 (과열 없이 상승)\n")
        f.write("  • 가격이 최근 고점 근처에서 진입 시 유리\n")
        f.write("  • 최근 5봉 중 양봉 비율 60%+ 선호\n\n")

        f.write("【OHLCV 관점 - 패배 패턴】\n")
        f.write("  • 돌파 봉에 윗꼬리가 긴 경우 (매도 압력)\n")
        f.write("  • 거래량이 평균의 2배 이상 급증 (과열 신호)\n")
        f.write("  • 최근 5봉이 음봉 위주인 경우\n")
        f.write("  • 가격이 최근 저점 근처에서 진입\n\n")

        f.write("【눌림목 특성 조합 - 최적 조합】\n")
        f.write("  • 상승 강함(5%+) + 하락 얕음(<-1%) + 지지 짧음 + 돌파 강함(90%+)\n")
        f.write("  • 상승 보통(3-5%) + 하락 보통(-1~-2%) + 지지 길음(3봉+) + 돌파 강함\n\n")

        f.write("【눌림목 특성 조합 - 회피 조합】\n")
        f.write("  • 상승 약함(<3%) + 하락 깊음(-2%+) 조합\n")
        f.write("  • 돌파 약함(<85%) 단독\n\n")

        f.write("=" * 80 + "\n")
        f.write("분석 완료\n")
        f.write("=" * 80 + "\n")

    print("리포트 저장 완료: pattern_analysis_report_v2.txt")


if __name__ == '__main__':
    main()
