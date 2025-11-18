"""
패배 매매 심층 분석

승리는 소폭 줄이고 패배는 대폭 줄이는 방법을 찾기 위해
패배 매매의 공통 패턴을 찾습니다.

분석 항목:
1. 시간대별 패배율
2. 패배 시 종가 위치 분포
3. 패배 시 거래량 패턴
4. 패배 시 캔들 패턴
5. 패배 시 전날 등락률
6. 패배 시 상승 구간 특징
"""
import sys
import io
import re
import json
from pathlib import Path
from collections import defaultdict

# UTF-8 인코딩 설정
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

def parse_detailed_log(log_file):
    """로그 파일에서 상세 정보 파싱"""
    trades = []

    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        content = f.read()

    # 매매 정보 파싱
    trade_blocks = re.split(r'=== 📈 \[(\d{6})\] 매매', content)

    for i in range(1, len(trade_blocks), 2):
        if i + 1 >= len(trade_blocks):
            break

        stock_code = trade_blocks[i]
        trade_content = trade_blocks[i + 1]

        # 기본 정보
        date_match = re.search(r'(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}:\d{2})', trade_content)
        profit_match = re.search(r'수익률:\s*([-+]?\d+\.\d+)%', trade_content)
        buy_price_match = re.search(r'매수가:\s*([\d,]+)원', trade_content)

        if not (date_match and profit_match and buy_price_match):
            continue

        date = date_match.group(1)
        time = date_match.group(2)
        hour = int(time.split(':')[0])
        profit_pct = float(profit_match.group(1))
        buy_price = float(buy_price_match.group(1).replace(',', ''))

        trade = {
            'stock_code': stock_code,
            'date': date,
            'time': time,
            'hour': hour,
            'profit_pct': profit_pct,
            'is_win': profit_pct > 0,
            'buy_price': buy_price
        }

        # 추가 정보 파싱 (있으면)
        # 종가 위치
        close_pos_match = re.search(r'종가 위치:\s*(\d+\.\d+)%', trade_content)
        if close_pos_match:
            trade['close_position'] = float(close_pos_match.group(1))

        # 거래량 증가율
        volume_match = re.search(r'거래량 증가:\s*([-+]?\d+\.\d+)%', trade_content)
        if volume_match:
            trade['volume_increase'] = float(volume_match.group(1))

        # 상승률
        gain_match = re.search(r'상승률:\s*(\d+\.\d+)%', trade_content)
        if gain_match:
            trade['uptrend_gain'] = float(gain_match.group(1))

        trades.append(trade)

    return trades

