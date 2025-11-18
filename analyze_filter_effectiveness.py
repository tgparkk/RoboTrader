"""
필터 효과성 분석 스크립트

필터가 차단한 매매가 실제로는 승리였는지 손실이었는지 분석합니다.

사용법:
  1. 필터 없이 시뮬레이션 실행:
     - pullback_candle_pattern.py에서 필터 코드 주석처리
     - python utils/signal_replay.py --date 20250901 --end_date 20251107
     - 결과를 signal_replay_log_no_filter/에 저장

  2. 필터 있이 시뮬레이션 실행 (현재):
     - python utils/signal_replay.py --date 20250901 --end_date 20251107
     - 결과를 signal_replay_log/에 저장

  3. 이 스크립트 실행:
     - python analyze_filter_effectiveness.py

"""
import sys
import io
import re
from pathlib import Path
from collections import defaultdict

# UTF-8 인코딩 설정 (Windows)
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def parse_replay_log(log_file):
    """
    signal_new2_replay_YYYYMMDD_9_00_0.txt 파일 파싱

    Returns:
        list of dict: 각 매매의 정보
            {
                'stock_code': str,
                'date': str,
                'time': str,
                'buy_price': float,
                'sell_price': float,
                'profit_pct': float,
                'is_win': bool
            }
    """
    trades = []

    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()

    # === 📈 [종목코드] 매매 YYYY-MM-DD HH:MM:SS === 형식 찾기
    trade_pattern = re.compile(
        r'=== 📈 \[(\d{6})\] 매매 (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ===.*?'
        r'매수가:\s*([\d,]+)원.*?'
        r'매도가:\s*([\d,]+)원.*?'
        r'수익률:\s*([-+]?\d+\.\d+)%',
        re.DOTALL
    )

    for match in trade_pattern.finditer(content):
        stock_code = match.group(1)
        date = match.group(2)
        time = match.group(3)
        buy_price = float(match.group(4).replace(',', ''))
        sell_price = float(match.group(5).replace(',', ''))
        profit_pct = float(match.group(6))

        trades.append({
            'stock_code': stock_code,
            'date': date,
            'time': time,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'profit_pct': profit_pct,
            'is_win': profit_pct > 0
        })

    return trades

def analyze_filter_effectiveness():
    """필터 효과성 분석"""

    print("="*70)
    print("필터 효과성 분석")
    print("="*70)
    print()

    # 1. 필터 없는 시뮬레이션 결과 로드
    no_filter_dir = Path("signal_replay_log_no_filter")
    if not no_filter_dir.exists():
        print("❌ signal_replay_log_no_filter/ 디렉토리가 없습니다.")
        print("   필터를 끄고 시뮬레이션을 실행한 후 다시 시도하세요.")
        return

    # 2. 필터 있는 시뮬레이션 결과 로드
    filter_dir = Path("signal_replay_log")
    if not filter_dir.exists():
        print("❌ signal_replay_log/ 디렉토리가 없습니다.")
        return

    # 3. 모든 날짜의 로그 파일 수집
    no_filter_logs = sorted(no_filter_dir.glob("signal_new2_replay_*.txt"))
    filter_logs = sorted(filter_dir.glob("signal_new2_replay_*.txt"))

    print(f"📂 필터 없음: {len(no_filter_logs)}개 파일")
    print(f"📂 필터 있음: {len(filter_logs)}개 파일")
    print()

    # 4. 각 파일 파싱
    all_no_filter_trades = []
    all_filter_trades = []

    for log_file in no_filter_logs:
        trades = parse_replay_log(log_file)
        all_no_filter_trades.extend(trades)

    for log_file in filter_logs:
        trades = parse_replay_log(log_file)
        all_filter_trades.extend(trades)

    print(f"📊 필터 없음: 총 {len(all_no_filter_trades)}건 매매")
    print(f"📊 필터 있음: 총 {len(all_filter_trades)}건 매매")
    print()

    # 5. 차단된 매매 식별 (필터 없음에는 있지만 필터 있음에는 없는 매매)
    filter_trades_set = {
        (t['stock_code'], t['date'], t['time']) for t in all_filter_trades
    }

    blocked_trades = [
        t for t in all_no_filter_trades
        if (t['stock_code'], t['date'], t['time']) not in filter_trades_set
    ]

    print(f"🚫 필터가 차단한 매매: {len(blocked_trades)}건")
    print()

    if len(blocked_trades) == 0:
        print("차단된 매매가 없습니다.")
        return

    # 6. 차단된 매매의 승/패 분석
    blocked_wins = [t for t in blocked_trades if t['is_win']]
    blocked_losses = [t for t in blocked_trades if not t['is_win']]

    win_rate = len(blocked_wins) / len(blocked_trades) * 100

    print("="*70)
    print("🔍 차단된 매매 분석")
    print("="*70)
    print(f"총 차단: {len(blocked_trades)}건")
    print(f"  ✅ 승리 (필터가 잘못 차단): {len(blocked_wins)}건")
    print(f"  ❌ 손실 (필터가 잘 차단): {len(blocked_losses)}건")
    print(f"  승률: {win_rate:.1f}%")
    print()

    # 7. 필터 효과성 평가
    print("="*70)
    print("💡 필터 효과성 평가")
    print("="*70)

    if win_rate < 50:
        print(f"✅ 필터가 효과적입니다!")
        print(f"   차단된 매매의 승률({win_rate:.1f}%)이 50% 미만이므로,")
        print(f"   필터가 손실 가능성이 높은 매매를 잘 걸러내고 있습니다.")
    else:
        print(f"⚠️ 필터를 재검토해야 합니다!")
        print(f"   차단된 매매의 승률({win_rate:.1f}%)이 50% 이상이므로,")
        print(f"   필터가 승리 가능성이 있는 매매를 과도하게 차단하고 있습니다.")
    print()

    # 8. 차단된 매매 중 손실률이 큰 상위 10건 출력
    print("="*70)
    print("🚫 차단된 매매 중 손실 상위 10건 (필터가 잘 차단한 경우)")
    print("="*70)
    blocked_losses_sorted = sorted(blocked_losses, key=lambda x: x['profit_pct'])[:10]
    for i, t in enumerate(blocked_losses_sorted, 1):
        print(f"{i:2d}. [{t['stock_code']}] {t['date']} {t['time']} → {t['profit_pct']:+.2f}%")
    print()

    # 9. 차단된 매매 중 승률이 높은 상위 10건 출력 (아쉬운 차단)
    print("="*70)
    print("😢 차단된 매매 중 승리 상위 10건 (아쉬운 차단)")
    print("="*70)
    blocked_wins_sorted = sorted(blocked_wins, key=lambda x: x['profit_pct'], reverse=True)[:10]
    for i, t in enumerate(blocked_wins_sorted, 1):
        print(f"{i:2d}. [{t['stock_code']}] {t['date']} {t['time']} → {t['profit_pct']:+.2f}%")
    print()

if __name__ == "__main__":
    analyze_filter_effectiveness()
