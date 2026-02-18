#!/usr/bin/env python3
"""
고속 배치 신호 리플레이 스크립트 (직접 함수 호출 방식)

subprocess 대신 signal_replay 모듈을 직접 import하여 호출합니다.
- Python 프로세스 생성 오버헤드 제거
- 리소스(API, 필터, 캐시) 한 번만 초기화 후 재사용
- 3~5배 속도 향상 예상

사용법:
python batch_signal_replay_fast.py --start 20250901 --end 20260130
python batch_signal_replay_fast.py -s 20250901 -e 20260130 --advanced-filter
"""

import argparse
import sys
import os
import json
import time as time_module
from datetime import datetime, timedelta, time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from multiprocessing import cpu_count
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import threading

# UTF-8 인코딩 설정
sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# 프로젝트 루트 디렉토리를 sys.path에 추가
project_root = os.path.dirname(os.path.abspath(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 환경 변수로 조용한 모드 활성화
os.environ['BATCH_QUIET_MODE'] = '1'

import pandas as pd
import logging

# stdout 필터링 클래스 (불필요한 print 메시지 숨기기)
class _QuietStdout:
    """배치 모드에서 특정 메시지만 출력하는 stdout wrapper"""
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.consecutive_newlines = 0
        # 허용할 메시지 패턴들 (진행 상황, 에러, 결과 요약 등)
        self.allowed_patterns = [
            '====', '📅', '⏳', '✅ 종목명', '✅ 리소스', '🔄',
            '✅ [', '⬚ [', '❌ [', '📊 배치', '💰', '📈', '⏱️', '⚡',
            '🔰', '🤖', '⚠️ 고급', '⚠️ ML', '필터 통계',
            '실행 중:', '완료:', 'python batch', '🚀'
        ]
        # 차단할 메시지 패턴들
        self.blocked_patterns = [
            '📝 패턴', '[패턴로거]', '[스킵]', '[경고]',
            '✅ 0', '📊 0', '🚫', '매수 신호 감지', '패턴 필터 통과',
            '약한 패턴', '거래량', '가격변화'
        ]

    def write(self, text):
        if not text:
            return

        # 줄바꿈만 있는 경우 - 연속 2개까지만 허용
        if text == '\n' or text.isspace():
            if self.consecutive_newlines < 2:
                self.original_stdout.write(text)
                self.consecutive_newlines += 1
            return

        # 차단 패턴 확인
        for pattern in self.blocked_patterns:
            if pattern in text:
                return  # 차단

        # 허용된 패턴 확인
        for pattern in self.allowed_patterns:
            if pattern in text:
                self.consecutive_newlines = 0  # 메시지 출력 시 카운터 리셋
                self.original_stdout.write(text)
                return

        # 그 외에는 무시

    def flush(self):
        self.original_stdout.flush()

    def __getattr__(self, name):
        return getattr(self.original_stdout, name)

# stdout을 필터링 wrapper로 교체
_original_stdout = sys.stdout
sys.stdout = _QuietStdout(_original_stdout)

# 배치 실행 시 모든 INFO/DEBUG 로그 완전히 비활성화
# WARNING 미만의 모든 로그를 전역적으로 차단
logging.disable(logging.INFO)

# 루트 로거 설정
logging.basicConfig(level=logging.CRITICAL, format='%(message)s', force=True)
logging.getLogger().setLevel(logging.CRITICAL)

from utils.data_cache import DataCache, DailyDataCache
from utils.signal_replay import (
    simulate_trades,
    calculate_trading_signals_once,
    calculate_max_concurrent_holdings,
    load_stock_names,
    PROFIT_TAKE_RATE,
    STOP_LOSS_RATE,
    USE_DYNAMIC_PROFIT_LOSS
)
from utils.signal_replay_utils import (
    get_stocks_with_selection_date,
    calculate_selection_date_stats,
    to_csv_rows
)
from core.timeframe_converter import TimeFrameConverter
from config.settings import load_trading_config
from config.market_hours import MarketHours

# 배치용 조용한 로거 (모든 로그 숨기기)
logger = logging.getLogger('batch_replay')
logger.setLevel(logging.CRITICAL)

# simulate_trades에 전달할 조용한 로거 (아무것도 출력 안함)
_quiet_logger = logging.getLogger('quiet_simulate')
_quiet_logger.setLevel(logging.CRITICAL)
_quiet_logger.handlers = []
_quiet_logger.addHandler(logging.NullHandler())
_quiet_logger.propagate = False


class BatchReplayContext:
    """배치 리플레이에서 공유되는 리소스를 관리하는 컨텍스트 클래스"""

    def __init__(self, advanced_filter: bool = False, ml_filter: bool = False,
                 ml_model_path: str = "ml_model.pkl", ml_threshold: float = None):
        self.minute_cache = DataCache()
        self.daily_cache = DailyDataCache()
        self.stock_names = load_stock_names()
        self.trading_config = load_trading_config()

        # 고급 필터 초기화
        self.advanced_filter_enabled = advanced_filter
        self.advanced_filter_manager = None
        if advanced_filter:
            try:
                from core.indicators.advanced_filters import AdvancedFilterManager
                self.advanced_filter_manager = AdvancedFilterManager()
                active_filters = self.advanced_filter_manager.get_active_filters()
                print(f"🔰 고급 필터 활성화: {', '.join(active_filters) if active_filters else '없음'}")
            except Exception as e:
                print(f"⚠️ 고급 필터 초기화 실패: {e}")
                self.advanced_filter_enabled = False

        # ML 필터 초기화
        self.ml_filter_enabled = ml_filter
        self.ml_model = None
        self.ml_feature_names = None
        self.ml_threshold = ml_threshold or 0.5
        if ml_filter:
            try:
                from apply_ml_filter import load_ml_model
                self.ml_model, self.ml_feature_names = load_ml_model(ml_model_path)
                if self.ml_model is None:
                    print("⚠️ ML 모델 로드 실패 - ML 필터 비활성화")
                    self.ml_filter_enabled = False
                else:
                    print(f"🤖 ML 필터 활성화 (임계값: {self.ml_threshold:.1%})")
            except Exception as e:
                print(f"⚠️ ML 모델 로드 실패: {e}")
                self.ml_filter_enabled = False

        # 스레드 안전을 위한 락
        self._lock = threading.Lock()

    def load_pattern_data_cache(self, date_str: str) -> Dict:
        """패턴 데이터 캐시 로드"""
        pattern_data_cache = {}
        if self.ml_filter_enabled:
            try:
                pattern_log_file = Path(f"pattern_data_log/pattern_data_{date_str}.jsonl")
                if pattern_log_file.exists():
                    with open(pattern_log_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            if line.strip():
                                try:
                                    record = json.loads(line)
                                    pattern_id = record.get('pattern_id', '')
                                    if pattern_id:
                                        pattern_data_cache[pattern_id] = record
                                except:
                                    pass
            except Exception:
                pass  # 패턴 데이터 로드 실패는 조용히 무시
        return pattern_data_cache


def parse_date(date_str):
    """날짜 문자열을 datetime 객체로 변환"""
    try:
        return datetime.strptime(date_str, '%Y%m%d')
    except ValueError:
        raise argparse.ArgumentTypeError(f"Invalid date format: {date_str}. Use YYYYMMDD format.")


def generate_date_range(start_date, end_date):
    """시작일부터 종료일까지의 평일 날짜 리스트 생성"""
    dates = []
    current = start_date
    while current <= end_date:
        if current.weekday() < 5:  # 월-금
            dates.append(current.strftime('%Y%m%d'))
        current += timedelta(days=1)
    return dates


def process_single_stock(
    stock_code: str,
    date_str: str,
    stock_selection_map: Dict[str, str],
    ctx: BatchReplayContext,
    pattern_data_cache: Dict
) -> Tuple[str, List[Dict], pd.DataFrame, List[Dict]]:
    """단일 종목 처리 함수"""
    try:
        df_1min = None

        # DuckDB 캐시에서 데이터 로드 시도
        cached_data = ctx.minute_cache.load_data(stock_code, date_str)

        if cached_data is not None and not cached_data.empty:
            try:
                if 'datetime' in cached_data.columns:
                    cached_data['datetime'] = pd.to_datetime(cached_data['datetime'])

                    # 시장 시간 검증
                    target_date = datetime.strptime(date_str, '%Y%m%d')
                    market_hours = MarketHours.get_market_hours('KRX', target_date)
                    market_open_time = market_hours['market_open']
                    market_close_time = market_hours['market_close']

                    times = cached_data['datetime'].dt.time
                    has_morning = any(t >= market_open_time for t in times)
                    check_time = time(market_close_time.hour - 1, 0)
                    has_afternoon = any(t >= check_time for t in times)

                    if has_morning and has_afternoon:
                        df_1min = cached_data
            except Exception as e:
                logger.debug(f"[{stock_code}] 캐시 검증 실패: {e}")

        if df_1min is None:
            # 캐시가 없으면 건너뜀 (API 호출 없이)
            return stock_code, [], pd.DataFrame(), []

        # 3분봉 변환
        df_3min = TimeFrameConverter.convert_to_3min_data(df_1min)
        if df_3min is None or df_3min.empty:
            return stock_code, [], pd.DataFrame(), []

        # 거래 시뮬레이션 실행
        selection_date = stock_selection_map.get(stock_code)
        simulation_result = simulate_trades(
            df_3min, df_1min,
            logger=_quiet_logger,
            stock_code=stock_code,
            selection_date=selection_date,
            simulation_date=date_str,
            ml_filter_enabled=ctx.ml_filter_enabled,
            ml_model=ctx.ml_model,
            ml_feature_names=ctx.ml_feature_names,
            ml_threshold=ctx.ml_threshold,
            pattern_data_cache=pattern_data_cache,
            advanced_filter_enabled=ctx.advanced_filter_enabled,
            advanced_filter_manager=ctx.advanced_filter_manager
        )

        # 반환값 처리
        if isinstance(simulation_result, dict):
            trades = simulation_result.get('trades', [])
            missed_opportunities = simulation_result.get('missed_opportunities', [])
        else:
            trades = simulation_result
            missed_opportunities = []

        return stock_code, trades, df_1min, missed_opportunities

    except Exception as e:
        logger.debug(f"[{stock_code}] 처리 실패: {e}")
        return stock_code, [], pd.DataFrame(), []


def process_single_date(
    date_str: str,
    ctx: BatchReplayContext,
    output_dir: str,
    time_range: str = "9:00-16:00"
) -> Tuple[bool, str, Dict]:
    """단일 날짜 처리 함수"""
    try:
        # 해당 날짜의 종목 조회
        stock_selection_map = get_stocks_with_selection_date(date_str)
        codes = list(stock_selection_map.keys())

        if not codes:
            return True, date_str, {'trades': 0, 'wins': 0, 'losses': 0}

        # 패턴 데이터 캐시 로드 (ML 필터용)
        pattern_data_cache = ctx.load_pattern_data_cache(date_str)

        # 종목별 병렬 처리
        all_trades: Dict[str, List[Dict]] = {}
        all_missed_opportunities: Dict[str, List[Dict]] = {}

        with ThreadPoolExecutor(max_workers=10) as executor:
            future_to_stock = {
                executor.submit(
                    process_single_stock,
                    code, date_str, stock_selection_map, ctx, pattern_data_cache
                ): code for code in codes
            }

            for future in as_completed(future_to_stock):
                try:
                    result = future.result()
                    if len(result) == 4:
                        processed_code, trades, _, missed = result
                        all_trades[processed_code] = trades
                        all_missed_opportunities[processed_code] = missed
                except Exception as e:
                    stock_code = future_to_stock[future]
                    all_trades[stock_code] = []
                    all_missed_opportunities[stock_code] = []

        # 결과 집계
        all_completed_trades = [trade for trades in all_trades.values() for trade in trades]
        total_wins = sum(1 for trade in all_completed_trades if trade.get('profit_rate', 0) > 0 and trade.get('sell_time'))
        total_losses = sum(1 for trade in all_completed_trades if trade.get('profit_rate', 0) <= 0 and trade.get('sell_time'))
        max_concurrent = calculate_max_concurrent_holdings(all_trades)

        # 결과 파일 저장
        save_result_file(
            date_str, all_trades, all_missed_opportunities,
            stock_selection_map, output_dir, time_range, max_concurrent
        )

        return True, date_str, {
            'trades': len(all_completed_trades),
            'wins': total_wins,
            'losses': total_losses
        }

    except Exception as e:
        print(f"❌ [{date_str}] 처리 오류: {e}")
        return False, date_str, {'trades': 0, 'wins': 0, 'losses': 0}


def save_result_file(
    date_str: str,
    all_trades: Dict[str, List[Dict]],
    all_missed_opportunities: Dict[str, List[Dict]],
    stock_selection_map: Dict[str, str],
    output_dir: str,
    time_range: str,
    max_concurrent: int
):
    """결과 파일 저장"""
    os.makedirs(output_dir, exist_ok=True)

    start_time = time_range.split('-')[0]
    hour = start_time.split(':')[0]
    minute = start_time.split(':')[1] if ':' in start_time else '0'
    time_parts = f"{hour}_{minute}_0"
    txt_filename = os.path.join(output_dir, f"signal_new2_replay_{date_str}_{time_parts}.txt")

    all_completed_trades = [trade for trades in all_trades.values() for trade in trades]
    total_wins = sum(1 for trade in all_completed_trades if trade.get('profit_rate', 0) > 0 and trade.get('sell_time'))
    total_losses = sum(1 for trade in all_completed_trades if trade.get('profit_rate', 0) <= 0 and trade.get('sell_time'))

    # selection_date 이후 승패 계산
    selection_date_wins = 0
    selection_date_losses = 0

    for stock_code, trades in all_trades.items():
        selection_date = stock_selection_map.get(stock_code)
        if selection_date and selection_date != "알수없음":
            try:
                if len(selection_date) >= 19:
                    selection_dt = datetime.strptime(selection_date[:19], '%Y-%m-%d %H:%M:%S')
                elif len(selection_date) >= 16:
                    selection_dt = datetime.strptime(selection_date[:16], '%Y-%m-%d %H:%M')
                else:
                    selection_dt = datetime.strptime(selection_date[:10], '%Y-%m-%d')

                for trade in trades:
                    if trade.get('sell_time'):
                        buy_time_str = trade.get('buy_time', '')
                        if buy_time_str:
                            try:
                                trade_datetime_str = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:8]} {buy_time_str}:00"
                                trade_dt = datetime.strptime(trade_datetime_str, '%Y-%m-%d %H:%M:%S')

                                if trade_dt >= selection_dt:
                                    if trade.get('profit_rate', 0) > 0:
                                        selection_date_wins += 1
                                    else:
                                        selection_date_losses += 1
                            except:
                                if trade.get('profit_rate', 0) > 0:
                                    selection_date_wins += 1
                                else:
                                    selection_date_losses += 1
            except:
                for trade in trades:
                    if trade.get('sell_time'):
                        if trade.get('profit_rate', 0) > 0:
                            selection_date_wins += 1
                        else:
                            selection_date_losses += 1
        else:
            for trade in trades:
                if trade.get('sell_time'):
                    if trade.get('profit_rate', 0) > 0:
                        selection_date_wins += 1
                    else:
                        selection_date_losses += 1

    # 12시 이전 매수 통계
    market_hours = MarketHours.get_market_hours('KRX', datetime.strptime(date_str, '%Y%m%d'))
    buy_cutoff_hour = market_hours.get('buy_cutoff_hour', 12)

    morning_wins = 0
    morning_losses = 0
    morning_trades_details = []

    for trade in all_completed_trades:
        if trade.get('sell_time'):
            buy_time_str = trade.get('buy_time', '')
            stock_code = trade.get('stock_code', '')
            if buy_time_str and stock_code:
                try:
                    buy_hour = int(buy_time_str.split(':')[0])
                    if buy_hour < buy_cutoff_hour:
                        profit_rate = trade.get('profit_rate', 0)
                        if profit_rate > 0:
                            morning_wins += 1
                            status_icon = "🟢"
                        else:
                            morning_losses += 1
                            status_icon = "🔴"

                        morning_trades_details.append({
                            'stock_code': stock_code,
                            'buy_time': buy_time_str,
                            'profit_rate': profit_rate,
                            'status_icon': status_icon
                        })
                except (ValueError, IndexError):
                    continue

    # 파일 작성
    lines = []
    total_trades = total_wins + total_losses

    # 종목명 로드 (오전 거래 상세에서 사용)
    stock_names = load_stock_names()

    if total_trades > 0:
        profit_loss_ratio = PROFIT_TAKE_RATE / STOP_LOSS_RATE
        investment_per_trade = 1_000_000

        total_profit = 0
        total_loss = 0
        for trade in all_completed_trades:
            if trade.get('sell_time'):
                profit_rate = trade.get('profit_rate', 0)
                if profit_rate > 0:
                    total_profit += investment_per_trade * (profit_rate / 100)
                else:
                    total_loss += investment_per_trade * abs(profit_rate / 100)

        net_profit = total_profit - total_loss
        net_profit_rate = (net_profit / investment_per_trade) * 100

        lines.append(f"=== 📊 거래 설정 ===")
        if USE_DYNAMIC_PROFIT_LOSS:
            lines.append(f"🔧 동적 손익비: 패턴별 최적화 적용")
        else:
            lines.append(f"손익비: {profit_loss_ratio:.1f}:1 (익절 +{PROFIT_TAKE_RATE:.1f}% / 손절 -{STOP_LOSS_RATE:.1f}%)")
        lines.append(f"거래당 투자금: {investment_per_trade:,}원")
        lines.append("")
        lines.append(f"=== 💰 당일 수익 요약 ===")
        lines.append(f"총 거래: {total_trades}건 ({total_wins}승 {total_losses}패)")
        lines.append(f"총 수익금: {net_profit:+,.0f}원 ({net_profit_rate:+.1f}%)")
        lines.append(f"  ㄴ 승리 수익: +{total_profit:,.0f}원")
        lines.append(f"  ㄴ 손실 금액: -{total_loss:,.0f}원")
        lines.append("")

    lines.append(f"=== 총 승패: {total_wins}승 {total_losses}패 ===")
    lines.append(f"=== selection_date 이후 승패: {selection_date_wins}승 {selection_date_losses}패 ===")
    lines.append(f"=== 📊 최대 동시 보유 종목 수: {max_concurrent}개 ===")

    # 오전 거래 상세 섹션
    if morning_wins + morning_losses > 0:
        morning_total = morning_wins + morning_losses
        morning_win_rate = (morning_wins / morning_total * 100) if morning_total > 0 else 0

        # 오전 거래 수익 계산
        morning_profit = 0
        morning_loss = 0
        for detail in morning_trades_details:
            profit_rate = detail['profit_rate']
            if profit_rate > 0:
                morning_profit += investment_per_trade * (profit_rate / 100)
            else:
                morning_loss += investment_per_trade * abs(profit_rate / 100)

        morning_net_profit = morning_profit - morning_loss
        morning_net_profit_rate = (morning_net_profit / investment_per_trade) * 100

        lines.append("")
        lines.append(f"=== 🌅 {buy_cutoff_hour}시 이전 매수 종목: {morning_wins}승 {morning_losses}패 (승률 {morning_win_rate:.1f}%) ===")
        lines.append(f"총 수익금: {morning_net_profit:+,.0f}원 ({morning_net_profit_rate:+.1f}%)")
        lines.append(f"  ㄴ 승리 수익: +{morning_profit:,.0f}원")
        lines.append(f"  ㄴ 손실 금액: -{morning_loss:,.0f}원")
        lines.append("")

        # 종목별 상세 (시간순 정렬)
        morning_trades_details.sort(key=lambda x: x['buy_time'])
        for detail in morning_trades_details:
            stock_code = detail['stock_code']
            stock_name = stock_names.get(stock_code, stock_code)
            buy_time = detail['buy_time']
            profit_rate = detail['profit_rate']
            icon = detail['status_icon']

            lines.append(f"   {icon} {stock_code}({stock_name}) {buy_time} 매수 → {profit_rate:+.2f}%")

    # 종목별 상세 거래 내역
    for stock_code, trades in all_trades.items():
        if trades:
            stock_name = stock_names.get(stock_code, stock_code)
            lines.append("")
            lines.append(f"=== {stock_code} {stock_name} ===")

            for trade in trades:
                buy_time = trade.get('buy_time', '')
                sell_time = trade.get('sell_time', '')
                buy_price = trade.get('buy_price', 0)
                sell_price = trade.get('sell_price', 0)
                profit_rate = trade.get('profit_rate', 0)
                sell_reason = trade.get('sell_reason', '')

                profit_sign = '+' if profit_rate > 0 else ''
                lines.append(f"{buy_time} 매수[pullback_pattern] @{buy_price:,} → {sell_time} 매도[{sell_reason}] @{sell_price:,} ({profit_sign}{profit_rate:.2f}%)")

    with open(txt_filename, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="고속 배치 신호 리플레이 (직접 함수 호출 방식)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python batch_signal_replay_fast.py -s 20250901 -e 20260130
  python batch_signal_replay_fast.py -s 20250901 -e 20260130 --advanced-filter
  python batch_signal_replay_fast.py -s 20250901 -e 20260130 --workers 8
        """
    )

    parser.add_argument('--start', '-s', type=parse_date, required=True, help='시작 날짜 (YYYYMMDD)')
    parser.add_argument('--end', '-e', type=parse_date, required=True, help='종료 날짜 (YYYYMMDD)')
    parser.add_argument('--time-range', '-t', type=str, default='9:00-16:00', help='시간 범위')
    parser.add_argument('--workers', '-w', type=int, default=None, help='병렬 날짜 처리 수')
    parser.add_argument('--output-dir', '-o', type=str, default=None, help='출력 디렉토리 (기본값: signal_replay_log, --advanced-filter 시 signal_replay_log_advanced)')
    parser.add_argument('--advanced-filter', action='store_true', help='고급 필터 적용')
    parser.add_argument('--ml-filter', action='store_true', help='ML 필터 적용')
    parser.add_argument('--ml-model', default='ml_model.pkl', help='ML 모델 경로')
    parser.add_argument('--ml-threshold', type=float, default=None, help='ML 임계값')
    parser.add_argument('--serial', action='store_true', help='순차 실행')

    args = parser.parse_args()

    # 출력 디렉토리 자동 설정
    if args.output_dir is None:
        if args.advanced_filter:
            args.output_dir = 'signal_replay_log_advanced'
        elif args.ml_filter:
            args.output_dir = 'signal_replay_log_ml'
        else:
            args.output_dir = 'signal_replay_log'

    if args.start > args.end:
        print("❌ 오류: 시작 날짜가 종료 날짜보다 늦습니다.")
        sys.exit(1)

    dates = generate_date_range(args.start, args.end)

    if not dates:
        print("처리할 날짜가 없습니다.")
        sys.exit(1)

    # 병렬 작업 수 결정
    if args.serial:
        max_workers = 1
    else:
        max_workers = args.workers or max(1, min(cpu_count() // 2, 4))

    print("=" * 70)
    print("🚀 고속 배치 신호 리플레이 (직접 함수 호출 방식)")
    print("=" * 70)
    print(f"📅 처리 기간: {dates[0]} ~ {dates[-1]} ({len(dates)}일)")
    print(f"⚙️ 날짜 병렬 처리: {max_workers}개")
    print(f"📁 출력 디렉토리: {args.output_dir}")
    if args.advanced_filter:
        print(f"🔰 고급 필터: 활성화")
    if args.ml_filter:
        print(f"🤖 ML 필터: 활성화")
    print("=" * 70)

    # 컨텍스트 초기화 (리소스 한 번만 로드)
    print("\n⏳ 리소스 초기화 중...")
    start_time = time_module.time()

    ctx = BatchReplayContext(
        advanced_filter=args.advanced_filter,
        ml_filter=args.ml_filter,
        ml_model_path=args.ml_model,
        ml_threshold=args.ml_threshold
    )

    init_time = time_module.time() - start_time
    print(f"✅ 리소스 초기화 완료 ({init_time:.1f}초)")

    # 날짜별 처리
    print(f"\n🔄 {len(dates)}일 처리 시작...\n")
    process_start = time_module.time()

    success_count = 0
    failed_dates = []
    total_stats = {'trades': 0, 'wins': 0, 'losses': 0}

    if max_workers == 1:
        # 순차 실행
        for i, date in enumerate(dates, 1):
            success, result_date, stats = process_single_date(
                date, ctx, args.output_dir, args.time_range
            )

            if success:
                success_count += 1
                total_stats['trades'] += stats['trades']
                total_stats['wins'] += stats['wins']
                total_stats['losses'] += stats['losses']

                if stats['trades'] > 0:
                    print(f"✅ [{i}/{len(dates)}] {date}: {stats['wins']}승 {stats['losses']}패")
                else:
                    print(f"⬚ [{i}/{len(dates)}] {date}: 거래 없음")
            else:
                failed_dates.append(result_date)
                print(f"❌ [{i}/{len(dates)}] {date}: 처리 실패")
    else:
        # 병렬 실행
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_date = {
                executor.submit(
                    process_single_date, date, ctx, args.output_dir, args.time_range
                ): date for date in dates
            }

            completed = 0
            for future in as_completed(future_to_date):
                completed += 1
                date = future_to_date[future]

                try:
                    success, result_date, stats = future.result()

                    if success:
                        success_count += 1
                        total_stats['trades'] += stats['trades']
                        total_stats['wins'] += stats['wins']
                        total_stats['losses'] += stats['losses']

                        if stats['trades'] > 0:
                            print(f"✅ [{completed}/{len(dates)}] {date}: {stats['wins']}승 {stats['losses']}패")
                        else:
                            print(f"⬚ [{completed}/{len(dates)}] {date}: 거래 없음")
                    else:
                        failed_dates.append(result_date)
                        print(f"❌ [{completed}/{len(dates)}] {date}: 처리 실패")

                except Exception as e:
                    failed_dates.append(date)
                    print(f"❌ [{completed}/{len(dates)}] {date}: {e}")

    process_time = time_module.time() - process_start
    total_time = time_module.time() - start_time

    # 시간을 분:초 형식으로 변환하는 함수
    def format_time(seconds):
        """초를 분:초 형식으로 변환 (예: 125.3초 → 2분 5초)"""
        mins = int(seconds // 60)
        secs = int(seconds % 60)
        if mins > 0:
            return f"{mins}분 {secs}초"
        else:
            return f"{secs}초"

    # 결과 요약
    print("\n" + "=" * 70)
    print("📊 배치 처리 결과")
    print("=" * 70)
    print(f"✅ 처리 완료: {success_count}/{len(dates)}일")

    # 완료된 거래 수 계산
    completed_trades = total_stats['wins'] + total_stats['losses']
    uncompleted_trades = total_stats['trades'] - completed_trades

    print(f"💰 총 매수 신호: {total_stats['trades']}건")
    print(f"   ㄴ 완료된 거래: {completed_trades}건 ({total_stats['wins']}승 {total_stats['losses']}패)")
    if uncompleted_trades > 0:
        print(f"   ㄴ 미체결: {uncompleted_trades}건 (장 마감 시점 매수)")

    if total_stats['trades'] > 0:
        # 전략 성과 평가: 모든 매수 신호 기준 승률
        signal_win_rate = total_stats['wins'] / total_stats['trades'] * 100
        print(f"📈 신호 승률: {signal_win_rate:.1f}% (전략 성과 - 모든 매수 신호 기준)")

        # 실시간 검증용: 완료된 거래 기준 승률
        if completed_trades > 0:
            completed_win_rate = total_stats['wins'] / completed_trades * 100
            print(f"📈 체결 승률: {completed_win_rate:.1f}% (실시간 비교용 - 완료된 거래 기준)")

    print(f"⏱️ 처리 시간: {format_time(process_time)} (총 {format_time(total_time)})")
    print(f"⚡ 평균 속도: {len(dates) / process_time:.1f}일/초")

    if failed_dates:
        print(f"\n⚠️ 실패한 날짜 ({len(failed_dates)}개):")
        for date in failed_dates[:10]:
            print(f"   - {date}")
        if len(failed_dates) > 10:
            print(f"   ... 외 {len(failed_dates) - 10}개")

    # 필터 통계 출력
    try:
        from core.indicators.filter_stats import filter_stats
        print("\n" + filter_stats.get_summary())
    except Exception:
        pass


if __name__ == '__main__':
    os.environ['ENABLE_PATTERN_LOGGING'] = 'true'
    main()
