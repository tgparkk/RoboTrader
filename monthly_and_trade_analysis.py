"""
월별 및 승/패 종목 특징 분석 스크립트
"""
import os
import re
import json
from collections import defaultdict
from datetime import datetime

def parse_signal_replay_file(file_path):
    """신호 리플레이 파일 파싱"""
    trades = []

    with open(file_path, 'r', encoding='utf-8-sig') as f:
        content = f.read()

    # 날짜 추출 (파일명에서)
    filename = os.path.basename(file_path)
    date_match = re.search(r'(\d{8})', filename)
    if not date_match:
        return trades

    trade_date = date_match.group(1)

    # 12시 이전 매수 종목 섹션에서 거래 파싱
    # 패턴: 🟢 또는 🔴 + 종목코드 + 시간 + 수익률
    trade_pattern = r'[🟢🔴]\s+(\d{6})\s+(\d{2}:\d{2})\s+매수\s+→\s+([-+]?\d+\.\d+)%'
    matches = re.findall(trade_pattern, content)

    for match in matches:
        stock_code, time_str, profit_rate = match
        profit_rate = float(profit_rate)
        is_win = profit_rate > 0

        # 시간을 전체 datetime 형식으로 변환
        trade_time = f"{trade_date[:4]}-{trade_date[4:6]}-{trade_date[6:8]} {time_str}:00"
        hour = int(time_str.split(':')[0])

        trade = {
            'date': trade_date,
            'time': trade_time,
            'hour': hour,
            'code': stock_code,
            'profit_rate': profit_rate,
            'is_win': is_win,
            'close_reason': '익절' if profit_rate >= 3.5 else '손절' if profit_rate <= -2.5 else '부분익절'
        }

        trades.append(trade)

    return trades

def collect_all_trades(log_dir):
    """모든 거래 데이터 수집"""
    all_trades = []

    for filename in os.listdir(log_dir):
        if filename.startswith('signal_new2_replay_') and filename.endswith('.txt'):
            file_path = os.path.join(log_dir, filename)
            trades = parse_signal_replay_file(file_path)
            all_trades.extend(trades)

    return all_trades

def analyze_monthly_comparison(trades):
    """월별 비교 분석"""
    monthly_data = defaultdict(lambda: {
        'total': 0,
        'wins': 0,
        'losses': 0,
        'total_profit': 0.0,
        'win_profits': [],
        'loss_profits': [],
        'trades': []
    })

    for trade in trades:
        month = trade['date'][:6]  # YYYYMM
        data = monthly_data[month]

        data['total'] += 1
        data['total_profit'] += trade['profit_rate']
        data['trades'].append(trade)

        if trade['is_win']:
            data['wins'] += 1
            data['win_profits'].append(trade['profit_rate'])
        else:
            data['losses'] += 1
            data['loss_profits'].append(trade['profit_rate'])

    # 통계 계산
    monthly_stats = {}
    for month, data in monthly_data.items():
        win_rate = (data['wins'] / data['total'] * 100) if data['total'] > 0 else 0
        avg_profit = data['total_profit'] / data['total'] if data['total'] > 0 else 0
        avg_win = sum(data['win_profits']) / len(data['win_profits']) if data['win_profits'] else 0
        avg_loss = sum(data['loss_profits']) / len(data['loss_profits']) if data['loss_profits'] else 0

        # 실제 수익금 계산 (실제 수익률 기반, 100만원 거래 기준)
        actual_profit = 0
        for trade in data['trades']:
            # 실제 수익률을 그대로 반영 (%, 100만원 기준)
            actual_profit += trade['profit_rate'] * 10000

        monthly_stats[month] = {
            'total_trades': data['total'],
            'wins': data['wins'],
            'losses': data['losses'],
            'win_rate': win_rate,
            'total_profit': data['total_profit'],
            'avg_profit': avg_profit,
            'avg_win': avg_win,
            'avg_loss': avg_loss,
            'actual_profit': actual_profit,
            'trades': data['trades']
        }

    return monthly_stats

