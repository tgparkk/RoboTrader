"""
돌파봉 몸통 0.6% 필터 적용 후 백테스트
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from signal_replay import SignalReplay
from datetime import datetime

def main():
    print("="*80)
    print("돌파봉 몸통 >= 0.6% 필터 적용 백테스트")
    print("="*80)

    # 백테스트 실행
    replay = SignalReplay(
        start_date="20250901",
        end_date="20251031",
        stock_list_file="stock_list.txt",
        cache_dir="cache",
        log_dir="signal_replay_log"
    )

    print("\n[*] 백테스트 실행 중...")
    replay.run()

    print("\n" + "="*80)
    print("[OK] 백테스트 완료!")
    print("="*80)

if __name__ == "__main__":
    main()
