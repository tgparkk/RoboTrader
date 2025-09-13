#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
분봉 데이터를 기반으로 일봉 데이터를 생성하는 스크립트
"""

import os
import pickle
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import glob

class DailyDataGenerator:
    """일봉 데이터 생성 클래스"""
    
    def __init__(self, minute_data_dir: str, daily_data_dir: str):
        self.minute_data_dir = minute_data_dir
        self.daily_data_dir = daily_data_dir
        
        # daily_data 디렉토리 생성
        os.makedirs(daily_data_dir, exist_ok=True)
    
    def load_minute_data(self, stock_code: str, date: str):
        """특정 종목의 특정 날짜 분봉 데이터 로드"""
        cache_file = os.path.join(self.minute_data_dir, f"{stock_code}_{date}.pkl")
        
        if not os.path.exists(cache_file):
            return None
        
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)
            
            if isinstance(data, pd.DataFrame):
                return data
            else:
                return pd.DataFrame(data)
                
        except Exception as e:
            print(f"데이터 로드 실패 {cache_file}: {e}")
            return None
    
    def convert_minute_to_daily(self, minute_data):
        """분봉 데이터를 일봉 데이터로 변환"""
        if minute_data.empty:
            return None
        
        # datetime 컬럼이 있는지 확인
        if 'datetime' in minute_data.columns:
            minute_data['datetime_converted'] = pd.to_datetime(minute_data['datetime'])
        else:
            # time과 date 컬럼을 합쳐서 datetime 생성
            minute_data['datetime_converted'] = pd.to_datetime(
                minute_data['date'].astype(str) + minute_data['time'].astype(str), 
                format='%Y%m%d%H%M%S'
            )
        
        # 날짜별로 그룹화
        minute_data['date_only'] = minute_data['datetime_converted'].dt.date
        
        # 일봉 데이터 생성
        daily_data = minute_data.groupby('date_only').agg({
            'open': 'first',
            'high': 'max',
            'low': 'min',
            'close': 'last',
            'volume': 'sum',
            'amount': 'sum'
        }).reset_index()
        
        # 날짜 형식 변환
        daily_data['date'] = daily_data['date_only'].apply(lambda x: x.strftime('%Y%m%d'))
        
        # 컬럼 순서 정리
        daily_data = daily_data[['date', 'open', 'high', 'low', 'close', 'volume', 'amount']]
        
        return daily_data.sort_values('date').reset_index(drop=True)
    
    def generate_daily_data_for_stock(self, stock_code: str, days_back: int = 30):
        """특정 종목의 일봉 데이터 생성"""
        print(f"\n{stock_code} 종목 일봉 데이터 생성 중...")
        
        # 해당 종목의 모든 분봉 파일 찾기
        pattern = os.path.join(self.minute_data_dir, f"{stock_code}_*.pkl")
        minute_files = glob.glob(pattern)
        
        if not minute_files:
            print(f"  {stock_code}: 분봉 데이터 파일이 없습니다.")
            return
        
        # 날짜별로 정렬
        minute_files.sort()
        
        # 최근 날짜부터 역순으로 처리
        all_minute_data = []
        processed_dates = set()
        
        for file_path in minute_files[-days_back:]:  # 최근 days_back개 파일만 처리
            filename = os.path.basename(file_path)
            date_str = filename.split('_')[1].replace('.pkl', '')
            
            if date_str in processed_dates:
                continue
            
            minute_data = self.load_minute_data(stock_code, date_str)
            if minute_data is not None and not minute_data.empty:
                all_minute_data.append(minute_data)
                processed_dates.add(date_str)
        
        if not all_minute_data:
            print(f"  {stock_code}: 유효한 분봉 데이터가 없습니다.")
            return
        
        # 모든 분봉 데이터 합치기
        combined_minute_data = pd.concat(all_minute_data, ignore_index=True)
        
        # 일봉 데이터로 변환
        daily_data = self.convert_minute_to_daily(combined_minute_data)
        
        if daily_data is None or daily_data.empty:
            print(f"  {stock_code}: 일봉 데이터 변환 실패")
            return
        
        # 일봉 데이터 저장
        daily_file = os.path.join(self.daily_data_dir, f"{stock_code}_daily.pkl")
        with open(daily_file, 'wb') as f:
            pickle.dump(daily_data, f)
        
        print(f"  {stock_code}: {len(daily_data)}일 일봉 데이터 저장 완료")
        return daily_data
    
    def generate_all_daily_data(self, days_back: int = 30):
        """모든 종목의 일봉 데이터 생성"""
        print("일봉 데이터 생성 시작...")
        
        # 모든 분봉 파일에서 종목 코드 추출
        pattern = os.path.join(self.minute_data_dir, "*_*.pkl")
        all_files = glob.glob(pattern)
        
        # 종목 코드 추출
        stock_codes = set()
        for file_path in all_files:
            filename = os.path.basename(file_path)
            stock_code = filename.split('_')[0]
            stock_codes.add(stock_code)
        
        stock_codes = sorted(list(stock_codes))
        print(f"총 {len(stock_codes)}개 종목 발견")
        
        # 각 종목별로 일봉 데이터 생성
        success_count = 0
        for i, stock_code in enumerate(stock_codes):
            print(f"진행률: {i+1}/{len(stock_codes)} - {stock_code}")
            try:
                daily_data = self.generate_daily_data_for_stock(stock_code, days_back)
                if daily_data is not None:
                    success_count += 1
            except Exception as e:
                print(f"  {stock_code}: 오류 발생 - {e}")
        
        print(f"\n일봉 데이터 생성 완료: {success_count}/{len(stock_codes)}개 종목")
    
    def load_daily_data(self, stock_code: str):
        """생성된 일봉 데이터 로드"""
        daily_file = os.path.join(self.daily_data_dir, f"{stock_code}_daily.pkl")
        
        if not os.path.exists(daily_file):
            return None
        
        try:
            with open(daily_file, 'rb') as f:
                data = pickle.load(f)
            return data
        except Exception as e:
            print(f"일봉 데이터 로드 실패 {daily_file}: {e}")
            return None
    
    def get_trading_dates(self, stock_code: str, start_date: str, end_date: str):
        """특정 기간의 거래일 데이터 반환"""
        daily_data = self.load_daily_data(stock_code)
        
        if daily_data is None:
            return None
        
        # 날짜 필터링
        mask = (daily_data['date'] >= start_date) & (daily_data['date'] <= end_date)
        filtered_data = daily_data[mask].copy()
        
        return filtered_data.sort_values('date').reset_index(drop=True)

def main():
    """메인 실행 함수"""
    minute_data_dir = r"C:\GIT\RoboTrader\cache\minute_data"
    daily_data_dir = r"C:\GIT\RoboTrader\cache\daily_data"
    
    generator = DailyDataGenerator(minute_data_dir, daily_data_dir)
    
    # 일봉 데이터 생성 (최근 30일)
    generator.generate_all_daily_data(days_back=30)
    
    # 테스트: 특정 종목의 일봉 데이터 확인
    test_stock = "007820"
    daily_data = generator.load_daily_data(test_stock)
    
    if daily_data is not None:
        print(f"\n{test_stock} 일봉 데이터 샘플:")
        print(daily_data.head())
        print(f"총 {len(daily_data)}일 데이터")
    else:
        print(f"{test_stock} 일봉 데이터를 찾을 수 없습니다.")

if __name__ == "__main__":
    main()