def analyze_win_loss_characteristics(trades):
    """승리/패배 종목 특징 분석"""

    # 승리와 패배 거래 분리
    winning_trades = [t for t in trades if t['is_win']]
    losing_trades = [t for t in trades if not t['is_win']]

    def analyze_group(trades, label):
        """그룹별 특징 분석"""
        if not trades:
            return {
                'total_count': 0,
                'close_reasons': {},
                'hourly_distribution': {},
                'top_stocks': [],
                'avg_profit_rate': 0
            }

        # 청산 사유별 통계
        close_reasons = defaultdict(int)
        for t in trades:
            close_reasons[t['close_reason']] += 1

        # 시간대별 통계
        hourly_stats = defaultdict(int)
        for t in trades:
            hourly_stats[t['hour']] += 1

        # 종목별 빈도
        stock_frequency = defaultdict(int)
        for t in trades:
            stock_frequency[t['code']] += 1

        # 상위 10개 종목
        top_stocks = sorted(stock_frequency.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            'total_count': len(trades),
            'close_reasons': dict(close_reasons),
            'hourly_distribution': dict(hourly_stats),
            'top_stocks': top_stocks,
            'avg_profit_rate': sum(t['profit_rate'] for t in trades) / len(trades)
        }

    winning_analysis = analyze_group(winning_trades, 'winning')
    losing_analysis = analyze_group(losing_trades, 'losing')

    return {
        'winning': winning_analysis,
        'losing': losing_analysis,
        'comparison': compare_characteristics(winning_analysis, losing_analysis)
    }

def compare_characteristics(winning, losing):
    """승/패 특징 비교"""
    comparison = {}

    # 시간대 비교
    win_hourly = winning.get('hourly_distribution', {})
    loss_hourly = losing.get('hourly_distribution', {})
    comparison['hourly_comparison'] = {
        'winning': win_hourly,
        'losing': loss_hourly
    }

    # 승률이 높은 시간대 찾기
    win_total = winning.get('total_count', 0)
    loss_total = losing.get('total_count', 0)

    if win_total > 0 and loss_total > 0:
        hourly_win_rates = {}
        all_hours = set(list(win_hourly.keys()) + list(loss_hourly.keys()))
        for hour in all_hours:
            wins = win_hourly.get(hour, 0)
            losses = loss_hourly.get(hour, 0)
            total = wins + losses
            if total > 0:
                hourly_win_rates[hour] = (wins / total) * 100

        comparison['hourly_win_rates'] = hourly_win_rates

    return comparison

