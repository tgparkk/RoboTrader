"""
스크리너 통합 시뮬레이션 - 데이터 수집부터 시뮬까지

Phase A: 일봉 수집 (FinanceDataReader, KIS API 불필요)
Phase B: 일봉으로 스크리너 후보 선정
Phase C: 후보 종목만 분봉 수집 (KIS API)
Phase D: 시뮬레이션 실행

Usage:
    python collect_and_simulate.py --phase A       # 일봉만 수집
    python collect_and_simulate.py --phase AB      # 일봉 + 후보 선정
    python collect_and_simulate.py --phase ABCD    # 전체 (기본값)
    python collect_and_simulate.py --phase D       # 시뮬만 (데이터 있을 때)
"""

import json
import os
import sys
import time
import argparse
import pickle
import traceback
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import pandas as pd
import psycopg2

# === Phase A: FinanceDataReader ===
try:
    import FinanceDataReader as fdr
except ImportError:
    fdr = None

# === Phase C: KIS API ===
try:
    from api.kis_auth import auth as kis_auth
    from api.kis_chart_api import get_full_trading_day_data
    KIS_AVAILABLE = True
except ImportError:
    KIS_AVAILABLE = False

from config.settings import PG_HOST, PG_PORT, PG_DATABASE, PG_USER, PG_PASSWORD
from core.strategies.price_position_strategy import PricePositionStrategy


# ============================================================
# 경로 설정
# ============================================================
DATA_DIR = Path('data/simulation')
DAILY_DATA_FILE = DATA_DIR / 'daily_ohlcv.pkl'
CANDIDATES_FILE = DATA_DIR / 'screener_candidates.pkl'
MINUTE_PROGRESS_FILE = DATA_DIR / 'minute_collection_progress.pkl'


def get_pg_connection():
    return psycopg2.connect(
        host=PG_HOST, port=PG_PORT, database=PG_DATABASE,
        user=PG_USER, password=PG_PASSWORD,
    )


# ============================================================
# Phase A: 일봉 데이터 수집 (FinanceDataReader)
# ============================================================
def phase_a_collect_daily(start_date='20250224', end_date='20260223', resume=True):
    """
    전종목 일봉 OHLCV 수집 (FinanceDataReader 사용, KIS API 불필요)

    Returns:
        {stock_code: DataFrame(Date, Open, High, Low, Close, Volume)}
    """
    if fdr is None:
        print('ERROR: FinanceDataReader 미설치. pip install finance-datareader')
        sys.exit(1)

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # 기존 데이터 로드 (resume)
    daily_data = {}
    if resume and DAILY_DATA_FILE.exists():
        daily_data = pickle.loads(DAILY_DATA_FILE.read_bytes())
        print(f'기존 데이터 로드: {len(daily_data)}종목')

    # 종목 리스트 로드
    with open('stock_list.json', 'r', encoding='utf-8') as f:
        stock_list = json.load(f)

    stocks = stock_list['stocks']
    total = len(stocks)
    print(f'\nPhase A: 일봉 수집 시작 ({total}종목, {start_date}~{end_date})')

    start_dt = f'{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}'
    end_dt = f'{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}'

    errors = []
    skipped = 0
    collected = 0
    save_interval = 100  # 100종목마다 중간 저장

    for i, stock in enumerate(stocks):
        code = stock['code']

        # 이미 수집된 종목은 건너뛰기
        if code in daily_data and len(daily_data[code]) > 200:
            skipped += 1
            continue

        try:
            df = fdr.DataReader(code, start_dt, end_dt)
            if df is not None and len(df) > 0:
                # 거래대금 추정 (Volume × Close)
                df['Amount'] = df['Volume'] * df['Close']
                daily_data[code] = df
                collected += 1
            else:
                errors.append((code, stock['name'], 'empty'))
        except Exception as e:
            errors.append((code, stock['name'], str(e)[:50]))
            time.sleep(0.5)  # 에러 시 잠시 대기

        # 진행률 출력
        if (i + 1) % 50 == 0 or i == total - 1:
            print(f'  {i+1}/{total} ({collected}수집, {skipped}스킵, {len(errors)}에러)')

        # 중간 저장
        if (collected + skipped) % save_interval == 0 and collected > 0:
            DAILY_DATA_FILE.write_bytes(pickle.dumps(daily_data))

        # FDR rate limit (너무 빠르면 차단됨)
        if collected % 10 == 0 and collected > 0:
            time.sleep(0.3)

    # 최종 저장
    DAILY_DATA_FILE.write_bytes(pickle.dumps(daily_data))

    print(f'\nPhase A 완료: {len(daily_data)}종목 수집')
    if errors:
        print(f'  에러: {len(errors)}건')
        for code, name, err in errors[:10]:
            print(f'    {code} {name}: {err}')

    return daily_data


