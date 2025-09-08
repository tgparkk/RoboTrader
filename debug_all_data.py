"""
각 API 호출의 전체 데이터 확인
"""
import sys
import os
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from api.kis_chart_api import get_inquire_time_itemchartprice
from api import kis_auth

def debug_all_data():
    # KIS API 인증
    print("KIS API 인증 중...")
    kis_auth.auth()
    print("인증 완료")
    
    stock_code = "064820"
    test_times = ["090030", "090150", "090201", "090301", "090401"]
    
    print(f"\n=== {stock_code} 각 API 호출의 전체 데이터 확인 ===")
    
    # 결과 파일 생성
    from datetime import datetime
    output_filename = f"{stock_code}_debug_all_data.txt"
    
    with open(output_filename, 'w', encoding='utf-8') as f:
        f.write(f"종목코드: {stock_code}\n")
        f.write(f"테스트 시간: {test_times}\n")
        f.write(f"실행시각: {datetime.now()}\n")
        f.write("=" * 80 + "\n\n")
        
        f.write("각 API 호출별 누적 데이터 확인\n")
        f.write("stck_bsop_date (주식 영업일자) → date 변환\n")
        f.write("stck_cntg_hour (주식 체결시간) → time 변환\n")
        f.write("=" * 80 + "\n\n")
    
    for i, test_time in enumerate(test_times, 1):
        print(f"\n[{i}] {test_time[:2]}:{test_time[2:4]}:{test_time[4:6]} 조회...")
        
        # 파일에 헤더 저장
        with open(output_filename, 'a', encoding='utf-8') as f:
            f.write(f"\n[{i}] {test_time[:2]}:{test_time[2:4]}:{test_time[4:6]} 조회\n")
        
        try:
            result = get_inquire_time_itemchartprice(
                div_code="J",
                stock_code=stock_code,
                input_hour=test_time,
                past_data_yn="N"
            )
            
            if result is not None:
                summary_df, chart_df = result
                data_count = len(chart_df)
                
                print(f"    총 {data_count}건 수집")
                
                # 파일에 개수 정보 저장
                with open(output_filename, 'a', encoding='utf-8') as f:
                    f.write(f"    총 {data_count}건 수집\n")
                
                if not chart_df.empty:
                    # 컬럼 매핑
                    column_mapping = {
                        'stck_bsop_date': 'date',
                        'stck_cntg_hour': 'time',
                        'stck_prpr': 'close',
                        'stck_oprc': 'open',
                        'stck_hgpr': 'high',
                        'stck_lwpr': 'low',
                        'cntg_vol': 'volume',
                        'acml_tr_pbmn': 'amount'
                    }
                    
                    processed_df = chart_df.copy()
                    existing_columns = {k: v for k, v in column_mapping.items() if k in processed_df.columns}
                    if existing_columns:
                        processed_df = processed_df.rename(columns=existing_columns)
                    
                    # 전체 데이터 출력 (원본 필드 + 변환 필드)
                    for j, (idx, orig_row) in enumerate(chart_df.iterrows()):
                        proc_row = processed_df.iloc[j]
                        
                        # 원본 KIS API 필드
                        orig_date = orig_row.get('date', 'N/A')
                        orig_time = str(orig_row.get('time', 'N/A')).zfill(6)
                        
                        # 변환된 필드
                        time_val = str(proc_row.get('time', 'N/A')).zfill(6)
                        close_val = proc_row.get('close', 0)
                        volume_val = proc_row.get('volume', 0)
                        
                        print(f"      [{j+1}] {time_val[:2]}:{time_val[2:4]}:{time_val[4:6]}")
                        print(f"          원본: stck_bsop_date={orig_date}, stck_cntg_hour={orig_time}")
                        print(f"          변환: date={proc_row.get('date', 'N/A')}, time={time_val}")
                        print(f"          가격: {close_val:,.0f}원, 거래량: {volume_val:,.0f}주")
                        
                        # 파일에도 저장
                        with open(output_filename, 'a', encoding='utf-8') as f:
                            f.write(f"      [{j+1}] {time_val[:2]}:{time_val[2:4]}:{time_val[4:6]}\n")
                            f.write(f"          원본: stck_bsop_date={orig_date}, stck_cntg_hour={orig_time}\n")
                            f.write(f"          변환: date={proc_row.get('date', 'N/A')}, time={time_val}\n")
                            f.write(f"          가격: {close_val:,.0f}원, 거래량: {volume_val:,.0f}주\n\n")
                    
        except Exception as e:
            print(f"    오류: {e}")
            
            # 오류도 파일에 저장
            with open(output_filename, 'a', encoding='utf-8') as f:
                f.write(f"    오류: {e}\n")
    
    print(f"\n결과 파일 저장 완료: {output_filename}")

if __name__ == "__main__":
    debug_all_data()