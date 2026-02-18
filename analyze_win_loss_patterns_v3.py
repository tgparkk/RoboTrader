"""
승리/패배 패턴 심층 분석 스크립트 v3
- 종목별 승률 분석
- 복합 필터 시뮬레이션
- 손익비 최적화 분석
- 시간대 + 요일 교차 분석
- 기술적 지표 조합 분석
- 최적 진입 조건 탐색
"""

import os
import re
import json
from collections import defaultdict
from datetime import datetime
import statistics
from itertools import combinations

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


def analyze_ohlcv_features(sequence):
    """OHLCV 시퀀스에서 특징 추출"""
    if not sequence or len(sequence) < 5:
        return None

    features = {}
    recent = sequence[-5:]

    # 캔들 데이터 추출
    candle_bodies = []
    volumes = []
    closes = []

    for candle in recent:
        o, h, l, c, v = candle['open'], candle['high'], candle['low'], candle['close'], candle['volume']
        body = c - o
        candle_bodies.append(body)
        volumes.append(v)
        closes.append(c)

    # 양봉 비율
    bullish_count = sum(1 for b in candle_bodies if b > 0)
    features['bullish_ratio'] = bullish_count / len(candle_bodies)

    # 연속 양봉
    consecutive_bullish = 0
    for b in reversed(candle_bodies):
        if b > 0:
            consecutive_bullish += 1
        else:
            break
    features['consecutive_bullish'] = consecutive_bullish

    # 거래량 비율
    avg_vol = statistics.mean(volumes[:-1]) if len(volumes) > 1 else volumes[0]
    features['volume_vs_avg'] = volumes[-1] / avg_vol if avg_vol > 0 else 1.0

    # 가격 위치
    high_5 = max(c['high'] for c in recent)
    low_5 = min(c['low'] for c in recent)
    features['price_position'] = (closes[-1] - low_5) / (high_5 - low_5) if high_5 > low_5 else 0.5

    # 마지막 봉 형태
    last = recent[-1]
    last_range = last['high'] - last['low']
    if last_range > 0:
        features['upper_wick_ratio'] = (last['high'] - max(last['open'], last['close'])) / last_range
    else:
        features['upper_wick_ratio'] = 0

    return features