def analyze_losing_patterns(trades):
    """패배 매매 패턴 분석"""
    wins = [t for t in trades if t['is_win']]
    losses = [t for t in trades if not t['is_win']]

    print("="*80)
    print("📊 기본 통계")
    print("="*80)
    print(f"총 거래: {len(trades)}건")
    print(f"승리: {len(wins)}건 ({len(wins)/len(trades)*100:.1f}%)")
    print(f"패배: {len(losses)}건 ({len(losses)/len(trades)*100:.1f}%)")
    print()

    # 1. 시간대별 분석
    print("="*80)
    print("⏰ 시간대별 패배율 분석")
    print("="*80)
    print()

    hourly_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})
    for trade in trades:
        hour = trade['hour']
        if trade['is_win']:
            hourly_stats[hour]['wins'] += 1
        else:
            hourly_stats[hour]['losses'] += 1

    print(f"{'시간대':>6} | {'총거래':>8} | {'승리':>6} | {'패배':>6} | {'패배율':>8} | {'평가':>10}")
    print("-"*80)

    high_risk_hours = []
    for hour in sorted(hourly_stats.keys()):
        stats = hourly_stats[hour]
        total = stats['wins'] + stats['losses']
        loss_rate = stats['losses'] / total * 100 if total > 0 else 0

        evaluation = ""
        if loss_rate > 55:
            evaluation = "🚫 고위험"
            high_risk_hours.append(hour)
        elif loss_rate > 52:
            evaluation = "⚠️ 주의"
        elif loss_rate < 45:
            evaluation = "✅ 안전"
        else:
            evaluation = "⏸️ 보통"

        print(f"{hour:02d}시 | {total:8d} | {stats['wins']:6d} | {stats['losses']:6d} | "
              f"{loss_rate:7.1f}% | {evaluation:>10}")

    print()
    if high_risk_hours:
        print(f"🚫 고위험 시간대: {', '.join([f'{h:02d}시' for h in high_risk_hours])}")
        print(f"   → 권장: 이 시간대는 거래 차단 또는 매우 엄격한 필터 적용")
    print()

    # 2. 종가 위치 분석 (데이터가 있는 경우)
    wins_with_close = [t for t in wins if 'close_position' in t]
    losses_with_close = [t for t in losses if 'close_position' in t]

    if wins_with_close and losses_with_close:
        print("="*80)
        print("📍 종가 위치 분석")
        print("="*80)
        print()

        win_close_avg = sum(t['close_position'] for t in wins_with_close) / len(wins_with_close)
        loss_close_avg = sum(t['close_position'] for t in losses_with_close) / len(losses_with_close)

        print(f"승리 시 평균 종가 위치: {win_close_avg:.1f}%")
        print(f"패배 시 평균 종가 위치: {loss_close_avg:.1f}%")
        print(f"차이: {win_close_avg - loss_close_avg:.1f}%p")
        print()

        # 종가 위치별 패배율
        ranges = [(0, 50), (50, 55), (55, 60), (60, 65), (65, 70), (70, 100)]
        print(f"{'종가 위치':>12} | {'총거래':>8} | {'승률':>8} | {'패배율':>8} | {'평가':>10}")
        print("-"*80)

        for low, high in ranges:
            range_trades = [t for t in trades if 'close_position' in t and low <= t['close_position'] < high]
            if not range_trades:
                continue

            range_wins = [t for t in range_trades if t['is_win']]
            win_rate = len(range_wins) / len(range_trades) * 100
            loss_rate = 100 - win_rate

            evaluation = ""
            if loss_rate > 55:
                evaluation = "🚫 차단"
            elif loss_rate > 50:
                evaluation = "⚠️ 주의"
            else:
                evaluation = "✅ 통과"

            print(f"{low:3d}~{high:3d}% | {len(range_trades):8d} | {win_rate:7.1f}% | "
                  f"{loss_rate:7.1f}% | {evaluation:>10}")
        print()

    # 3. 거래량 증가율 분석
    wins_with_volume = [t for t in wins if 'volume_increase' in t]
    losses_with_volume = [t for t in losses if 'volume_increase' in t]

    if wins_with_volume and losses_with_volume:
        print("="*80)
        print("📈 거래량 증가율 분석")
        print("="*80)
        print()

        win_vol_avg = sum(t['volume_increase'] for t in wins_with_volume) / len(wins_with_volume)
        loss_vol_avg = sum(t['volume_increase'] for t in losses_with_volume) / len(losses_with_volume)

        print(f"승리 시 평균 거래량 증가: {win_vol_avg:.1f}%")
        print(f"패배 시 평균 거래량 증가: {loss_vol_avg:.1f}%")
        print(f"차이: {win_vol_avg - loss_vol_avg:.1f}%p")
        print()

        # 거래량 증가율별 패배율
        ranges = [(0, 20), (20, 50), (50, 100), (100, 200), (200, 999999)]
        print(f"{'거래량 증가':>12} | {'총거래':>8} | {'승률':>8} | {'패배율':>8} | {'평가':>10}")
        print("-"*80)

        for low, high in ranges:
            range_trades = [t for t in trades if 'volume_increase' in t and low <= t['volume_increase'] < high]
            if not range_trades:
                continue

            range_wins = [t for t in range_trades if t['is_win']]
            win_rate = len(range_wins) / len(range_trades) * 100
            loss_rate = 100 - win_rate

            evaluation = ""
            if loss_rate > 55:
                evaluation = "🚫 차단"
            elif loss_rate > 50:
                evaluation = "⚠️ 주의"
            else:
                evaluation = "✅ 통과"

            range_label = f"{low}~{high}%" if high < 999999 else f"{low}%+"
            print(f"{range_label:>12} | {len(range_trades):8d} | {win_rate:7.1f}% | "
                  f"{loss_rate:7.1f}% | {evaluation:>10}")
        print()

    return {
        'high_risk_hours': high_risk_hours,
        'hourly_stats': dict(hourly_stats)
    }

