"""
Signal Replay Log 비교 분석 스크립트

두 폴더(signal_replay_log, signal_replay_log_prev)의 파일들을 비교하여
성과 변화, 거래 결과 차이, 승률 변화 등을 분석합니다.

사용법:
    python compare_signal_replay_logs.py
    python compare_signal_replay_logs.py --date 20250901
    python compare_signal_replay_logs.py --export csv
"""

import os
import re
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
import json

@dataclass
class TradeResult:
    """거래 결과 데이터 클래스"""
    time: str
    trade_type: str  # 매수/매도
    price: int
    signal_type: str = ""
    profit_rate: float = 0.0
    reason: str = ""

@dataclass
class StockAnalysis:
    """종목별 분석 결과"""
    stock_code: str
    date: str
    total_wins: int = 0
    total_losses: int = 0
    selection_wins: int = 0
    selection_losses: int = 0
    trades: List[TradeResult] = field(default_factory=list)
    missed_opportunities: int = 0
    profit_rates: List[float] = field(default_factory=list)

    @property
    def win_rate(self) -> float:
        """승률 계산"""
        total = self.selection_wins + self.selection_losses
        return (self.selection_wins / total * 100) if total > 0 else 0.0

    @property
    def avg_profit_rate(self) -> float:
        """평균 수익률"""
        return sum(self.profit_rates) / len(self.profit_rates) if self.profit_rates else 0.0

@dataclass
class DayAnalysis:
    """일별 분석 결과"""
    date: str
    stocks: Dict[str, StockAnalysis] = field(default_factory=dict)

    @property
    def total_wins(self) -> int:
        return sum(stock.selection_wins for stock in self.stocks.values())

    @property
    def total_losses(self) -> int:
        return sum(stock.selection_losses for stock in self.stocks.values())

    @property
    def win_rate(self) -> float:
        total = self.total_wins + self.total_losses
        return (self.total_wins / total * 100) if total > 0 else 0.0

    @property
    def avg_profit_rate(self) -> float:
        all_rates = []
        for stock in self.stocks.values():
            all_rates.extend(stock.profit_rates)
        return sum(all_rates) / len(all_rates) if all_rates else 0.0