def main():
    all_trades = []

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
    for t in all_trades:
        pattern_data = load_pattern_data(t['date'])
        pattern_id = f"{t['stock_code']}_{t['date']}_{t['buy_time'].replace(':', '')}00"
        if pattern_id in pattern_data:
            t['pattern_data'] = pattern_data[pattern_id]

            # OHLCV 특징 추출
            seq = t['pattern_data'].get('signal_snapshot', {}).get('lookback_sequence_1min', [])
            t['ohlcv_features'] = analyze_ohlcv_features(seq)

            # 기술적 지표 추출
            tech_3min = t['pattern_data'].get('signal_snapshot', {}).get('technical_indicators_3min', {})
            t['rsi'] = tech_3min.get('rsi_14')
            t['volume_ma_ratio'] = tech_3min.get('volume_vs_ma_ratio')
            t['price_vs_ma5'] = tech_3min.get('price_vs_ma5_pct')
            t['price_vs_ma20'] = tech_3min.get('price_vs_ma20_pct')
            t['atr_pct'] = tech_3min.get('atr_pct')

    # 리포트 작성
    with open("D:/GIT/RoboTrader/pattern_analysis_report_v3.txt", 'w', encoding='utf-8') as f:
        wins = [t for t in all_trades if t['is_win']]
        losses = [t for t in all_trades if not t['is_win']]

        f.write("=" * 80 + "\n")
        f.write("         승리/패배 패턴 심층 분석 리포트 v3\n")
        f.write("=" * 80 + "\n\n")

        f.write(f"총 매매: {len(all_trades)}건 ({len(wins)}승 {len(losses)}패, 승률 {100*len(wins)/len(all_trades):.1f}%)\n")
        total_profit = sum(t['profit_pct'] for t in all_trades)
        f.write(f"총 수익률: {total_profit:.2f}% (거래당 평균 {total_profit/len(all_trades):.3f}%)\n\n")

        # ========================================
        # 1. 종목별 승률 분석
        # ========================================
        f.write("=" * 80 + "\n")
        f.write("1. 종목별 승률 분석\n")
        f.write("=" * 80 + "\n\n")

        stock_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'profit': 0})
        for t in all_trades:
            stock = t['stock_code']
            if t['is_win']:
                stock_stats[stock]['wins'] += 1
            else:
                stock_stats[stock]['losses'] += 1
            stock_stats[stock]['profit'] += t['profit_pct']

        # 거래 10회 이상 종목만
        active_stocks = [(s, d) for s, d in stock_stats.items() if d['wins'] + d['losses'] >= 10]
        active_stocks.sort(key=lambda x: x[1]['wins'] / (x[1]['wins'] + x[1]['losses']), reverse=True)

        f.write("거래 10회 이상 종목 (승률 순):\n")
        f.write("-" * 80 + "\n")

        high_win_stocks = []
        low_win_stocks = []

        for stock, stats in active_stocks:
            total = stats['wins'] + stats['losses']
            wr = 100 * stats['wins'] / total
            avg_profit = stats['profit'] / total
            marker = "★" if wr >= 55 else "▼" if wr < 40 else "  "

            if wr >= 55:
                high_win_stocks.append(stock)
            elif wr < 40:
                low_win_stocks.append(stock)

            f.write(f"{marker} {stock}: {stats['wins']:2d}승 {stats['losses']:2d}패 (승률 {wr:5.1f}%, 평균수익 {avg_profit:+.2f}%)\n")

        f.write(f"\n★ 고승률 종목 (55%+): {', '.join(high_win_stocks) if high_win_stocks else '없음'}\n")
        f.write(f"▼ 저승률 종목 (<40%): {', '.join(low_win_stocks) if low_win_stocks else '없음'}\n")

        # ========================================
        # 2. 시간대 + 요일 교차 분석
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("2. 시간대 × 요일 교차 분석\n")
        f.write("=" * 80 + "\n\n")

        day_names = ['월', '화', '수', '목', '금']
        time_day_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for t in all_trades:
            try:
                date = datetime.strptime(t['date'], '%Y%m%d')
                weekday = date.weekday()
                if weekday < 5:
                    hour = int(t['buy_time'].split(':')[0])
                    key = (hour, weekday)
                    if t['is_win']:
                        time_day_stats[key]['wins'] += 1
                    else:
                        time_day_stats[key]['losses'] += 1
            except:
                pass

        f.write("시간\\요일  월      화      수      목      금\n")
        f.write("-" * 80 + "\n")

        for hour in [9, 10, 11]:
            row = f"  {hour:02d}시   "
            for day in range(5):
                stats = time_day_stats.get((hour, day), {'wins': 0, 'losses': 0})
                total = stats['wins'] + stats['losses']
                if total >= 5:
                    wr = 100 * stats['wins'] / total
                    cell = f"{wr:4.0f}%"
                    if wr >= 55:
                        cell = f"★{wr:3.0f}%"
                    elif wr < 40:
                        cell = f"▼{wr:3.0f}%"
                else:
                    cell = "  -  "
                row += f"  {cell}"
            f.write(row + "\n")

        # 최적/최악 조합 찾기
        best_combo = max(time_day_stats.items(),
                         key=lambda x: (x[1]['wins'] / max(x[1]['wins'] + x[1]['losses'], 1)
                                        if x[1]['wins'] + x[1]['losses'] >= 10 else 0))
        worst_combo = min(time_day_stats.items(),
                          key=lambda x: (x[1]['wins'] / max(x[1]['wins'] + x[1]['losses'], 1)
                                         if x[1]['wins'] + x[1]['losses'] >= 10 else 1))

        best_total = best_combo[1]['wins'] + best_combo[1]['losses']
        worst_total = worst_combo[1]['wins'] + worst_combo[1]['losses']

        if best_total >= 10:
            f.write(f"\n★ 최적 조합: {best_combo[0][0]}시 {day_names[best_combo[0][1]]}요일 "
                    f"({best_combo[1]['wins']}승 {best_combo[1]['losses']}패, "
                    f"승률 {100*best_combo[1]['wins']/best_total:.1f}%)\n")
        if worst_total >= 10:
            f.write(f"▼ 최악 조합: {worst_combo[0][0]}시 {day_names[worst_combo[0][1]]}요일 "
                    f"({worst_combo[1]['wins']}승 {worst_combo[1]['losses']}패, "
                    f"승률 {100*worst_combo[1]['wins']/worst_total:.1f}%)\n")

        # ========================================
        # 3. 기술적 지표 조합 분석
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("3. 기술적 지표 조합 분석\n")
        f.write("=" * 80 + "\n\n")

        # RSI + 거래량 MA 비율 조합
        f.write("RSI × 거래량비율 조합:\n")
        f.write("-" * 80 + "\n")

        rsi_vol_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for t in all_trades:
            rsi = t.get('rsi')
            vol_ratio = t.get('volume_ma_ratio')

            if rsi and vol_ratio:
                # RSI 구간
                if rsi < 50:
                    rsi_cat = 'RSI<50'
                elif rsi < 70:
                    rsi_cat = 'RSI50-70'
                else:
                    rsi_cat = 'RSI70+'

                # 거래량 구간
                if vol_ratio < 0.7:
                    vol_cat = '거래량↓'
                elif vol_ratio < 1.3:
                    vol_cat = '거래량보통'
                else:
                    vol_cat = '거래량↑'

                key = (rsi_cat, vol_cat)
                if t['is_win']:
                    rsi_vol_stats[key]['wins'] += 1
                else:
                    rsi_vol_stats[key]['losses'] += 1

        for key, stats in sorted(rsi_vol_stats.items()):
            total = stats['wins'] + stats['losses']
            if total >= 10:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "▼" if wr < 40 else "  "
                f.write(f"{marker} {key[0]} + {key[1]}: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # RSI + 가격위치(MA5대비) 조합
        f.write("\nRSI × MA5대비가격 조합:\n")
        f.write("-" * 80 + "\n")

        rsi_ma_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for t in all_trades:
            rsi = t.get('rsi')
            price_ma5 = t.get('price_vs_ma5')

            if rsi and price_ma5 is not None:
                if rsi < 50:
                    rsi_cat = 'RSI<50'
                elif rsi < 70:
                    rsi_cat = 'RSI50-70'
                else:
                    rsi_cat = 'RSI70+'

                if price_ma5 < 0:
                    ma_cat = 'MA5아래'
                elif price_ma5 < 1:
                    ma_cat = 'MA5근처'
                else:
                    ma_cat = 'MA5위(1%+)'

                key = (rsi_cat, ma_cat)
                if t['is_win']:
                    rsi_ma_stats[key]['wins'] += 1
                else:
                    rsi_ma_stats[key]['losses'] += 1

        for key, stats in sorted(rsi_ma_stats.items()):
            total = stats['wins'] + stats['losses']
            if total >= 10:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "▼" if wr < 40 else "  "
                f.write(f"{marker} {key[0]} + {key[1]}: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # ========================================
        # 4. 복합 필터 시뮬레이션
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("4. 복합 필터 시뮬레이션\n")
        f.write("=" * 80 + "\n\n")

        def apply_filters(trades, filters):
            """필터 조합을 적용하여 통과한 거래만 반환"""
            filtered = []
            for t in trades:
                passed = True
                for filter_name, filter_func in filters.items():
                    if not filter_func(t):
                        passed = False
                        break
                if passed:
                    filtered.append(t)
            return filtered

        # 개별 필터 정의 (None 체크 추가)
        def safe_get(t, key, subkey, default):
            feat = t.get(key)
            if feat is None:
                return default
            return feat.get(subkey, default)

        filter_defs = {
            '연속양봉1+': lambda t: safe_get(t, 'ohlcv_features', 'consecutive_bullish', 0) >= 1,
            '가격위치70%+': lambda t: safe_get(t, 'ohlcv_features', 'price_position', 0) >= 0.7,
            '윗꼬리10%이하': lambda t: safe_get(t, 'ohlcv_features', 'upper_wick_ratio', 1) <= 0.1,
            '거래량1.5x이하': lambda t: safe_get(t, 'ohlcv_features', 'volume_vs_avg', 2) <= 1.5,
            'RSI50이하': lambda t: (t.get('rsi') or 100) <= 50,
            'RSI70이상': lambda t: (t.get('rsi') or 0) >= 70,
            '화요일제외': lambda t: datetime.strptime(t['date'], '%Y%m%d').weekday() != 1,
            '10시이후': lambda t: int(t['buy_time'].split(':')[0]) >= 10,
        }

        f.write("개별 필터 효과:\n")
        f.write("-" * 80 + "\n")

        filter_results = []
        for name, func in filter_defs.items():
            filtered = [t for t in all_trades if func(t)]
            if len(filtered) >= 20:
                w = sum(1 for t in filtered if t['is_win'])
                l = len(filtered) - w
                wr = 100 * w / len(filtered)
                total_pct = sum(t['profit_pct'] for t in filtered)
                avg_pct = total_pct / len(filtered)
                filter_results.append((name, w, l, wr, avg_pct, len(filtered)))

        filter_results.sort(key=lambda x: x[3], reverse=True)

        for name, w, l, wr, avg_pct, total in filter_results:
            marker = "★" if wr >= 50 else "  "
            pass_rate = 100 * total / len(all_trades)
            f.write(f"{marker} {name}: {w}승 {l}패 (승률 {wr:.1f}%, 평균 {avg_pct:+.2f}%, 통과율 {pass_rate:.0f}%)\n")

        # 필터 조합 테스트
        f.write("\n필터 조합 테스트 (2개 조합):\n")
        f.write("-" * 80 + "\n")

        combo_results = []
        filter_names = list(filter_defs.keys())

        for combo in combinations(filter_names, 2):
            filters = {name: filter_defs[name] for name in combo}
            filtered = apply_filters(all_trades, filters)

            if len(filtered) >= 20:
                w = sum(1 for t in filtered if t['is_win'])
                l = len(filtered) - w
                wr = 100 * w / len(filtered)
                total_pct = sum(t['profit_pct'] for t in filtered)
                avg_pct = total_pct / len(filtered)
                combo_results.append((combo, w, l, wr, avg_pct, len(filtered)))

        combo_results.sort(key=lambda x: x[3], reverse=True)

        for combo, w, l, wr, avg_pct, total in combo_results[:15]:
            marker = "★" if wr >= 55 else "  "
            pass_rate = 100 * total / len(all_trades)
            combo_str = " + ".join(combo)
            f.write(f"{marker} {combo_str}\n")
            f.write(f"    → {w}승 {l}패 (승률 {wr:.1f}%, 평균 {avg_pct:+.2f}%, 통과율 {pass_rate:.0f}%)\n")

        # 3개 조합
        f.write("\n필터 조합 테스트 (3개 조합, 상위 10개):\n")
        f.write("-" * 80 + "\n")

        combo3_results = []
        for combo in combinations(filter_names, 3):
            filters = {name: filter_defs[name] for name in combo}
            filtered = apply_filters(all_trades, filters)

            if len(filtered) >= 15:
                w = sum(1 for t in filtered if t['is_win'])
                l = len(filtered) - w
                wr = 100 * w / len(filtered)
                total_pct = sum(t['profit_pct'] for t in filtered)
                avg_pct = total_pct / len(filtered)
                combo3_results.append((combo, w, l, wr, avg_pct, len(filtered)))

        combo3_results.sort(key=lambda x: x[3], reverse=True)

        for combo, w, l, wr, avg_pct, total in combo3_results[:10]:
            marker = "★" if wr >= 55 else "  "
            pass_rate = 100 * total / len(all_trades)
            combo_str = " + ".join(combo)
            f.write(f"{marker} {combo_str}\n")
            f.write(f"    → {w}승 {l}패 (승률 {wr:.1f}%, 평균 {avg_pct:+.2f}%, 통과율 {pass_rate:.0f}%)\n")

        # ========================================
        # 5. 손익비 최적화 분석
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("5. 손익비 최적화 분석\n")
        f.write("=" * 80 + "\n\n")

        f.write("현재 설정: 익절 +3.5% / 손절 -2.5% (손익비 1.4:1)\n\n")

        # 실제 분포 분석
        win_profits = [t['profit_pct'] for t in wins]
        loss_profits = [t['profit_pct'] for t in losses]

        f.write("실제 수익률 분포:\n")
        f.write(f"  승리 평균: +{statistics.mean(win_profits):.2f}%\n")
        f.write(f"  패배 평균: {statistics.mean(loss_profits):.2f}%\n")

        # 손익비별 시뮬레이션 (가상)
        f.write("\n손익비 시뮬레이션 (현재 승률 45.2% 기준):\n")
        f.write("-" * 80 + "\n")

        current_wr = len(wins) / len(all_trades)

        for take_profit in [2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0]:
            for stop_loss in [1.5, 2.0, 2.5, 3.0]:
                # 기대값 계산: EV = (승률 × 익절) - ((1-승률) × 손절)
                ev = (current_wr * take_profit) - ((1 - current_wr) * stop_loss)
                ratio = take_profit / stop_loss
                marker = "★" if ev > 0.2 else "  "
                f.write(f"{marker} 익절 +{take_profit:.1f}% / 손절 -{stop_loss:.1f}% "
                        f"(비율 {ratio:.2f}:1) → 기대값 {ev:+.3f}%\n")

        # 조기 익절/손절 시뮬레이션
        f.write("\n조기 청산 분석:\n")
        f.write("-" * 80 + "\n")

        # 승리 중 조기 익절 가능했던 비율
        early_profit_count = sum(1 for t in wins if t['profit_pct'] < 3.5)
        late_loss_count = sum(1 for t in losses if t['profit_pct'] > -2.5)

        f.write(f"  승리 중 익절선(3.5%) 미달 청산: {early_profit_count}건 ({100*early_profit_count/len(wins):.1f}%)\n")
        f.write(f"  패배 중 손절선(-2.5%) 미달 청산: {late_loss_count}건 ({100*late_loss_count/len(losses):.1f}%)\n")

        # ========================================
        # 6. 연속 거래 패턴 분석
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("6. 연속 거래 패턴 분석\n")
        f.write("=" * 80 + "\n\n")

        # 일별 거래 그룹화
        daily_trades = defaultdict(list)
        for t in all_trades:
            daily_trades[t['date']].append(t)

        # 당일 N번째 거래 승률
        nth_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
        for date, trades in daily_trades.items():
            trades.sort(key=lambda x: x['buy_time'])
            for i, t in enumerate(trades):
                if t['is_win']:
                    nth_stats[i+1]['wins'] += 1
                else:
                    nth_stats[i+1]['losses'] += 1

        f.write("당일 N번째 거래 승률:\n")
        f.write("-" * 80 + "\n")

        for n in sorted(nth_stats.keys()):
            stats = nth_stats[n]
            total = stats['wins'] + stats['losses']
            if total >= 10:
                wr = 100 * stats['wins'] / total
                marker = "★" if wr >= 50 else "  "
                f.write(f"{marker} {n}번째 거래: {stats['wins']}승 {stats['losses']}패 (승률 {wr:.1f}%)\n")

        # 이전 거래 결과 후 승률
        f.write("\n이전 거래 결과에 따른 다음 거래 승률:\n")
        f.write("-" * 80 + "\n")

        after_win_stats = {'wins': 0, 'losses': 0}
        after_loss_stats = {'wins': 0, 'losses': 0}

        for date, trades in daily_trades.items():
            trades.sort(key=lambda x: x['buy_time'])
            for i in range(1, len(trades)):
                prev = trades[i-1]
                curr = trades[i]
                if prev['is_win']:
                    if curr['is_win']:
                        after_win_stats['wins'] += 1
                    else:
                        after_win_stats['losses'] += 1
                else:
                    if curr['is_win']:
                        after_loss_stats['wins'] += 1
                    else:
                        after_loss_stats['losses'] += 1

        aw_total = after_win_stats['wins'] + after_win_stats['losses']
        al_total = after_loss_stats['wins'] + after_loss_stats['losses']

        if aw_total > 0:
            aw_wr = 100 * after_win_stats['wins'] / aw_total
            f.write(f"  승리 후 다음 거래: {after_win_stats['wins']}승 {after_win_stats['losses']}패 (승률 {aw_wr:.1f}%)\n")
        if al_total > 0:
            al_wr = 100 * after_loss_stats['wins'] / al_total
            f.write(f"  패배 후 다음 거래: {after_loss_stats['wins']}승 {after_loss_stats['losses']}패 (승률 {al_wr:.1f}%)\n")

        # ========================================
        # 7. 최적 조건 종합
        # ========================================
        f.write("\n" + "=" * 80 + "\n")
        f.write("7. 최적 진입 조건 종합\n")
        f.write("=" * 80 + "\n\n")

        f.write("【고승률 조건 (데이터 기반)】\n")
        f.write("  1. 연속 양봉 1개 이상\n")
        f.write("  2. 가격 위치 70%+ (최근 고점 근처)\n")
        f.write("  3. 윗꼬리 10% 이하 (매수세 강함)\n")
        f.write("  4. 거래량 평균의 0.5~1.5x (과열 아님)\n")
        f.write("  5. RSI 50 이하 또는 70 이상\n")
        f.write("  6. 화요일 회피\n")
        f.write("  7. 10시 이후 진입 선호\n\n")

        f.write("【회피 조건】\n")
        f.write("  1. 거래량 1.0~1.5x (애매한 구간)\n")
        f.write("  2. RSI 50-70 구간\n")
        f.write("  3. 화요일 오전\n")
        f.write("  4. 저승률 종목군\n\n")

        # 최적 필터 조합으로 필터링 결과
        optimal_filters = {
            '연속양봉1+': filter_defs['연속양봉1+'],
            '가격위치70%+': filter_defs['가격위치70%+'],
            '화요일제외': filter_defs['화요일제외'],
        }

        optimal_filtered = apply_filters(all_trades, optimal_filters)
        if optimal_filtered:
            opt_w = sum(1 for t in optimal_filtered if t['is_win'])
            opt_l = len(optimal_filtered) - opt_w
            opt_wr = 100 * opt_w / len(optimal_filtered)
            opt_profit = sum(t['profit_pct'] for t in optimal_filtered)
            opt_avg = opt_profit / len(optimal_filtered)

            f.write("【최적 필터 적용 시 예상 성과】\n")
            f.write(f"  필터: 연속양봉1+ & 가격위치70%+ & 화요일제외\n")
            f.write(f"  결과: {opt_w}승 {opt_l}패 (승률 {opt_wr:.1f}%)\n")
            f.write(f"  총 수익률: {opt_profit:.2f}% (거래당 {opt_avg:+.3f}%)\n")
            f.write(f"  거래 감소율: {100*(1-len(optimal_filtered)/len(all_trades)):.1f}%\n")

        f.write("\n" + "=" * 80 + "\n")
        f.write("분석 완료\n")
        f.write("=" * 80 + "\n")

    print("리포트 저장 완료: pattern_analysis_report_v3.txt")


if __name__ == '__main__':
    main()