# ============================================================
# Phase B: 스크리너 후보 선정 (일봉 기반)
# ============================================================
def phase_b_select_candidates(
    daily_data,
    top_n=60,
    min_price=5000,
    max_price=500000,
    min_amount=1_000_000_000,
    max_gap_pct=3.0,
    min_change_rate=0.5,
    max_change_rate=5.0,
):
    """
    매 거래일마다 스크리너 후보 선정 (실시간 스크리너 시뮬레이션)

    거래량순위 API 시뮬:
      1. 거래대금 상위 top_n 종목 선별
      2. 등락률/가격/거래대금/갭 필터 적용

    Returns:
        {trade_date_str: set(stock_codes)}
    """
    print(f'\nPhase B: 스크리너 후보 선정 (거래대금 상위 {top_n}개 → 필터)')

    # 모든 거래일 수집
    all_dates = set()
    for code, df in daily_data.items():
        for dt in df.index:
            all_dates.add(dt)
    trading_dates = sorted(all_dates)
    print(f'  거래일: {len(trading_dates)}일')

    # 종목별 데이터를 날짜 인덱싱
    # {date: {code: {Open, High, Low, Close, Volume, Amount}}}

    candidates_by_date = {}
    prev_date_map = {}  # {date: prev_date}

    for idx, date in enumerate(trading_dates):
        if idx > 0:
            prev_date_map[date] = trading_dates[idx - 1]

    total_candidates = 0
    total_days = 0

    for date in trading_dates:
        date_str = date.strftime('%Y%m%d')

        # 해당일 데이터 수집
        day_stocks = {}
        for code, df in daily_data.items():
            if date in df.index:
                row = df.loc[date]
                if pd.notna(row['Open']) and row['Open'] > 0 and row['Volume'] > 0:
                    day_stocks[code] = {
                        'open': float(row['Open']),
                        'high': float(row['High']),
                        'low': float(row['Low']),
                        'close': float(row['Close']),
                        'volume': int(row['Volume']),
                        'amount': float(row['Amount']),
                    }

        if not day_stocks:
            continue

        # Phase 1 시뮬: 거래대금 상위 top_n
        ranked = sorted(
            day_stocks.items(),
            key=lambda x: x[1]['amount'],
            reverse=True,
        )[:top_n]

        # 전일 종가 수집
        prev_close = {}
        prev_date = prev_date_map.get(date)
        if prev_date:
            for code, df in daily_data.items():
                if prev_date in df.index:
                    row = df.loc[prev_date]
                    if pd.notna(row['Close']) and row['Close'] > 0:
                        prev_close[code] = float(row['Close'])

        # Phase 2: 기본 필터
        passed = set()
        for code, metrics in ranked:
            day_open = metrics['open']
            close = metrics['close']

            # 우선주 제외 (코드 끝자리)
            if code[-1] in ('5', 'K', 'L'):
                continue

            # 가격 필터
            if not (min_price <= day_open <= max_price):
                continue

            # 거래대금 필터
            if metrics['amount'] < min_amount:
                continue

            # 등락률 필터 (전일종가 대비)
            pc = prev_close.get(code)
            if pc and pc > 0:
                change_rate = (close / pc - 1) * 100
                if not (min_change_rate <= change_rate <= max_change_rate):
                    continue

                # 갭 필터 (시가 vs 전일종가)
                gap_pct = abs(day_open / pc - 1) * 100
                if gap_pct > max_gap_pct:
                    continue

            passed.add(code)

        if passed:
            candidates_by_date[date_str] = passed
            total_candidates += len(passed)
            total_days += 1

    # 저장
    CANDIDATES_FILE.write_bytes(pickle.dumps(candidates_by_date))

    avg_candidates = total_candidates / max(total_days, 1)
    print(f'\nPhase B 완료: {total_days}거래일, 일평균 {avg_candidates:.1f}개 후보')
    print(f'  총 고유 후보: {len(set().union(*candidates_by_date.values()))}종목')

    return candidates_by_date


