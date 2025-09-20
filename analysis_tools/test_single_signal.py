"""
단일 날짜 신호 재생 테스트
"""

import sys
import os
sys.path.append(os.getcwd())

import subprocess

def run_signal_replay():
    """신호 재생 실행"""
    try:
        cmd = [
            sys.executable, '-m', 'utils.signal_replay',
            '--date', '20250919',
            '--export', 'txt',
            '--txt-path', 'signal_replay_log/test_corrected_20250919.txt'
        ]

        print("실행 명령:", ' '.join(cmd))

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='ignore'
        )

        print("Return code:", result.returncode)

        if result.stdout:
            # 유니코드 문제 방지를 위해 ascii만 출력
            lines = result.stdout.split('\n')
            for line in lines[:20]:  # 처음 20줄만
                try:
                    print(line.encode('ascii', 'ignore').decode('ascii'))
                except:
                    print("(non-ascii line)")

        if result.stderr:
            print("STDERR:", result.stderr[:500])

        return result.returncode == 0

    except Exception as e:
        print(f"오류: {e}")
        return False

if __name__ == "__main__":
    success = run_signal_replay()
    print(f"실행 {'성공' if success else '실패'}")