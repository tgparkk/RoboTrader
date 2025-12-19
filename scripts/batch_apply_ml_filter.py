#!/usr/bin/env python3
"""
기존 signal_replay_log 파일들에 ML 필터를 일괄 적용
"""
import os
import sys
import glob
import subprocess
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from multiprocessing import cpu_count

sys.stdout.reconfigure(encoding='utf-8')


def apply_ml_filter_to_file(input_file, output_dir, threshold):
    """단일 파일에 ML 필터 적용"""
    try:
        # 출력 파일명 생성
        input_path = Path(input_file)
        output_filename = input_path.name.replace('signal_new2_replay', 'signal_ml_replay')
        output_file = os.path.join(output_dir, output_filename)
        
        # ML 필터 실행
        cmd = [
            sys.executable, 'apply_ml_filter.py',
            input_file,
            '--output', output_file,
            '--threshold', str(threshold)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )
        
        if result.returncode == 0:
            # 결과 파싱
            stats = {}
            if result.stdout:
                for line in result.stdout.split('\n'):
                    if '총 신호:' in line:
                        stats['total'] = int(line.split(':')[1].split('개')[0].strip())
                    elif '통과:' in line:
                        stats['passed'] = int(line.split(':')[1].split('개')[0].strip())
                    elif '차단:' in line:
                        stats['blocked'] = int(line.split(':')[1].split('개')[0].strip())
            
            return {
                'file': input_path.name,
                'success': True,
                'stats': stats
            }
        else:
            return {
                'file': input_path.name,
                'success': False,
                'error': result.stderr.strip() if result.stderr else "알 수 없는 오류"
            }
            
    except Exception as e:
        return {
            'file': Path(input_file).name,
            'success': False,
            'error': str(e)
        }


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='기존 백테스트 결과에 ML 필터 일괄 적용')
    parser.add_argument('--threshold', '-t', type=float, default=0.5,
                       help='ML 승률 임계값 (기본: 0.5)')
    parser.add_argument('--workers', '-w', type=int, default=min(8, cpu_count()),
                       help=f'병렬 처리 워커 수 (기본: min(8, {cpu_count()}))')
    parser.add_argument('--input-dir', default='signal_replay_log',
                       help='입력 디렉토리 (기본: signal_replay_log)')
    parser.add_argument('--output-dir', default='signal_replay_log_ml',
                       help='출력 디렉토리 (기본: signal_replay_log_ml)')
    
    args = parser.parse_args()
    
    # 출력 디렉토리 생성
    os.makedirs(args.output_dir, exist_ok=True)
    
    # 입력 파일 목록
    input_files = glob.glob(os.path.join(args.input_dir, 'signal_new2_replay_*.txt'))
    
    if not input_files:
        print(f"❌ {args.input_dir}에 백테스트 파일이 없습니다.")
        return
    
    print(f"🤖 ML 필터 일괄 적용")
    print("=" * 60)
    print(f"📂 입력 디렉토리: {args.input_dir}")
    print(f"📂 출력 디렉토리: {args.output_dir}")
    print(f"📄 처리 대상: {len(input_files)}개 파일")
    print(f"🎯 ML 임계값: {args.threshold:.1%}")
    print(f"⚡ 병렬 처리: {args.workers} 워커")
    print()
    
    # 통계
    success_count = 0
    total_signals = 0
    total_passed = 0
    total_blocked = 0
    
    # 병렬 처리
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(apply_ml_filter_to_file, f, args.output_dir, args.threshold): f
            for f in input_files
        }
        
        completed = 0
        for future in as_completed(futures):
            input_file = futures[future]
            completed += 1
            
            try:
                result = future.result()
                print(f"[{completed}/{len(input_files)}] {result['file']}: ", end="")
                
                if result['success']:
                    success_count += 1
                    stats = result.get('stats', {})
                    if stats:
                        total_signals += stats.get('total', 0)
                        total_passed += stats.get('passed', 0)
                        total_blocked += stats.get('blocked', 0)
                        print(f"✅ (신호 {stats.get('total', 0)}개, 통과 {stats.get('passed', 0)}개, 차단 {stats.get('blocked', 0)}개)")
                    else:
                        print("✅")
                else:
                    print(f"❌ {result.get('error', '알 수 없는 오류')}")
                    
            except Exception as e:
                print(f"[{completed}/{len(input_files)}] {Path(input_file).name}: ❌ 예외: {e}")
    
    print()
    print("=" * 60)
    print(f"🏁 처리 완료: {success_count}/{len(input_files)}개 성공")
    
    if total_signals > 0:
        print()
        print(f"📊 전체 통계:")
        print(f"   총 신호: {total_signals}개")
        print(f"   통과: {total_passed}개 ({total_passed/total_signals*100:.1f}%)")
        print(f"   차단: {total_blocked}개 ({total_blocked/total_signals*100:.1f}%)")


if __name__ == "__main__":
    main()