# ============================================================
# Phase C: 후보 종목 분봉 수집 (KIS API)
# ============================================================
def phase_c_collect_minute_data(candidates_by_date, batch_size=50, resume=True):
    """
    스크리너 후보 종목의 분봉 데이터를 PostgreSQL에 저장

    Args:
        candidates_by_date: {trade_date: set(stock_codes)}
        batch_size: DB 배치 insert 크기
    """
    if not KIS_AVAILABLE:
        print('ERROR: KIS API 모듈 로드 실패')
        sys.exit(1)

    print(f'\nPhase C: 분봉 수집 시작')

    # KIS 인증
    print('  KIS API 인증 중...')
    kis_auth()
    time.sleep(1)

    conn = get_pg_connection()
    cur = conn.cursor()

    # DB에 이미 있는 데이터 확인
    cur.execute("""
        SELECT DISTINCT stock_code, trade_date
        FROM minute_candles
    """)
    existing = set((row[0], row[1]) for row in cur.fetchall())
    print(f'  DB 기존 데이터: {len(existing)}건 (종목×일)')

    # 수집 진행 상황 로드
    progress = set()
    if resume and MINUTE_PROGRESS_FILE.exists():
        progress = pickle.loads(MINUTE_PROGRESS_FILE.read_bytes())
        print(f'  이전 진행: {len(progress)}건 완료')

    # 수집 대상 결정
    to_collect = []
    for date_str, stock_codes in sorted(candidates_by_date.items()):
        for code in sorted(stock_codes):
            key = (code, date_str)
            if key not in existing and key not in progress:
                to_collect.append(key)

    print(f'  수집 대상: {len(to_collect)}건 (종목×일)')

    if not to_collect:
        print('  수집할 데이터 없음')
        cur.close()
        conn.close()
        return

    # 예상 시간
    api_calls = len(to_collect) * 4  # 4 API calls per stock-day
    est_minutes = api_calls / 180  # ~3 calls/sec
    print(f'  예상 API 호출: {api_calls}회, 예상 소요: ~{est_minutes:.0f}분')

    errors = []
    collected = 0
    save_interval = 50

    for i, (code, date_str) in enumerate(to_collect):
        try:
            df = get_full_trading_day_data(code, date_str)

            if df is not None and len(df) > 0:
                # DB에 저장
                _save_minute_data_to_db(cur, conn, code, date_str, df)
                collected += 1
            else:
                errors.append((code, date_str, 'empty'))

            progress.add((code, date_str))

        except Exception as e:
            errors.append((code, date_str, str(e)[:80]))
            time.sleep(1)

        # 진행률
        if (i + 1) % 20 == 0 or i == len(to_collect) - 1:
            elapsed = i + 1
            remaining = len(to_collect) - elapsed
            print(f'  {elapsed}/{len(to_collect)} ({collected}수집, {len(errors)}에러, '
                  f'남은: {remaining}건)')

        # 중간 저장
        if (i + 1) % save_interval == 0:
            MINUTE_PROGRESS_FILE.write_bytes(pickle.dumps(progress))
            conn.commit()

        # API rate limit
        time.sleep(0.3)

    # 최종 저장
    conn.commit()
    MINUTE_PROGRESS_FILE.write_bytes(pickle.dumps(progress))
    cur.close()
    conn.close()

    print(f'\nPhase C 완료: {collected}건 수집, {len(errors)}건 에러')
    if errors:
        for code, date_str, err in errors[:10]:
            print(f'  {code} {date_str}: {err}')


