"""
지지 캔들 ≥ 2 기준 승/패 패턴 분석
signal_replay_log 결과에서 거래 패턴 분석하여 새로운 필터 개발

실행:
    python analyze_support_patterns.py
"""

import os
import re
from datetime import datetime
from collections import defaultdict

# 경로 설정
SIGNAL_LOG_DIR = "signal_replay_log"
OUTPUT_FILE = "analysis_support_pattern_report.txt"


def parse_summary_line(line):
    """요약 라인에서 거래 정보 추출

    예: 🔴 067000(조이시티) 09:36 매수 → -2.50%
        🟢 039490(키움증권) 09:44 매수 → +0.93%
    """
    # 패턴: 이모지 종목코드(종목명) 시간 매수 → 수익률
    pattern = r'[🔴🟢]\s+(\d{6})\(([^)]+)\)\s+(\d{1,2}:\d{2})\s+매수\s+→\s+([+-]?\d+\.?\d*)%'
    match = re.search(pattern, line)

    if match:
        return {
            'stock_code': match.group(1),
            'stock_name': match.group(2),
            'buy_time': match.group(3),
            'profit_pct': float(match.group(4)),
            'is_win': float(match.group(4)) > 0
        }
    return None


def extract_trades_from_file(filepath):
    """파일에서 모든 거래 추출"""
    trades = []

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        in_summary = False
        for line in lines:
            line = line.strip()

            # 요약 섹션 시작
            if '12시 이전 매수 종목' in line:
                in_summary = True
                continue

            # 상세 섹션 시작하면 요약 끝
            if in_summary and line.startswith('===') and '눌림목' not in line:
                break

            # 요약 섹션에서 거래 파싱
            if in_summary:
                trade = parse_summary_line(line)
                if trade:
                    trades.append(trade)

    except Exception as e:
        print(f"⚠️ 파일 읽기 오류 ({filepath}): {e}")

    return trades


def extract_date_from_filename(filename):
    """파일명에서 날짜 추출

    예: signal_new2_replay_20260130_9_00_0.txt → 20260130
    """
    match = re.search(r'(\d{8})', filename)
    return match.group(1) if match else None


def analyze_patterns(all_trades):
    """승/패 패턴 분석"""

    wins = [t for t in all_trades if t['is_win']]
    losses = [t for t in all_trades if not t['is_win']]

    print(f"\n기본 통계:")
    print(f"  총 거래: {len(all_trades)}건")
    print(f"  승리: {len(wins)}건 ({len(wins)/len(all_trades)*100:.1f}%)")
    print(f"  패배: {len(losses)}건 ({len(losses)/len(all_trades)*100:.1f}%)")

    # 시간대별 분석
    print(f"\n시간대별 승률:")
    hourly_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

    for trade in all_trades:
        hour = int(trade['buy_time'].split(':')[0])
        if trade['is_win']:
            hourly_stats[hour]['wins'] += 1
        else:
            hourly_stats[hour]['losses'] += 1

    for hour in sorted(hourly_stats.keys()):
        stats = hourly_stats[hour]
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        print(f"  {hour:02d}시: {stats['wins']}승 {stats['losses']}패 = {win_rate:.1f}% ({total}건)")

    # 종목별 분석 (상위/하위)
    print(f"\n종목별 분석:")
    stock_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

    for trade in all_trades:
        code = trade['stock_code']
        if trade['is_win']:
            stock_stats[code]['wins'] += 1
        else:
            stock_stats[code]['losses'] += 1

    # 거래 많은 종목
    stock_totals = [(code, stats['wins'] + stats['losses'], stats)
                    for code, stats in stock_stats.items()]
    stock_totals.sort(key=lambda x: x[1], reverse=True)

    print(f"\n  거래 많은 종목 TOP 10:")
    for code, total, stats in stock_totals[:10]:
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        print(f"    {code}: {stats['wins']}승 {stats['losses']}패 = {win_rate:.1f}% ({total}건)")

    # 승률 낮은 종목
    stock_winrates = [(code, stats['wins'] / (stats['wins'] + stats['losses']) * 100,
                       stats['wins'] + stats['losses'], stats)
                      for code, stats in stock_stats.items()
                      if stats['wins'] + stats['losses'] >= 3]  # 최소 3건 이상
    stock_winrates.sort(key=lambda x: x[1])

    print(f"\n  승률 낮은 종목 (3건 이상):")
    for code, winrate, total, stats in stock_winrates[:10]:
        print(f"    {code}: {stats['wins']}승 {stats['losses']}패 = {winrate:.1f}% ({total}건)")

    # 요일별 분석 (날짜 정보가 있다면)
    if 'date' in all_trades[0]:
        print(f"\n요일별 승률:")
        weekday_stats = defaultdict(lambda: {'wins': 0, 'losses': 0})

        for trade in all_trades:
            try:
                date_obj = datetime.strptime(trade['date'], '%Y%m%d')
                weekday = date_obj.weekday()  # 0=월, 1=화, ...
                if trade['is_win']:
                    weekday_stats[weekday]['wins'] += 1
                else:
                    weekday_stats[weekday]['losses'] += 1
            except:
                pass

        weekday_names = ['월', '화', '수', '목', '금']
        for day in range(5):
            if day in weekday_stats:
                stats = weekday_stats[day]
                total = stats['wins'] + stats['losses']
                win_rate = stats['wins'] / total * 100 if total > 0 else 0
                print(f"  {weekday_names[day]}요일: {stats['wins']}승 {stats['losses']}패 = {win_rate:.1f}% ({total}건)")

    return {
        'hourly': hourly_stats,
        'stocks': stock_stats,
        'weekday': weekday_stats if 'date' in all_trades[0] else {}
    }


