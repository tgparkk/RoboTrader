"""
데이터 검증 로직
"""
from typing import List, Optional
import pandas as pd

from utils.logger import setup_logger
from utils.korean_time import now_kst


class DataValidator:
    """
    분봉 데이터 검증 클래스
    
    연속성, 품질, 당일 데이터 검증
    """
    
    def __init__(self):
        self.logger = setup_logger(__name__)
    
    def validate_minute_data_continuity(self, data: pd.DataFrame, stock_code: str) -> dict:
        """
        1분봉 데이터 연속성 검증
        
        09:00부터 순서대로 1분 간격으로 데이터가 있는지 확인
        
        Args:
            data: 1분봉 DataFrame
            stock_code: 종목코드 (로깅용)
            
        Returns:
            dict: {'valid': bool, 'reason': str, 'missing_times': list}
        """
        try:
            if data.empty:
                return {'valid': False, 'reason': '데이터 없음', 'missing_times': []}
            
            # datetime 컬럼 확인 및 변환
            if 'datetime' in data.columns:
                data_copy = data.copy()
                data_copy['datetime'] = pd.to_datetime(data_copy['datetime'])
                
                # 첫 봉이 09:00인지 확인
                first_time = data_copy['datetime'].iloc[0]
                if first_time.hour != 9 or first_time.minute != 0:
                    return {
                        'valid': False,
                        'reason': f'첫 봉이 09:00 아님 (실제: {first_time.strftime("%H:%M")})',
                        'missing_times': []
                    }
                
                # 각 봉 사이의 시간 간격 계산 (초 단위)
                time_diffs = data_copy['datetime'].diff().dt.total_seconds().fillna(0)
                
                # 1분봉이므로 간격이 정확히 60초여야 함 (첫 봉은 0이므로 제외)
                invalid_gaps = time_diffs[1:][(time_diffs[1:] != 60.0) & (time_diffs[1:] != 0.0)]
                
                if len(invalid_gaps) > 0:
                    # 불연속 구간 발견
                    gap_indices = invalid_gaps.index.tolist()
                    missing_times = []
                    for idx in gap_indices[:5]:  # 최대 5개만 표시
                        prev_time = data_copy.loc[idx-1, 'datetime']
                        curr_time = data_copy.loc[idx, 'datetime']
                        gap_minutes = int(time_diffs[idx] / 60)
                        missing_times.append(f"{prev_time.strftime('%H:%M')}→{curr_time.strftime('%H:%M')} ({gap_minutes}분 간격)")
                    
                    return {
                        'valid': False,
                        'reason': f'불연속 구간 {len(invalid_gaps)}개 발견',
                        'missing_times': missing_times
                    }
                
                # 모든 검증 통과
                return {'valid': True, 'reason': 'OK', 'missing_times': []}
            
            elif 'time' in data.columns:
                # time 컬럼 기반 검증
                data_copy = data.copy()
                data_copy['time_int'] = data_copy['time'].astype(str).str.zfill(6).str[:4].astype(int)
                
                # 첫 봉이 0900인지 확인
                if data_copy['time_int'].iloc[0] != 900:
                    return {
                        'valid': False,
                        'reason': f'첫 봉이 09:00 아님 (실제: {data_copy["time_int"].iloc[0]})',
                        'missing_times': []
                    }
                
                # 시간 간격 계산
                time_diffs = data_copy['time_int'].diff().fillna(0)
                
                # 1분 간격 (0900→0901=1, 0959→1000=41 등 처리 필요)
                invalid_gaps = []
                missing_times = []
                
                for i in range(1, len(data_copy)):
                    prev_time = data_copy['time_int'].iloc[i-1]
                    curr_time = data_copy['time_int'].iloc[i]
                    
                    # 예상 다음 시간 계산
                    prev_hour = prev_time // 100
                    prev_min = prev_time % 100
                    
                    if prev_min == 59:
                        expected_next = (prev_hour + 1) * 100
                    else:
                        expected_next = prev_time + 1
                    
                    if curr_time != expected_next:
                        invalid_gaps.append(i)
                        if len(missing_times) < 5:
                            missing_times.append(f"{prev_time:04d}→{curr_time:04d}")
                
                if invalid_gaps:
                    return {
                        'valid': False,
                        'reason': f'불연속 구간 {len(invalid_gaps)}개 발견',
                        'missing_times': missing_times
                    }
                
                return {'valid': True, 'reason': 'OK', 'missing_times': []}
            
            else:
                # 시간 컬럼이 없으면 검증 불가
                return {'valid': True, 'reason': '시간컬럼없음(검증생략)', 'missing_times': []}
        
        except Exception as e:
            self.logger.error(f"❌ {stock_code} 연속성 검증 오류: {e}")
            return {'valid': True, 'reason': f'검증오류(통과처리): {str(e)}', 'missing_times': []}
    
    def check_sufficient_base_data(self, combined_data: Optional[pd.DataFrame], stock_code: str) -> bool:
        """
        09시부터 분봉 데이터가 충분한지 간단 체크
        
        Args:
            combined_data: 결합된 차트 데이터
            stock_code: 종목코드 (로깅용)
            
        Returns:
            bool: 기본 데이터 충분 여부
        """
        try:
            if combined_data is None or combined_data.empty:
                self.logger.debug(f"❌ {stock_code} 데이터 없음")
                return False
            
            # 1. 당일 데이터인지 먼저 확인
            today_str = now_kst().strftime('%Y%m%d')
            
            # date 컬럼으로 당일 데이터만 필터링
            if 'date' in combined_data.columns:
                today_data = combined_data[combined_data['date'].astype(str) == today_str].copy()
                if today_data.empty:
                    self.logger.debug(f"❌ {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                    return False
                combined_data = today_data
            elif 'datetime' in combined_data.columns:
                try:
                    combined_data['date_str'] = pd.to_datetime(combined_data['datetime']).dt.strftime('%Y%m%d')
                    today_data = combined_data[combined_data['date_str'] == today_str].copy()
                    if today_data.empty:
                        self.logger.debug(f"❌ {stock_code} 당일 데이터 없음 (전일 데이터만 존재)")
                        return False
                    combined_data = today_data.drop('date_str', axis=1)
                except Exception:
                    pass
            
            data_count = len(combined_data)
            
            # 최소 데이터 개수 체크 (3분봉 최소 5개 = 15분봉 필요)
            if data_count < 5:
                self.logger.debug(f"❌ {stock_code} 데이터 부족: {data_count}/15")
                return False
            
            # 시작 시간 체크 (09:00대 시작 확인)
            if 'time' in combined_data.columns:
                start_time_str = str(combined_data.iloc[0]['time']).zfill(6)
                start_hour = int(start_time_str[:2])
                
                # 09시 시작 확인
                if start_hour != 9:
                    self.logger.debug(f"❌ {stock_code} 시작 시간 문제: {start_time_str} (09시 아님)")
                    return False
            
            elif 'datetime' in combined_data.columns:
                start_dt = combined_data.iloc[0]['datetime']
                if hasattr(start_dt, 'hour'):
                    start_hour = start_dt.hour
                    # 09시 시작 확인
                    if start_hour != 9:
                        self.logger.debug(f"❌ {stock_code} 시작 시간 문제: {start_hour}시 (09시 아님)")
                        return False
            
            return True
        
        except Exception as e:
            self.logger.warning(f"⚠️ {stock_code} 기본 데이터 체크 오류: {e}")
            return False
    
    def check_data_quality(self, stock_code: str, all_data: pd.DataFrame) -> dict:
        """
        실시간 데이터 품질 검사
        
        Args:
            stock_code: 종목코드
            all_data: 전체 분봉 데이터 (historical + realtime)
            
        Returns:
            dict: {'has_issues': bool, 'issues': List[str], 'missing_times': List[str]}
        """
        try:
            if all_data.empty:
                return {'has_issues': True, 'issues': ['데이터 없음'], 'missing_times': []}
            
            # 🆕 당일 데이터만 필터링 (전일 데이터 제외)
            today_str = now_kst().strftime('%Y%m%d')
            
            if 'date' in all_data.columns:
                all_data = all_data[all_data['date'].astype(str) == today_str].copy()
            elif 'datetime' in all_data.columns:
                try:
                    all_data['date_str'] = pd.to_datetime(all_data['datetime']).dt.strftime('%Y%m%d')
                    all_data = all_data[all_data['date_str'] == today_str].copy()
                    all_data = all_data.drop('date_str', axis=1)
                except Exception:
                    pass
            
            if all_data.empty:
                return {'has_issues': True, 'issues': ['당일 데이터 없음'], 'missing_times': []}
            
            issues = []
            missing_times = []
            
            # DataFrame을 dict 형태로 변환하여 기존 로직과 호환
            data = all_data.to_dict('records')
            
            # 1. 데이터 양 검사 (최소 5개 이상)
            if len(data) < 5:
                issues.append(f'데이터 부족 ({len(data)}개)')
            
            # 2. 거래량 체크 (HTS에도 데이터가 없는 경우 감지) - 먼저 체크
            total_volume = sum(row.get('volume', 0) for row in data)
            avg_volume = total_volume / len(data) if len(data) > 0 else 0
            is_low_volume = avg_volume < 1000  # 평균 거래량이 1000주 미만이면 거래 거의 없음
            
            # 3. 시간 순서 및 연속성 검사 (거래량이 정상인 경우만)
            if len(data) >= 2 and not is_low_volume:
                times = [row['time'] for row in data]
                # 순서 확인
                if times != sorted(times):
                    issues.append('시간 순서 오류')
                
                # 🆕 1분 간격 연속성 확인 (중간 누락 감지)
                for i in range(1, len(times)):
                    try:
                        prev_time_str = str(times[i-1]).zfill(6)
                        curr_time_str = str(times[i]).zfill(6)
                        
                        prev_hour = int(prev_time_str[:2])
                        prev_min = int(prev_time_str[2:4])
                        curr_hour = int(curr_time_str[:2])
                        curr_min = int(curr_time_str[2:4])
                        
                        # 예상 다음 시간 계산
                        if prev_min == 59:
                            expected_hour = prev_hour + 1
                            expected_min = 0
                        else:
                            expected_hour = prev_hour
                            expected_min = prev_min + 1
                        
                        # 1분 간격이 아니면 누락
                        if curr_hour != expected_hour or curr_min != expected_min:
                            # 🆕 15:18 이후 누락은 장 마감 후라 정상 (체크 생략)
                            prev_time_int = prev_hour * 100 + prev_min
                            if prev_time_int >= 1518:
                                break  # 15:18 이후는 체크 안함
                            
                            # 누락된 시간들을 모두 수집
                            check_hour, check_min = expected_hour, expected_min
                            while check_hour < curr_hour or (check_hour == curr_hour and check_min < curr_min):
                                missing_time_str = f"{check_hour:02d}{check_min:02d}00"
                                missing_times.append(missing_time_str)
                                
                                # 다음 분으로 이동
                                if check_min == 59:
                                    check_hour += 1
                                    check_min = 0
                                else:
                                    check_min += 1
                                
                                # 무한 루프 방지 (최대 60분봉까지만)
                                if len(missing_times) > 60:
                                    break
                            
                            # 1개 누락은 HTS 자체에 데이터 없을 가능성 - 경고만
                            # 2개 이상 연속 누락은 3분봉 생성에 영향 - 이슈로 보고
                            missing_count = len(missing_times)
                            if missing_count == 1:
                                self.logger.debug(f"{stock_code} 소규모 분봉 누락(1개): {prev_time_str}→{curr_time_str} (HTS 데이터 없음 가능)")
                            else:
                                # 2개 이상 누락은 매매 제한 필요
                                issues.append(f'분봉 누락: {prev_time_str}→{curr_time_str} ({missing_count}개)')
                            break  # 첫 번째 누락 구간만 보고
                    except Exception:
                        pass
            
            # 4. 가격 이상치 검사 (최근 데이터 기준)
            if len(data) >= 2:
                current_price = data[-1].get('close', 0)
                prev_price = data[-2].get('close', 0)
                
                if current_price > 0 and prev_price > 0:
                    price_change = abs(current_price - prev_price) / prev_price
                    if price_change > 0.3:  # 30% 이상 변동시 이상치로 판단
                        issues.append(f'가격 급변동 ({price_change*100:.1f}%)')
            
            # 5. 데이터 지연 검사 (15:18까지 데이터가 있으면 정상, 거래량 없으면 정상)
            if data and not is_low_volume:  # 거래량이 정상인 경우만 지연 체크
                latest_time_str = str(data[-1].get('time', '000000')).zfill(6)
                current_time = now_kst()
                
                try:
                    latest_hour = int(latest_time_str[:2])
                    latest_minute = int(latest_time_str[2:4])
                    latest_time_int = latest_hour * 100 + latest_minute
                    
                    # 15:18 이상이면 정상 (장 마감 시간 고려)
                    if latest_time_int >= 1518:
                        pass  # 정상 데이터
                    else:
                        # 15:18 이전이면 현재 시간과 비교
                        latest_time = current_time.replace(hour=latest_hour, minute=latest_minute, second=0, microsecond=0)
                        time_diff = (current_time - latest_time).total_seconds()
                        if time_diff > 300:  # 5분 이상 지연
                            issues.append(f'데이터 지연 ({time_diff/60:.1f}분)')
                except Exception:
                    issues.append('시간 파싱 오류')
            elif is_low_volume:
                # 거래량이 매우 적은 경우 (HTS에도 데이터 없을 가능성)
                self.logger.debug(f"{stock_code} 거래량 매우 적음 (평균 {avg_volume:.0f}주) - 데이터 지연 체크 생략")
            
            # 6. 당일 날짜 검증
            date_issues = self.validate_today_data(all_data)
            if date_issues:
                issues.extend(date_issues)
            
            return {
                'has_issues': bool(issues),
                'issues': issues,
                'missing_times': missing_times
            }
        
        except Exception as e:
            return {'has_issues': True, 'issues': [f'품질검사 오류: {str(e)[:30]}'], 'missing_times': []}
    
    def validate_today_data(self, data: pd.DataFrame) -> List[str]:
        """
        당일 데이터인지 검증
        
        Args:
            data: 분봉 데이터
            
        Returns:
            List[str]: 검증 이슈 목록
        """
        issues = []
        
        try:
            today_str = now_kst().strftime('%Y%m%d')
            
            # 1. date 컬럼이 있는 경우 (YYYYMMDD 형태)
            if 'date' in data.columns:
                unique_dates = data['date'].unique()
                wrong_dates = [d for d in unique_dates if str(d) != today_str]
                if wrong_dates:
                    issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')
            
            # 2. datetime 컬럼이 있는 경우
            elif 'datetime' in data.columns:
                # datetime 컬럼에서 날짜 추출
                try:
                    data_dates = pd.to_datetime(data['datetime']).dt.strftime('%Y%m%d').unique()
                    wrong_dates = [d for d in data_dates if d != today_str]
                    if wrong_dates:
                        issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')
                except Exception:
                    # datetime 파싱 실패시 무시
                    pass
            
            # 3. stck_bsop_date 컬럼이 있는 경우 (KIS API 응답)
            elif 'stck_bsop_date' in data.columns:
                unique_dates = data['stck_bsop_date'].unique()
                wrong_dates = [d for d in unique_dates if str(d) != today_str]
                if wrong_dates:
                    issues.append(f'다른 날짜 데이터 포함: {wrong_dates[:3]}')
        
        except Exception as e:
            issues.append(f'날짜 검증 오류: {str(e)[:30]}')
        
        return issues