def _save_minute_data_to_db(cur, conn, stock_code, trade_date, df):
    """분봉 데이터를 minute_candles 테이블에 저장"""
    # 기존 데이터 삭제 (중복 방지)
    cur.execute(
        "DELETE FROM minute_candles WHERE stock_code = %s AND trade_date = %s",
        [stock_code, trade_date]
    )

    for idx, (_, row) in enumerate(df.iterrows()):
        try:
            # get_full_trading_day_data 반환 컬럼 매핑
            time_val = str(row.get('time', row.get('stck_cntg_hour', '')))
            close_val = int(float(row.get('close', row.get('stck_prpr', 0))))
            open_val = int(float(row.get('open', row.get('stck_oprc', 0))))
            high_val = int(float(row.get('high', row.get('stck_hgpr', 0))))
            low_val = int(float(row.get('low', row.get('stck_lwpr', 0))))
            volume_val = int(float(row.get('volume', row.get('cntg_vol', 0))))
            amount_val = int(float(row.get('amount', row.get('acml_tr_pbmn', 0))))

            # date 컬럼
            date_val = trade_date

            # datetime 컬럼
            datetime_val = None
            if len(time_val) >= 6:
                try:
                    datetime_val = datetime.strptime(
                        f'{trade_date}{time_val[:6]}', '%Y%m%d%H%M%S'
                    )
                except:
                    pass

            cur.execute("""
                INSERT INTO minute_candles
                    (stock_code, trade_date, idx, date, time, close, open, high, low,
                     volume, amount, datetime)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (stock_code, trade_date, idx) DO NOTHING
            """, [
                stock_code, trade_date, idx,
                date_val, time_val, close_val, open_val, high_val, low_val,
                volume_val, amount_val, datetime_val,
            ])
        except Exception:
            continue


