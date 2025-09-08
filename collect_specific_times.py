"""
특정 시간대 분봉 데이터 수집기
09:00:00, 09:00:30, 09:00:50, 09:01:00, 09:01:20 만 정확히 수집
"""
import sys
import os

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.kis_chart_api import get_inquire_time_dailychartprice
from api import kis_auth
import pandas as pd
from datetime import datetime

def collect_specific_times(stock_code: str, target_date: str):
    """특정 시간대만 정확히 수집"""
    
    # KIS API 인증
    print("KIS API 인증 중...")
    try:
        kis_auth.auth()
        print("인증 완료")
    except Exception as e:
        print(f"인증 실패: {e}")
        return None
    
    # 수집하고자 하는 특정 시간들
    target_times = ["090000", "090030", "090050", "090100", "090120"]
    collected_data = []
    
    print(f"\n=== {stock_code} 특정 시간대 수집 ({target_date}) ===")
    
    # 전체 하루 데이터를 먼저 수집
    print("전체 하루 분봉 데이터 수집 중...")
    
    # 여러 시간대로 나누어서 전체 데이터 수집
    time_segments = [
        "100000",  # 10시까지
        "120000",  # 12시까지  
        "140000",  # 14시까지
        "153000"   # 장 마감까지
    ]
    
    all_minute_data = []
    
    for end_time in time_segments:
        try:
            result = get_inquire_time_dailychartprice(
                div_code="J",
                stock_code=stock_code,
                input_date=target_date,
                input_hour=end_time,
                past_data_yn="Y"
            )
            
            if result is not None:
                summary_df, chart_df = result
                if not chart_df.empty:
                    all_minute_data.append(chart_df)
                    print(f"  {end_time}까지: {len(chart_df)}건 수집")
        except Exception as e:
            print(f"  {end_time} 구간 수집 실패: {e}")
            continue
    
    if not all_minute_data:
        print("전체 데이터 수집 실패")
        return None
    
    # 모든 데이터 합치기
    combined_df = pd.concat(all_minute_data, ignore_index=True)
    
    # 중복 제거 (시간 기준)
    if 'time' in combined_df.columns:
        combined_df = combined_df.drop_duplicates(subset=['time']).sort_values('time').reset_index(drop=True)
    
    print(f"전체 수집 데이터: {len(combined_df)}건")
    
    # 특정 시간대만 필터링
    print("\n=== 특정 시간대 필터링 ===")
    
    for target_time in target_times:
        if 'time' in combined_df.columns:
            # 시간 컬럼을 6자리 문자열로 변환하여 비교
            combined_df['time_str'] = combined_df['time'].astype(str).str.zfill(6)
            filtered_data = combined_df[combined_df['time_str'] == target_time]
            
            if not filtered_data.empty:
                data_row = filtered_data.iloc[0]
                collected_data.append({
                    'time': target_time,
                    'date': data_row.get('date', target_date),
                    'open': data_row.get('open', 0),
                    'high': data_row.get('high', 0), 
                    'low': data_row.get('low', 0),
                    'close': data_row.get('close', 0),
                    'volume': data_row.get('volume', 0),
                    'amount': data_row.get('amount', 0)
                })
                
                hour = target_time[:2]
                minute = target_time[2:4]
                second = target_time[4:6]
                print(f"[SUCCESS] {hour}:{minute}:{second} - 종가: {data_row.get('close', 0):,.0f}원, 거래량: {data_row.get('volume', 0):,.0f}주")
            else:
                hour = target_time[:2]
                minute = target_time[2:4] 
                second = target_time[4:6]
                print(f"[NOT FOUND] {hour}:{minute}:{second} - 데이터 없음")
    
    return collected_data

def save_results(stock_code: str, target_date: str, data: list):
    """결과를 파일로 저장"""
    if not data:
        print("저장할 데이터가 없습니다.")
        return
    
    filename = f"{stock_code}_{target_date}_specific_times.txt"
    
    with open(filename, 'w', encoding='utf-8') as f:
        f.write(f"종목코드: {stock_code}\n")
        f.write(f"조회날짜: {target_date}\n")
        f.write(f"수집시각: {datetime.now()}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("특정 시간대 분봉 데이터:\n")
        f.write("09:00:00, 09:00:30, 09:00:50, 09:01:00, 09:01:20\n")
        f.write("=" * 80 + "\n\n")
        
        for i, row in enumerate(data, 1):
            time_str = row['time']
            hour = time_str[:2]
            minute = time_str[2:4]
            second = time_str[4:6]
            
            f.write(f"--- {i}번째: {hour}:{minute}:{second} ---\n")
            f.write(f"  date: {row['date']}\n")
            f.write(f"  time: {row['time']}\n")
            f.write(f"  open: {row['open']}\n")
            f.write(f"  high: {row['high']}\n")
            f.write(f"  low: {row['low']}\n")
            f.write(f"  close: {row['close']}\n")
            f.write(f"  volume: {row['volume']}\n")
            f.write(f"  amount: {row['amount']}\n")
            f.write(f"  datetime: {row['date'][:4]}-{row['date'][4:6]}-{row['date'][6:8]} {hour}:{minute}:{second}\n\n")
    
    print(f"\n결과 저장 완료: {filename}")

if __name__ == "__main__":
    # 테스트 실행
    stock_code = "054540"
    target_date = "20250905"  # 2025년 9월 5일
    
    print(f"특정 시간대 데이터 수집: {stock_code} ({target_date})")
    print("수집 시간: 09:00:00, 09:00:30, 09:00:50, 09:01:00, 09:01:20")
    
    collected_data = collect_specific_times(stock_code, target_date)
    
    if collected_data:
        save_results(stock_code, target_date, collected_data)
        print(f"\n총 {len(collected_data)}개 시간대 데이터 수집 완료")
    else:
        print("데이터 수집 실패")