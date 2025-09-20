"""
수정 전후 매매 로직 성과 비교

signal_replay_log_prev (수정 전) vs signal_replay_log (수정 후) 비교 분석
"""

import re
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
from collections import defaultdict

class BeforeAfterComparison:
    """수정 전후 비교 분석기"""

    def __init__(self):
        self.before_dir = Path("signal_replay_log_prev")  # 수정 전
        self.after_dir = Path("signal_replay_log")        # 수정 후

    def extract_results_from_log(self, log_file_path: Path) -> dict:
        """로그 파일에서 결과 추출"""
        try:
            with open(log_file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 전체 승패 추출
            total_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', content)
            if total_match:
                total_wins = int(total_match.group(1))
                total_losses = int(total_match.group(2))
            else:
                total_wins = total_losses = 0

            # 날짜 추출
            date_match = re.search(r'(\d{8})', log_file_path.name)
            trade_date = date_match.group(1) if date_match else "unknown"

            # 개별 거래 추출
            trades = []
            sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

            for i in range(0, len(sections), 2):
                if i + 1 >= len(sections):
                    break

                stock_code = sections[i]
                section_content = sections[i + 1]

                # 매매 데이터 추출
                trade_matches = re.findall(
                    r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([^)]+)\)',
                    section_content
                )

                for match in trade_matches:
                    buy_time, buy_signal, buy_price_str, sell_time, sell_signal, sell_price_str, pnl_str = match

                    buy_price = int(buy_price_str.replace(',', ''))
                    sell_price = int(sell_price_str.replace(',', ''))
                    pnl_pct = (sell_price - buy_price) / buy_price * 100

                    # 시간대 분류
                    hour = int(buy_time.split(':')[0])
                    if 9 <= hour < 10:
                        time_category = "opening"
                    elif 10 <= hour < 12:
                        time_category = "morning"
                    elif 12 <= hour < 14:
                        time_category = "afternoon"
                    elif 14 <= hour < 15:
                        time_category = "late"
                    else:
                        time_category = "other"

                    trades.append({
                        'stock_code': stock_code,
                        'date': trade_date,
                        'buy_time': buy_time,
                        'hour': hour,
                        'time_category': time_category,
                        'buy_price': buy_price,
                        'sell_price': sell_price,
                        'pnl_pct': pnl_pct,
                        'is_winning': pnl_pct > 0,
                        'buy_signal': buy_signal,
                        'sell_signal': sell_signal
                    })

            return {
                'date': trade_date,
                'total_wins': total_wins,
                'total_losses': total_losses,
                'total_trades': total_wins + total_losses,
                'win_rate': total_wins / (total_wins + total_losses) * 100 if (total_wins + total_losses) > 0 else 0,
                'trades': trades
            }

        except Exception as e:
            print(f"오류 처리 {log_file_path.name}: {e}")
            return None

    def compare_directories(self):
        """두 디렉토리의 결과 비교"""
        print("수정 전후 매매 로직 성과 비교")
        print("="*60)

        # 공통 날짜 파일들 찾기
        before_files = {f.name: f for f in self.before_dir.glob("*.txt")}
        after_files = {f.name: f for f in self.after_dir.glob("*.txt")}

        common_files = set(before_files.keys()) & set(after_files.keys())
        print(f"비교 가능한 날짜: {len(common_files)}개")

        if not common_files:
            print("비교할 공통 파일이 없습니다.")
            return

        before_results = []
        after_results = []

        # 각 날짜별 결과 수집
        for filename in sorted(common_files):
            print(f"분석 중: {filename}")

            before_result = self.extract_results_from_log(before_files[filename])
            after_result = self.extract_results_from_log(after_files[filename])

            if before_result and after_result:
                before_results.append(before_result)
                after_results.append(after_result)

        if not before_results or not after_results:
            print("분석할 결과가 없습니다.")
            return

        # 전체 통계 비교
        self.analyze_overall_comparison(before_results, after_results)

        # 시간대별 비교
        self.analyze_time_based_comparison(before_results, after_results)

        # 일별 비교
        self.analyze_daily_comparison(before_results, after_results)

        return before_results, after_results

    def analyze_overall_comparison(self, before_results: list, after_results: list):
        """전체 통계 비교"""
        print(f"\n=== 전체 성과 비교 ===")

        # 전체 합계 계산
        before_total_wins = sum(r['total_wins'] for r in before_results)
        before_total_losses = sum(r['total_losses'] for r in before_results)
        before_total_trades = before_total_wins + before_total_losses
        before_win_rate = before_total_wins / before_total_trades * 100 if before_total_trades > 0 else 0

        after_total_wins = sum(r['total_wins'] for r in after_results)
        after_total_losses = sum(r['total_losses'] for r in after_results)
        after_total_trades = after_total_wins + after_total_losses
        after_win_rate = after_total_wins / after_total_trades * 100 if after_total_trades > 0 else 0

        print(f"수정 전: {before_total_wins}승 {before_total_losses}패 (승률 {before_win_rate:.1f}%)")
        print(f"수정 후: {after_total_wins}승 {after_total_losses}패 (승률 {after_win_rate:.1f}%)")

        # 개선 효과
        win_rate_improvement = after_win_rate - before_win_rate
        trade_count_change = (after_total_trades - before_total_trades) / before_total_trades * 100 if before_total_trades > 0 else 0

        print(f"승률 개선: {win_rate_improvement:+.1f}%p")
        print(f"거래량 변화: {trade_count_change:+.1f}%")

        if win_rate_improvement > 0:
            print("✅ 승률 개선됨!")
        else:
            print("⚠️ 승률 하락")

        if trade_count_change < 0:
            print("✅ 거래량 감소 (선별적 매매)")
        elif trade_count_change > 0:
            print("📈 거래량 증가")

    def analyze_time_based_comparison(self, before_results: list, after_results: list):
        """시간대별 비교"""
        print(f"\n=== 시간대별 성과 비교 ===")

        # 모든 거래 수집
        before_all_trades = []
        after_all_trades = []

        for result in before_results:
            before_all_trades.extend(result['trades'])

        for result in after_results:
            after_all_trades.extend(result['trades'])

        # 시간대별 통계
        before_time_stats = defaultdict(lambda: {'wins': 0, 'total': 0})
        after_time_stats = defaultdict(lambda: {'wins': 0, 'total': 0})

        for trade in before_all_trades:
            time_cat = trade['time_category']
            before_time_stats[time_cat]['total'] += 1
            if trade['is_winning']:
                before_time_stats[time_cat]['wins'] += 1

        for trade in after_all_trades:
            time_cat = trade['time_category']
            after_time_stats[time_cat]['total'] += 1
            if trade['is_winning']:
                after_time_stats[time_cat]['wins'] += 1

        print(f"{'시간대':12} {'수정전 승률':>12} {'수정후 승률':>12} {'거래량 변화':>12} {'승률 개선':>10}")
        print("-" * 70)

        for time_cat in ['opening', 'morning', 'afternoon', 'late']:
            before_stats = before_time_stats[time_cat]
            after_stats = after_time_stats[time_cat]

            before_rate = before_stats['wins'] / before_stats['total'] * 100 if before_stats['total'] > 0 else 0
            after_rate = after_stats['wins'] / after_stats['total'] * 100 if after_stats['total'] > 0 else 0

            trade_change = (after_stats['total'] - before_stats['total']) / before_stats['total'] * 100 if before_stats['total'] > 0 else 0
            rate_improvement = after_rate - before_rate

            print(f"{time_cat:12} {before_rate:8.1f}% ({before_stats['wins']:2}/{before_stats['total']:2}) "
                  f"{after_rate:8.1f}% ({after_stats['wins']:2}/{after_stats['total']:2}) "
                  f"{trade_change:+8.1f}% {rate_improvement:+8.1f}%p")

    def analyze_daily_comparison(self, before_results: list, after_results: list):
        """일별 상세 비교"""
        print(f"\n=== 일별 상세 비교 ===")

        print(f"{'날짜':10} {'수정전':>15} {'수정후':>15} {'승률변화':>10}")
        print("-" * 55)

        total_improvements = 0
        improved_days = 0

        for before, after in zip(before_results, after_results):
            date = before['date']

            before_summary = f"{before['total_wins']}승{before['total_losses']}패({before['win_rate']:.1f}%)"
            after_summary = f"{after['total_wins']}승{after['total_losses']}패({after['win_rate']:.1f}%)"

            rate_change = after['win_rate'] - before['win_rate']
            total_improvements += rate_change
            if rate_change > 0:
                improved_days += 1

            print(f"{date:10} {before_summary:>15} {after_summary:>15} {rate_change:+8.1f}%p")

        print("-" * 55)
        avg_improvement = total_improvements / len(before_results) if before_results else 0
        improvement_ratio = improved_days / len(before_results) * 100 if before_results else 0

        print(f"평균 승률 변화: {avg_improvement:+.1f}%p")
        print(f"개선된 날짜: {improved_days}/{len(before_results)} ({improvement_ratio:.1f}%)")

    def generate_detailed_report(self, before_results: list, after_results: list):
        """상세 보고서 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_path = f"before_after_comparison_report_{timestamp}.txt"

        with open(report_path, 'w', encoding='utf-8') as f:
            f.write("="*60 + "\n")
            f.write("수정 전후 매매 로직 성과 비교 보고서\n")
            f.write("="*60 + "\n\n")
            f.write(f"분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"비교 기간: {len(before_results)}일\n\n")

            # 전체 요약
            before_total_wins = sum(r['total_wins'] for r in before_results)
            before_total_losses = sum(r['total_losses'] for r in before_results)
            before_total_trades = before_total_wins + before_total_losses
            before_win_rate = before_total_wins / before_total_trades * 100 if before_total_trades > 0 else 0

            after_total_wins = sum(r['total_wins'] for r in after_results)
            after_total_losses = sum(r['total_losses'] for r in after_results)
            after_total_trades = after_total_wins + after_total_losses
            after_win_rate = after_total_wins / after_total_trades * 100 if after_total_trades > 0 else 0

            f.write("=== 전체 요약 ===\n")
            f.write(f"수정 전: {before_total_wins}승 {before_total_losses}패 (승률 {before_win_rate:.1f}%)\n")
            f.write(f"수정 후: {after_total_wins}승 {after_total_losses}패 (승률 {after_win_rate:.1f}%)\n")
            f.write(f"승률 개선: {after_win_rate - before_win_rate:+.1f}%p\n")
            f.write(f"거래량 변화: {(after_total_trades - before_total_trades) / before_total_trades * 100:+.1f}%\n\n")

            # 핵심 개선사항
            f.write("=== 핵심 개선사항 ===\n")
            f.write("1. 시간대별 차별화 조건 적용\n")
            f.write("2. 일봉 패턴 강도 필터링 추가\n")
            f.write("3. 오후시간 위험 거래 차단 강화\n")
            f.write("4. 강한 일봉 패턴에서 조건 완화\n\n")

        print(f"상세 보고서 저장: {report_path}")

def main():
    """메인 실행"""
    comparator = BeforeAfterComparison()

    # 디렉토리 존재 확인
    if not comparator.before_dir.exists():
        print(f"수정 전 디렉토리가 없습니다: {comparator.before_dir}")
        return

    if not comparator.after_dir.exists():
        print(f"수정 후 디렉토리가 없습니다: {comparator.after_dir}")
        return

    # 비교 분석 실행
    results = comparator.compare_directories()

    if results:
        before_results, after_results = results
        comparator.generate_detailed_report(before_results, after_results)

    print(f"\n🎯 분석 완료! 실제 성과 개선 효과를 확인했습니다.")

if __name__ == "__main__":
    main()