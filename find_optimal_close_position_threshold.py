"""
최적의 종가 위치 필터 임계값 찾기

여러 임계값(50%, 55%, 60%, 65%, 70%)을 시뮬레이션하여
승률과 거래 빈도의 최적 균형점을 찾습니다.
"""
import sys
import io
import re
from pathlib import Path

# UTF-8 인코딩 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def parse_signal_log(log_file):
    """신호 로그 파일 파싱"""
    trades = []

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # "=== 📈 [종목코드] 매매 날짜 시간 ===" 패턴 찾기
    trade_pattern = re.compile(
        r'=== 📈 \[(\d{6})\] 매매 (\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2}) ===.*?'
        r'매수가:\s*([\d,]+)원.*?'
        r'매도가:\s*([\d,]+)원.*?'
        r'수익률:\s*([-+]?\d+\.\d+)%.*?'
        r'종가 위치:\s*(\d+\.\d+)%',
        re.DOTALL
    )

    for match in trade_pattern.finditer(content):
        stock_code = match.group(1)
        date = match.group(2)
        time = match.group(3)
        buy_price = float(match.group(4).replace(',', ''))
        sell_price = float(match.group(5).replace(',', ''))
        profit_pct = float(match.group(6))
        close_position = float(match.group(7))

        trades.append({
            'stock_code': stock_code,
            'date': date,
            'time': time,
            'buy_price': buy_price,
            'sell_price': sell_price,
            'profit_pct': profit_pct,
            'is_win': profit_pct > 0,
            'close_position': close_position
        })

    return trades

def simulate_filter(trades, threshold):
    """특정 임계값으로 필터 시뮬레이션"""
    # 종가 위치가 threshold 이상인 매매만 통과
    filtered_trades = [t for t in trades if t['close_position'] >= threshold]

    if len(filtered_trades) == 0:
        return {
            'threshold': threshold,
            'total': 0,
            'wins': 0,
            'losses': 0,
            'win_rate': 0,
            'blocked': len(trades),
            'blocked_pct': 100
        }

    wins = [t for t in filtered_trades if t['is_win']]
    losses = [t for t in filtered_trades if not t['is_win']]

    return {
        'threshold': threshold,
        'total': len(filtered_trades),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(filtered_trades) * 100,
        'blocked': len(trades) - len(filtered_trades),
        'blocked_pct': (len(trades) - len(filtered_trades)) / len(trades) * 100
    }

def main():
    print("="*80)
    print("🔍 최적 종가 위치 필터 임계값 찾기")
    print("="*80)
    print()

    # 필터 없는 로그에서 모든 거래 데이터 수집
    log_dir = Path("signal_replay_log_no_filter")
    log_files = sorted(log_dir.glob("signal_new2_replay_*.txt"))

    print(f"📂 분석 대상: {len(log_files)}개 파일")
    print()

    all_trades = []
    for log_file in log_files:
        trades = parse_signal_log(log_file)
        all_trades.extend(trades)

    print(f"📊 총 거래 수: {len(all_trades)}건")

    if len(all_trades) == 0:
        print("❌ 종가 위치 데이터가 없습니다.")
        print("   로그 파일에 '종가 위치' 정보가 포함되어 있는지 확인하세요.")
        return

    # 기본 통계
    wins = [t for t in all_trades if t['is_win']]
    losses = [t for t in all_trades if not t['is_win']]
    base_win_rate = len(wins) / len(all_trades) * 100

    print(f"   승: {len(wins)}건, 패: {len(losses)}건")
    print(f"   기본 승률: {base_win_rate:.1f}%")
    print()

    # 종가 위치 분포 분석
    close_positions = [t['close_position'] for t in all_trades]
    avg_close_position = sum(close_positions) / len(close_positions)

    win_close_positions = [t['close_position'] for t in wins]
    loss_close_positions = [t['close_position'] for t in losses]

    avg_win_close = sum(win_close_positions) / len(win_close_positions) if win_close_positions else 0
    avg_loss_close = sum(loss_close_positions) / len(loss_close_positions) if loss_close_positions else 0

    print("📊 종가 위치 분포")
    print("-"*80)
    print(f"전체 평균: {avg_close_position:.1f}%")
    print(f"승리 평균: {avg_win_close:.1f}%")
    print(f"손실 평균: {avg_loss_close:.1f}%")
    print(f"차이: {avg_win_close - avg_loss_close:.1f}%p")
    print()

    # 여러 임계값 테스트
    thresholds = [50, 55, 60, 65, 70]

    print("="*80)
    print("🧪 여러 임계값 시뮬레이션")
    print("="*80)
    print()

    results = []
    for threshold in thresholds:
        result = simulate_filter(all_trades, threshold)
        results.append(result)

    # 결과 테이블
    print(f"{'임계값':>8} | {'총거래':>8} | {'승률':>8} | {'차단':>8} | {'승률개선':>10} | {'평가':>10}")
    print("-"*80)

    for result in results:
        win_rate_change = result['win_rate'] - base_win_rate

        # 평가 점수 = 승률 개선 - (차단 비율 * 0.5)
        # 승률은 높이되 거래 빈도도 유지해야 함
        score = win_rate_change - (result['blocked_pct'] * 0.3)

        evaluation = "⭐" * int(min(5, max(0, score + 2)))

        print(f"{result['threshold']:>7}% | "
              f"{result['total']:>7}건 | "
              f"{result['win_rate']:>7.1f}% | "
              f"{result['blocked']:>7}건 | "
              f"{win_rate_change:>+9.1f}%p | "
              f"{evaluation:>10}")

    print()

    # 최적 임계값 추천
    print("="*80)
    print("💡 최적 임계값 추천")
    print("="*80)
    print()

    # 승률 개선 - 거래 빈도 감소를 고려한 점수
    best_result = None
    best_score = -999

    for result in results:
        win_rate_change = result['win_rate'] - base_win_rate
        # 승률 개선에 3배 가중치, 거래 빈도 유지에 1배 가중치
        score = (win_rate_change * 3) - (result['blocked_pct'] * 0.3)

        if score > best_score:
            best_score = score
            best_result = result

    if best_result:
        print(f"✅ 추천 임계값: {best_result['threshold']}%")
        print()
        print(f"   예상 승률: {best_result['win_rate']:.1f}% (기본 대비 +{best_result['win_rate'] - base_win_rate:.1f}%p)")
        print(f"   예상 거래 수: {best_result['total']}건 (기본 대비 -{best_result['blocked_pct']:.1f}%)")
        print(f"   차단되는 매매: {best_result['blocked']}건")
        print()

    print("📝 권장 사항:")
    print()
    print("1. 보수적 접근 (승률 우선):")
    print(f"   임계값: 65% 이상")
    print()
    print("2. 균형적 접근 (승률 + 거래 빈도):")
    print(f"   임계값: 60%")
    print()
    print("3. 공격적 접근 (거래 빈도 우선):")
    print(f"   임계값: 55%")
    print()

if __name__ == "__main__":
    main()