# ============================================================
# Phase D: 시뮬레이션
# ============================================================
def phase_d_simulate(
    candidates_by_date,
    config=None,
    max_daily=5,
    verbose=True,
):
    """스크리너 후보 기반 시뮬레이션"""
    strategy = PricePositionStrategy(config=config)
    info = strategy.get_strategy_info()

    print('\n' + '=' * 80)
    print(f"스크리너 통합 시뮬레이션: {info['name']}")
    print('=' * 80)
    print(f"진입: 시가 대비 {info['entry_conditions']['pct_from_open']}, "
          f"{info['entry_conditions']['time_range']}, "
          f"요일: {info['entry_conditions']['weekdays']}")
    print(f"청산: 손절 {info['exit_conditions']['stop_loss']}, "
          f"익절 {info['exit_conditions']['take_profit']}")
    print(f"동시보유: {max_daily}종목")

    conn = get_pg_connection()
    cur = conn.cursor()

    # DB에 있는 거래일 확인
    cur.execute("SELECT DISTINCT trade_date FROM minute_candles ORDER BY trade_date")
    db_dates = set(row[0] for row in cur.fetchall())
    print(f'DB 거래일: {len(db_dates)}일')

    # 후보가 있고 DB에도 있는 날짜만
    sim_dates = sorted(d for d in candidates_by_date.keys() if d in db_dates)
    print(f'시뮬 대상: {len(sim_dates)}일')

    all_trades = []
    screener_stats = {'candidates': 0, 'db_hits': 0, 'days': 0}

    for day_idx, trade_date in enumerate(sim_dates):
        try:
            dt = datetime.strptime(trade_date, '%Y%m%d')
            weekday = dt.weekday()
        except:
            continue

        if verbose and day_idx % 20 == 0:
            print(f'  {day_idx}/{len(sim_dates)} ({trade_date}) '
                  f'거래 {len(all_trades)}건')

        candidate_codes = candidates_by_date[trade_date]
        screener_stats['candidates'] += len(candidate_codes)
        screener_stats['days'] += 1

        for stock_code in candidate_codes:
            try:
                cur.execute("""
                    SELECT idx, date, time, close, open, high, low, volume, amount, datetime
                    FROM minute_candles
                    WHERE stock_code = %s AND trade_date = %s
                    ORDER BY idx
                """, [stock_code, trade_date])
                rows = cur.fetchall()
                if len(rows) < 50:
                    continue

                screener_stats['db_hits'] += 1

                columns = ['idx', 'date', 'time', 'close', 'open', 'high',
                           'low', 'volume', 'amount', 'datetime']
                df = pd.DataFrame(rows, columns=columns)

                # 시가 계산 (09:00~09:03 봉)
                morning = df[
                    (df['time'].astype(str) >= '090000') &
                    (df['time'].astype(str) <= '090300')
                ]
                if len(morning) > 0:
                    day_open = float(morning.iloc[0]['open'])
                else:
                    day_open = float(df.iloc[0]['open'])

                if day_open <= 0:
                    continue

                traded = False
                for candle_idx in range(10, len(df) - 10):
                    if traded:
                        break

                    row = df.iloc[candle_idx]
                    current_time = str(row['time'])
                    current_price = float(row['close'])

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
                        df=df, candle_idx=candle_idx,
                    )
                    if not adv_ok:
                        continue

                    result = strategy.simulate_trade(df, candle_idx)
                    if result:
                        pct_from_open = (current_price / day_open - 1) * 100
                        all_trades.append({
                            'date': trade_date,
                            'stock_code': stock_code,
                            'weekday': weekday,
                            'pct_from_open': pct_from_open,
                            **result,
                        })
                        strategy.record_trade(stock_code, trade_date)
                        traded = True

            except Exception:
                continue

    cur.close()
    conn.close()

    # 결과 출력
    avg_cand = screener_stats['candidates'] / max(screener_stats['days'], 1)
    avg_hits = screener_stats['db_hits'] / max(screener_stats['days'], 1)
    print(f'\n스크리너 통계: 일평균 후보 {avg_cand:.1f}개, DB 존재 {avg_hits:.1f}개')
    print(f'총 거래: {len(all_trades)}건')

    if not all_trades:
        print('거래 없음')
        return

    trades_df = pd.DataFrame(all_trades)

    # 무제한 결과
    print_stats(trades_df, '무제한')

    # 동시보유 제한
    if max_daily > 0:
        limited_df = apply_daily_limit(trades_df, max_daily)
        print('\n' + '#' * 80)
        print(f'#  동시보유 {max_daily}종목 제한')
        print('#' * 80)
        print_stats(limited_df, f'동시보유 {max_daily}종목')

        # 비교 요약
        _print_comparison(trades_df, limited_df, max_daily)


# ============================================================
# 통계 출력
# ============================================================
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


