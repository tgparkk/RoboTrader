"""
패배 거래 심층 분석 스크립트
데이터베이스에서 직접 거래 기록을 읽어 패배 패턴을 분석합니다.
"""
import sqlite3
import json
from datetime import datetime
from collections import defaultdict
import sys
import os

# Windows 인코딩 문제 해결
if os.name == 'nt':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def get_trading_records(db_path='data/robotrader.db'):
    """데이터베이스에서 모든 거래 기록 가져오기"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # trading_records 테이블 구조 확인
    cursor.execute("PRAGMA table_info(trading_records)")
    columns = [col[1] for col in cursor.fetchall()]
    print(f"📋 컬럼: {columns}")
    print()

    # 모든 거래 기록 가져오기
    query = "SELECT * FROM trading_records ORDER BY buy_time"
    cursor.execute(query)
    records = cursor.fetchall()

    # 딕셔너리로 변환
    trades = []
    for record in records:
        trade = dict(zip(columns, record))
        trades.append(trade)

    conn.close()
    return trades, columns

def calculate_profit_pct(trade):
    """수익률 계산"""
    buy_price = trade.get('buy_price', 0)
    sell_price = trade.get('sell_price', 0)

    if buy_price and sell_price and buy_price > 0:
        return ((sell_price - buy_price) / buy_price) * 100
    return 0

def parse_time(time_str):
    """시간 문자열에서 시간대 추출"""
    if not time_str:
        return None
    try:
        if isinstance(time_str, str):
            # '2025-09-01 09:30:00' 형식
            dt = datetime.strptime(time_str, '%Y-%m-%d %H:%M:%S')
            return dt.hour
        return None
    except:
        return None

def analyze_trades(trades):
    """거래 데이터 분석"""
    print("="*80)
    print("📊 전체 통계")
    print("="*80)

    total = len(trades)
    wins = [t for t in trades if t.get('profit_pct', 0) > 0]
    losses = [t for t in trades if t.get('profit_pct', 0) <= 0]

    print(f"총 거래: {total}개")
    print(f"승리: {len(wins)}개 ({len(wins)/total*100:.1f}%)")
    print(f"패배: {len(losses)}개 ({len(losses)/total*100:.1f}%)")
    print()

    if wins:
        avg_win = sum(t['profit_pct'] for t in wins) / len(wins)
        print(f"평균 승리: +{avg_win:.2f}%")

    if losses:
        avg_loss = sum(t['profit_pct'] for t in losses) / len(losses)
        print(f"평균 손실: {avg_loss:.2f}%")

    print()

    # 시간대별 분석
    print("="*80)
    print("⏰ 시간대별 패배율 분석")
    print("="*80)
    print()

    hourly_stats = defaultdict(lambda: {'wins': 0, 'losses': 0, 'win_profit': 0, 'loss_profit': 0})

    for trade in trades:
        hour = parse_time(trade.get('buy_time'))
        if hour is None:
            continue

        profit = trade.get('profit_pct', 0)
        if profit > 0:
            hourly_stats[hour]['wins'] += 1
            hourly_stats[hour]['win_profit'] += profit
        else:
            hourly_stats[hour]['losses'] += 1
            hourly_stats[hour]['loss_profit'] += profit

    print(f"{'시간대':>6} | {'총거래':>8} | {'승리':>6} | {'패배':>6} | {'승률':>8} | {'평균손익':>10} | {'평가':>10}")
    print("-"*90)

    high_risk_hours = []
    recommendations = []

    for hour in sorted(hourly_stats.keys()):
        stats = hourly_stats[hour]
        total_h = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total_h * 100 if total_h > 0 else 0
        loss_rate = 100 - win_rate

        avg_profit = (stats['win_profit'] + stats['loss_profit']) / total_h if total_h > 0 else 0

        evaluation = ""
        if loss_rate > 55:
            evaluation = "🚫 고위험"
            high_risk_hours.append(hour)
        elif loss_rate > 52:
            evaluation = "⚠️ 주의"
        elif win_rate > 55:
            evaluation = "✅ 안전"
        else:
            evaluation = "⏸️ 보통"

        print(f"{hour:02d}시 | {total_h:8d} | {stats['wins']:6d} | {stats['losses']:6d} | "
              f"{win_rate:7.1f}% | {avg_profit:+9.2f}% | {evaluation:>10}")

    print()

    if high_risk_hours:
        print(f"🚫 고위험 시간대: {', '.join([f'{h:02d}시' for h in high_risk_hours])}")
        print(f"   → 권장: 이 시간대 거래 차단 또는 매우 엄격한 필터 적용")
        recommendations.append(f"고위험 시간대 거래 차단: {high_risk_hours}")
    print()

    # 패배 거래의 추가 분석
    print("="*80)
    print("🔍 패배 거래 상세 분석")
    print("="*80)
    print()

    if losses:
        # 패턴별 분석 (패턴 정보가 있는 경우)
        pattern_losses = defaultdict(int)
        pattern_wins = defaultdict(int)

        for trade in trades:
            pattern = trade.get('pattern') or trade.get('signal_reason', 'unknown')
            profit = trade.get('profit_pct', 0)

            if profit > 0:
                pattern_wins[pattern] += 1
            else:
                pattern_losses[pattern] += 1

        if pattern_losses:
            print("📊 패턴별 패배율")
            print("-"*80)
            print(f"{'패턴':>20} | {'총거래':>8} | {'승리':>6} | {'패배':>6} | {'패배율':>8}")
            print("-"*80)

            for pattern in sorted(pattern_losses.keys(), key=lambda p: pattern_losses[p], reverse=True):
                wins_p = pattern_wins.get(pattern, 0)
                losses_p = pattern_losses[pattern]
                total_p = wins_p + losses_p
                loss_rate = losses_p / total_p * 100 if total_p > 0 else 0

                print(f"{pattern:>20} | {total_p:8d} | {wins_p:6d} | {losses_p:6d} | {loss_rate:7.1f}%")

            print()

    # 손실 크기별 분포
    print("="*80)
    print("📉 손실 크기 분포")
    print("="*80)
    print()

    loss_ranges = [
        (-100, -5, "대손실 (-5% 이하)"),
        (-5, -3, "큰손실 (-3% ~ -5%)"),
        (-3, -2, "중손실 (-2% ~ -3%)"),
        (-2, -1, "소손실 (-1% ~ -2%)"),
        (-1, 0, "경미손실 (-1% 이하)"),
    ]

    for low, high, label in loss_ranges:
        count = len([t for t in losses if low <= t.get('profit_pct', 0) < high])
        if count > 0:
            pct = count / len(losses) * 100
            print(f"{label:>25}: {count:3d}개 ({pct:5.1f}%)")

    print()

    return {
        'total': total,
        'wins': len(wins),
        'losses': len(losses),
        'high_risk_hours': high_risk_hours,
        'hourly_stats': dict(hourly_stats),
        'recommendations': recommendations
    }

def generate_recommendations(analysis):
    """분석 결과 기반 권장 사항 생성"""
    print("="*80)
    print("💡 패배 대폭 감소를 위한 권장 사항")
    print("="*80)
    print()

    print("🎯 1순위: 고위험 시간대 거래 차단")
    print("-"*80)
    if analysis['high_risk_hours']:
        print(f"   차단 시간대: {', '.join([f'{h:02d}시' for h in analysis['high_risk_hours']])}")
        print(f"   예상 효과: 패배 20-30% 감소")
        print(f"   구현 난이도: ⭐ (매우 쉬움)")
        print()
        print("   구현 코드 예시:")
        print("   ```python")
        print(f"   BLOCKED_HOURS = {analysis['high_risk_hours']}")
        print("   if current_hour in BLOCKED_HOURS:")
        print("       return False  # 거래 차단")
        print("   ```")
    else:
        print("   ✅ 현재 고위험 시간대 없음")
    print()

    print("🎯 2순위: 손절 기준 강화")
    print("-"*80)
    print("   현재: -2.5% 손절")
    print("   권장: -2.0% 손절 (손실 20% 감소)")
    print("   또는: 시간대별 차등 손절")
    print("     - 09시: -2.5% (완화)")
    print("     - 10시 이후: -2.0% (강화)")
    print("     - 14시: -1.5% (매우 강화) 또는 거래 금지")
    print("   구현 난이도: ⭐ (매우 쉬움)")
    print()

    print("🎯 3순위: 진입 조건 강화")
    print("-"*80)
    print("   A. 거래량 필터 강화")
    print("      - 평균 거래량 대비 2배 이상")
    print("      - 최근 5분 거래량 증가 추세 확인")
    print()
    print("   B. 가격 위치 필터")
    print("      - 당일 고가 대비 95% 이상 위치에서만 진입")
    print("      - 전일 종가 대비 +2% 이상 상승 종목만")
    print()
    print("   C. 시간대별 필터 차등 적용")
    print("      - 09시: 관대한 기준 (승률 57.8%)")
    print("      - 10시: 중간 기준 (승률 48.1%)")
    print("      - 14시: 매우 엄격 또는 거래 금지 (승률 43.3%)")
    print()
    print("   구현 난이도: ⭐⭐ (쉬움)")
    print()

    print("🎯 4순위: 연속 손실 브레이크")
    print("-"*80)
    print("   같은 날 2회 연속 손실 시 당일 거래 중지")
    print("   → 감정적 판단 방지 + 불리한 시장 환경 회피")
    print("   예상 효과: 패배 10-15% 감소")
    print("   구현 난이도: ⭐ (매우 쉬움)")
    print()

    print("="*80)
    print("📊 예상 개선 효과")
    print("="*80)
    print()

    current_loss = analysis['losses']
    current_win_rate = analysis['wins'] / analysis['total'] * 100

    print(f"현재 상태:")
    print(f"  - 승률: {current_win_rate:.1f}%")
    print(f"  - 패배: {current_loss}건")
    print()

    expected_loss_reduction = int(current_loss * 0.35)  # 35% 감소 예상
    expected_new_loss = current_loss - expected_loss_reduction
    expected_new_win_rate = analysis['wins'] / (analysis['wins'] + expected_new_loss) * 100

    print(f"개선 후 예상:")
    print(f"  - 승률: {expected_new_win_rate:.1f}% (▲{expected_new_win_rate - current_win_rate:.1f}%p)")
    print(f"  - 패배: {expected_new_loss}건 (▼{expected_loss_reduction}건, -{expected_loss_reduction/current_loss*100:.1f}%)")
    print()

def main():
    print("="*80)
    print("🔍 거래 데이터 패배 패턴 분석")
    print("="*80)
    print()

    try:
        # 거래 기록 가져오기
        trades, columns = get_trading_records()

        if not trades:
            print("❌ 거래 기록이 없습니다.")
            return

        print(f"✅ {len(trades)}개 거래 기록 로드 완료")
        print()

        # 수익률 계산
        for trade in trades:
            trade['profit_pct'] = calculate_profit_pct(trade)

        # 분석 실행
        analysis = analyze_trades(trades)

        # 권장 사항 생성
        generate_recommendations(analysis)

        print("="*80)
        print("✅ 분석 완료")
        print("="*80)

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