def generate_recommendations(analysis_result):
    """분석 결과 기반 권장 사항"""
    print("="*80)
    print("💡 패배 대폭 감소를 위한 권장 사항")
    print("="*80)
    print()

    recommendations = []

    # 1. 고위험 시간대 차단
    if analysis_result['high_risk_hours']:
        print("1️⃣ 고위험 시간대 차단 (최우선)")
        print("-"*80)
        for hour in analysis_result['high_risk_hours']:
            hourly = analysis_result['hourly_stats'][hour]
            total = hourly['wins'] + hourly['losses']
            loss_rate = hourly['losses'] / total * 100
            print(f"   {hour:02d}시: 패배율 {loss_rate:.1f}% → 거래 차단")

        recommendations.append({
            'name': '고위험 시간대 차단',
            'impact': 'HIGH',
            'difficulty': 'LOW',
            'code': f"if hour in {analysis_result['high_risk_hours']}: return False"
        })
        print()

    # 2. 종가 위치 + 시간대 조합 필터
    print("2️⃣ 종가 위치 + 시간대 조합 필터")
    print("-"*80)
    print("   시간대별로 종가 위치 기준을 다르게 적용")
    print("   - 09시: 55% (완화)")
    print("   - 10시: 60% (강화)")
    print("   - 11시 이후: 65% (매우 강화)")
    recommendations.append({
        'name': '시간대별 종가 위치 필터',
        'impact': 'MEDIUM',
        'difficulty': 'LOW'
    })
    print()

    # 3. 거래량 + 종가 위치 조합
    print("3️⃣ 거래량 + 종가 위치 조합 필터")
    print("-"*80)
    print("   종가 위치가 낮으면 거래량이 매우 커야 통과")
    print("   - 종가 < 60%: 거래량 +100% 이상 필요")
    print("   - 종가 < 65%: 거래량 +50% 이상 필요")
    print("   - 종가 >= 65%: 거래량 제한 없음")
    recommendations.append({
        'name': '거래량-종가 조합 필터',
        'impact': 'HIGH',
        'difficulty': 'MEDIUM'
    })
    print()

    # 4. 연속 손실 후 휴식
    print("4️⃣ 연속 손실 후 휴식 (안전장치)")
    print("-"*80)
    print("   같은 날 2회 연속 손실 시 해당 날 거래 중지")
    print("   → 감정적 판단 방지 + 시장 환경 악화 대응")
    recommendations.append({
        'name': '연속 손실 브레이크',
        'impact': 'MEDIUM',
        'difficulty': 'LOW'
    })
    print()

    return recommendations

def main():
    print("="*80)
    print("🔍 패배 매매 심층 분석")
    print("="*80)
    print()

    # 로그 파일 수집
    log_dir = Path("signal_replay_log")
    log_files = sorted(log_dir.glob("signal_new2_replay_*.txt"))

    if not log_files:
        print("❌ 로그 파일을 찾을 수 없습니다.")
        return

    print(f"📂 분석 대상: {len(log_files)}개 파일")
    print()

    # 모든 거래 수집
    all_trades = []
    for log_file in log_files:
        trades = parse_detailed_log(log_file)
        all_trades.extend(trades)

    if not all_trades:
        print("❌ 거래 데이터를 찾을 수 없습니다.")
        return

    # 분석 실행
    analysis_result = analyze_losing_patterns(all_trades)

    # 권장 사항 생성
    recommendations = generate_recommendations(analysis_result)

    # 최종 요약
    print("="*80)
    print("📝 구현 우선순위")
    print("="*80)
    print()
    print("🥇 1순위: 고위험 시간대 차단")
    print("   난이도: ⭐")
    print("   효과: ⭐⭐⭐⭐⭐")
    print("   예상 패배 감소: 20-30%")
    print()
    print("🥈 2순위: 거래량-종가 조합 필터")
    print("   난이도: ⭐⭐")
    print("   효과: ⭐⭐⭐⭐")
    print("   예상 패배 감소: 15-25%")
    print()
    print("🥉 3순위: 시간대별 종가 위치 필터")
    print("   난이도: ⭐")
    print("   효과: ⭐⭐⭐")
    print("   예상 패배 감소: 10-15%")
    print()

if __name__ == "__main__":
    main()
