"""KIS chk-holiday 동기화 유닛 테스트 (네트워크 호출 금지 — fetch_fn/mock 주입).

테스트 항목:
1. get_chk_holiday 파싱: isOK=True → list 반환, 실패 시 None.
2. sync_today + fetch_fn 주입 → is_kis_closed_day 판정.
3. 하루 1회 가드 + 페이지네이션 (2페이지 누적).
4. fallback: fetch_fn 실패 → False, 기존 set 보존, 예외 전파 안 함.
5. 게이트 통합: _runtime_closed 주입 후 MarketHours.is_trading_day 판정.
"""
from datetime import date, datetime
from unittest.mock import MagicMock

import pytest
import pytz

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rows(pairs):
    """[(bass_dt, opnd_yn), ...] → API 응답 행 리스트."""
    return [{"bass_dt": bd, "opnd_yn": oy, "bzdy_yn": "N" if oy == "N" else "Y"}
            for bd, oy in pairs]


def _page1_rows():
    """1페이지: 20260603=N(휴장), 나머지 Y."""
    rows = []
    for i in range(24):
        bd = f"2026060{3 + i}" if 3 + i <= 9 else f"202606{3 + i}"
        # 간단히 첫 번째만 N
        rows.append({"bass_dt": f"20260{603 + i:03d}"[:8] if False else
                     (datetime(2026, 6, 3) + __import__('datetime').timedelta(days=i))
                     .strftime("%Y%m%d"),
                     "opnd_yn": "N" if i == 0 else "Y",
                     "bzdy_yn": "Y"})
    return rows


def _make_page(start_date: date, closed_indices=()):
    """start_date 기준 24일치 rows 생성. closed_indices의 i번 행은 opnd_yn='N'."""
    from datetime import timedelta
    rows = []
    for i in range(24):
        d = start_date + timedelta(days=i)
        rows.append({"bass_dt": d.strftime("%Y%m%d"),
                     "opnd_yn": "N" if i in closed_indices else "Y",
                     "bzdy_yn": "Y"})
    return rows


# ---------------------------------------------------------------------------
# 1. get_chk_holiday 파싱
# ---------------------------------------------------------------------------

class TestGetChkHoliday:
    def test_returns_list_on_ok(self, monkeypatch):
        """isOK=True, output=24행 샘플 → list 반환."""
        import api.kis_auth as kis_auth_mod
        sample_rows = _make_page(date(2026, 6, 3), closed_indices=(0,))

        mock_body = MagicMock()
        mock_body.output = sample_rows
        mock_resp = MagicMock()
        mock_resp.isOK.return_value = True
        mock_resp.getBody.return_value = mock_body

        monkeypatch.setattr(kis_auth_mod, "_url_fetch", lambda *a, **kw: mock_resp)

        from api.kis_market_api import get_chk_holiday
        result = get_chk_holiday("20260603")
        assert isinstance(result, list)
        assert len(result) == 24
        assert result[0]["bass_dt"] == "20260603"

    def test_returns_none_on_failure(self, monkeypatch):
        """isOK=False → None 반환."""
        import api.kis_auth as kis_auth_mod
        mock_resp = MagicMock()
        mock_resp.isOK.return_value = False
        monkeypatch.setattr(kis_auth_mod, "_url_fetch", lambda *a, **kw: mock_resp)

        from api.kis_market_api import get_chk_holiday
        result = get_chk_holiday("20260603")
        assert result is None

    def test_returns_none_when_fetch_returns_none(self, monkeypatch):
        """_url_fetch가 None 반환 → None."""
        import api.kis_auth as kis_auth_mod
        monkeypatch.setattr(kis_auth_mod, "_url_fetch", lambda *a, **kw: None)

        from api.kis_market_api import get_chk_holiday
        result = get_chk_holiday("20260603")
        assert result is None


# ---------------------------------------------------------------------------
# 2. sync_today + fetch_fn 주입 → is_kis_closed_day 판정
# ---------------------------------------------------------------------------

