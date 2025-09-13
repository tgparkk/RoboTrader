#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
로그 파싱 디버깅 스크립트
"""

import re
import os

def test_parsing():
    log_dir = r"C:\GIT\RoboTrader\새 폴더 (2)"
    log_file = os.path.join(log_dir, "signal_new2_replay_20250901_9_00_0.txt")
    
    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 섹션 분리 - 종목별로 분리
    sections = re.split(r'^=== \d{6} - \d{8}', content, flags=re.MULTILINE)
    print(f"총 {len(sections)}개의 섹션을 찾았습니다.")
    
    for i, section in enumerate(sections[:5]):  # 처음 5개 섹션만 확인
        print(f"\n=== 섹션 {i} ===")
        print(section[:200] + "..." if len(section) > 200 else section)
        
        # 종목 코드 추출 테스트
        stock_code_match = re.search(r'=== (\d{6}) - \d{8}', section)
        if stock_code_match:
            print(f"종목 코드: {stock_code_match.group(1)}")
        
        # 거래 정보 추출 테스트
        if '체결 시뮬레이션:' in section:
            print("체결 시뮬레이션 섹션을 찾았습니다!")
            # 거래 라인 찾기
            lines = section.split('\n')
            for line in lines:
                if '매수' in line and '매도' in line:
                    print(f"거래 라인: {line}")
            
            trade_lines = re.findall(
                r'(\d{2}:\d{2})\s+매수\[pullback_pattern\]\s+@([0-9,]+)\s+→\s+(\d{2}:\d{2})\s+매도\[(profit|stop_loss)_([0-9.]+)pct\]\s+@([0-9,]+)\s+([+-][0-9.]+%)',
                section
            )
            print(f"정규식 매칭 결과: {trade_lines}")

if __name__ == "__main__":
    test_parsing()
