"""
한국 시간 관련 유틸리티
"""
from datetime import datetime, time
import pytz


KST = pytz.timezone('Asia/Seoul')


def now_kst() -> datetime:
    """현재 한국 시간 반환"""
    return datetime.now(KST)


def is_market_open(dt: datetime = None) -> bool:
    """장중 시간인지 확인"""
    if dt is None:
        dt = now_kst()
    
    # 평일만 확인 (월-금)
    if dt.weekday() >= 5:  # 토요일(5), 일요일(6)
        return False
    
    market_open = time(9, 0)    # 09:00
    market_close = time(15, 30) # 15:30
    
    current_time = dt.time()
    return market_open <= current_time <= market_close


def is_before_market_open(dt: datetime = None) -> bool:
    """장 시작 전인지 확인"""
    if dt is None:
        dt = now_kst()
    
    # 평일이 아니면 False
    if dt.weekday() >= 5:
        return False
    
    market_open = time(9, 0)
    current_time = dt.time()
    return current_time < market_open


def get_market_status() -> str:
    """시장 상태 반환"""
    now = now_kst()
    
    if now.weekday() >= 5:
        return "weekend"
    elif is_before_market_open(now):
        return "pre_market"
    elif is_market_open(now):
        return "market_open"
    else:
        return "after_market"