class SignalReplayLogParser:
    """Signal Replay 로그 파서"""

    def __init__(self):
        self.summary_pattern = re.compile(r'=== 총 승패: (\d+)승 (\d+)패 ===')
        self.selection_summary_pattern = re.compile(r'=== selection_date 이후 승패: (\d+)승 (\d+)패 ===')
        self.stock_section_pattern = re.compile(r'=== (\d+) - (\d+) 눌림목\(3분\) 신호 재현 ===')
        self.stock_summary_pattern = re.compile(r'승패: (\d+)승 (\d+)패')
        self.selection_stock_summary_pattern = re.compile(r'selection_date 이후 승패: (\d+)승 (\d+)패')
        self.trade_pattern = re.compile(r'(\d{2}:\d{2}) 매수\[(.*?)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[(.*?)\] @([\d,]+) \(([-+]?\d+\.?\d*)%\)')
        self.missed_pattern = re.compile(r'매수 못한 기회:\s*(\d+)건' )

    def parse_file(self, file_path: Path) -> DayAnalysis:
        """파일 파싱하여 일별 분석 결과 반환"""
        try:
            with open(file_path, 'r', encoding='utf-8-sig') as f:
                content = f.read()

            # 파일명에서 날짜 추출
            date_match = re.search(r'(\d{8})', file_path.name)
            date = date_match.group(1) if date_match else "unknown"

            day_analysis = DayAnalysis(date=date)

            # 종목별 섹션 분할
            stock_sections = re.split(r'=== \d+ - \d+ 눌림목\(3분\) 신호 재현 ===', content)
            stock_headers = re.findall(r'=== (\d+) - (\d+) 눌림목\(3분\) 신호 재현 ===', content)

            for i, (stock_code, section_date) in enumerate(stock_headers):
                if i + 1 < len(stock_sections):
                    section_content = stock_sections[i + 1]
                    stock_analysis = self._parse_stock_section(stock_code, date, section_content)
                    day_analysis.stocks[stock_code] = stock_analysis

            return day_analysis

        except Exception as e:
            print(f"파일 파싱 오류 ({file_path}): {e}")
            return DayAnalysis(date=date)

    def _parse_stock_section(self, stock_code: str, date: str, content: str) -> StockAnalysis:
        """종목별 섹션 파싱"""
        analysis = StockAnalysis(stock_code=stock_code, date=date)

        # 승패 정보
        stock_summary = self.stock_summary_pattern.search(content)
        if stock_summary:
            analysis.total_wins = int(stock_summary.group(1))
            analysis.total_losses = int(stock_summary.group(2))

        selection_summary = self.selection_stock_summary_pattern.search(content)
        if selection_summary:
            analysis.selection_wins = int(selection_summary.group(1))
            analysis.selection_losses = int(selection_summary.group(2))

        # 거래 내역 파싱
        trades = self.trade_pattern.findall(content)
        for trade in trades:
            buy_time, signal_type, buy_price_str, sell_time, sell_reason, sell_price_str, profit_rate_str = trade

            buy_price = int(buy_price_str.replace(',', ''))
            sell_price = int(sell_price_str.replace(',', ''))
            profit_rate = float(profit_rate_str)

            # 매수 거래
            analysis.trades.append(TradeResult(
                time=buy_time,
                trade_type="매수",
                price=buy_price,
                signal_type=signal_type
            ))

            # 매도 거래
            analysis.trades.append(TradeResult(
                time=sell_time,
                trade_type="매도",
                price=sell_price,
                profit_rate=profit_rate,
                reason=sell_reason
            ))

            analysis.profit_rates.append(profit_rate)

        # 매수 못한 기회
        missed_match = self.missed_pattern.search(content)
        if missed_match:
            analysis.missed_opportunities = int(missed_match.group(1))

        return analysis

class LogComparator:
    """로그 비교 분석기"""

    def __init__(self, current_dir: str = "signal_replay_log", prev_dir: str = "signal_replay_log_prev"):
        self.current_dir = Path(current_dir)
        self.prev_dir = Path(prev_dir)
        self.parser = SignalReplayLogParser()

    def compare_all_files(self, target_date: Optional[str] = None) -> Dict[str, Dict]:
        """모든 파일 비교"""
        results = {}

        current_files = list(self.current_dir.glob("*.txt"))
        prev_files = list(self.prev_dir.glob("*.txt"))

        # 파일명 매칭
        common_files = []
        for current_file in current_files:
            prev_file = self.prev_dir / current_file.name
            if prev_file.exists():
                # 특정 날짜 필터링
                if target_date:
                    if target_date not in current_file.name:
                        continue
                common_files.append((current_file, prev_file))

        for current_file, prev_file in common_files:
            date = re.search(r'(\d{8})', current_file.name).group(1)

            current_analysis = self.parser.parse_file(current_file)
            prev_analysis = self.parser.parse_file(prev_file)

            comparison = self._compare_day_analyses(current_analysis, prev_analysis)
            results[date] = comparison

        return results

    def _compare_day_analyses(self, current: DayAnalysis, prev: DayAnalysis) -> Dict:
        """일별 분석 결과 비교"""
        return {
            'date': current.date,
            'current': {
                'total_stocks': len(current.stocks),
                'total_wins': current.total_wins,
                'total_losses': current.total_losses,
                'win_rate': round(current.win_rate, 2),
                'avg_profit_rate': round(current.avg_profit_rate, 2)
            },
            'prev': {
                'total_stocks': len(prev.stocks),
                'total_wins': prev.total_wins,
                'total_losses': prev.total_losses,
                'win_rate': round(prev.win_rate, 2),
                'avg_profit_rate': round(prev.avg_profit_rate, 2)
            },
            'changes': {
                'wins_diff': current.total_wins - prev.total_wins,
                'losses_diff': current.total_losses - prev.total_losses,
                'win_rate_diff': round(current.win_rate - prev.win_rate, 2),
                'avg_profit_diff': round(current.avg_profit_rate - prev.avg_profit_rate, 2)
            },
            'stock_details': self._compare_stock_details(current.stocks, prev.stocks)
        }

    def _compare_stock_details(self, current_stocks: Dict[str, StockAnalysis],
                              prev_stocks: Dict[str, StockAnalysis]) -> Dict:
        """종목별 상세 비교"""
        details = {}

        all_stocks = set(current_stocks.keys()) | set(prev_stocks.keys())

        for stock_code in all_stocks:
            current_stock = current_stocks.get(stock_code)
            prev_stock = prev_stocks.get(stock_code)

            if current_stock and prev_stock:
                details[stock_code] = {
                    'current': {
                        'wins': current_stock.selection_wins,
                        'losses': current_stock.selection_losses,
                        'win_rate': round(current_stock.win_rate, 2),
                        'avg_profit': round(current_stock.avg_profit_rate, 2),
                        'trades': len(current_stock.profit_rates)
                    },
                    'prev': {
                        'wins': prev_stock.selection_wins,
                        'losses': prev_stock.selection_losses,
                        'win_rate': round(prev_stock.win_rate, 2),
                        'avg_profit': round(prev_stock.avg_profit_rate, 2),
                        'trades': len(prev_stock.profit_rates)
                    },
                    'changes': {
                        'wins_diff': current_stock.selection_wins - prev_stock.selection_wins,
                        'losses_diff': current_stock.selection_losses - prev_stock.selection_losses,
                        'win_rate_diff': round(current_stock.win_rate - prev_stock.win_rate, 2),
                        'avg_profit_diff': round(current_stock.avg_profit_rate - prev_stock.avg_profit_rate, 2)
                    }
                }
            elif current_stock:
                details[stock_code] = {'status': 'new_in_current'}
            elif prev_stock:
                details[stock_code] = {'status': 'missing_in_current'}

        return details

