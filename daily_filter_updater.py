"""
매일 자동 필터 업데이트 시스템

signal_replay_log의 거래 결과와 pattern_data_log를 결합하여
매일 패턴 조합별 수익률을 분석하고 PatternCombinationFilter를 자동 업데이트합니다.

실행 방법:
1. 특정 날짜만: python daily_filter_updater.py --date 20251114
2. 날짜 범위: python daily_filter_updater.py --start 20250901 --end 20251114
3. 전체 데이터: python daily_filter_updater.py --all
"""

import os
import json
import argparse
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

from utils.logger import setup_logger


class DailyFilterUpdater:
    """매일 필터 조합을 갱신하는 클래스"""

    def __init__(self, logger=None):
        self.logger = logger or setup_logger(__name__)
        self.pattern_combos = defaultdict(lambda: {
            'trades': [],
            'wins': 0,
            'losses': 0,
            'total_profit': 0.0,
            'win_profits': [],
            'loss_profits': []
        })

    def categorize_uptrend(self, price_gain_str: str) -> str:
        """상승 강도 카테고리"""
        try:
            # "3.05%" -> 3.05
            price_gain = float(price_gain_str.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            return '알수없음'

        if price_gain < 4.0:
            return '약함(<4%)'
        elif price_gain < 6.0:
            return '보통(4-6%)'
        else:
            return '강함(>6%)'

    def categorize_decline(self, decline_pct_str: str) -> str:
        """하락 정도 카테고리"""
        try:
            decline_pct = float(decline_pct_str.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            return '알수없음'

        if decline_pct < 1.5:
            return '얕음(<1.5%)'
        elif decline_pct < 2.5:
            return '보통(1.5-2.5%)'
        else:
            return '깊음(>2.5%)'

    def categorize_support(self, candle_count: int) -> str:
        """지지 길이 카테고리"""
        if candle_count <= 2:
            return '짧음(≤2)'
        elif candle_count <= 4:
            return '보통(3-4)'
        else:
            return '김(>4)'

    def extract_pattern_category(self, pattern_stages: Dict) -> Optional[Tuple[str, str, str]]:
        """패턴 단계에서 카테고리 추출"""
        try:
            # 1단계: 상승
            uptrend = pattern_stages.get('1_uptrend', {})
            price_gain = uptrend.get('price_gain', '0%')
            uptrend_cat = self.categorize_uptrend(price_gain)

            # 2단계: 하락
            decline = pattern_stages.get('2_decline', {})
            decline_pct = decline.get('decline_pct', '0%')
            decline_cat = self.categorize_decline(decline_pct)

            # 3단계: 지지
            support = pattern_stages.get('3_support', {})
            candle_count = support.get('candle_count', 0)
            support_cat = self.categorize_support(candle_count)

            if '알수없음' in [uptrend_cat, decline_cat, support_cat]:
                return None

            return (uptrend_cat, decline_cat, support_cat)

        except Exception as e:
            self.logger.debug(f"패턴 카테고리 추출 실패: {e}")
            return None

    def load_pattern_data(self, date_str: str) -> List[Dict]:
        """특정 날짜의 패턴 데이터 로드"""
        pattern_file = Path(f"pattern_data_log/pattern_data_{date_str}.jsonl")

        if not pattern_file.exists():
            self.logger.debug(f"패턴 파일 없음: {pattern_file}")
            return []

        patterns = []
        with open(pattern_file, 'r', encoding='utf-8') as f:
            for line in f:
                try:
                    data = json.loads(line.strip())

                    # trade_result가 있는 항목만 (실제 거래된 것만)
                    trade_result = data.get('trade_result')
                    if not trade_result:
                        continue

                    # 거래가 실행되지 않은 경우 제외
                    if not trade_result.get('trade_executed', False):
                        continue

                    patterns.append(data)

                except (json.JSONDecodeError, KeyError) as e:
                    self.logger.debug(f"패턴 파싱 오류: {e}")
                    continue

        return patterns

    def analyze_patterns(self, patterns: List[Dict]):
        """패턴 분석 및 조합별 집계"""
        for pattern in patterns:
            try:
                # 패턴 카테고리 추출
                pattern_stages = pattern.get('pattern_stages', {})
                category = self.extract_pattern_category(pattern_stages)

                if not category:
                    continue

                uptrend_cat, decline_cat, support_cat = category
                combo_key = f"{uptrend_cat} + {decline_cat} + {support_cat}"

                # 거래 결과 추출
                trade_result = pattern.get('trade_result', {})
                profit_rate = trade_result.get('profit_rate', 0.0)

                # 통계 업데이트
                self.pattern_combos[combo_key]['trades'].append(profit_rate)
                self.pattern_combos[combo_key]['total_profit'] += profit_rate

                if profit_rate > 0:
                    self.pattern_combos[combo_key]['wins'] += 1
                    self.pattern_combos[combo_key]['win_profits'].append(profit_rate)
                else:
                    self.pattern_combos[combo_key]['losses'] += 1
                    self.pattern_combos[combo_key]['loss_profits'].append(profit_rate)

            except Exception as e:
                self.logger.debug(f"패턴 분석 오류: {e}")
                continue

    def get_combo_statistics(self, min_trades: int = 3) -> List[Dict]:
        """조합별 통계 계산"""
        results = []

        for combo, stats in self.pattern_combos.items():
            total = len(stats['trades'])

            if total < min_trades:
                continue

            wins = stats['wins']
            losses = stats['losses']
            total_profit = stats['total_profit']

            win_rate = (wins / total * 100) if total > 0 else 0
            avg_profit = total_profit / total if total > 0 else 0

            results.append({
                'combo': combo,
                'total': total,
                'wins': wins,
                'losses': losses,
                'win_rate': win_rate,
                'total_profit': total_profit,
                'avg_profit': avg_profit
            })

        # 총 수익 기준으로 정렬
        results.sort(key=lambda x: x['total_profit'])

        return results

    def find_negative_combinations(
        self,
        statistics: List[Dict],
        min_loss_threshold: float = -1.0,
        max_win_rate: float = 50.0
    ) -> List[Dict]:
        """마이너스 조합 찾기"""
        negative = []

        for stat in statistics:
            # 총 수익이 마이너스이고, 승률도 낮은 조합
            if stat['total_profit'] < min_loss_threshold:
                negative.append(stat)
            # 또는 승률이 매우 낮은 조합 (총 수익은 플러스일 수 있음)
            elif stat['win_rate'] < max_win_rate and stat['total_profit'] < 0:
                negative.append(stat)

        return negative

    def generate_daily_report(
        self,
        statistics: List[Dict],
        negative_combos: List[Dict],
        start_date: str,
        end_date: str
    ):
        """일일 분석 보고서 생성"""
        report_dir = Path("filter_reports")
        report_dir.mkdir(exist_ok=True)

        today = datetime.now().strftime('%Y%m%d')
        report_file = report_dir / f"filter_analysis_{today}.md"

        total_trades = sum(len(v['trades']) for v in self.pattern_combos.values())
        total_combos = len(self.pattern_combos)
        positive_combos = [s for s in statistics if s['total_profit'] > 0]
        negative_combos_all = [s for s in statistics if s['total_profit'] <= 0]

        # 상위 5개 조합
        top_combos = sorted(statistics, key=lambda x: x['total_profit'], reverse=True)[:5]

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"# 필터 분석 보고서\n\n")
            f.write(f"**생성일시**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**분석 기간**: {start_date} ~ {end_date}\n\n")

            f.write("---\n\n")
            f.write("## 📊 전체 통계\n\n")
            f.write(f"- **총 조합 수**: {total_combos}개\n")
            f.write(f"- **총 거래 수**: {total_trades}건\n")
            f.write(f"- **분석된 조합**: {len(statistics)}개 (최소 3건 이상)\n")
            f.write(f"- **양수 수익 조합**: {len(positive_combos)}개 ({len(positive_combos)/len(statistics)*100:.1f}%)\n")
            f.write(f"- **마이너스 조합**: {len(negative_combos_all)}개 ({len(negative_combos_all)/len(statistics)*100:.1f}%)\n")
            f.write(f"- **필터 대상**: {len(negative_combos)}개\n\n")

            if negative_combos:
                f.write("---\n\n")
                f.write("## 🚫 제외된 조합 상세\n\n")
                f.write("| 순위 | 조합 | 거래수 | 승률 | 총손실 |\n")
                f.write("|------|------|--------|------|--------|\n")

                for i, combo in enumerate(negative_combos, 1):
                    f.write(f"| {i} | {combo['combo']} | {combo['total']}건 | {combo['win_rate']:.1f}% | {combo['total_profit']:.2f}% |\n")

                f.write(f"\n**총 필터 대상 거래**: {sum(c['total'] for c in negative_combos)}건\n\n")

            if top_combos:
                f.write("---\n\n")
                f.write("## 🏆 상위 수익 조합 (Top 5)\n\n")
                f.write("| 순위 | 조합 | 거래수 | 승률 | 총수익 |\n")
                f.write("|------|------|--------|------|--------|\n")

                for i, combo in enumerate(top_combos, 1):
                    f.write(f"| {i} | {combo['combo']} | {combo['total']}건 | {combo['win_rate']:.1f}% | {combo['total_profit']:.2f}% |\n")

            # 패턴 인사이트
            f.write("\n---\n\n")
            f.write("## 💡 주요 인사이트\n\n")

            # 지지길이별 분석
            support_stats = defaultdict(lambda: {'wins': 0, 'total': 0})
            for combo_key, data in self.pattern_combos.items():
                if '짧음' in combo_key:
                    support_type = '짧음(≤2)'
                elif '보통(3-4)' in combo_key:
                    support_type = '보통(3-4)'
                else:
                    support_type = '김(>4)'

                support_stats[support_type]['wins'] += data['wins']
                support_stats[support_type]['total'] += len(data['trades'])

            f.write("### 지지길이별 패턴\n\n")
            f.write("| 지지길이 | 거래수 | 승률 |\n")
            f.write("|----------|--------|------|\n")

            for support_type in ['짧음(≤2)', '보통(3-4)', '김(>4)']:
                if support_type in support_stats:
                    stats = support_stats[support_type]
                    win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
                    f.write(f"| {support_type} | {stats['total']}건 | {win_rate:.1f}% |\n")

            # 상승강도별 분석
            uptrend_stats = defaultdict(lambda: {'wins': 0, 'total': 0})
            for combo_key, data in self.pattern_combos.items():
                if '약함(<4%)' in combo_key:
                    uptrend_type = '약함(<4%)'
                elif '보통(4-6%)' in combo_key:
                    uptrend_type = '보통(4-6%)'
                else:
                    uptrend_type = '강함(>6%)'

                uptrend_stats[uptrend_type]['wins'] += data['wins']
                uptrend_stats[uptrend_type]['total'] += len(data['trades'])

            f.write("\n### 상승강도별 패턴\n\n")
            f.write("| 상승강도 | 거래수 | 승률 |\n")
            f.write("|----------|--------|------|\n")

            for uptrend_type in ['약함(<4%)', '보통(4-6%)', '강함(>6%)']:
                if uptrend_type in uptrend_stats:
                    stats = uptrend_stats[uptrend_type]
                    win_rate = (stats['wins'] / stats['total'] * 100) if stats['total'] > 0 else 0
                    f.write(f"| {uptrend_type} | {stats['total']}건 | {win_rate:.1f}% |\n")

            f.write("\n---\n\n")
            f.write("## 📝 다음 단계\n\n")
            f.write("1. 시뮬레이션 재시작하여 새로운 필터 적용\n")
            f.write("2. 일주일 후 필터 효과 검증\n")
            f.write("3. 필요 시 임계값 조정 (`--min-trades`, `--min-loss`)\n\n")

            f.write("---\n\n")
            f.write(f"*보고서 생성 시각: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*\n")

        self.logger.info(f"일일 보고서 생성: {report_file}")
        return str(report_file)

    def generate_filter_code(
        self,
        negative_combos: List[Dict],
        output_file: str = "core/indicators/pattern_combination_filter.py"
    ):
        """필터 코드 생성 및 저장"""

        # 기존 파일 읽기
        with open(output_file, 'r', encoding='utf-8') as f:
            original_content = f.read()

        # 제외 조합 코드 생성
        excluded_code_lines = []
        excluded_code_lines.append("        # 🚫 제외할 조합 (총 수익 마이너스)")
        excluded_code_lines.append(f"        # 자동 생성: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        excluded_code_lines.append(f"        # 분석 데이터: {len(self.pattern_combos)}개 조합, {sum(len(v['trades']) for v in self.pattern_combos.values())}건 거래")
        excluded_code_lines.append("        self.excluded_combinations = [")

        for i, combo_stat in enumerate(negative_combos, 1):
            combo = combo_stat['combo']
            parts = combo.split(' + ')

            if len(parts) != 3:
                continue

            excluded_code_lines.append(f"            # 조합 {i}: {combo}")
            excluded_code_lines.append(f"            # {combo_stat['total']}건, 승률 {combo_stat['win_rate']:.1f}%, 총손실 {combo_stat['total_profit']:.2f}%")
            excluded_code_lines.append("            {")
            excluded_code_lines.append(f"                '상승강도': '{parts[0]}',")
            excluded_code_lines.append(f"                '하락정도': '{parts[1]}',")
            excluded_code_lines.append(f"                '지지길이': '{parts[2]}',")
            excluded_code_lines.append("            },")
            excluded_code_lines.append("")

        excluded_code_lines.append("        ]")

        # 새로운 코드로 교체
        import re

        # self.excluded_combinations = [ ... ] 부분을 찾아 교체
        pattern = r'(        # 🚫 제외할 조합.*?)(        self\.excluded_combinations = \[)(.*?)(        \])'

        new_excluded_section = '\n'.join(excluded_code_lines)

        # 정규표현식으로 교체
        new_content = re.sub(
            pattern,
            new_excluded_section,
            original_content,
            flags=re.DOTALL
        )

        # 파일 저장
        backup_file = output_file.replace('.py', f'_backup_{datetime.now().strftime("%Y%m%d_%H%M%S")}.py')

        # 백업 생성
        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write(original_content)

        self.logger.info(f"백업 생성: {backup_file}")

        # 새로운 코드 저장
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(new_content)

        self.logger.info(f"필터 업데이트 완료: {output_file}")
        self.logger.info(f"제외 조합 수: {len(negative_combos)}개")

    def print_report(self, statistics: List[Dict], negative_combos: List[Dict]):
        """분석 보고서 출력"""
        print("\n" + "="*80)
        print("패턴 조합 분석 보고서")
        print("="*80)

        total_trades = sum(len(v['trades']) for v in self.pattern_combos.values())
        total_combos = len(self.pattern_combos)

        print(f"\n총 조합 수: {total_combos}개")
        print(f"총 거래 수: {total_trades}건")
        print(f"분석된 조합 (최소 3건 이상): {len(statistics)}개")

        # 양수/음수 조합
        positive_combos = [s for s in statistics if s['total_profit'] > 0]
        negative_combos_all = [s for s in statistics if s['total_profit'] <= 0]

        print(f"\n[+] 양수 수익 조합: {len(positive_combos)}개")
        print(f"[-] 마이너스 수익 조합: {len(negative_combos_all)}개")
        print(f"    -> 필터 대상: {len(negative_combos)}개")

        # 제외할 조합 상세
        if negative_combos:
            print(f"\n{'='*80}")
            print(f"[-] 제외할 조합 상세")
            print(f"{'='*80}")
            print(f"{'조합':<50} {'거래수':>6} {'승률':>7} {'총손실':>9}")
            print("-"*80)

            for combo_stat in negative_combos:
                print(
                    f"{combo_stat['combo']:<50} "
                    f"{combo_stat['total']:>6} "
                    f"{combo_stat['win_rate']:>6.1f}% "
                    f"{combo_stat['total_profit']:>8.2f}%"
                )

        # 상위 수익 조합
        top_combos = sorted(statistics, key=lambda x: x['total_profit'], reverse=True)[:5]

        if top_combos:
            print(f"\n{'='*80}")
            print(f"[*] 상위 수익 조합 (Top 5)")
            print(f"{'='*80}")
            print(f"{'조합':<50} {'거래수':>6} {'승률':>7} {'총수익':>9}")
            print("-"*80)

            for combo_stat in top_combos:
                print(
                    f"{combo_stat['combo']:<50} "
                    f"{combo_stat['total']:>6} "
                    f"{combo_stat['win_rate']:>6.1f}% "
                    f"{combo_stat['total_profit']:>8.2f}%"
                )

        print("\n" + "="*80)

    def run(
        self,
        start_date: str,
        end_date: str,
        min_trades: int = 3,
        min_loss_threshold: float = -1.0,
        auto_update: bool = False
    ):
        """분석 실행"""
        self.logger.info(f"필터 분석 시작: {start_date} ~ {end_date}")

        # 날짜 범위의 모든 패턴 데이터 로드
        current_date = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')

        total_patterns = 0

        while current_date <= end_dt:
            date_str = current_date.strftime('%Y%m%d')
            patterns = self.load_pattern_data(date_str)

            if patterns:
                self.logger.info(f"  {date_str}: {len(patterns)}건 로드")
                self.analyze_patterns(patterns)
                total_patterns += len(patterns)

            current_date += timedelta(days=1)

        self.logger.info(f"총 {total_patterns}건의 패턴 분석 완료")

        # 통계 계산
        statistics = self.get_combo_statistics(min_trades=min_trades)

        # 마이너스 조합 찾기
        negative_combos = self.find_negative_combinations(
            statistics,
            min_loss_threshold=min_loss_threshold
        )

        # 보고서 출력
        self.print_report(statistics, negative_combos)

        # 일일 보고서 생성
        report_file = self.generate_daily_report(statistics, negative_combos, start_date, end_date)

        print("\n" + "="*80)
        print(f"[+] 일일 보고서 생성 완료: {report_file}")
        print("="*80)

        # 자동 업데이트
        if auto_update and negative_combos:
            print("\n" + "="*80)
            print("필터 자동 업데이트 중...")
            print("="*80)

            self.generate_filter_code(negative_combos)

            print("\n[+] 필터 업데이트 완료!")
            print("    -> 변경 사항을 적용하려면 시뮬레이션을 재시작하세요.")
        elif negative_combos:
            print("\n" + "="*80)
            print("[i] 필터 업데이트를 원하시면 --update 옵션을 추가하세요.")
            print("="*80)


def parse_arguments():
    """명령줄 인자 파싱"""
    parser = argparse.ArgumentParser(
        description='매일 패턴 조합을 분석하고 필터를 업데이트합니다.'
    )

    # 날짜 옵션
    parser.add_argument(
        '--date',
        type=str,
        help='특정 날짜 (YYYYMMDD 형식, 예: 20251114)'
    )
    parser.add_argument(
        '--all',
        action='store_true',
        help='전체 데이터 분석 (pattern_data_log의 모든 파일)'
    )
    parser.add_argument(
        '--start',
        type=str,
        help='시작 날짜 (YYYYMMDD 형식, --end와 함께 사용)'
    )
    parser.add_argument(
        '--end',
        type=str,
        help='종료 날짜 (YYYYMMDD 형식, --start와 함께 사용)'
    )

    # 분석 옵션
    parser.add_argument(
        '--min-trades',
        type=int,
        default=3,
        help='최소 거래 수 (기본값: 3)'
    )
    parser.add_argument(
        '--min-loss',
        type=float,
        default=-1.0,
        help='최소 손실 임계값 (기본값: -1.0%%)'
    )

    # 업데이트 옵션
    parser.add_argument(
        '--update',
        action='store_true',
        help='필터 파일 자동 업데이트'
    )

    return parser.parse_args()


def main():
    """메인 함수"""
    args = parse_arguments()

    # 로거 설정
    logger = setup_logger(__name__)

    # 날짜 범위 결정
    if args.start and args.end:
        start_date = args.start
        end_date = args.end
    elif args.date:
        start_date = args.date
        end_date = args.date
    elif args.all:
        # pattern_data_log의 모든 파일에서 날짜 추출
        pattern_dir = Path("pattern_data_log")
        if not pattern_dir.exists():
            logger.error(f"패턴 데이터 디렉토리가 없습니다: {pattern_dir}")
            return

        pattern_files = sorted(pattern_dir.glob("pattern_data_*.jsonl"))
        if not pattern_files:
            logger.error("패턴 데이터 파일이 없습니다.")
            return

        # 첫 번째와 마지막 파일에서 날짜 추출
        start_date = pattern_files[0].stem.replace('pattern_data_', '')
        end_date = pattern_files[-1].stem.replace('pattern_data_', '')

        logger.info(f"전체 데이터 분석: {start_date} ~ {end_date}")
    else:
        logger.error("날짜를 지정해야 합니다. --help를 참고하세요.")
        return

    # 업데이터 생성 및 실행
    updater = DailyFilterUpdater(logger=logger)

    updater.run(
        start_date=start_date,
        end_date=end_date,
        min_trades=args.min_trades,
        min_loss_threshold=args.min_loss,
        auto_update=args.update
    )


if __name__ == '__main__':
    main()
