"""
패턴별 동적 손익비 최적화 스크립트

과거 매매 데이터를 분석하여 각 패턴 조합에 대한 최적의 손익비를 계산합니다.
"""

import sys
import os
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
import json
from typing import Dict, List, Tuple
import subprocess

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from config.dynamic_profit_loss_config import DynamicProfitLossConfig


class PatternOptimizer:
    """패턴별 손익비 최적화"""

    def __init__(self, start_date: str, end_date: str):
        self.start_date = start_date
        self.end_date = end_date
        self.pattern_trades = defaultdict(list)  # {(support, decline): [trade_results]}

    def collect_pattern_data(self, output_dir: str = "signal_replay_log"):
        """
        신호 리플레이 로그에서 패턴별 매매 데이터 수집

        Args:
            output_dir: 시뮬레이션 결과가 저장된 디렉토리
        """
        print(f"\n{'='*80}")
        print(f"📊 패턴 데이터 수집 중: {self.start_date} ~ {self.end_date}")
        print(f"{'='*80}\n")

        # 날짜 범위 생성
        start = datetime.strptime(self.start_date, "%Y%m%d")
        end = datetime.strptime(self.end_date, "%Y%m%d")

        total_trades = 0
        dates_processed = 0

        current = start
        while current <= end:
            date_str = current.strftime("%Y%m%d")

            # 주말 스킵
            if current.weekday() >= 5:
                current += timedelta(days=1)
                continue

            # 해당 날짜의 시뮬레이션 결과 파일 찾기
            log_files = list(Path(output_dir).glob(f"signal_*_replay_{date_str}_*.txt"))

            if log_files:
                dates_processed += 1
                for log_file in log_files:
                    trades_count = self._parse_log_file(log_file)
                    total_trades += trades_count
                    if trades_count > 0:
                        print(f"  📅 {date_str}: {trades_count}건 수집")

            current += timedelta(days=1)

        print(f"\n✅ 총 {dates_processed}일, {total_trades}건의 매매 데이터 수집 완료\n")

        # 패턴별 통계 출력
        print(f"{'='*80}")
        print("📈 패턴별 수집 데이터:")
        print(f"{'='*80}")
        for pattern, trades in sorted(self.pattern_trades.items()):
            support, decline = pattern
            print(f"  {support:15s} x {decline:20s}: {len(trades):4d}건")
        print()

    def _parse_log_file(self, log_file: Path) -> int:
        """
        로그 파일에서 매매 데이터 파싱

        Returns:
            수집된 매매 건수
        """
        trades_count = 0

        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()

            # 매매 기록 파싱
            # 형식: [HH:MM:SS] 종목코드(종목명) 매수 XXX원 -> 매도 YYY원 (수익률 ±Z.ZZ%)
            # 다음 줄에 패턴 정보: support=XXX, decline=YYY

            lines = content.split('\n')
            i = 0
            while i < len(lines):
                line = lines[i].strip()

                # 매매 결과 라인 찾기
                if '매수' in line and '매도' in line and '수익률' in line:
                    # 수익률 추출
                    if '(' in line and '%)' in line:
                        try:
                            profit_str = line.split('(수익률')[1].split('%)')[0].strip()
                            profit = float(profit_str.replace('%', ''))

                            # 다음 라인에서 패턴 정보 찾기
                            if i + 1 < len(lines):
                                next_line = lines[i + 1].strip()

                                # 패턴 정보 파싱: support=XXX, decline=YYY
                                if 'support=' in next_line and 'decline=' in next_line:
                                    support = None
                                    decline = None

                                    parts = next_line.split(',')
                                    for part in parts:
                                        if 'support=' in part:
                                            support = part.split('support=')[1].strip()
                                        elif 'decline=' in part:
                                            decline = part.split('decline=')[1].strip()

                                    if support and decline:
                                        pattern = (support, decline)
                                        self.pattern_trades[pattern].append({
                                            'profit': profit,
                                            'date': log_file.stem.split('_')[3] if '_' in log_file.stem else 'unknown'
                                        })
                                        trades_count += 1
                        except (ValueError, IndexError):
                            pass

                i += 1

        except Exception as e:
            print(f"  ⚠️  로그 파일 파싱 오류 ({log_file.name}): {e}")

        return trades_count

    def optimize_ratios(self) -> Dict[Tuple[str, str], Dict[str, float]]:
        """
        패턴별 최적 손익비 계산

        Returns:
            {(support, decline): {'stop_loss': X, 'take_profit': Y}}
        """
        print(f"{'='*80}")
        print("🔍 패턴별 최적 손익비 계산 중...")
        print(f"{'='*80}\n")

        optimized_ratios = {}

        # 테스트할 손익비 조합
        stop_loss_options = [-1.5, -2.0, -2.5, -3.0, -3.5, -4.0, -4.5, -5.0, -5.5, -6.0]
        take_profit_options = [3.0, 3.5, 4.0, 4.5, 5.0, 5.5, 6.0, 6.5, 7.0, 7.5, 8.0]

        for pattern, trades in self.pattern_trades.items():
            if len(trades) < 5:  # 최소 5건 이상의 데이터가 있어야 분석
                print(f"  ⚠️  {pattern}: 데이터 부족 ({len(trades)}건) - 스킵")
                continue

            support, decline = pattern
            best_score = float('-inf')
            best_ratio = None

            # 모든 손익비 조합 테스트
            for stop_loss in stop_loss_options:
                for take_profit in take_profit_options:
                    score = self._calculate_score(trades, stop_loss, take_profit)

                    if score > best_score:
                        best_score = score
                        best_ratio = {
                            'stop_loss': stop_loss,
                            'take_profit': take_profit,
                            'score': score
                        }

            if best_ratio:
                optimized_ratios[pattern] = best_ratio

                # 기존 설정과 비교
                old_ratio = DynamicProfitLossConfig.PATTERN_COMBINATION_RATIOS.get(pattern, {})
                old_sl = old_ratio.get('stop_loss', 'N/A')
                old_tp = old_ratio.get('take_profit', 'N/A')

                print(f"  ✅ {support:15s} x {decline:20s} ({len(trades):3d}건)")
                print(f"      기존: 손절 {old_sl:+6.1f}% / 익절 {old_tp:+6.1f}%")
                print(f"      최적: 손절 {best_ratio['stop_loss']:+6.1f}% / 익절 {best_ratio['take_profit']:+6.1f}% (점수: {best_score:.3f})")
                print()

        return optimized_ratios

    def _calculate_score(self, trades: List[Dict], stop_loss: float, take_profit: float) -> float:
        """
        특정 손익비에 대한 점수 계산

        전략:
        - 손절/익절 기준을 적용했을 때의 예상 수익률 계산
        - 승률과 평균 수익을 모두 고려한 종합 점수

        Args:
            trades: 매매 데이터 리스트
            stop_loss: 손절 비율 (음수)
            take_profit: 익절 비율 (양수)

        Returns:
            점수 (높을수록 좋음)
        """
        wins = 0
        total_profit = 0.0

        for trade in trades:
            actual_profit = trade['profit']

            # 손익비 기준 적용
            if actual_profit <= stop_loss:
                # 손절 발동
                simulated_profit = stop_loss
            elif actual_profit >= take_profit:
                # 익절 발동
                simulated_profit = take_profit
            else:
                # 실제 수익률 사용 (손익비 범위 내)
                simulated_profit = actual_profit

            if simulated_profit > 0:
                wins += 1

            total_profit += simulated_profit

        # 승률
        win_rate = wins / len(trades) if trades else 0

        # 평균 수익률
        avg_profit = total_profit / len(trades) if trades else 0

        # 종합 점수: 승률과 평균 수익의 가중 평균
        # 승률 60%, 평균 수익 40% 비중
        score = (win_rate * 0.6) + (avg_profit / 10.0 * 0.4)

        return score

    def update_config_file(self, optimized_ratios: Dict[Tuple[str, str], Dict[str, float]]):
        """
        최적화된 손익비를 config 파일에 업데이트

        Args:
            optimized_ratios: 최적화된 손익비 딕셔너리
        """
        config_file = project_root / "config" / "dynamic_profit_loss_config.py"

        print(f"{'='*80}")
        print(f"📝 설정 파일 업데이트 중: {config_file.name}")
        print(f"{'='*80}\n")

        # 백업 파일 생성
        backup_file = config_file.with_suffix('.py.backup')
        with open(config_file, 'r', encoding='utf-8') as f:
            original_content = f.read()

        with open(backup_file, 'w', encoding='utf-8') as f:
            f.write(original_content)

        print(f"  💾 백업 파일 생성: {backup_file.name}")

        # 새로운 PATTERN_COMBINATION_RATIOS 딕셔너리 생성
        new_ratios_dict = {}
        for pattern, ratio_info in sorted(optimized_ratios.items()):
            new_ratios_dict[pattern] = {
                'stop_loss': ratio_info['stop_loss'],
                'take_profit': ratio_info['take_profit']
            }

        # 기존 설정에서 누락된 패턴은 유지
        for pattern, ratio in DynamicProfitLossConfig.PATTERN_COMBINATION_RATIOS.items():
            if pattern not in new_ratios_dict:
                new_ratios_dict[pattern] = ratio
                print(f"  ℹ️  데이터 부족으로 기존 설정 유지: {pattern}")

        # 딕셔너리를 문자열로 변환
        dict_str = "PATTERN_COMBINATION_RATIOS = {\n"
        for pattern, ratio in sorted(new_ratios_dict.items()):
            support, decline = pattern
            dict_str += f"    ('{support}', '{decline}'): {{'stop_loss': {ratio['stop_loss']}, 'take_profit': {ratio['take_profit']}}},\n"
        dict_str += "}"

        # 파일 내용 업데이트
        lines = original_content.split('\n')
        new_lines = []
        skip_until_closing = False

        for line in lines:
            if 'PATTERN_COMBINATION_RATIOS = {' in line:
                # 기존 딕셔너리 시작 - 새로운 내용으로 교체
                new_lines.append(dict_str)
                skip_until_closing = True
            elif skip_until_closing:
                # 딕셔너리 끝나는 지점 찾기
                if line.strip().startswith('}'):
                    skip_until_closing = False
                # 이 범위의 라인은 스킵 (이미 새로운 내용으로 교체됨)
            else:
                new_lines.append(line)

        # 파일에 쓰기
        with open(config_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(new_lines))

        print(f"  ✅ 설정 파일 업데이트 완료\n")
        print(f"  📋 업데이트된 패턴 수: {len(optimized_ratios)}")
        print(f"  📋 유지된 패턴 수: {len(new_ratios_dict) - len(optimized_ratios)}\n")

    def generate_report(self, optimized_ratios: Dict[Tuple[str, str], Dict[str, float]]):
        """
        최적화 결과 리포트 생성

        Args:
            optimized_ratios: 최적화된 손익비 딕셔너리
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        report_file = project_root / f"pattern_optimization_report_{timestamp}.md"

        print(f"{'='*80}")
        print(f"📄 최적화 리포트 생성 중...")
        print(f"{'='*80}\n")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"# 패턴별 동적 손익비 최적화 리포트\n\n")
            f.write(f"**생성 시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write(f"**분석 기간**: {self.start_date} ~ {self.end_date}\n\n")
            f.write(f"---\n\n")

            f.write(f"## 📊 전체 통계\n\n")
            total_trades = sum(len(trades) for trades in self.pattern_trades.values())
            f.write(f"- **총 매매 건수**: {total_trades:,}건\n")
            f.write(f"- **분석된 패턴 수**: {len(self.pattern_trades)}개\n")
            f.write(f"- **최적화된 패턴 수**: {len(optimized_ratios)}개\n\n")

            f.write(f"---\n\n")
            f.write(f"## 🎯 패턴별 최적 손익비\n\n")
            f.write(f"| Support Volume | Decline Volume | 매매건수 | 손절 (%) | 익절 (%) | 점수 |\n")
            f.write(f"|:---------------|:---------------|--------:|---------:|---------:|-----:|\n")

            for pattern in sorted(optimized_ratios.keys()):
                support, decline = pattern
                ratio_info = optimized_ratios[pattern]
                trade_count = len(self.pattern_trades[pattern])

                f.write(f"| {support} | {decline} | {trade_count} | ")
                f.write(f"{ratio_info['stop_loss']:+.1f} | {ratio_info['take_profit']:+.1f} | ")
                f.write(f"{ratio_info['score']:.3f} |\n")

            f.write(f"\n---\n\n")
            f.write(f"## 📈 패턴별 상세 분석\n\n")

            for pattern in sorted(optimized_ratios.keys()):
                support, decline = pattern
                trades = self.pattern_trades[pattern]
                ratio_info = optimized_ratios[pattern]

                f.write(f"### {support} x {decline}\n\n")
                f.write(f"- **매매 건수**: {len(trades)}건\n")
                f.write(f"- **최적 손절**: {ratio_info['stop_loss']:+.1f}%\n")
                f.write(f"- **최적 익절**: {ratio_info['take_profit']:+.1f}%\n")
                f.write(f"- **최적화 점수**: {ratio_info['score']:.3f}\n")

                # 기존 설정과 비교
                old_ratio = DynamicProfitLossConfig.PATTERN_COMBINATION_RATIOS.get(pattern)
                if old_ratio:
                    f.write(f"- **기존 손절**: {old_ratio['stop_loss']:+.1f}%\n")
                    f.write(f"- **기존 익절**: {old_ratio['take_profit']:+.1f}%\n")

                    # 변화량 계산
                    sl_change = ratio_info['stop_loss'] - old_ratio['stop_loss']
                    tp_change = ratio_info['take_profit'] - old_ratio['take_profit']
                    f.write(f"- **변화**: 손절 {sl_change:+.1f}%p, 익절 {tp_change:+.1f}%p\n")

                f.write(f"\n")

            f.write(f"---\n\n")
            f.write(f"## ⚙️ 최적화 설정\n\n")
            f.write(f"- **테스트 손절 범위**: -1.5% ~ -6.0% (0.5% 간격)\n")
            f.write(f"- **테스트 익절 범위**: +3.0% ~ +8.0% (0.5% 간격)\n")
            f.write(f"- **점수 계산 방식**: 승률 60% + 평균수익 40%\n")
            f.write(f"- **최소 매매 건수**: 5건\n\n")

            f.write(f"---\n\n")
            f.write(f"## 📝 참고사항\n\n")
            f.write(f"- 이 리포트는 과거 데이터 기반 최적화 결과입니다.\n")
            f.write(f"- 실제 매매에 적용하기 전에 충분한 검증이 필요합니다.\n")
            f.write(f"- 시장 상황에 따라 주기적으로 재최적화를 권장합니다.\n")

        print(f"  ✅ 리포트 생성 완료: {report_file.name}\n")


def main():
    """메인 실행 함수"""
    import argparse

    parser = argparse.ArgumentParser(description='패턴별 동적 손익비 최적화')
    parser.add_argument('-s', '--start-date', required=True, help='시작 날짜 (YYYYMMDD)')
    parser.add_argument('-e', '--end-date', required=True, help='종료 날짜 (YYYYMMDD)')
    parser.add_argument('-d', '--output-dir', default='signal_replay_log', help='시뮬레이션 로그 디렉토리')
    parser.add_argument('--no-update', action='store_true', help='config 파일 업데이트 안함 (분석만)')

    args = parser.parse_args()

    print(f"\n{'='*80}")
    print(f"🚀 패턴별 동적 손익비 최적화 시작")
    print(f"{'='*80}\n")
    print(f"  📅 분석 기간: {args.start_date} ~ {args.end_date}")
    print(f"  📂 로그 디렉토리: {args.output_dir}")
    print(f"  ⚙️  설정 업데이트: {'아니오' if args.no_update else '예'}\n")

    # 최적화 실행
    optimizer = PatternOptimizer(args.start_date, args.end_date)

    # 1단계: 패턴 데이터 수집
    optimizer.collect_pattern_data(args.output_dir)

    if not optimizer.pattern_trades:
        print("❌ 수집된 패턴 데이터가 없습니다. 시뮬레이션 로그를 먼저 생성하세요.")
        return

    # 2단계: 최적 손익비 계산
    optimized_ratios = optimizer.optimize_ratios()

    if not optimized_ratios:
        print("❌ 최적화된 손익비를 계산할 수 없습니다. 데이터가 부족합니다.")
        return

    # 3단계: 리포트 생성
    optimizer.generate_report(optimized_ratios)

    # 4단계: config 파일 업데이트
    if not args.no_update:
        optimizer.update_config_file(optimized_ratios)

        print(f"{'='*80}")
        print(f"✅ 최적화 완료!")
        print(f"{'='*80}\n")
        print(f"  ✔️  설정 파일이 업데이트되었습니다.")
        print(f"  ✔️  백업 파일: config/dynamic_profit_loss_config.py.backup")
        print(f"  💡 변경사항을 확인한 후 trading_config.json에서 use_dynamic_profit_loss를 true로 설정하세요.\n")
    else:
        print(f"{'='*80}")
        print(f"✅ 분석 완료!")
        print(f"{'='*80}\n")
        print(f"  ℹ️  --no-update 옵션으로 실행되어 설정 파일은 변경되지 않았습니다.")
        print(f"  💡 리포트를 확인한 후 필요시 --no-update 없이 다시 실행하세요.\n")


if __name__ == "__main__":
    main()
