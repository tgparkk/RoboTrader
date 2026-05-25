"""MarketHours 휴일 인식 회귀 방지 (2026-05-25).

incident: 2026-05-25 석가탄신일(평일 공휴일)에 봇이 분봉 수집 무한 재시도.
원인: MarketHours.is_market_open() 가드가 주말만 차단하고 KOREAN_HOLIDAYS 미체크.
영향:
  - _update_intraday_data 33,798회 호출, "당일 데이터 없음" 폭주
  - 19MB 로그, API rate 압력, 봇 크래시
fix: MarketHours.is_market_open / is_before_market_open 본체에서 KRX KOREAN_HOLIDAYS 차단.
"""
from datetime import datetime

import pytest
import pytz

from config.market_hours import MarketHours, KOREAN_HOLIDAYS

KST = pytz.timezone('Asia/Seoul')


# ---------------------------------------------------------------------------
# 회귀: is_market_open 이 공휴일을 인식해야 한다
# ---------------------------------------------------------------------------

def test_is_market_open_false_on_buddha_birthday():
    """2026-05-25 석가탄신일(월) 09:30 → False (장 안 열림).

    이전 버그: 평일만 체크해서 True 반환 → 분봉 수집 무한 재시도.
    """
    assert '20260525' in KOREAN_HOLIDAYS, 'KOREAN_HOLIDAYS 등록 누락'
    dt = KST.localize(datetime(2026, 5, 25, 9, 30))
    assert MarketHours.is_market_open('KRX', dt) is False


def test_is_market_open_false_on_childrens_day():
    """2026-05-05 어린이날(화) 10:00 → False."""
    assert '20260505' in KOREAN_HOLIDAYS
    dt = KST.localize(datetime(2026, 5, 5, 10, 0))
    assert MarketHours.is_market_open('KRX', dt) is False


def test_is_market_open_true_on_normal_weekday():
    """2026-05-26 화요일(평일 + 비휴일) 10:00 → True."""
    assert '20260526' not in KOREAN_HOLIDAYS
    dt = KST.localize(datetime(2026, 5, 26, 10, 0))
    assert MarketHours.is_market_open('KRX', dt) is True


def test_is_market_open_false_on_weekend():
    """주말 가드 회귀 — 2026-05-23 토요일 → False (기존 동작 유지)."""
    dt = KST.localize(datetime(2026, 5, 23, 10, 0))
    assert MarketHours.is_market_open('KRX', dt) is False


# ---------------------------------------------------------------------------
# 회귀: is_before_market_open 도 공휴일을 인식해야 한다
# ---------------------------------------------------------------------------

def test_is_before_market_open_false_on_holiday():
    """공휴일 08:30 → False (장 자체가 없으므로 'pre-market' 의미 없음)."""
    dt = KST.localize(datetime(2026, 5, 25, 8, 30))
    assert MarketHours.is_before_market_open('KRX', dt) is False


def test_is_before_market_open_true_on_normal_weekday_premarket():
    """정상 평일 08:30 → True (기존 동작 유지)."""
    dt = KST.localize(datetime(2026, 5, 26, 8, 30))
    assert MarketHours.is_before_market_open('KRX', dt) is True


# ---------------------------------------------------------------------------
# 회귀: get_market_status 가 공휴일을 'weekend' 로 분류
# ---------------------------------------------------------------------------

def test_get_market_status_holiday_classified_as_weekend():
    """공휴일 10:00 → 'weekend' (장 안 열린 날을 의미)."""
    dt = KST.localize(datetime(2026, 5, 25, 10, 0))
    assert MarketHours.get_market_status('KRX', dt) == 'weekend'


# ---------------------------------------------------------------------------
# 캘린더 완전성: mom-strategy 1:1 대조로 잡힌 누락 회귀 방지
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('date_str,label', [
    ('20250501', '2025 근로자의 날'),
    ('20250603', '2025 21대 대선'),
    ('20251231', '2025 연말 증시 휴장'),
    ('20260501', '2026 근로자의 날'),
    ('20270501', '2027 근로자의 날 (토 자연차단, 일관성)'),
])
def test_added_holidays_present(date_str, label):
    """mom 캘린더 대조로 발견된 누락 5건 등록 회귀 방지."""
    assert date_str in KOREAN_HOLIDAYS, f'{label} 누락'


def test_is_market_open_false_on_2026_labor_day():
    """2026-05-01 근로자의 날(금) — 평일이지만 KRX 휴장."""
    dt = KST.localize(datetime(2026, 5, 1, 10, 0))
    assert MarketHours.is_market_open('KRX', dt) is False


# ---------------------------------------------------------------------------
# 오등록 정정: 현충일/추석은 특정 조건에서만 대체공휴일 적용
# (관공서의 공휴일에 관한 규정 + KRX 공식 캘린더 검증)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('date_str,label', [
    ('20260608', '현충일은 토요일이어도 대체공휴일 없음 (법적 대체 대상 아님)'),
    ('20270607', '현충일은 일요일이어도 대체공휴일 없음'),
    ('20260928', '추석 대체는 일요일 겹침 시만 — 2026 추석은 목/금/토(일요일 없음)'),
])
def test_incorrectly_registered_holidays_removed(date_str, label):
    """KRX 공식 캘린더 + 법령 대조로 오등록 정정. 회귀 방지."""
    assert date_str not in KOREAN_HOLIDAYS, f'오등록 회귀: {label}'


def test_is_market_open_true_on_2026_06_08():
    """2026-06-08(월) — 6/6 현충일 토요일이지만 대체 없음 → 정상 영업."""
    dt = KST.localize(datetime(2026, 6, 8, 10, 0))
    assert MarketHours.is_market_open('KRX', dt) is True


def test_is_market_open_true_on_2026_09_28():
    """2026-09-28(월) — 추석 9/24-26 중 일요일 없으므로 대체 없음 → 정상 영업."""
    dt = KST.localize(datetime(2026, 9, 28, 10, 0))
    assert MarketHours.is_market_open('KRX', dt) is True