class TestSyncToday:
    def setup_method(self):
        """각 테스트 전 모듈 상태 초기화."""
        import utils.holiday_kis_sync as m
        m._runtime_closed = set()
        m._synced_date = None

    def test_closed_day_detected(self, tmp_path, monkeypatch):
        """20260603=N → is_kis_closed_day(date(2026,6,3)) True."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page = _make_page(date(2026, 6, 3), closed_indices=(0,))  # index 0 = 20260603
        fetch_fn = MagicMock(return_value=page)

        result = m.sync_today(today=date(2026, 6, 3), fetch_fn=fetch_fn, pages=1)
        assert result is True
        assert m.is_kis_closed_day(date(2026, 6, 3)) is True

    def test_open_day_not_detected(self, tmp_path, monkeypatch):
        """20260604=Y → is_kis_closed_day(date(2026,6,4)) False."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page = _make_page(date(2026, 6, 3), closed_indices=(0,))  # only index 0 closed
        fetch_fn = MagicMock(return_value=page)

        m.sync_today(today=date(2026, 6, 3), fetch_fn=fetch_fn, pages=1)
        assert m.is_kis_closed_day(date(2026, 6, 4)) is False

    def test_datetime_input_works(self, tmp_path, monkeypatch):
        """is_kis_closed_day accepts datetime (not just date)."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page = _make_page(date(2026, 6, 3), closed_indices=(0,))
        m.sync_today(today=date(2026, 6, 3), fetch_fn=MagicMock(return_value=page), pages=1)

        KST = pytz.timezone('Asia/Seoul')
        dt = KST.localize(datetime(2026, 6, 3, 10, 0))
        assert m.is_kis_closed_day(dt) is True


# ---------------------------------------------------------------------------
# 3. 하루 1회 가드 + 페이지네이션
# ---------------------------------------------------------------------------

class TestOncePerDayAndPagination:
    def setup_method(self):
        import utils.holiday_kis_sync as m
        m._runtime_closed = set()
        m._synced_date = None

    def test_second_call_same_day_skips_fetch(self, tmp_path, monkeypatch):
        """같은 today로 2번 호출 시 fetch_fn은 1일치(pages회)만, 2번째는 0회."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page = _make_page(date(2026, 6, 3), closed_indices=(0,))
        fetch_fn = MagicMock(return_value=page)

        m.sync_today(today=date(2026, 6, 3), fetch_fn=fetch_fn, pages=1)
        first_call_count = fetch_fn.call_count  # should be 1

        m.sync_today(today=date(2026, 6, 3), fetch_fn=fetch_fn, pages=1)
        assert fetch_fn.call_count == first_call_count  # no additional calls

    def test_force_true_refetches(self, tmp_path, monkeypatch):
        """force=True면 같은 날도 재수집."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page = _make_page(date(2026, 6, 3), closed_indices=(0,))
        fetch_fn = MagicMock(return_value=page)

        m.sync_today(today=date(2026, 6, 3), fetch_fn=fetch_fn, pages=1)
        count_after_first = fetch_fn.call_count

        m.sync_today(today=date(2026, 6, 3), force=True, fetch_fn=fetch_fn, pages=1)
        assert fetch_fn.call_count == count_after_first + 1

    def test_pagination_two_pages_both_accumulated(self, tmp_path, monkeypatch):
        """pages=2: 1페이지에 20260603=N, 2페이지에 20261231=N → 둘 다 is_kis_closed_day True.
        fetch_fn이 BASS_DT별로 다른 24행 반환; fetch_fn 2회 호출 검증."""
        import utils.holiday_kis_sync as m
        from datetime import timedelta
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page1_start = date(2026, 6, 3)
        page1 = _make_page(page1_start, closed_indices=(0,))   # 20260603=N
        # page1 마지막 날: 20260626
        page1_last = page1_start + timedelta(days=23)
        page2_start = page1_last + timedelta(days=1)           # 20260627
        # 20261231이 page2에 들어가도록: index = (date(2026,12,31) - page2_start).days
        idx_dec31 = (date(2026, 12, 31) - page2_start).days
        if 0 <= idx_dec31 < 24:
            page2 = _make_page(page2_start, closed_indices=(idx_dec31,))
        else:
            # 24일 안에 없으면 첫 번째 행을 20261231로 강제 설정
            page2 = _make_page(page2_start, closed_indices=(0,))
            page2[0]["bass_dt"] = "20261231"

        call_log = []

        def multi_page_fetch(bass_dt):
            call_log.append(bass_dt)
            if bass_dt == page1_start.strftime("%Y%m%d"):
                return page1
            return page2

        m.sync_today(today=page1_start, fetch_fn=multi_page_fetch, pages=2)

        assert len(call_log) == 2, f"fetch_fn should be called twice, got {call_log}"
        assert m.is_kis_closed_day(date(2026, 6, 3)) is True
        assert m.is_kis_closed_day(date(2026, 12, 31)) is True

    def test_pagination_bass_dt_advances(self, tmp_path, monkeypatch):
        """2페이지째 BASS_DT = 1페이지 마지막날 + 1일 (전진 검증)."""
        import utils.holiday_kis_sync as m
        from datetime import timedelta
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        page1_start = date(2026, 6, 3)
        page1 = _make_page(page1_start, closed_indices=())
        page1_last_date = page1_start + timedelta(days=23)
        expected_page2_bass = (page1_last_date + timedelta(days=1)).strftime("%Y%m%d")

        bass_calls = []

        def tracking_fetch(bass_dt):
            bass_calls.append(bass_dt)
            if len(bass_calls) == 1:
                return page1
            return []  # stop after 2 calls

        m.sync_today(today=page1_start, fetch_fn=tracking_fetch, pages=2)

        assert len(bass_calls) >= 2
        assert bass_calls[1] == expected_page2_bass


# ---------------------------------------------------------------------------
# 4. fallback: fetch_fn 실패 → False, 기존 set 보존, 예외 전파 안 함
# ---------------------------------------------------------------------------

class TestFallback:
    def setup_method(self):
        import utils.holiday_kis_sync as m
        m._runtime_closed = set()
        m._synced_date = None

    def test_fetch_returns_none_returns_false(self, tmp_path, monkeypatch):
        """fetch_fn이 None 반환 → sync_today False, 예외 없음."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        result = m.sync_today(today=date(2026, 6, 3), fetch_fn=lambda _: None, pages=1)
        assert result is False

    def test_fetch_returns_empty_returns_false(self, tmp_path, monkeypatch):
        """fetch_fn이 [] 반환 → sync_today False."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        result = m.sync_today(today=date(2026, 6, 3), fetch_fn=lambda _: [], pages=1)
        assert result is False

    def test_fetch_raises_exception_returns_false(self, tmp_path, monkeypatch):
        """fetch_fn이 예외 던짐 → sync_today False, 예외 전파 없음."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        def bad_fetch(_):
            raise ConnectionError("network error")

        result = m.sync_today(today=date(2026, 6, 3), fetch_fn=bad_fetch, pages=1)
        assert result is False

    def test_existing_runtime_closed_preserved_on_failure(self, tmp_path, monkeypatch):
        """실패해도 기존 _runtime_closed 보존."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        m._runtime_closed = {"20260101"}  # 기존 데이터 있음
        m.sync_today(today=date(2026, 6, 3), fetch_fn=lambda _: None, pages=1)
        assert "20260101" in m._runtime_closed


# ---------------------------------------------------------------------------
# 5. 게이트 통합: _runtime_closed 주입 후 MarketHours.is_trading_day 판정
# ---------------------------------------------------------------------------

class TestGateIntegration:
    def setup_method(self):
        import utils.holiday_kis_sync as m
        m._runtime_closed = set()
        m._synced_date = None

    def test_runtime_closed_blocks_is_trading_day(self, monkeypatch):
        """_runtime_closed에 '20261231' 주입 → is_trading_day('KRX', 2026-12-31) False."""
        import utils.holiday_kis_sync as m
        m._runtime_closed = {"20261231"}

        from config.market_hours import MarketHours, KOREAN_HOLIDAYS
        KST = pytz.timezone('Asia/Seoul')

        # 20261231은 이미 KOREAN_HOLIDAYS에 있지만, 런타임 경로도 검증
        # 먼저 정적 set에서 제거해서 런타임 경로만 테스트
        original = frozenset(KOREAN_HOLIDAYS)
        KOREAN_HOLIDAYS.discard("20261231")
        try:
            dt = KST.localize(datetime(2026, 12, 31, 10, 0))
            assert MarketHours.is_trading_day('KRX', dt) is False
        finally:
            KOREAN_HOLIDAYS.update(original)

    def test_normal_trading_day_unaffected(self, monkeypatch):
        """2026-06-04(목, 비휴일) → is_trading_day True (런타임셋 무관)."""
        import utils.holiday_kis_sync as m
        m._runtime_closed = {"20261231"}

        from config.market_hours import MarketHours
        KST = pytz.timezone('Asia/Seoul')
        dt = KST.localize(datetime(2026, 6, 4, 10, 0))
        assert MarketHours.is_trading_day('KRX', dt) is True

    def test_runtime_closed_overrides_static_set(self, tmp_path, monkeypatch):
        """sync_today로 채운 _runtime_closed가 is_trading_day에 반영된다."""
        import utils.holiday_kis_sync as m
        monkeypatch.setattr(m, "_CACHE_PATH", str(tmp_path / "cache.json"))

        # 정적 set에 없는 임의 날짜(2026-07-17 제헌절 재지정)를 런타임으로 주입
        from config.market_hours import KOREAN_HOLIDAYS
        KOREAN_HOLIDAYS.discard("20260717")  # 혹시 있어도 제거
        try:
            page = _make_page(date(2026, 7, 17), closed_indices=(0,))  # 20260717=N
            m.sync_today(today=date(2026, 7, 17), fetch_fn=lambda _: page, pages=1)

            from config.market_hours import MarketHours
            KST = pytz.timezone('Asia/Seoul')
            dt = KST.localize(datetime(2026, 7, 17, 10, 0))
            assert MarketHours.is_trading_day('KRX', dt) is False
        finally:
            pass  # KOREAN_HOLIDAYS 원복 불필요(테스트 격리)