def generate_report(monthly_stats, win_loss_analysis):
    """분석 리포트 생성"""
    report = []
    report.append("=" * 80)
    report.append("📊 월별 및 승/패 종목 특징 분석 리포트")
    report.append("=" * 80)
    report.append("")

    # === 월별 비교 ===
    report.append("📅 월별 성과 비교")
    report.append("-" * 80)

    sorted_months = sorted(monthly_stats.keys())
    for month in sorted_months:
        stats = monthly_stats[month]
        report.append(f"\n[{month[:4]}년 {month[4:]}월]")
        report.append(f"총 거래: {stats['total_trades']}건")
        report.append(f"승리: {stats['wins']}건 / 패배: {stats['losses']}건")
        report.append(f"승률: {stats['win_rate']:.1f}%")
        report.append(f"총 수익률: {stats['total_profit']:+.2f}%")
        report.append(f"평균 수익률: {stats['avg_profit']:+.2f}%")
        report.append(f"평균 승리: {stats['avg_win']:+.2f}%")
        report.append(f"평균 손실: {stats['avg_loss']:+.2f}%")
        report.append(f"실제 수익금: {stats['actual_profit']:+,}원")

    # 월별 차이 분석
    if len(sorted_months) >= 2:
        report.append("\n" + "=" * 80)
        report.append("📈 월별 차이 분석")
        report.append("-" * 80)

        for i in range(len(sorted_months) - 1):
            month1 = sorted_months[i]
            month2 = sorted_months[i + 1]
            stats1 = monthly_stats[month1]
            stats2 = monthly_stats[month2]

            report.append(f"\n[{month1} vs {month2}]")
            report.append(f"거래 수 변화: {stats1['total_trades']}건 → {stats2['total_trades']}건 ({stats2['total_trades']-stats1['total_trades']:+d}건)")
            report.append(f"승률 변화: {stats1['win_rate']:.1f}% → {stats2['win_rate']:.1f}% ({stats2['win_rate']-stats1['win_rate']:+.1f}%p)")
            report.append(f"평균 수익률 변화: {stats1['avg_profit']:+.2f}% → {stats2['avg_profit']:+.2f}% ({stats2['avg_profit']-stats1['avg_profit']:+.2f}%p)")
            report.append(f"실제 수익금 변화: {stats1['actual_profit']:+,}원 → {stats2['actual_profit']:+,}원 ({stats2['actual_profit']-stats1['actual_profit']:+,}원)")

    # === 승/패 특징 분석 ===
    report.append("\n" + "=" * 80)
    report.append("🎯 승리 vs 패배 종목 특징 분석")
    report.append("=" * 80)

    winning = win_loss_analysis['winning']
    losing = win_loss_analysis['losing']
    comparison = win_loss_analysis['comparison']

    # 기본 통계
    report.append("\n[기본 통계]")
    report.append(f"총 승리 거래: {winning['total_count']}건")
    report.append(f"총 패배 거래: {losing['total_count']}건")
    report.append(f"승리 평균 수익률: {winning['avg_profit_rate']:+.2f}%")
    report.append(f"패배 평균 손실률: {losing['avg_profit_rate']:+.2f}%")

    # 청산 사유 비교
    report.append("\n[청산 사유 분석]")
    report.append("승리 거래 청산 사유:")
    if winning['close_reasons']:
        for reason, count in sorted(winning['close_reasons'].items(), key=lambda x: x[1], reverse=True):
            percentage = count / winning['total_count'] * 100 if winning['total_count'] > 0 else 0
            report.append(f"  - {reason}: {count}건 ({percentage:.1f}%)")
    else:
        report.append("  - 데이터 없음")

    report.append("\n패배 거래 청산 사유:")
    if losing['close_reasons']:
        for reason, count in sorted(losing['close_reasons'].items(), key=lambda x: x[1], reverse=True):
            percentage = count / losing['total_count'] * 100 if losing['total_count'] > 0 else 0
            report.append(f"  - {reason}: {count}건 ({percentage:.1f}%)")
    else:
        report.append("  - 데이터 없음")

    # 시간대 분포 비교
    report.append("\n[시간대 분포 분석]")
    report.append("승리 거래 시간대:")
    if winning['hourly_distribution']:
        for hour, count in sorted(winning['hourly_distribution'].items()):
            percentage = count / winning['total_count'] * 100 if winning['total_count'] > 0 else 0
            report.append(f"  - {hour:02d}시: {count}건 ({percentage:.1f}%)")
    else:
        report.append("  - 데이터 없음")

    report.append("\n패배 거래 시간대:")
    if losing['hourly_distribution']:
        for hour, count in sorted(losing['hourly_distribution'].items()):
            percentage = count / losing['total_count'] * 100 if losing['total_count'] > 0 else 0
            report.append(f"  - {hour:02d}시: {count}건 ({percentage:.1f}%)")
    else:
        report.append("  - 데이터 없음")

    # 시간대별 승률
    if 'hourly_win_rates' in comparison:
        report.append("\n시간대별 승률:")
        for hour, win_rate in sorted(comparison['hourly_win_rates'].items()):
            report.append(f"  - {hour:02d}시: {win_rate:.1f}%")

    # 자주 나오는 종목 비교
    report.append("\n[자주 거래된 종목 (상위 10개)]")
    report.append("승리가 많은 종목:")
    if winning['top_stocks']:
        for i, (code, count) in enumerate(winning['top_stocks'], 1):
            report.append(f"  {i}. {code}: {count}회")
    else:
        report.append("  - 데이터 없음")

    report.append("\n패배가 많은 종목:")
    if losing['top_stocks']:
        for i, (code, count) in enumerate(losing['top_stocks'], 1):
            report.append(f"  {i}. {code}: {count}회")
    else:
        report.append("  - 데이터 없음")

    # === 인사이트 및 권장사항 ===
    report.append("\n" + "=" * 80)
    report.append("💡 주요 인사이트 및 권장사항")
    report.append("=" * 80)

    # 월별 인사이트
    if len(sorted_months) >= 2:
        month1 = sorted_months[0]
        month2 = sorted_months[-1]
        stats1 = monthly_stats[month1]
        stats2 = monthly_stats[month2]

        report.append(f"\n1. 월별 성과 변화 ({month1} → {month2})")

        if stats2['win_rate'] < stats1['win_rate']:
            report.append(f"   - 승률이 {stats1['win_rate']:.1f}%에서 {stats2['win_rate']:.1f}%로 하락했습니다.")
            report.append(f"   - 특히 평균 수익률도 {stats1['avg_profit']:.2f}%에서 {stats2['avg_profit']:.2f}%로 감소했습니다.")

        if stats2['actual_profit'] < stats1['actual_profit']:
            profit_decrease = stats1['actual_profit'] - stats2['actual_profit']
            report.append(f"   - 실제 수익금이 {profit_decrease:,}원 감소했습니다.")

    # 승/패 인사이트
    report.append("\n2. 승리/패배 특징 차이")

    # 시간대별 승률 인사이트
    if 'hourly_win_rates' in comparison:
        hourly_win_rates = comparison['hourly_win_rates']
        if hourly_win_rates:
            best_hour = max(hourly_win_rates.items(), key=lambda x: x[1])
            worst_hour = min(hourly_win_rates.items(), key=lambda x: x[1])
            report.append(f"   - 가장 승률이 높은 시간대: {best_hour[0]:02d}시 ({best_hour[1]:.1f}%)")
            report.append(f"   - 가장 승률이 낮은 시간대: {worst_hour[0]:02d}시 ({worst_hour[1]:.1f}%)")

    # 종목별 인사이트
    win_codes = set([code for code, _ in winning['top_stocks']])
    loss_codes = set([code for code, _ in losing['top_stocks']])
    common_codes = win_codes & loss_codes
    if common_codes:
        report.append(f"   - 승리/패배 모두에 자주 등장하는 종목: {len(common_codes)}개")
        report.append(f"     {', '.join(list(common_codes)[:5])}")

    report.append("\n3. 개선 방향 제안")
    if 'hourly_win_rates' in comparison and comparison['hourly_win_rates']:
        best_hour = max(comparison['hourly_win_rates'].items(), key=lambda x: x[1])
        if best_hour[1] > 55:
            report.append(f"   - 시간대별 가중치 조정: {best_hour[0]:02d}시대 거래 비중 증가 고려 (승률 {best_hour[1]:.1f}%)")
    report.append("   - 종목별 승률 분석: 반복적으로 패배하는 종목 제외 고려")
    report.append("   - 청산 사유 분석: 손절이 많은 패턴 파악 및 조건 강화")

    return "\n".join(report)