def print_stats(trades_df, label):
    """거래 통계 출력"""
    if len(trades_df) == 0:
        print(f'\n[{label}] 거래 없음')
        return

    wins = (trades_df['result'] == 'WIN').sum()
    losses = (trades_df['result'] == 'LOSS').sum()
    total = len(trades_df)
    winrate = wins / total * 100
    total_pnl = trades_df['pnl'].sum()
    avg_pnl = trades_df['pnl'].mean()
    avg_win = trades_df[trades_df['result'] == 'WIN']['pnl'].mean() if wins else 0
    avg_loss = trades_df[trades_df['result'] == 'LOSS']['pnl'].mean() if losses else 0
    pl_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    print('\n' + '=' * 80)
    print(f'전체 통계 [{label}]')
    print('=' * 80)
    print(f'총 거래: {total}건 ({wins}승 {losses}패)')
    print(f'승률: {winrate:.1f}%')
    print(f'총 수익률: {total_pnl:+.1f}%')
    print(f'평균 수익률: {avg_pnl:+.2f}%')
    print(f'평균 승리: {avg_win:+.2f}% | 평균 손실: {avg_loss:.2f}%')
    print(f'손익비: {pl_ratio:.2f}:1')

    # 요일별
    print('\n' + '-' * 60)
    print(f'요일별 [{label}]')
    weekday_names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']
    for wd in sorted(trades_df['weekday'].unique()):
        f = trades_df[trades_df['weekday'] == wd]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        pnl = f['pnl'].sum()
        print(f'  {weekday_names[wd]}: {len(f)}건, {w}승 {len(f)-w}패, '
              f'{rate:.1f}%, {pnl:+.1f}%')

    # 시간대별
    print('\n' + '-' * 60)
    print(f'시간대별 [{label}]')
    trades_copy = trades_df.copy()
    trades_copy['hour'] = trades_copy['entry_time'].apply(
        lambda x: int(str(x)[:2]) if len(str(x)) >= 2 else 0
    )
    for h in sorted(trades_copy['hour'].unique()):
        f = trades_copy[trades_copy['hour'] == h]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        pnl = f['pnl'].sum()
        print(f'  {h}시: {len(f)}건, {w}승 {len(f)-w}패, {rate:.1f}%, {pnl:+.1f}%')

    # 월별
    print('\n' + '-' * 60)
    print(f'월별 [{label}]')
    trades_copy['month'] = trades_copy['date'].str[:6]
    for month in sorted(trades_copy['month'].unique()):
        f = trades_copy[trades_copy['month'] == month]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        pnl = f['pnl'].sum()
        avg = f['pnl'].mean()
        print(f'  {month}: {len(f)}건, {w}승 {len(f)-w}패, '
              f'{rate:.1f}%, 총{pnl:+.1f}%, 평균{avg:+.2f}%')

    # 청산 사유별
    print('\n' + '-' * 60)
    print(f'청산 사유별 [{label}]')
    for reason in trades_df['exit_reason'].unique():
        f = trades_df[trades_df['exit_reason'] == reason]
        w = (f['result'] == 'WIN').sum()
        rate = w / len(f) * 100
        pnl = f['pnl'].sum()
        print(f'  {reason}: {len(f)}건, {w}승 {len(f)-w}패, {rate:.1f}%, {pnl:+.1f}%')

    # 수익 예상
    dates = sorted(trades_df['date'].unique())
    num_months = max(len(set(d[:6] for d in dates)), 1)
    monthly_profit = (total_pnl / num_months) * 10000
    print(f'\n  기간: {dates[0]}~{dates[-1]} ({num_months}개월)')
    print(f'  월평균 거래: {total/num_months:.0f}건, '
          f'월평균 수익(100만원/건): {monthly_profit:+,.0f}원')


def _print_comparison(trades_df, limited_df, max_daily):
    u_total = len(trades_df)
    u_wins = (trades_df['result'] == 'WIN').sum()
    u_pnl = trades_df['pnl'].sum()
    l_total = len(limited_df)
    l_wins = (limited_df['result'] == 'WIN').sum() if l_total > 0 else 0
    l_pnl = limited_df['pnl'].sum() if l_total > 0 else 0

    print('\n' + '=' * 80)
    print('비교 요약')
    print('=' * 80)
    print(f"{'':>20} {'무제한':>15} {'최대 '+str(max_daily)+'종목':>15}")
    print('-' * 50)
    print(f"{'거래수':>20} {u_total:>14}건 {l_total:>14}건")
    print(f"{'승률':>20} {u_wins/u_total*100:>13.1f}% "
          f"{l_wins/l_total*100 if l_total else 0:>13.1f}%")
    print(f"{'총 수익률':>20} {u_pnl:>+13.1f}% {l_pnl:>+13.1f}%")
    print(f"{'평균 수익률':>20} {trades_df['pnl'].mean():>+13.2f}% "
          f"{limited_df['pnl'].mean() if l_total else 0:>+13.2f}%")


