"""
시장 상황별 전략 성과 분석 시뮬레이션

기존 simulate_with_screener.py와 동일한 진입/청산 로직을 사용하되,
각 거래일을 KOSPI/KOSDAQ 시장 상황으로 분류하여 성과를 세분화.

분류 기준:
  1. 당일 시장 (당일 시가 대비 종가)
  2. 전일 시장 (전일 시가 대비 종가)
  3. 5일 추세 (5거래일 전 종가 대비 당일 종가)

각 축마다: KOSPI 단독 / KOSDAQ 단독 / 종합(가중평균)

Usage:
  python simulate_market_regime.py --start 20250224 --end 20260223
  python simulate_market_regime.py --start 20250901 --threshold 0.5
"""

import psycopg2
import pandas as pd
from datetime import datetime, timedelta
from collections import defaultdict
import argparse
import time as time_module

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


# ===== DB 헬퍼 (simulate_with_screener.py 동일) =====

def get_trading_dates(cur, start_date, end_date=None):
    """거래일 목록 조회"""
    sql = "SELECT DISTINCT trade_date FROM minute_candles WHERE trade_date >= %s"
    params = [start_date]
    if end_date:
        sql += " AND trade_date <= %s"
        params.append(end_date)
    sql += " ORDER BY trade_date"
    cur.execute(sql, params)
    return [row[0] for row in cur.fetchall()]


def get_prev_close_map(cur, trade_date, prev_date):
    """전일 종가 맵 생성"""
    cur.execute('''
        SELECT stock_code, close
        FROM minute_candles
        WHERE trade_date = %s
          AND idx = (
            SELECT MAX(idx) FROM minute_candles mc2
            WHERE mc2.stock_code = minute_candles.stock_code
              AND mc2.trade_date = %s
          )
    ''', [prev_date, prev_date])
    return {row[0]: row[1] for row in cur.fetchall()}


def get_daily_metrics(cur, trade_date):
    """해당 거래일의 종목별 일간 지표 계산"""
    cur.execute('''
        SELECT
            stock_code,
            MIN(CASE WHEN time >= '090000' AND time <= '090300' THEN open END) as day_open,
            SUM(amount) as daily_amount,
            MAX(close) as max_price,
            MIN(close) as min_price
        FROM minute_candles
        WHERE trade_date = %s
        GROUP BY stock_code
        HAVING COUNT(*) >= 50
    ''', [trade_date])

    metrics = {}
    for row in cur.fetchall():
        stock_code, day_open, daily_amount, max_price, min_price = row
        if day_open and day_open > 0 and daily_amount:
            metrics[stock_code] = {
                'day_open': float(day_open),
                'daily_amount': float(daily_amount),
                'max_price': float(max_price),
                'min_price': float(min_price),
            }
    return metrics


def apply_screener_filter(
    daily_metrics, prev_close_map,
    top_n=60,
    min_price=5000, max_price=500000,
    min_amount=1_000_000_000,
    max_gap_pct=3.0,
):
    """스크리너 필터 적용 (Phase 1 + Phase 2)"""
    ranked = sorted(
        daily_metrics.items(),
        key=lambda x: x[1]['daily_amount'],
        reverse=True
    )[:top_n]

    passed = set()
    for stock_code, metrics in ranked:
        day_open = metrics['day_open']
        if stock_code[-1] == '5':
            continue
        if not (min_price <= day_open <= max_price):
            continue
        if metrics['daily_amount'] < min_amount:
            continue
        prev_close = prev_close_map.get(stock_code)
        if prev_close and prev_close > 0:
            gap_pct = abs(day_open / prev_close - 1) * 100
            if gap_pct > max_gap_pct:
                continue
        passed.add(stock_code)

    return passed


def apply_daily_limit(trades_df, max_daily):
    """동시 보유 제한 적용"""
    limited = []
    for date in trades_df['date'].unique():
        day_trades = trades_df[trades_df['date'] == date].copy()
        day_trades = day_trades.sort_values('entry_time')

        accepted = []
        for _, trade in day_trades.iterrows():
            entry_t = str(trade['entry_time']).zfill(6)
            exit_t = str(trade['exit_time']).zfill(6)
            holding = sum(1 for _, et in accepted if et > entry_t)
            if holding < max_daily:
                accepted.append((entry_t, exit_t))
                limited.append(trade)

    return pd.DataFrame(limited).reset_index(drop=True) if limited else pd.DataFrame()