def main():
    print("=" * 70)
    print("지지 캔들 ≥ 2 기준 승/패 패턴 분석")
    print("=" * 70)

    # 모든 시뮬레이션 파일 수집
    all_trades = []
    file_count = 0

    for filename in sorted(os.listdir(SIGNAL_LOG_DIR)):
        if filename.startswith('signal_new2_replay_') and filename.endswith('.txt'):
            filepath = os.path.join(SIGNAL_LOG_DIR, filename)
            date_str = extract_date_from_filename(filename)

            trades = extract_trades_from_file(filepath)

            # 각 거래에 날짜 정보 추가
            for trade in trades:
                trade['date'] = date_str

            all_trades.extend(trades)
            file_count += 1

    print(f"\n파일 수: {file_count}개")
    print(f"총 거래 수: {len(all_trades)}개")

    if len(all_trades) == 0:
        print("❌ 거래 데이터가 없습니다.")
        return

    # 패턴 분석
    analysis = analyze_patterns(all_trades)

    # 필터 제안
    print("\n" + "=" * 70)
    print("필터 제안:")
    print("=" * 70)

    # 시간대 필터
    print("\n1. 시간대 필터:")
    for hour, stats in sorted(analysis['hourly'].items()):
        total = stats['wins'] + stats['losses']
        win_rate = stats['wins'] / total * 100 if total > 0 else 0
        if win_rate < 40 and total >= 10:
            print(f"  ⚠️ {hour}시 회피 권장 (승률 {win_rate:.1f}%, {total}건)")

    # 종목 블랙리스트
    print("\n2. 종목 블랙리스트 (승률 30% 이하, 3건 이상):")
    stock_blacklist = []
    for code, stats in analysis['stocks'].items():
        total = stats['wins'] + stats['losses']
        if total >= 3:
            win_rate = stats['wins'] / total * 100
            if win_rate <= 30:
                stock_blacklist.append(code)
                print(f"  {code}: {win_rate:.1f}% ({stats['wins']}승 {stats['losses']}패)")

    if stock_blacklist:
        print(f"\n  블랙리스트 코드: {stock_blacklist}")

    # 요일 필터
    if analysis['weekday']:
        print("\n3. 요일 필터:")
        weekday_names = ['월', '화', '수', '목', '금']
        for day, stats in sorted(analysis['weekday'].items()):
            total = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total * 100 if total > 0 else 0
            if win_rate < 40 and total >= 20:
                print(f"  ⚠️ {weekday_names[day]}요일 회피 권장 (승률 {win_rate:.1f}%, {total}건)")

    print("\n분석 완료!")


if __name__ == '__main__':
    main()