def main():
    log_dir = 'signal_replay_log'

    print("거래 데이터 수집 중...")
    all_trades = collect_all_trades(log_dir)
    print(f"총 {len(all_trades)}건의 거래 수집 완료")

    print("\n월별 분석 중...")
    monthly_stats = analyze_monthly_comparison(all_trades)

    print("승/패 특징 분석 중...")
    win_loss_analysis = analyze_win_loss_characteristics(all_trades)

    print("\n리포트 생성 중...")
    report = generate_report(monthly_stats, win_loss_analysis)

    # 파일 저장
    output_file = 'MONTHLY_AND_WIN_LOSS_ANALYSIS.md'
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(report)

    print(f"\n분석 리포트가 '{output_file}' 파일로 저장되었습니다.")

    # JSON 데이터도 저장
    json_output = {
        'monthly_stats': {k: {
            'total_trades': v['total_trades'],
            'wins': v['wins'],
            'losses': v['losses'],
            'win_rate': v['win_rate'],
            'total_profit': v['total_profit'],
            'avg_profit': v['avg_profit'],
            'avg_win': v['avg_win'],
            'avg_loss': v['avg_loss'],
            'actual_profit': v['actual_profit']
        } for k, v in monthly_stats.items()},
        'win_loss_analysis': win_loss_analysis
    }

    json_file = 'monthly_and_win_loss_analysis.json'
    with open(json_file, 'w', encoding='utf-8') as f:
        json.dump(json_output, f, ensure_ascii=False, indent=2)

    print(f"JSON 데이터가 '{json_file}' 파일로 저장되었습니다.")

if __name__ == '__main__':
    main()