# ===== 지수 데이터 로딩 =====

def load_index_data(start_date, end_date=None):
    """
    KOSPI/KOSDAQ 일봉 데이터 로드

    1차: FinanceDataReader (무료, API 키 불필요)
    로드 후 PostgreSQL에 캐시 저장

    Returns:
        dict: {date_str: {kospi_open, kospi_close, kosdaq_open, kosdaq_close}}
    """
    # 날짜 변환
    start_dt = datetime.strptime(start_date, '%Y%m%d')
    # 5일 추세 계산을 위해 10거래일 이전부터 로드
    fetch_start = (start_dt - timedelta(days=15)).strftime('%Y-%m-%d')
    end_str = None
    if end_date:
        end_str = datetime.strptime(end_date, '%Y%m%d').strftime('%Y-%m-%d')

    # PostgreSQL 캐시 확인
    index_data = _load_from_pg(start_date, end_date)
    if index_data and len(index_data) > 10:
        print(f'  지수 데이터: PostgreSQL 캐시에서 로드 ({len(index_data)}일)')
        return index_data

    # FinanceDataReader로 로드
    print('  지수 데이터: FinanceDataReader에서 다운로드 중...')
    try:
        import FinanceDataReader as fdr

        kospi_df = fdr.DataReader('KS11', fetch_start, end_str)
        kosdaq_df = fdr.DataReader('KQ11', fetch_start, end_str)

        if kospi_df.empty or kosdaq_df.empty:
            print('  [경고] FinanceDataReader에서 데이터를 가져올 수 없습니다')
            return {}

        print(f'  KOSPI: {len(kospi_df)}일, KOSDAQ: {len(kosdaq_df)}일 로드 완료')

        # 날짜 키로 병합
        index_data = {}
        for dt_idx in kospi_df.index:
            date_str = dt_idx.strftime('%Y%m%d')
            kospi_row = kospi_df.loc[dt_idx]
            kosdaq_row = kosdaq_df.loc[dt_idx] if dt_idx in kosdaq_df.index else None

            entry = {
                'kospi_open': float(kospi_row['Open']),
                'kospi_close': float(kospi_row['Close']),
            }
            if kosdaq_row is not None:
                entry['kosdaq_open'] = float(kosdaq_row['Open'])
                entry['kosdaq_close'] = float(kosdaq_row['Close'])
            else:
                entry['kosdaq_open'] = 0.0
                entry['kosdaq_close'] = 0.0

            index_data[date_str] = entry

        # PostgreSQL에 캐시 저장
        _save_to_pg(kospi_df, kosdaq_df)

        return index_data

    except ImportError:
        print('  [경고] FinanceDataReader 미설치 (pip install finance-datareader)')
        return {}
    except Exception as e:
        print(f'  [경고] 지수 데이터 로드 실패: {e}')
        return {}


def _load_from_pg(start_date, end_date=None):
    """PostgreSQL daily_candles에서 지수 데이터 로드"""
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD,
        )
        cur = conn.cursor()

        # 5일 추세용으로 더 이전 데이터도 필요
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        fetch_start = (start_dt - timedelta(days=15)).strftime('%Y%m%d')

        sql = """
            SELECT stock_code, stck_bsop_date, stck_oprc, stck_clpr
            FROM daily_candles
            WHERE stock_code IN ('KS11', 'KQ11')
              AND stck_bsop_date >= %s
        """
        params = [fetch_start]
        if end_date:
            sql += " AND stck_bsop_date <= %s"
            params.append(end_date)
        sql += " ORDER BY stck_bsop_date"

        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        conn.close()

        if not rows:
            return {}

        # 날짜별로 병합
        kospi_data = {}
        kosdaq_data = {}
        for code, date_str, open_val, close_val in rows:
            entry = {'open': float(open_val), 'close': float(close_val)}
            if code == 'KS11':
                kospi_data[date_str] = entry
            elif code == 'KQ11':
                kosdaq_data[date_str] = entry

        index_data = {}
        all_dates = sorted(set(list(kospi_data.keys()) + list(kosdaq_data.keys())))
        for d in all_dates:
            ki = kospi_data.get(d, {})
            kd = kosdaq_data.get(d, {})
            index_data[d] = {
                'kospi_open': ki.get('open', 0.0),
                'kospi_close': ki.get('close', 0.0),
                'kosdaq_open': kd.get('open', 0.0),
                'kosdaq_close': kd.get('close', 0.0),
            }

        return index_data

    except Exception:
        return {}


