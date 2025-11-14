#!/usr/bin/env python3
"""
전략 파라미터 최적화 도구
설정 파일을 읽어서 백테스트를 실행하고 결과를 비교합니다.

사용법:
python optimize_strategy.py --config backtest_configs/default.yaml
python optimize_strategy.py --config backtest_configs/aggressive_morning.yaml
python optimize_strategy.py --compare backtest_configs/default.yaml backtest_configs/aggressive_morning.yaml
python optimize_strategy.py --batch backtest_configs/*.yaml
"""

import argparse
import yaml
import os
import sys
import subprocess
from datetime import datetime
from pathlib import Path
import json


class StrategyOptimizer:
    """전략 최적화 도구"""

    def __init__(self, config_path):
        self.config_path = config_path
        self.config = self.load_config(config_path)
        self.results = {}

    def load_config(self, path):
        """설정 파일 로드"""
        with open(path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)

    def apply_config_to_code(self):
        """설정을 코드에 임시 적용"""
        # 임시 설정 파일 생성
        temp_config_path = 'temp_backtest_config.json'
        with open(temp_config_path, 'w', encoding='utf-8') as f:
            json.dump(self.config, f, indent=2, ensure_ascii=False)

        return temp_config_path

    def run_backtest(self):
        """백테스트 실행"""
        print(f"\n{'='*60}")
        print(f"🔄 백테스트 실행: {self.config['name']}")
        print(f"   설명: {self.config['description']}")
        print(f"{'='*60}\n")

        # 설정 적용
        temp_config = self.apply_config_to_code()

        try:
            # 백테스트 실행 (signal_replay 사용)
            start_date = self.config['backtest_period']['start_date']
            end_date = self.config['backtest_period']['end_date']

            cmd = [
                'python', '-X', 'utf8', 'utils/signal_replay.py',
                '--start-date', start_date,
                '--end-date', end_date,
                '--config', temp_config  # 임시 설정 파일 전달
            ]

            print(f"실행 명령: {' '.join(cmd)}")
            print("\n백테스트 진행 중...\n")

            # 실행
            result = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')

            if result.returncode == 0:
                print("✅ 백테스트 완료!")
                self.parse_results(result.stdout)
            else:
                print(f"❌ 백테스트 실패: {result.stderr}")
                return None

        finally:
            # 임시 파일 삭제
            if os.path.exists(temp_config):
                os.remove(temp_config)

        return self.results

    def parse_results(self, output):
        """백테스트 결과 파싱"""
        # signal_replay 출력에서 통계 추출
        lines = output.split('\n')

        for i, line in enumerate(lines):
            if '총 거래:' in line:
                # 예: "총 거래: 14건 (6승 8패)"
                parts = line.split()
                trades = int(parts[2].replace('건', ''))
                wins = int(parts[3].replace('(', '').replace('승', ''))
                losses = int(parts[4].replace('패)', ''))

                self.results['total_trades'] = trades
                self.results['wins'] = wins
                self.results['losses'] = losses
                self.results['win_rate'] = wins / trades * 100 if trades > 0 else 0

            elif '총 수익금:' in line:
                # 예: "총 수익금: +10,000원 (+1.0%)"
                parts = line.split()
                profit_str = parts[2].replace('원', '').replace(',', '').replace('+', '')
                profit = int(profit_str)

                self.results['total_profit'] = profit
                self.results['avg_profit_per_trade'] = profit / self.results['total_trades'] if self.results.get('total_trades', 0) > 0 else 0

        # 결과 출력
        print("\n📊 백테스트 결과:")
        print(f"   총 거래: {self.results.get('total_trades', 0)}건")
        print(f"   승패: {self.results.get('wins', 0)}승 {self.results.get('losses', 0)}패")
        print(f"   승률: {self.results.get('win_rate', 0):.1f}%")
        print(f"   총 수익: {self.results.get('total_profit', 0):+,}원")
        print(f"   거래당 평균: {self.results.get('avg_profit_per_trade', 0):+,.0f}원")

    def generate_report(self, output_dir='backtest_results'):
        """결과 리포트 생성"""
        os.makedirs(output_dir, exist_ok=True)

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        report_file = os.path.join(output_dir, f"{self.config['name']}_{timestamp}.txt")

        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(f"{'='*60}\n")
            f.write(f"백테스트 결과 리포트\n")
            f.write(f"{'='*60}\n\n")

            f.write(f"전략명: {self.config['name']}\n")
            f.write(f"설명: {self.config['description']}\n")
            f.write(f"백테스트 기간: {self.config['backtest_period']['start_date']} ~ {self.config['backtest_period']['end_date']}\n")
            f.write(f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write(f"--- 결과 ---\n")
            f.write(f"총 거래: {self.results.get('total_trades', 0)}건\n")
            f.write(f"승패: {self.results.get('wins', 0)}승 {self.results.get('losses', 0)}패\n")
            f.write(f"승률: {self.results.get('win_rate', 0):.1f}%\n")
            f.write(f"총 수익: {self.results.get('total_profit', 0):+,}원\n")
            f.write(f"거래당 평균: {self.results.get('avg_profit_per_trade', 0):+,.0f}원\n\n")

            f.write(f"--- 설정 상세 ---\n")
            f.write(yaml.dump(self.config, allow_unicode=True, default_flow_style=False))

        print(f"\n💾 리포트 저장: {report_file}")
        return report_file


def compare_strategies(config_paths):
    """여러 전략 비교"""
    print(f"\n{'='*60}")
    print(f"📊 전략 비교 모드")
    print(f"{'='*60}\n")

    results = []

    for config_path in config_paths:
        optimizer = StrategyOptimizer(config_path)
        result = optimizer.run_backtest()

        if result:
            results.append({
                'name': optimizer.config['name'],
                'description': optimizer.config['description'],
                'config_path': config_path,
                'results': result
            })

    # 비교 테이블 출력
    print(f"\n{'='*80}")
    print(f"📊 전략 비교 결과")
    print(f"{'='*80}\n")

    print(f"{'전략명':20} | {'총거래':>8} | {'승률':>8} | {'총수익':>12} | {'거래당평균':>12}")
    print(f"{'-'*80}")

    for r in results:
        name = r['name'][:18]
        trades = r['results'].get('total_trades', 0)
        win_rate = r['results'].get('win_rate', 0)
        profit = r['results'].get('total_profit', 0)
        avg = r['results'].get('avg_profit_per_trade', 0)

        print(f"{name:20} | {trades:8d}건 | {win_rate:7.1f}% | {profit:+11,}원 | {avg:+11,.0f}원")

    # 최고 성과 전략
    best_by_profit = max(results, key=lambda x: x['results'].get('total_profit', 0))
    best_by_winrate = max(results, key=lambda x: x['results'].get('win_rate', 0))

    print(f"\n🏆 최고 수익 전략: {best_by_profit['name']} ({best_by_profit['results'].get('total_profit', 0):+,}원)")
    print(f"🎯 최고 승률 전략: {best_by_winrate['name']} ({best_by_winrate['results'].get('win_rate', 0):.1f}%)")

    # 비교 리포트 저장
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = f"backtest_results/comparison_{timestamp}.txt"

    os.makedirs('backtest_results', exist_ok=True)
    with open(report_file, 'w', encoding='utf-8') as f:
        f.write(f"{'='*80}\n")
        f.write(f"전략 비교 리포트\n")
        f.write(f"생성 시간: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(f"{'='*80}\n\n")

        for r in results:
            f.write(f"[{r['name']}] {r['description']}\n")
            f.write(f"  총 거래: {r['results'].get('total_trades', 0)}건\n")
            f.write(f"  승률: {r['results'].get('win_rate', 0):.1f}%\n")
            f.write(f"  총 수익: {r['results'].get('total_profit', 0):+,}원\n")
            f.write(f"  거래당 평균: {r['results'].get('avg_profit_per_trade', 0):+,.0f}원\n\n")

        f.write(f"\n최고 수익 전략: {best_by_profit['name']}\n")
        f.write(f"최고 승률 전략: {best_by_winrate['name']}\n")

    print(f"\n💾 비교 리포트 저장: {report_file}")


def main():
    parser = argparse.ArgumentParser(
        description="전략 파라미터 최적화 도구",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 단일 전략 백테스트
  python optimize_strategy.py --config backtest_configs/default.yaml

  # 여러 전략 비교
  python optimize_strategy.py --compare backtest_configs/default.yaml backtest_configs/aggressive_morning.yaml

  # 모든 설정 파일 일괄 비교
  python optimize_strategy.py --batch backtest_configs/*.yaml
        """
    )

    parser.add_argument('--config', type=str, help='단일 설정 파일 경로')
    parser.add_argument('--compare', nargs='+', help='비교할 설정 파일들')
    parser.add_argument('--batch', nargs='+', help='일괄 실행할 설정 파일들')

    args = parser.parse_args()

    if args.config:
        # 단일 전략 실행
        optimizer = StrategyOptimizer(args.config)
        optimizer.run_backtest()
        optimizer.generate_report()

    elif args.compare:
        # 여러 전략 비교
        compare_strategies(args.compare)

    elif args.batch:
        # 일괄 실행
        compare_strategies(args.batch)

    else:
        parser.print_help()
        return 1

    return 0


if __name__ == '__main__':
    exit(main())
