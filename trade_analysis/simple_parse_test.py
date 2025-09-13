#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
간단한 파싱 테스트
"""

import re

# 실제 거래 라인 예시
trade_line = "    13:33 매수[pullback_pattern] @4,773 → 13:47 매도[stop_loss_3.0pct] @4,630 (-3.00%)"

# 정규식 패턴 테스트
pattern = r'(\d{2}:\d{2})\s+매수\[pullback_pattern\]\s+@([0-9,]+)\s+→\s+(\d{2}:\d{2})\s+매도\[(profit|stop_loss)_([0-9.]+)pct\]\s+@([0-9,]+)\s+([+-][0-9.]+%)'

match = re.search(pattern, trade_line)
if match:
    print("매칭 성공!")
    print(f"매칭 결과: {match.groups()}")
else:
    print("매칭 실패!")
    print(f"원본 라인: {trade_line}")
    
    # 다른 패턴들 시도
    patterns = [
        r'(\d{2}:\d{2})\s+매수\[pullback_pattern\]\s+@([0-9,]+)\s+→\s+(\d{2}:\d{2})\s+매도\[(profit|stop_loss)_([0-9.]+)pct\]\s+@([0-9,]+)\s+([+-][0-9.]+%)',
        r'(\d{2}:\d{2})\s+매수.*?@([0-9,]+)\s+→\s+(\d{2}:\d{2})\s+매도.*?@([0-9,]+)\s+([+-][0-9.]+%)',
        r'(\d{2}:\d{2})\s+매수.*?@([0-9,]+).*?(\d{2}:\d{2})\s+매도.*?@([0-9,]+).*?([+-][0-9.]+%)'
    ]
    
    for i, p in enumerate(patterns):
        match = re.search(p, trade_line)
        if match:
            print(f"패턴 {i+1} 매칭 성공: {match.groups()}")
        else:
            print(f"패턴 {i+1} 매칭 실패")