def print_comparison_report(results: Dict[str, Dict]):
    """비교 결과 출력"""
    print("=" * 80)
    print("Signal Replay Log 비교 분석 결과")
    print("=" * 80)

    # 전체 요약
    total_current_wins = sum(day['current']['total_wins'] for day in results.values())
    total_prev_wins = sum(day['prev']['total_wins'] for day in results.values())
    total_current_losses = sum(day['current']['total_losses'] for day in results.values())
    total_prev_losses = sum(day['prev']['total_losses'] for day in results.values())

    current_total = total_current_wins + total_current_losses
    prev_total = total_prev_wins + total_prev_losses

    current_win_rate = (total_current_wins / current_total * 100) if current_total > 0 else 0
    prev_win_rate = (total_prev_wins / prev_total * 100) if prev_total > 0 else 0

    print(f"\n[전체 요약] ({len(results)}일)")
    print(f"현재 버전: {total_current_wins}승 {total_current_losses}패 (승률: {current_win_rate:.2f}%)")
    print(f"이전 버전: {total_prev_wins}승 {total_prev_losses}패 (승률: {prev_win_rate:.2f}%)")
    print(f"변화: {total_current_wins - total_prev_wins:+d}승 {total_current_losses - total_prev_losses:+d}패 (승률: {current_win_rate - prev_win_rate:+.2f}%p)")

    # 일별 상세 결과
    print(f"\n[일별 비교 결과]")
    print("-" * 80)

    for date in sorted(results.keys()):
        day_result = results[date]
        current = day_result['current']
        prev = day_result['prev']
        changes = day_result['changes']

        print(f"\n[{date}]")
        print(f"  현재: {current['total_wins']}승 {current['total_losses']}패 (승률: {current['win_rate']}%, 평균: {current['avg_profit_rate']:+.2f}%)")
        print(f"  이전: {prev['total_wins']}승 {prev['total_losses']}패 (승률: {prev['win_rate']}%, 평균: {prev['avg_profit_rate']:+.2f}%)")
        print(f"  변화: {changes['wins_diff']:+d}승 {changes['losses_diff']:+d}패 (승률: {changes['win_rate_diff']:+.2f}%p, 평균: {changes['avg_profit_diff']:+.2f}%p)")

        # 개선된 종목과 악화된 종목 찾기
        stock_details = day_result['stock_details']
        improved_stocks = []
        worsened_stocks = []

        for stock_code, detail in stock_details.items():
            if 'changes' in detail:
                win_rate_diff = detail['changes'].get('win_rate_diff', 0)
                if win_rate_diff > 0:
                    improved_stocks.append((stock_code, win_rate_diff))
                elif win_rate_diff < 0:
                    worsened_stocks.append((stock_code, win_rate_diff))

        if improved_stocks:
            improved_stocks.sort(key=lambda x: x[1], reverse=True)
            print(f"  [개선] {', '.join([f'{code}({rate:+.1f}%p)' for code, rate in improved_stocks[:3]])}")

        if worsened_stocks:
            worsened_stocks.sort(key=lambda x: x[1])
            print(f"  [악화] {', '.join([f'{code}({rate:+.1f}%p)' for code, rate in worsened_stocks[:3]])}")

