"""
데이터 품질 검사 모듈

IntradayStockManager에서 분리된 데이터 품질 검사 로직
"""
import pandas as pd
from typing import Dict, List, Any

from utils.logger import setup_logger
from utils.korean_time import now_kst
from core.intraday_data_utils import validate_today_data
from config.market_hours import MarketHours


class DataQualityChecker:
    """
    데이터 품질 검사 담당 클래스

    책임:
    - 실시간 데이터 품질 검사
    - 당일 데이터 검증
    - 데이터 연속성 확인
    """

    def __init__(self, manager):
        """
        초기화

        Args:
            manager: IntradayStockManager 인스턴스 (의존성 주입)
        """
        self.manager = manager
        self.logger = manager.logger
        self._lock = manager._lock

    def check_data_quality(self, stock_code: str) -> Dict[str, Any]:
        """실시간 데이터 품질 검사"""
        try:
            with self._lock:
                stock_data = self.manager.selected_stocks.get(stock_code)

            if not stock_data:
                return {'has_issues': True, 'issues': ['데이터 없음']}

            # historical_data와 realtime_data를 합쳐서 전체 분봉 데이터 생성
            all_data = pd.concat([stock_data.historical_data, stock_data.realtime_data], ignore_index=True)
            if all_data.empty:
                return {'has_issues': True, 'issues': ['데이터 없음']}

            # 당일 데이터만 필터링 (품질 검사 전 최우선)
            today_str = now_kst().strftime('%Y%m%d')
            before_filter_count = len(all_data)

            if 'date' in all_data.columns:
                all_data = all_data[all_data['date'].astype(str) == today_str].copy()
            elif 'datetime' in all_data.columns:
                all_data['date_str'] = pd.to_datetime(all_data['datetime']).dt.strftime('%Y%m%d')
                all_data = all_data[all_data['date_str'] == today_str].copy()
                if 'date_str' in all_data.columns:
                    all_data = all_data.drop('date_str', axis=1)

            if all_data.empty:
                return {'has_issues': True, 'issues': ['당일 데이터 없음']}

            # 시간순 정렬 및 중복 제거
            if 'time' in all_data.columns:
                all_data = all_data.drop_duplicates(subset=['time'], keep='last').sort_values('time').reset_index(drop=True)
            elif 'datetime' in all_data.columns:
                all_data = all_data.drop_duplicates(subset=['datetime'], keep='last').sort_values('datetime').reset_index(drop=True)

            issues = []
            data = all_data.to_dict('records')

            # 1. 데이터 양 검사 (최소 5개 이상)
            if len(data) < 5:
                issues.append(f'데이터 부족 ({len(data)}개)')

            # 2. 시간 순서 및 연속성 검사
            time_issues = self._check_time_continuity(data)
            issues.extend(time_issues)

            # 3. 가격 이상치 검사 (최근 데이터 기준)
            price_issues = self._check_price_anomaly(data)
            issues.extend(price_issues)

            # 4. 데이터 지연 검사 (최신 데이터가 5분 이상 오래된 경우)
            delay_issues = self._check_data_delay(data)
            issues.extend(delay_issues)

            # 5. 당일 날짜 검증
            date_issues = validate_today_data(all_data)
            if date_issues:
                issues.extend(date_issues)

            return {'has_issues': bool(issues), 'issues': issues}

        except Exception as e:
            return {'has_issues': True, 'issues': [f'품질검사 오류: {str(e)[:30]}']}

    def _check_time_continuity(self, data: List[Dict]) -> List[str]:
        """시간 순서 및 연속성 검사 (장 시작 갭 포함)"""
        issues = []

        if len(data) >= 2:
            times = [row['time'] for row in data]

            # 장 시작 시간 대비 첫 캔들 갭 확인
            try:
                first_time_str = str(times[0]).zfill(6)
                first_hour = int(first_time_str[:2])
                first_min = int(first_time_str[2:4])

                current_time = now_kst()
                market_hours = MarketHours.get_market_hours('KRX', current_time)
                market_open = market_hours['market_open']

                if first_hour == market_open.hour and first_min > market_open.minute + 5:
                    open_str = f'{market_open.hour:02d}{market_open.minute:02d}00'
                    issues.append(f'분봉 누락: {open_str}->{first_time_str}')
                    return issues  # 장 시작 갭 → 즉시 반환하여 재수집 트리거
            except Exception:
                pass

            # 순서 확인
            if times != sorted(times):
                issues.append('시간 순서 오류')

            # 1분 간격 연속성 확인 (중간 누락 감지)
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
                        issues.append(f'분봉 누락: {prev_time_str}->{curr_time_str}')
                        break  # 첫 번째 누락만 보고
                except Exception:
                    pass

        return issues

    def _check_price_anomaly(self, data: List[Dict]) -> List[str]:
        """가격 이상치 검사"""
        issues = []

        if len(data) >= 2:
            current_price = data[-1].get('close', 0)
            prev_price = data[-2].get('close', 0)

            if current_price > 0 and prev_price > 0:
                price_change = abs(current_price - prev_price) / prev_price
                if price_change > 0.3:  # 30% 이상 변동시 이상치로 판단
                    issues.append(f'가격 급변동 ({price_change*100:.1f}%)')

        return issues

    def _check_data_delay(self, data: List[Dict]) -> List[str]:
        """데이터 지연 검사 (최신 데이터가 5분 이상 오래된 경우)"""
        issues = []

        if data:
            latest_time_str = str(data[-1].get('time', '000000')).zfill(6)
            current_time = now_kst()

            try:
                latest_hour = int(latest_time_str[:2])
                latest_minute = int(latest_time_str[2:4])
                latest_time = current_time.replace(hour=latest_hour, minute=latest_minute, second=0, microsecond=0)

                time_diff = (current_time - latest_time).total_seconds()
                if time_diff > 300:  # 5분 이상 지연
                    issues.append(f'데이터 지연 ({time_diff/60:.1f}분)')
            except Exception:
                issues.append('시간 파싱 오류')

        return issues
