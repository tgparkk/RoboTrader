"""
고급 필터 테스트 및 백테스트 시뮬레이션
signal_replay_log 데이터에 고급 필터를 적용하여 성과를 검증합니다.
"""

import os
import re
import json
from datetime import datetime
from collections import defaultdict

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


def load_pattern_data(date_str):
    """패턴 데이터 로드"""
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


def main():
    print("=" * 70)
    print("고급 필터 백테스트 시뮬레이션")
    print("=" * 70)

    # 필터 매니저 로드
    from core.indicators.advanced_filters import AdvancedFilterManager
    filter_manager = AdvancedFilterManager()

    print(f"\n{filter_manager.get_summary()}")
    print(f"활성 필터: {filter_manager.get_active_filters()}")

    # 모든 거래 로드
    print("\n데이터 로딩 중...")
    all_trades = []

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

    # 필터 적용 시뮬레이션
    print("\n필터 적용 중...")

    passed_trades = []
    blocked_trades = []
    block_reasons = defaultdict(int)

    for t in all_trades:
        # 신호 시간 파싱
        try:
            signal_time = datetime.strptime(f"{t['date']} {t['buy_time']}", '%Y%m%d %H:%M')
        except:
            signal_time = None

        # OHLCV 시퀀스 추출
        ohlcv_sequence = None
        rsi = None
        volume_ma_ratio = None

        if 'pattern_data' in t:
            ohlcv_sequence = t['pattern_data'].get('signal_snapshot', {}).get('lookback_sequence_1min', [])
            tech = t['pattern_data'].get('signal_snapshot', {}).get('technical_indicators_3min', {})
            rsi = tech.get('rsi_14')
            volume_ma_ratio = tech.get('volume_vs_ma_ratio')

        # 필터 적용
        result = filter_manager.check_signal(
            ohlcv_sequence=ohlcv_sequence,
            rsi=rsi,
            stock_code=t['stock_code'],
            signal_time=signal_time,
            volume_ma_ratio=volume_ma_ratio
        )

        if result.passed:
            passed_trades.append(t)
        else:
            blocked_trades.append(t)
            block_reasons[result.blocked_by] += 1

    # 결과 출력
    print("\n" + "=" * 70)
    print("필터 적용 결과")
    print("=" * 70)

    # 필터 전
    original_wins = sum(1 for t in all_trades if t['is_win'])
    original_losses = len(all_trades) - original_wins
    original_winrate = 100 * original_wins / len(all_trades) if all_trades else 0
    original_profit = sum(t['profit_pct'] for t in all_trades)

    print(f"\n【필터 전】")
    print(f"  거래: {len(all_trades)}건 ({original_wins}승 {original_losses}패)")
    print(f"  승률: {original_winrate:.1f}%")
    print(f"  총 수익률: {original_profit:.2f}%")
    print(f"  거래당 평균: {original_profit/len(all_trades):.3f}%")

    # 필터 후
    if passed_trades:
        filtered_wins = sum(1 for t in passed_trades if t['is_win'])
        filtered_losses = len(passed_trades) - filtered_wins
        filtered_winrate = 100 * filtered_wins / len(passed_trades)
        filtered_profit = sum(t['profit_pct'] for t in passed_trades)

        print(f"\n【필터 후】")
        print(f"  거래: {len(passed_trades)}건 ({filtered_wins}승 {filtered_losses}패)")
        print(f"  승률: {filtered_winrate:.1f}% ({filtered_winrate - original_winrate:+.1f}%p)")
        print(f"  총 수익률: {filtered_profit:.2f}%")
        print(f"  거래당 평균: {filtered_profit/len(passed_trades):.3f}%")

        # 차단된 거래 분석
        blocked_wins = sum(1 for t in blocked_trades if t['is_win'])
        blocked_losses = len(blocked_trades) - blocked_wins
        blocked_winrate = 100 * blocked_wins / len(blocked_trades) if blocked_trades else 0

        print(f"\n【차단된 거래 분석】")
        print(f"  차단: {len(blocked_trades)}건 ({blocked_wins}승 {blocked_losses}패)")
        print(f"  차단 거래 승률: {blocked_winrate:.1f}%")
        print(f"  거래 감소율: {100*(1-len(passed_trades)/len(all_trades)):.1f}%")

        print(f"\n【차단 사유별 통계】")
        for reason, count in sorted(block_reasons.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count}건")
    else:
        print("\n⚠️ 모든 거래가 필터링되었습니다!")

    # 개선 효과 요약
    print("\n" + "=" * 70)
    print("개선 효과 요약")
    print("=" * 70)

    if passed_trades:
        winrate_improvement = filtered_winrate - original_winrate
        avg_profit_improvement = (filtered_profit/len(passed_trades)) - (original_profit/len(all_trades))

        print(f"  승률 개선: {original_winrate:.1f}% → {filtered_winrate:.1f}% ({winrate_improvement:+.1f}%p)")
        print(f"  거래당 수익 개선: {original_profit/len(all_trades):.3f}% → {filtered_profit/len(passed_trades):.3f}% ({avg_profit_improvement:+.3f}%p)")

        # 필터 효과 판정
        if winrate_improvement > 5:
            print(f"\n[GOOD] 필터 효과: 우수 (승률 +{winrate_improvement:.1f}%p)")
        elif winrate_improvement > 0:
            print(f"\n[OK] 필터 효과: 양호 (승률 +{winrate_improvement:.1f}%p)")
        else:
            print(f"\n[WARN] 필터 효과: 미미 또는 역효과")


if __name__ == '__main__':
    main()