def export_to_csv(results: Dict[str, Dict], filename: str = "signal_replay_comparison.csv"):
    """CSV 파일로 내보내기"""
    import csv

    with open(filename, 'w', newline='', encoding='utf-8-sig') as csvfile:
        writer = csv.writer(csvfile)

        # 헤더
        writer.writerow([
            'Date', 'Current_Wins', 'Current_Losses', 'Current_WinRate', 'Current_AvgProfit',
            'Prev_Wins', 'Prev_Losses', 'Prev_WinRate', 'Prev_AvgProfit',
            'Wins_Diff', 'Losses_Diff', 'WinRate_Diff', 'AvgProfit_Diff'
        ])

        # 데이터
        for date in sorted(results.keys()):
            day_result = results[date]
            current = day_result['current']
            prev = day_result['prev']
            changes = day_result['changes']

            writer.writerow([
                date,
                current['total_wins'], current['total_losses'], current['win_rate'], current['avg_profit_rate'],
                prev['total_wins'], prev['total_losses'], prev['win_rate'], prev['avg_profit_rate'],
                changes['wins_diff'], changes['losses_diff'], changes['win_rate_diff'], changes['avg_profit_diff']
            ])

    print(f"\n[저장완료] 결과를 {filename} 파일로 저장했습니다.")

def main():
    parser = argparse.ArgumentParser(description='Signal Replay Log 비교 분석')
    parser.add_argument('--date', type=str, help='특정 날짜만 분석 (예: 20250901)')
    parser.add_argument('--export', choices=['csv', 'json'], help='결과를 파일로 내보내기')
    parser.add_argument('--current-dir', type=str, default='signal_replay_log',
                       help='현재 버전 로그 디렉토리 (기본: signal_replay_log)')
    parser.add_argument('--prev-dir', type=str, default='signal_replay_log_prev',
                       help='이전 버전 로그 디렉토리 (기본: signal_replay_log_prev)')

    args = parser.parse_args()

    # 디렉토리 존재 확인
    if not Path(args.current_dir).exists():
        print(f"[오류] 현재 버전 디렉토리가 존재하지 않습니다: {args.current_dir}")
        return

    if not Path(args.prev_dir).exists():
        print(f"[오류] 이전 버전 디렉토리가 존재하지 않습니다: {args.prev_dir}")
        return

    # 비교 분석 실행
    comparator = LogComparator(args.current_dir, args.prev_dir)
    results = comparator.compare_all_files(args.date)

    if not results:
        print("[알림] 비교할 파일이 없습니다.")
        return

    # 결과 출력
    print_comparison_report(results)

    # 파일 내보내기
    if args.export == 'csv':
        export_to_csv(results)
    elif args.export == 'json':
        filename = f"signal_replay_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\n[저장완료] 결과를 {filename} 파일로 저장했습니다.")

if __name__ == "__main__":
    main()