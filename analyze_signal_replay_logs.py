#!/usr/bin/env python3
"""
Signal Replay Log 비교 분석 스크립트

signal_replay_log와 signal_replay_log_prev 폴더의 로그 파일들을 비교하여
성능 변화를 분석합니다.
"""

import os
import re
import json
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pandas as pd

class SignalReplayLogAnalyzer:
    """Signal Replay 로그 분석기"""
    
    def __init__(self, current_log_dir: str = "signal_replay_log", 
                 prev_log_dir: str = "signal_replay_log_prev"):
        self.current_log_dir = Path(current_log_dir)
        self.prev_log_dir = Path(prev_log_dir)
        self.results = {}
        
    def parse_log_file(self, file_path: Path) -> Dict:
        """로그 파일을 파싱하여 결과 추출"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 총 승패 추출
            total_wins = 0
            total_losses = 0
            total_wins_after = 0
            total_losses_after = 0
            
            # 총 승패 패턴 매칭
            total_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', content)
            if total_match:
                total_wins = int(total_match.group(1))
                total_losses = int(total_match.group(2))
            
            # selection_date 이후 승패 패턴 매칭
            after_match = re.search(r'=== selection_date 이후 승패: (\d+)승 (\d+)패 ===', content)
            if after_match:
                total_wins_after = int(after_match.group(1))
                total_losses_after = int(after_match.group(2))
            
            # 개별 종목 결과 추출
            stock_results = []
            stock_pattern = r'=== (\d+) - (\d{8}) 눌림목\(3분\) 신호 재현 ==='
            stock_matches = re.finditer(stock_pattern, content)
            
            for match in stock_matches:
                stock_code = match.group(1)
                date = match.group(2)
                
                # 해당 종목의 결과 추출
                start_pos = match.end()
                next_stock_match = re.search(stock_pattern, content[start_pos:])
                end_pos = start_pos + next_stock_match.start() if next_stock_match else len(content)
                stock_content = content[start_pos:end_pos]
                
                # 승패 추출
                wins = 0
                losses = 0
                wins_after = 0
                losses_after = 0
                
                win_loss_match = re.search(r'승패: (\d+)승 (\d+)패', stock_content)
                if win_loss_match:
                    wins = int(win_loss_match.group(1))
                    losses = int(win_loss_match.group(2))
                
                after_match = re.search(r'selection_date 이후 승패: (\d+)승 (\d+)패', stock_content)
                if after_match:
                    wins_after = int(after_match.group(1))
                    losses_after = int(after_match.group(2))
                
                # 매매신호 개수 추출
                signal_count = 0
                if "매매신호:" in stock_content and "없음" not in stock_content:
                    # 매매신호가 있는 경우 개수 계산
                    signal_lines = [line for line in stock_content.split('\n') 
                                  if '매매신호:' in line or (line.strip() and not line.startswith('  '))]
                    signal_count = len([line for line in signal_lines if line.strip() and '매매신호:' not in line])
                
                # 체결 시뮬레이션 개수 추출
                execution_count = 0
                if "체결 시뮬레이션:" in stock_content and "없음" not in stock_content:
                    execution_lines = [line for line in stock_content.split('\n') 
                                     if '체결 시뮬레이션:' in line or (line.strip() and not line.startswith('  '))]
                    execution_count = len([line for line in execution_lines if line.strip() and '체결 시뮬레이션:' not in line])
                
                # 매수 못한 기회 개수 추출
                missed_count = 0
                if "매수 못한 기회:" in stock_content and "없음" not in stock_content:
                    missed_lines = [line for line in stock_content.split('\n') 
                                  if '매수 못한 기회:' in line or (line.strip() and not line.startswith('  '))]
                    missed_count = len([line for line in missed_lines if line.strip() and '매수 못한 기회:' not in line])
                
                stock_results.append({
                    'stock_code': stock_code,
                    'date': date,
                    'wins': wins,
                    'losses': losses,
                    'wins_after': wins_after,
                    'losses_after': losses_after,
                    'signal_count': signal_count,
                    'execution_count': execution_count,
                    'missed_count': missed_count
                })
            
            return {
                'file_name': file_path.name,
                'date': file_path.name.split('_')[3],  # 날짜 추출
                'total_wins': total_wins,
                'total_losses': total_losses,
                'total_wins_after': total_wins_after,
                'total_losses_after': total_losses_after,
                'stock_results': stock_results
            }
            
        except Exception as e:
            print(f"❌ 파일 파싱 오류 {file_path}: {e}")
            return None
    
    def analyze_logs(self) -> Dict:
        """로그 파일들을 분석"""
        print("🔍 Signal Replay 로그 분석 시작...")
        
        # 현재 로그 파일들 분석
        current_logs = {}
        if self.current_log_dir.exists():
            for log_file in self.current_log_dir.glob("*.txt"):
                result = self.parse_log_file(log_file)
                if result:
                    current_logs[result['date']] = result
        else:
            print(f"❌ 현재 로그 디렉토리가 존재하지 않습니다: {self.current_log_dir}")
            return {}
        
        # 이전 로그 파일들 분석
        prev_logs = {}
        if self.prev_log_dir.exists():
            for log_file in self.prev_log_dir.glob("*.txt"):
                result = self.parse_log_file(log_file)
                if result:
                    prev_logs[result['date']] = result
        else:
            print(f"❌ 이전 로그 디렉토리가 존재하지 않습니다: {self.prev_log_dir}")
            return {}
        
        # 비교 분석
        comparison_results = self.compare_logs(current_logs, prev_logs)
        
        return {
            'current_logs': current_logs,
            'prev_logs': prev_logs,
            'comparison': comparison_results
        }
    
    def compare_logs(self, current_logs: Dict, prev_logs: Dict) -> Dict:
        """로그 결과 비교"""
        comparison = {
            'summary': {},
            'daily_comparison': {},
            'stock_comparison': {},
            'performance_metrics': {}
        }
        
        # 전체 요약 비교
        current_total_wins = sum(log['total_wins'] for log in current_logs.values())
        current_total_losses = sum(log['total_losses'] for log in current_logs.values())
        prev_total_wins = sum(log['total_wins'] for log in prev_logs.values())
        prev_total_losses = sum(log['total_losses'] for log in prev_logs.values())
        
        current_win_rate = current_total_wins / (current_total_wins + current_total_losses) * 100 if (current_total_wins + current_total_losses) > 0 else 0
        prev_win_rate = prev_total_wins / (prev_total_wins + prev_total_losses) * 100 if (prev_total_wins + prev_total_losses) > 0 else 0
        
        comparison['summary'] = {
            'current': {
                'total_wins': current_total_wins,
                'total_losses': current_total_losses,
                'win_rate': current_win_rate,
                'total_trades': current_total_wins + current_total_losses
            },
            'prev': {
                'total_wins': prev_total_wins,
                'total_losses': prev_total_losses,
                'win_rate': prev_win_rate,
                'total_trades': prev_total_wins + prev_total_losses
            },
            'improvement': {
                'win_rate_change': current_win_rate - prev_win_rate,
                'total_trades_change': (current_total_wins + current_total_losses) - (prev_total_wins + prev_total_losses),
                'wins_change': current_total_wins - prev_total_wins,
                'losses_change': current_total_losses - prev_total_losses
            }
        }
        
        # 일별 비교
        all_dates = set(current_logs.keys()) | set(prev_logs.keys())
        for date in sorted(all_dates):
            current_log = current_logs.get(date)
            prev_log = prev_logs.get(date)
            
            if current_log and prev_log:
                current_win_rate = current_log['total_wins'] / (current_log['total_wins'] + current_log['total_losses']) * 100 if (current_log['total_wins'] + current_log['total_losses']) > 0 else 0
                prev_win_rate = prev_log['total_wins'] / (prev_log['total_wins'] + prev_log['total_losses']) * 100 if (prev_log['total_wins'] + prev_log['total_losses']) > 0 else 0
                
                comparison['daily_comparison'][date] = {
                    'current': {
                        'wins': current_log['total_wins'],
                        'losses': current_log['total_losses'],
                        'win_rate': current_win_rate,
                        'total_trades': current_log['total_wins'] + current_log['total_losses']
                    },
                    'prev': {
                        'wins': prev_log['total_wins'],
                        'losses': prev_log['total_losses'],
                        'win_rate': prev_win_rate,
                        'total_trades': prev_log['total_wins'] + prev_log['total_losses']
                    },
                    'improvement': {
                        'win_rate_change': current_win_rate - prev_win_rate,
                        'total_trades_change': (current_log['total_wins'] + current_log['total_losses']) - (prev_log['total_wins'] + prev_log['total_losses'])
                    }
                }
        
        # 성능 지표 계산
        comparison['performance_metrics'] = self.calculate_performance_metrics(comparison)
        
        return comparison
    
    def calculate_performance_metrics(self, comparison: Dict) -> Dict:
        """성능 지표 계산 (손익비 3:2 고려)"""
        metrics = {}
        
        # 전체 성능 지표
        summary = comparison['summary']
        current = summary['current']
        prev = summary['prev']
        improvement = summary['improvement']
        
        # 손익비 3:2 기준으로 수익률 계산
        # 승리 시 +3%, 패배 시 -2% 가정
        current_profit_rate = (current['total_wins'] * 3 - current['total_losses'] * 2) / 100
        prev_profit_rate = (prev['total_wins'] * 3 - prev['total_losses'] * 2) / 100
        profit_rate_improvement = current_profit_rate - prev_profit_rate
        
        # 손익비 기준 최소 승률 계산 (손익비 3:2에서 손익분기점)
        # 3x - 2(1-x) = 0 → 3x - 2 + 2x = 0 → 5x = 2 → x = 0.4 (40%)
        breakeven_win_rate = 40.0
        
        metrics['overall'] = {
            'win_rate_improvement': improvement['win_rate_change'],
            'total_trades_improvement': improvement['total_trades_change'],
            'wins_improvement': improvement['wins_change'],
            'losses_improvement': improvement['losses_change'],
            'current_win_rate': current['win_rate'],
            'prev_win_rate': prev['win_rate'],
            'current_profit_rate': current_profit_rate,
            'prev_profit_rate': prev_profit_rate,
            'profit_rate_improvement': profit_rate_improvement,
            'breakeven_win_rate': breakeven_win_rate,
            'current_above_breakeven': current['win_rate'] > breakeven_win_rate,
            'prev_above_breakeven': prev['win_rate'] > breakeven_win_rate
        }
        
        # 일별 성능 분석
        daily_improvements = []
        for date, daily_data in comparison['daily_comparison'].items():
            daily_improvements.append(daily_data['improvement']['win_rate_change'])
        
        if daily_improvements:
            metrics['daily_analysis'] = {
                'avg_daily_improvement': sum(daily_improvements) / len(daily_improvements),
                'best_day_improvement': max(daily_improvements),
                'worst_day_improvement': min(daily_improvements),
                'positive_days': len([x for x in daily_improvements if x > 0]),
                'negative_days': len([x for x in daily_improvements if x < 0]),
                'total_days': len(daily_improvements)
            }
        
        return metrics
    
    def generate_report(self, results: Dict) -> str:
        """분석 결과 리포트 생성"""
        if not results:
            return "❌ 분석할 데이터가 없습니다."
        
        report = []
        report.append("=" * 80)
        report.append("📊 Signal Replay 로그 비교 분석 리포트")
        report.append("=" * 80)
        report.append("")
        
        # 전체 요약
        summary = results['comparison']['summary']
        current = summary['current']
        prev = summary['prev']
        improvement = summary['improvement']
        metrics = results['comparison']['performance_metrics']['overall']
        
        report.append("📈 전체 성능 요약")
        report.append("-" * 40)
        report.append(f"현재 버전: {current['total_wins']}승 {current['total_losses']}패 (승률: {current['win_rate']:.1f}%)")
        report.append(f"이전 버전: {prev['total_wins']}승 {prev['total_losses']}패 (승률: {prev['win_rate']:.1f}%)")
        report.append("")
        
        # 손익비 3:2 기준 수익률 분석
        report.append("💰 손익비 3:2 기준 수익률 분석")
        report.append("-" * 40)
        report.append(f"현재 수익률: {metrics['current_profit_rate']:+.1f}% (승리시 +3%, 패배시 -2%)")
        report.append(f"이전 수익률: {metrics['prev_profit_rate']:+.1f}% (승리시 +3%, 패배시 -2%)")
        report.append(f"수익률 개선: {metrics['profit_rate_improvement']:+.1f}%p")
        report.append(f"손익분기점: {metrics['breakeven_win_rate']:.1f}% (손익비 3:2 기준)")
        report.append("")
        
        # 손익분기점 달성 여부
        if metrics['current_above_breakeven']:
            report.append(f"✅ 현재 버전: 손익분기점({metrics['breakeven_win_rate']:.1f}%) 달성")
        else:
            report.append(f"❌ 현재 버전: 손익분기점({metrics['breakeven_win_rate']:.1f}%) 미달성")
            
        if metrics['prev_above_breakeven']:
            report.append(f"✅ 이전 버전: 손익분기점({metrics['breakeven_win_rate']:.1f}%) 달성")
        else:
            report.append(f"❌ 이전 버전: 손익분기점({metrics['breakeven_win_rate']:.1f}%) 미달성")
        report.append("")
        
        report.append("📊 개선 사항:")
        report.append(f"  • 승률 변화: {improvement['win_rate_change']:+.1f}%p")
        report.append(f"  • 수익률 변화: {metrics['profit_rate_improvement']:+.1f}%p")
        report.append(f"  • 총 거래 수: {improvement['total_trades_change']:+d}건")
        report.append(f"  • 승리 수: {improvement['wins_change']:+d}건")
        report.append(f"  • 패배 수: {improvement['losses_change']:+d}건")
        report.append("")
        
        # 일별 비교
        report.append("📅 일별 성능 비교")
        report.append("-" * 40)
        report.append(f"{'날짜':<12} {'현재 승률':<10} {'이전 승률':<10} {'개선도':<10} {'현재 수익률':<12} {'이전 수익률':<12}")
        report.append("-" * 80)
        
        for date, daily_data in results['comparison']['daily_comparison'].items():
            current_win_rate = daily_data['current']['win_rate']
            prev_win_rate = daily_data['prev']['win_rate']
            win_rate_change = daily_data['improvement']['win_rate_change']
            
            # 일별 손익비 3:2 기준 수익률 계산
            current_profit = (daily_data['current']['wins'] * 3 - daily_data['current']['losses'] * 2) / 100
            prev_profit = (daily_data['prev']['wins'] * 3 - daily_data['prev']['losses'] * 2) / 100
            
            report.append(f"{date:<12} {current_win_rate:>8.1f}% {prev_win_rate:>8.1f}% {win_rate_change:>+8.1f}%p {current_profit:>+10.1f}% {prev_profit:>+10.1f}%")
        
        report.append("")
        
        # 성능 지표
        metrics = results['comparison']['performance_metrics']
        if 'daily_analysis' in metrics:
            daily_analysis = metrics['daily_analysis']
            report.append("📊 성능 지표 분석")
            report.append("-" * 40)
            report.append(f"평균 일일 개선도: {daily_analysis['avg_daily_improvement']:+.1f}%p")
            report.append(f"최고 개선일: {daily_analysis['best_day_improvement']:+.1f}%p")
            report.append(f"최악 개선일: {daily_analysis['worst_day_improvement']:+.1f}%p")
            report.append(f"개선된 날: {daily_analysis['positive_days']}일 / {daily_analysis['total_days']}일")
            report.append(f"악화된 날: {daily_analysis['negative_days']}일 / {daily_analysis['total_days']}일")
            report.append("")
        
        # 결론
        report.append("🎯 결론")
        report.append("-" * 40)
        
        # 승률 기준 결론
        if improvement['win_rate_change'] > 0:
            report.append("✅ 현재 버전이 이전 버전보다 승률이 개선되었습니다.")
        elif improvement['win_rate_change'] < 0:
            report.append("⚠️ 현재 버전이 이전 버전보다 승률이 악화되었습니다.")
        else:
            report.append("➖ 현재 버전과 이전 버전의 승률이 동일합니다.")
        
        # 손익비 3:2 기준 결론
        if metrics['overall']['profit_rate_improvement'] > 0:
            report.append(f"💰 손익비 3:2 기준 수익률이 {metrics['overall']['profit_rate_improvement']:+.1f}%p 개선되었습니다.")
        elif metrics['overall']['profit_rate_improvement'] < 0:
            report.append(f"💸 손익비 3:2 기준 수익률이 {metrics['overall']['profit_rate_improvement']:+.1f}%p 악화되었습니다.")
        else:
            report.append("💰 손익비 3:2 기준 수익률이 동일합니다.")
        
        # 손익분기점 달성 여부
        if metrics['overall']['current_above_breakeven'] and not metrics['overall']['prev_above_breakeven']:
            report.append(f"🎯 손익분기점({metrics['overall']['breakeven_win_rate']:.1f}%)을 달성했습니다!")
        elif not metrics['overall']['current_above_breakeven'] and metrics['overall']['prev_above_breakeven']:
            report.append(f"⚠️ 손익분기점({metrics['overall']['breakeven_win_rate']:.1f}%)을 달성하지 못했습니다.")
        elif metrics['overall']['current_above_breakeven'] and metrics['overall']['prev_above_breakeven']:
            report.append(f"✅ 손익분기점({metrics['overall']['breakeven_win_rate']:.1f}%)을 계속 달성하고 있습니다.")
        else:
            report.append(f"❌ 손익분기점({metrics['overall']['breakeven_win_rate']:.1f}%)을 달성하지 못하고 있습니다.")
        
        # 거래 기회 변화
        if improvement['total_trades_change'] > 0:
            report.append(f"📈 거래 기회가 {improvement['total_trades_change']}건 증가했습니다.")
        elif improvement['total_trades_change'] < 0:
            report.append(f"📉 거래 기회가 {abs(improvement['total_trades_change'])}건 감소했습니다.")
        
        report.append("")
        report.append("=" * 80)
        
        return "\n".join(report)
    
    def save_results(self, results: Dict, output_file: str = "signal_replay_comparison.json"):
        """분석 결과를 JSON 파일로 저장"""
        try:
            with open(output_file, 'w', encoding='utf-8') as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            print(f"💾 분석 결과가 {output_file}에 저장되었습니다.")
        except Exception as e:
            print(f"❌ 결과 저장 오류: {e}")
    
    def run_analysis(self, save_json: bool = True) -> str:
        """전체 분석 실행"""
        print("🚀 Signal Replay 로그 비교 분석을 시작합니다...")
        
        # 로그 분석
        results = self.analyze_logs()
        
        if not results:
            return "❌ 분석할 데이터가 없습니다."
        
        # 리포트 생성
        report = self.generate_report(results)
        
        # 결과 저장
        if save_json:
            self.save_results(results)
        
        # 리포트를 파일로도 저장
        report_file = "signal_replay_comparison_report.txt"
        try:
            with open(report_file, 'w', encoding='utf-8') as f:
                f.write(report)
            print(f"📄 리포트가 {report_file}에 저장되었습니다.")
        except Exception as e:
            print(f"❌ 리포트 저장 오류: {e}")
        
        return report

def main():
    """메인 함수"""
    print("🔍 Signal Replay 로그 비교 분석기")
    print("=" * 50)
    
    # 분석기 생성
    analyzer = SignalReplayLogAnalyzer()
    
    # 분석 실행
    report = analyzer.run_analysis()
    
    # 결과 출력
    print("\n" + report)

if __name__ == "__main__":
    main()