# ============================================================
# Main
# ============================================================
def main():
    parser = argparse.ArgumentParser(description='스크리너 통합 데이터 수집 및 시뮬레이션')
    parser.add_argument('--phase', default='ABCD',
                        help='실행할 Phase (A/B/C/D 조합, 기본: ABCD)')
    parser.add_argument('--start', default='20250224', help='시작일 (기본: 20250224)')
    parser.add_argument('--end', default='20260223', help='종료일 (기본: 20260223)')

    # 스크리너 설정
    parser.add_argument('--screener-top', type=int, default=60,
                        help='거래대금 상위 N개')
    parser.add_argument('--screener-min-amount', type=float, default=1e9,
                        help='최소 거래대금 (원)')
    parser.add_argument('--screener-max-gap', type=float, default=3.0)
    parser.add_argument('--screener-min-price', type=int, default=5000)
    parser.add_argument('--screener-max-price', type=int, default=500000)

    # 전략 설정
    parser.add_argument('--min-pct', type=float, default=1.0)
    parser.add_argument('--max-pct', type=float, default=3.0)
    parser.add_argument('--start-hour', type=int, default=9)
    parser.add_argument('--end-hour', type=int, default=12)
    parser.add_argument('--stop-loss', type=float, default=-4.0)
    parser.add_argument('--take-profit', type=float, default=5.0)
    parser.add_argument('--max-volatility', type=float, default=0.8)
    parser.add_argument('--max-momentum', type=float, default=2.0)
    parser.add_argument('--weekdays', default=None)
    parser.add_argument('--max-daily', type=int, default=5)

    # 기타
    parser.add_argument('--no-resume', action='store_true',
                        help='기존 데이터 무시하고 처음부터')
    parser.add_argument('--quiet', action='store_true')

    args = parser.parse_args()
    phases = args.phase.upper()

    print('=' * 80)
    print(f'스크리너 통합 시뮬레이션 파이프라인')
    print(f'Phase: {phases} | 기간: {args.start} ~ {args.end}')
    print('=' * 80)

    daily_data = None
    candidates = None

    # Phase A
    if 'A' in phases:
        daily_data = phase_a_collect_daily(
            start_date=args.start,
            end_date=args.end,
            resume=not args.no_resume,
        )

    # Phase B
    if 'B' in phases:
        if daily_data is None:
            if DAILY_DATA_FILE.exists():
                print('\n일봉 데이터 로드 중...')
                daily_data = pickle.loads(DAILY_DATA_FILE.read_bytes())
                print(f'  {len(daily_data)}종목 로드')
            else:
                print('ERROR: 일봉 데이터 없음. Phase A를 먼저 실행하세요.')
                sys.exit(1)

        candidates = phase_b_select_candidates(
            daily_data,
            top_n=args.screener_top,
            min_price=args.screener_min_price,
            max_price=args.screener_max_price,
            min_amount=args.screener_min_amount,
            max_gap_pct=args.screener_max_gap,
        )

    # Phase C
    if 'C' in phases:
        if candidates is None:
            if CANDIDATES_FILE.exists():
                candidates = pickle.loads(CANDIDATES_FILE.read_bytes())
                print(f'\n후보 데이터 로드: {len(candidates)}거래일')
            else:
                print('ERROR: 후보 데이터 없음. Phase B를 먼저 실행하세요.')
                sys.exit(1)

        phase_c_collect_minute_data(
            candidates,
            resume=not args.no_resume,
        )

    # Phase D
    if 'D' in phases:
        if candidates is None:
            if CANDIDATES_FILE.exists():
                candidates = pickle.loads(CANDIDATES_FILE.read_bytes())
                print(f'\n후보 데이터 로드: {len(candidates)}거래일')
            else:
                print('ERROR: 후보 데이터 없음. Phase B를 먼저 실행하세요.')
                sys.exit(1)

        strategy_config = {
            'min_pct_from_open': args.min_pct,
            'max_pct_from_open': args.max_pct,
            'entry_start_hour': args.start_hour,
            'entry_end_hour': args.end_hour,
            'stop_loss_pct': args.stop_loss,
            'take_profit_pct': args.take_profit,
            'max_pre_volatility': args.max_volatility,
            'max_pre20_momentum': args.max_momentum,
        }
        if args.weekdays is not None:
            strategy_config['allowed_weekdays'] = [
                int(d) for d in args.weekdays.split(',')
            ]

        phase_d_simulate(
            candidates,
            config=strategy_config,
            max_daily=args.max_daily,
            verbose=not args.quiet,
        )

    print('\nDone!')


if __name__ == '__main__':
    main()