def _save_to_pg(kospi_df, kosdaq_df):
    """지수 데이터를 PostgreSQL daily_candles에 캐시 저장"""
    try:
        conn = psycopg2.connect(
            host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
            user=PG_USER, password=PG_PASSWORD,
        )
        cur = conn.cursor()

        # 테이블 존재 확인
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_name = 'daily_candles'
            )
        """)
        if not cur.fetchone()[0]:
            cur.close()
            conn.close()
            return

        count = 0
        for symbol, df in [('KS11', kospi_df), ('KQ11', kosdaq_df)]:
            for dt_idx, row in df.iterrows():
                date_str = dt_idx.strftime('%Y%m%d')
                cur.execute("""
                    INSERT INTO daily_candles (stock_code, stck_bsop_date, stck_oprc, stck_clpr,
                                               stck_hgpr, stck_lwpr, acml_vol, acml_tr_pbmn)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (stock_code, stck_bsop_date) DO NOTHING
                """, [
                    symbol, date_str,
                    str(row['Open']), str(row['Close']),
                    str(row['High']), str(row['Low']),
                    str(int(row.get('Volume', 0))),
                    '0',
                ])
                count += 1

        conn.commit()
        cur.close()
        conn.close()
        print(f'  지수 데이터 PostgreSQL 캐시 저장: {count}건')
    except Exception as e:
        print(f'  [경고] PostgreSQL 캐시 저장 실패: {e}')


# ===== 시장 상황 분류 =====

def build_regime_lookup(index_data, trading_dates, kospi_weight=0.6):
    """
    전체 거래일에 대한 시장 상황 분류 룩업 테이블 생성

    Returns:
        dict: {date_str: {
            'same_day_kospi_pct': float,
            'same_day_kosdaq_pct': float,
            'same_day_combined_pct': float,
            'prev_day_kospi_pct': float,
            'prev_day_kosdaq_pct': float,
            'prev_day_combined_pct': float,
            'trend_5d_kospi_pct': float,
            'trend_5d_kosdaq_pct': float,
            'trend_5d_combined_pct': float,
        }}
    """
    # 인덱스 데이터의 날짜 정렬 리스트 (5거래일 전 조회용)
    all_index_dates = sorted(index_data.keys())
    date_to_pos = {d: i for i, d in enumerate(all_index_dates)}

    kosdaq_weight = 1.0 - kospi_weight
    regime_lookup = {}

    for date_str in trading_dates:
        entry = index_data.get(date_str)
        if not entry or entry['kospi_open'] <= 0:
            regime_lookup[date_str] = None
            continue

        regime = {}

        # [1] 당일: (종가/시가 - 1) * 100
        ki_same = (entry['kospi_close'] / entry['kospi_open'] - 1) * 100
        kd_same = 0.0
        if entry['kosdaq_open'] > 0:
            kd_same = (entry['kosdaq_close'] / entry['kosdaq_open'] - 1) * 100
        regime['same_day_kospi_pct'] = ki_same
        regime['same_day_kosdaq_pct'] = kd_same
        regime['same_day_combined_pct'] = ki_same * kospi_weight + kd_same * kosdaq_weight

        # [2] 전일: 전 거래일의 (종가/시가 - 1) * 100
        pos = date_to_pos.get(date_str)
        if pos is not None and pos >= 1:
            prev_date = all_index_dates[pos - 1]
            prev_entry = index_data.get(prev_date, {})
            if prev_entry.get('kospi_open', 0) > 0:
                ki_prev = (prev_entry['kospi_close'] / prev_entry['kospi_open'] - 1) * 100
            else:
                ki_prev = 0.0
            if prev_entry.get('kosdaq_open', 0) > 0:
                kd_prev = (prev_entry['kosdaq_close'] / prev_entry['kosdaq_open'] - 1) * 100
            else:
                kd_prev = 0.0
        else:
            ki_prev = 0.0
            kd_prev = 0.0
        regime['prev_day_kospi_pct'] = ki_prev
        regime['prev_day_kosdaq_pct'] = kd_prev
        regime['prev_day_combined_pct'] = ki_prev * kospi_weight + kd_prev * kosdaq_weight

        # [3] 5일 추세: (당일 종가 / 5거래일전 종가 - 1) * 100
        if pos is not None and pos >= 5:
            d5_date = all_index_dates[pos - 5]
            d5_entry = index_data.get(d5_date, {})
            if d5_entry.get('kospi_close', 0) > 0:
                ki_trend = (entry['kospi_close'] / d5_entry['kospi_close'] - 1) * 100
            else:
                ki_trend = 0.0
            if d5_entry.get('kosdaq_close', 0) > 0:
                kd_trend = (entry['kosdaq_close'] / d5_entry['kosdaq_close'] - 1) * 100
            else:
                kd_trend = 0.0
        else:
            ki_trend = 0.0
            kd_trend = 0.0
        regime['trend_5d_kospi_pct'] = ki_trend
        regime['trend_5d_kosdaq_pct'] = kd_trend
        regime['trend_5d_combined_pct'] = ki_trend * kospi_weight + kd_trend * kosdaq_weight

        regime_lookup[date_str] = regime

    return regime_lookup


def classify(pct, threshold):
    """등락률을 상승/하락/횡보로 분류"""
    if pct >= threshold:
        return 'UP'
    elif pct <= -threshold:
        return 'DOWN'
    else:
        return 'SIDE'


# ===== 출력 함수 =====

def _print_group_stats(group_df, label):
    """그룹별 통계 한 줄 출력"""
    n = len(group_df)
    if n == 0:
        return f'    {label:6s}: 거래 없음'
    w = (group_df['result'] == 'WIN').sum()
    rate = w / n * 100
    total_pnl = group_df['pnl'].sum()
    avg_pnl = group_df['pnl'].mean()
    return f'    {label:6s}: {n:>4}건, {w:>3}승 {n-w:>3}패, {rate:5.1f}%, 총{total_pnl:>+7.1f}%, 평균{avg_pnl:>+6.2f}%'


def print_regime_analysis(trades_df, axis_name, pct_col, thresholds, axis_label):
    """특정 축에 대한 시장 상황별 분석 출력"""
    if len(trades_df) == 0 or pct_col not in trades_df.columns:
        return

    print(f'\n{"=" * 80}')
    print(f'  {axis_label}')
    print(f'{"=" * 80}')

    # 시장 분류 일수 통계
    unique_days = trades_df.drop_duplicates('date')
    valid_days = unique_days[unique_days[pct_col].notna()]
    if len(valid_days) > 0:
        avg_pct = valid_days[pct_col].mean()
        print(f'  거래일 {len(valid_days)}일, 평균 등락: {avg_pct:+.2f}%')

    for threshold in thresholds:
        # 분류
        mask_valid = trades_df[pct_col].notna()
        valid = trades_df[mask_valid].copy()
        if len(valid) == 0:
            continue

        valid['_regime'] = valid[pct_col].apply(lambda x: classify(x, threshold))

        up_df = valid[valid['_regime'] == 'UP']
        side_df = valid[valid['_regime'] == 'SIDE']
        down_df = valid[valid['_regime'] == 'DOWN']

        # 일수 카운트
        up_days = up_df['date'].nunique()
        side_days = side_df['date'].nunique()
        down_days = down_df['date'].nunique()

        print(f'\n  threshold = {threshold}%  (상승 {up_days}일 / 횡보 {side_days}일 / 하락 {down_days}일)')
        print(_print_group_stats(up_df, '상승'))
        print(_print_group_stats(side_df, '횡보'))
        print(_print_group_stats(down_df, '하락'))

        # 상승-하락 차이 강조
        if len(up_df) > 0 and len(down_df) > 0:
            up_rate = (up_df['result'] == 'WIN').sum() / len(up_df) * 100
            down_rate = (down_df['result'] == 'WIN').sum() / len(down_df) * 100
            diff = up_rate - down_rate
            up_avg = up_df['pnl'].mean()
            down_avg = down_df['pnl'].mean()
            print(f'    -----> 승률 차이: {diff:+.1f}%p, 평균수익 차이: {up_avg - down_avg:+.2f}%')


def print_cross_analysis(trades_df, thresholds):
    """당일 × 전일 교차 분석 (3×3 매트릭스)"""
    if len(trades_df) == 0:
        return

    threshold = thresholds[1] if len(thresholds) > 1 else thresholds[0]

    # 필요한 컬럼 존재 확인
    if 'same_day_combined_pct' not in trades_df.columns:
        return
    if 'prev_day_combined_pct' not in trades_df.columns:
        return

    valid = trades_df[
        trades_df['same_day_combined_pct'].notna() &
        trades_df['prev_day_combined_pct'].notna()
    ].copy()
    if len(valid) == 0:
        return

    valid['same_regime'] = valid['same_day_combined_pct'].apply(lambda x: classify(x, threshold))
    valid['prev_regime'] = valid['prev_day_combined_pct'].apply(lambda x: classify(x, threshold))

    print(f'\n{"=" * 80}')
    print(f'  교차 분석: 당일 × 전일 (종합, threshold={threshold}%)')
    print(f'{"=" * 80}')

    labels = ['UP', 'SIDE', 'DOWN']
    label_kr = {'UP': '상승', 'SIDE': '횡보', 'DOWN': '하락'}

    # 헤더
    header = f'{"":>16}'
    for prev in labels:
        header += f'  전일{label_kr[prev]:>4}'
    print(header)
    print('  ' + '-' * 60)

    for same in labels:
        row_str = f'  당일{label_kr[same]:>4}  '
        for prev in labels:
            cell = valid[(valid['same_regime'] == same) & (valid['prev_regime'] == prev)]
            n = len(cell)
            if n == 0:
                row_str += f'  {"---":>10}'
            else:
                w = (cell['result'] == 'WIN').sum()
                rate = w / n * 100
                avg_pnl = cell['pnl'].mean()
                row_str += f'  {n}건 {rate:.0f}%({avg_pnl:+.1f})'
            row_str += '  '
        print(row_str)


def print_basic_stats(trades_df, label):
    """기본 전체 통계 (simulate_with_screener.py 형식)"""
    if len(trades_df) == 0:
        print(f'\n[{label}] 거래 없음')
        return

    wins = (trades_df['result'] == 'WIN').sum()
    losses = (trades_df['result'] == 'LOSS').sum()
    total = len(trades_df)
    winrate = wins / total * 100
    total_pnl = trades_df['pnl'].sum()
    avg_pnl = trades_df['pnl'].mean()
    avg_win = trades_df[trades_df['result'] == 'WIN']['pnl'].mean() if wins > 0 else 0
    avg_loss = trades_df[trades_df['result'] == 'LOSS']['pnl'].mean() if losses > 0 else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print(f'\n{"=" * 80}')
    print(f'  전체 통계 [{label}]')
    print(f'{"=" * 80}')
    print(f'  총 거래: {total}건 ({wins}승 {losses}패)')
    print(f'  승률: {winrate:.1f}%')
    print(f'  총 수익률: {total_pnl:+.1f}%')
    print(f'  평균 수익률: {avg_pnl:+.2f}%')
    print(f'  평균 승리: {avg_win:+.2f}% | 평균 손실: {avg_loss:.2f}%')
    print(f'  손익비: {pl_ratio:.2f}:1')

    # 수익 예상
    dates = sorted(trades_df['date'].unique())
    num_months = max(len(set(d[:6] for d in dates)), 1)
    monthly_profit = (total_pnl / num_months) * 10000
    print(f'  기간: {dates[0]}~{dates[-1]} ({num_months}개월)')
    print(f'  월평균 거래: {total/num_months:.0f}건, 월평균 수익(100만원/건): {monthly_profit:+,.0f}원')


# ===== 메인 시뮬레이션 =====

def run_simulation(
    start_date='20250901',
    end_date=None,
    config=None,
    max_daily=5,
    screener_top_n=60,
    screener_min_amount=1_000_000_000,
    screener_max_gap=3.0,
    screener_min_price=5000,
    screener_max_price=500000,
    thresholds=None,
    trend_thresholds=None,
    kospi_weight=0.6,
    verbose=True,
):
    if thresholds is None:
        thresholds = [0.3, 0.5, 0.8, 1.0]
    if trend_thresholds is None:
        trend_thresholds = [1.0, 2.0, 3.0]

    strategy = PricePositionStrategy(config=config)
    info = strategy.get_strategy_info()

    print('=' * 80)
    print(f"  시장 상황별 전략 성과 분석: {info['name']}")
    print('=' * 80)
    print(f"  진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}")
    print(f"  청산: 손절 {info['exit_conditions']['stop_loss']}, "
          f"익절 {info['exit_conditions']['take_profit']}")
    print(f"  스크리너: 거래대금 상위 {screener_top_n}개, "
          f"거래대금>{screener_min_amount/1e8:.0f}억, "
          f"갭<{screener_max_gap}%")
    print(f"  동시보유: {max_daily}종목")
    print(f"  기간: {start_date} ~ {end_date or '전체'}")
    print(f"  KOSPI 가중치: {kospi_weight:.0%} / KOSDAQ: {1-kospi_weight:.0%}")
    print(f"  임계값: {thresholds} / 5일추세: {trend_thresholds}")
    print('=' * 80)

    # 지수 데이터 로드
    print('\n[1단계] 지수 데이터 로드')
    index_data = load_index_data(start_date, end_date)
    if not index_data:
        print('  [오류] 지수 데이터를 로드할 수 없습니다')
        return None

    # DB 연결
    conn = psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )
    cur = conn.cursor()

    # 거래일 목록
    trading_dates = get_trading_dates(cur, start_date, end_date)
    print(f'\n[2단계] 시뮬레이션 실행 (거래일: {len(trading_dates)}일)')

    # 시장 상황 분류 룩업
    regime_lookup = build_regime_lookup(index_data, trading_dates, kospi_weight)

    # 지수 분류 통계 출력
    regime_count = {'up': 0, 'down': 0, 'side': 0, 'unknown': 0}
    for d in trading_dates:
        r = regime_lookup.get(d)
        if r is None:
            regime_count['unknown'] += 1
        else:
            cat = classify(r['same_day_combined_pct'], 0.5)
            if cat == 'UP':
                regime_count['up'] += 1
            elif cat == 'DOWN':
                regime_count['down'] += 1
            else:
                regime_count['side'] += 1
    print(f'  시장 분류 (당일종합, 0.5%): '
          f'상승 {regime_count["up"]}일 / 횡보 {regime_count["side"]}일 / '
          f'하락 {regime_count["down"]}일 / 미분류 {regime_count["unknown"]}일')

    # 시뮬레이션 루프
    all_trades = []
    screener_stats = {'total_stocks': 0, 'screened_stocks': 0, 'days': 0}
    t_start = time_module.time()

    for day_idx, trade_date in enumerate(trading_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except Exception:
            continue

        if verbose and day_idx % 20 == 0:
            elapsed = time_module.time() - t_start
            print(f'  {day_idx}/{len(trading_dates)} ({trade_date}) '
                  f'거래 {len(all_trades)}건 ({elapsed:.0f}s)')

        prev_date = trading_dates[day_idx - 1] if day_idx > 0 else None

        daily_metrics = get_daily_metrics(cur, trade_date)
        if not daily_metrics:
            continue

        prev_close_map = {}
        if prev_date:
            prev_close_map = get_prev_close_map(cur, trade_date, prev_date)

        screened = apply_screener_filter(
            daily_metrics, prev_close_map,
            top_n=screener_top_n,
            min_price=screener_min_price,
            max_price=screener_max_price,
            min_amount=screener_min_amount,
            max_gap_pct=screener_max_gap,
        )

        screener_stats['total_stocks'] += len(daily_metrics)
        screener_stats['screened_stocks'] += len(screened)
        screener_stats['days'] += 1

        if not screened:
            continue

        # 해당일의 시장 상황
        regime = regime_lookup.get(trade_date)

        for stock_code in screened:
            try:
                cur.execute('''
                    SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx
                ''', [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                columns = ['idx', 'date', 'time', 'close', 'open', 'high',
                           'low', 'volume', 'amount', 'datetime']
                df = pd.DataFrame(rows, columns=columns)

                day_open = daily_metrics[stock_code]['day_open']
                if day_open <= 0:
                    continue

                traded = False
                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = row['close']

                    can_enter, reason = strategy.check_entry_conditions(
                        stock_code=stock_code,
                        current_price=current_price,
                        day_open=day_open,
                        current_time=current_time,
                        trade_date=trade_date,
                        weekday=weekday,
                    )
                    if not can_enter:
                        continue

                    adv_ok, adv_reason = strategy.check_advanced_conditions(
                        df=df, candle_idx=candle_idx
                    )
                    if not adv_ok:
                        continue

                    result = strategy.simulate_trade(df, candle_idx)
                    if result:
                        pct_from_open = (current_price / day_open - 1) * 100
                        trade_record = {
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            **result,
                        }
                        # 시장 상황 필드 추가
                        if regime:
                            trade_record.update(regime)
                        else:
                            for key in ['same_day_kospi_pct', 'same_day_kosdaq_pct',
                                        'same_day_combined_pct', 'prev_day_kospi_pct',
                                        'prev_day_kosdaq_pct', 'prev_day_combined_pct',
                                        'trend_5d_kospi_pct', 'trend_5d_kosdaq_pct',
                                        'trend_5d_combined_pct']:
                                trade_record[key] = None

                        all_trades.append(trade_record)
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    elapsed = time_module.time() - t_start
    avg_total = screener_stats['total_stocks'] / max(screener_stats['days'], 1)
    avg_screened = screener_stats['screened_stocks'] / max(screener_stats['days'], 1)
    print(f'\n  스크리너 통계: 일평균 {avg_total:.0f}개 → {avg_screened:.0f}개 통과')
    print(f'  총 거래: {len(all_trades)}건 (소요시간: {elapsed:.0f}s)')

    if not all_trades:
        print('  거래 없음')
        return None

    trades_df = pd.DataFrame(all_trades)

    # 동시보유 제한 적용
    if max_daily > 0:
        limited_df = apply_daily_limit(trades_df, max_daily)
        print(f'  동시보유 {max_daily}종목 제한 후: {len(limited_df)}건')
    else:
        limited_df = trades_df

    if len(limited_df) == 0:
        print('  제한 후 거래 없음')
        return None

    # ===== 결과 출력 =====
    print(f'\n\n{"#" * 80}')
    print(f'#  시장 상황별 전략 성과 분석 결과')
    print(f'{"#" * 80}')

    # 기본 통계
    print_basic_stats(limited_df, f'동시보유 {max_daily}종목')

    # [1] 당일 시장 기준 - 종합
    print_regime_analysis(
        limited_df, 'same_day_combined',
        'same_day_combined_pct', thresholds,
        '[1] 당일 시장 기준 (종합 KOSPI×{:.0f}%+KOSDAQ×{:.0f}%)'.format(
            kospi_weight * 100, (1 - kospi_weight) * 100),
    )

    # [2] 전일 시장 기준 - 종합
    print_regime_analysis(
        limited_df, 'prev_day_combined',
        'prev_day_combined_pct', thresholds,
        '[2] 전일 시장 기준 (종합) - 실제 필터 적용 가능',
    )

    # [3] 5일 추세 기준 - 종합
    print_regime_analysis(
        limited_df, 'trend_5d_combined',
        'trend_5d_combined_pct', trend_thresholds,
        '[3] 5일 추세 기준 (종합)',
    )

    # [4] 지수별 상세
    print(f'\n{"=" * 80}')
    print(f'  [4] 지수별 상세 비교')
    print(f'{"=" * 80}')

    default_th = thresholds[1] if len(thresholds) > 1 else thresholds[0]
    for index_name, prefix in [('KOSPI', 'kospi'), ('KOSDAQ', 'kosdaq')]:
        for axis_name, axis_kr in [('same_day', '당일'), ('prev_day', '전일')]:
            col = f'{axis_name}_{prefix}_pct'
            if col not in limited_df.columns:
                continue
            valid = limited_df[limited_df[col].notna()].copy()
            if len(valid) == 0:
                continue
            valid['_regime'] = valid[col].apply(lambda x: classify(x, default_th))

            up_df = valid[valid['_regime'] == 'UP']
            down_df = valid[valid['_regime'] == 'DOWN']
            side_df = valid[valid['_regime'] == 'SIDE']

            up_rate = (up_df['result'] == 'WIN').sum() / len(up_df) * 100 if len(up_df) > 0 else 0
            down_rate = (down_df['result'] == 'WIN').sum() / len(down_df) * 100 if len(down_df) > 0 else 0
            side_rate = (side_df['result'] == 'WIN').sum() / len(side_df) * 100 if len(side_df) > 0 else 0

            print(f'  {axis_kr} {index_name} (threshold={default_th}%): '
                  f'상승 {len(up_df)}건({up_rate:.0f}%) | '
                  f'횡보 {len(side_df)}건({side_rate:.0f}%) | '
                  f'하락 {len(down_df)}건({down_rate:.0f}%)')

    # [5] 교차 분석
    print_cross_analysis(limited_df, thresholds)

    # [6] 하락장 필터 효과 시뮬레이션
    print(f'\n{"=" * 80}')
    print(f'  [6] 하락장 필터 효과 시뮬레이션')
    print(f'  "전일 시장이 하락이면 매매 안 함" 가정 시 결과')
    print(f'{"=" * 80}')

    for th in thresholds:
        col = 'prev_day_combined_pct'
        if col not in limited_df.columns:
            continue
        valid = limited_df[limited_df[col].notna()].copy()
        if len(valid) == 0:
            continue

        # 전일 하락 아닌 날만 필터링
        filtered = valid[valid[col] > -th]
        excluded = valid[valid[col] <= -th]

        if len(filtered) == 0:
            continue

        f_wins = (filtered['result'] == 'WIN').sum()
        f_total = len(filtered)
        f_rate = f_wins / f_total * 100
        f_pnl = filtered['pnl'].sum()
        f_avg = filtered['pnl'].mean()

        orig_wins = (valid['result'] == 'WIN').sum()
        orig_rate = orig_wins / len(valid) * 100
        orig_pnl = valid['pnl'].sum()

        exc_pnl = excluded['pnl'].sum() if len(excluded) > 0 else 0

        print(f'  threshold={th}%: 전일하락 {len(excluded)}건 제외 → {f_total}건 유지')
        print(f'    원본: {len(valid)}건, 승률 {orig_rate:.1f}%, 총{orig_pnl:+.1f}%')
        print(f'    필터: {f_total}건, 승률 {f_rate:.1f}%, 총{f_pnl:+.1f}%')
        print(f'    제외된 거래 손익: {exc_pnl:+.1f}% (이것이 -면 필터 효과 있음)')
        print()

    print('\nDone!')
    return limited_df


def main():
    parser = argparse.ArgumentParser(description='시장 상황별 전략 성과 분석')

    # 기존 simulate_with_screener.py 호환 인자
    parser.add_argument('--start', default='20250901', help='시작일 (YYYYMMDD)')
    parser.add_argument('--end', default=None, help='종료일 (YYYYMMDD)')
    parser.add_argument('--min-pct', type=float, default=1.0)
    parser.add_argument('--max-pct', type=float, default=3.0)
    parser.add_argument('--start-hour', type=int, default=9)
    parser.add_argument('--end-hour', type=int, default=12)
    parser.add_argument('--stop-loss', type=float, default=-4.0)
    parser.add_argument('--take-profit', type=float, default=5.0)
    parser.add_argument('--max-daily', type=int, default=5)
    parser.add_argument('--max-volatility', type=float, default=0.8)
    parser.add_argument('--max-momentum', type=float, default=2.0)
    parser.add_argument('--weekdays', default=None)
    parser.add_argument('--screener-top', type=int, default=60)
    parser.add_argument('--screener-min-amount', type=float, default=1e9)
    parser.add_argument('--screener-max-gap', type=float, default=3.0)
    parser.add_argument('--quiet', action='store_true')

    # 시장 상황 분석 전용 인자
    parser.add_argument('--threshold', type=float, default=None,
                        help='단일 임계값 (이것만 사용)')
    parser.add_argument('--thresholds', default='0.3,0.5,0.8,1.0',
                        help='당일/전일 임계값 목록 (쉼표 구분)')
    parser.add_argument('--trend-thresholds', default='1.0,2.0,3.0',
                        help='5일 추세 임계값 목록')
    parser.add_argument('--kospi-weight', type=float, default=0.6,
                        help='종합 지표에서 KOSPI 가중치 (0~1)')

    args = parser.parse_args()

    # 전략 설정
    config = {
        'min_pct_from_open': args.min_pct,
        'max_pct_from_open': args.max_pct,
        'entry_start_hour': args.start_hour,
        'entry_end_hour': args.end_hour,
        'stop_loss_pct': args.stop_loss,
        'take_profit_pct': args.take_profit,
    }
    if args.weekdays is not None:
        config['allowed_weekdays'] = [int(d) for d in args.weekdays.split(',')]
    if args.max_volatility > 0:
        config['max_pre_volatility'] = args.max_volatility
    if args.max_momentum > 0:
        config['max_pre20_momentum'] = args.max_momentum

    # 임계값 처리
    if args.threshold is not None:
        thresholds = [args.threshold]
        trend_thresholds = [args.threshold * 2]
    else:
        thresholds = [float(x) for x in args.thresholds.split(',')]
        trend_thresholds = [float(x) for x in args.trend_thresholds.split(',')]

    run_simulation(
        start_date=args.start,
        end_date=args.end,
        config=config,
        max_daily=args.max_daily,
        screener_top_n=args.screener_top,
        screener_min_amount=args.screener_min_amount,
        screener_max_gap=args.screener_max_gap,
        thresholds=thresholds,
        trend_thresholds=trend_thresholds,
        kospi_weight=args.kospi_weight,
        verbose=not args.quiet,
    )


if __name__ == '__main__':
    main()
