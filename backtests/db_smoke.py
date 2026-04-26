"""DB smoke test - 실제 KIS 데이터로 다중 전략 엔진 실행.

5 종목 × 4 주 분봉으로 대표 전략 6개 (intraday 4 + overnight 2) 단발 실행.
합성 데이터 벤치마크에서 검출 못하는 이슈 (NaN, 빈 거래일, hhmm 형식 등) 노출 목적.
"""
import time

from backtests.common.data_loader import load_minute_df, load_daily_df
from backtests.common.engine import BacktestEngine
from backtests.strategies.orb import ORBStrategy
from backtests.strategies.vwap_bounce import VWAPBounceStrategy
from backtests.strategies.volume_surge import VolumeSurgeStrategy
from backtests.strategies.intraday_pullback import IntradayPullbackStrategy
from backtests.strategies.closing_drift import ClosingDriftStrategy
from backtests.strategies.close_to_open import CloseToOpenStrategy
from backtests.strategies.breakout_52w import Breakout52wStrategy
from backtests.strategies.trend_followthrough import TrendFollowthroughStrategy


# 거래대금 상위 5종목 (대표 KOSPI/KOSDAQ)
UNIVERSE = ["005930", "000660", "035720", "035420", "068270"]
# 005930 삼성전자, 000660 SK하이닉스, 035720 카카오, 035420 네이버, 068270 셀트리온

# 분봉 4주 + daily 1년 (overnight 전략용 history)
MINUTE_START = "20260301"
MINUTE_END = "20260424"
DAILY_START = "20250101"  # 일봉 history 충분


def main():
    print(f"Loading data: minute {MINUTE_START}~{MINUTE_END}, daily {DAILY_START}~{MINUTE_END}")
    print(f"Universe: {UNIVERSE}")
    t0 = time.perf_counter()
    minute_df = load_minute_df(UNIVERSE, MINUTE_START, MINUTE_END)
    daily_df = load_daily_df(UNIVERSE, DAILY_START, MINUTE_END)
    print(f"loaded in {time.perf_counter()-t0:.1f}s - "
          f"minute={len(minute_df):,} rows, daily={len(daily_df):,} rows")

    if minute_df.empty:
        print("ERROR: minute data empty")
        return

    # per-code split
    minute_by_code = {
        c: minute_df[minute_df["stock_code"] == c].reset_index(drop=True)
        for c in UNIVERSE
    }
    daily_by_code = {
        c: daily_df[daily_df["stock_code"] == c].reset_index(drop=True)
        for c in UNIVERSE
    }

    # 종목별 분봉 가용성 확인
    print("\nPer-stock data availability:")
    for c in UNIVERSE:
        m = minute_by_code[c]
        d = daily_by_code[c]
        print(f"  {c}: minute={len(m):,} bars ({m['trade_date'].nunique()} days), "
              f"daily={len(d)} rows")

    nonempty = [c for c in UNIVERSE if len(minute_by_code[c]) > 0]
    if not nonempty:
        print("ERROR: no stock has minute data")
        return

    strategies = [
        ("orb", ORBStrategy()),
        ("vwap_bounce", VWAPBounceStrategy()),
        ("volume_surge", VolumeSurgeStrategy()),
        ("intraday_pullback", IntradayPullbackStrategy()),
        ("closing_drift", ClosingDriftStrategy()),
        ("close_to_open", CloseToOpenStrategy()),
        ("breakout_52w", Breakout52wStrategy(lookback_days=60)),
        ("trend_followthrough", TrendFollowthroughStrategy()),
    ]

    print(f"\n{'strategy':<22} {'elapsed':>8} {'trades':>7} "
          f"{'return':>9} {'mdd':>7} {'win%':>7} {'sharpe':>8}")
    print("-" * 75)

    for name, strat in strategies:
        engine = BacktestEngine(
            strategy=strat,
            initial_capital=100_000_000,
            universe=nonempty,
            minute_df_by_code={c: minute_by_code[c] for c in nonempty},
            daily_df_by_code={c: daily_by_code[c] for c in nonempty},
        )
        t0 = time.perf_counter()
        try:
            result = engine.run()
        except Exception as e:
            print(f"{name:<22} ERROR: {type(e).__name__}: {e}")
            continue
        elapsed = time.perf_counter() - t0
        m = result.metrics
        print(
            f"{name:<22} {elapsed:>7.1f}s {len(result.trades):>7d} "
            f"{m.get('total_return', 0):>8.2%} "
            f"{m.get('mdd', 0):>6.2%} "
            f"{m.get('win_rate', 0):>6.1%} "
            f"{m.get('sharpe', 0):>8.2f}"
        )


if __name__ == "__main__":
    main()
