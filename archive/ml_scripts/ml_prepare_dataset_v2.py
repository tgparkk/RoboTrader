#!/usr/bin/env python3
"""
패턴 데이터 로그에서 ML 학습용 데이터셋 생성 (V2 - 일봉 데이터 및 기술적 지표 포함)

입력: pattern_data_log/*.jsonl
출력: ml_dataset_v2.csv (학습용 피처 + 라벨)

추가 특성:
- 일봉 OHLCV 데이터 (과거 N일)
- 기술적 지표 (RSI, MACD, Bollinger Bands, 이동평균선)
- 일봉 기반 추세 및 거래량 지표
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import numpy as np
import pickle
import sys
sys.path.append(str(Path(__file__).parent))

from api.kis_market_api import get_inquire_daily_itemchartprice
from utils.korean_time import now_kst


# === 기술적 지표 계산 함수 ===

def calculate_rsi(prices: pd.Series, period: int = 14) -> float:
    """RSI (Relative Strength Index) 계산"""
    if len(prices) < period + 1:
        return 50.0  # 기본값

    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))

    return float(rsi.iloc[-1]) if not np.isnan(rsi.iloc[-1]) else 50.0


def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float]:
    """MACD (Moving Average Convergence Divergence) 계산"""
    if len(prices) < slow:
        return 0.0, 0.0, 0.0

    ema_fast = prices.ewm(span=fast, adjust=False).mean()
    ema_slow = prices.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    macd_histogram = macd_line - signal_line

    return (
        float(macd_line.iloc[-1]) if not np.isnan(macd_line.iloc[-1]) else 0.0,
        float(signal_line.iloc[-1]) if not np.isnan(signal_line.iloc[-1]) else 0.0,
        float(macd_histogram.iloc[-1]) if not np.isnan(macd_histogram.iloc[-1]) else 0.0
    )


def calculate_bollinger_bands(prices: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[float, float, float, float]:
    """볼린저 밴드 계산"""
    if len(prices) < period:
        return 0.0, 0.0, 0.0, 0.0

    sma = prices.rolling(window=period).mean()
    std = prices.rolling(window=period).std()

    upper_band = sma + (std * std_dev)
    lower_band = sma - (std * std_dev)

    current_price = prices.iloc[-1]
    bb_position = ((current_price - lower_band.iloc[-1]) / (upper_band.iloc[-1] - lower_band.iloc[-1])) * 100 if upper_band.iloc[-1] != lower_band.iloc[-1] else 50.0

    return (
        float(upper_band.iloc[-1]) if not np.isnan(upper_band.iloc[-1]) else 0.0,
        float(sma.iloc[-1]) if not np.isnan(sma.iloc[-1]) else 0.0,
        float(lower_band.iloc[-1]) if not np.isnan(lower_band.iloc[-1]) else 0.0,
        float(bb_position) if not np.isnan(bb_position) else 50.0
    )


def calculate_moving_averages(prices: pd.Series) -> Dict[str, float]:
    """이동평균선 계산"""
    mas = {}
    for period in [5, 10, 20, 60]:
        if len(prices) >= period:
            ma = prices.rolling(window=period).mean().iloc[-1]
            mas[f'ma{period}'] = float(ma) if not np.isnan(ma) else 0.0
        else:
            mas[f'ma{period}'] = 0.0

    # 이동평균선 간 관계
    current_price = prices.iloc[-1]
    mas['price_to_ma5_ratio'] = (current_price / mas['ma5'] - 1) * 100 if mas['ma5'] > 0 else 0.0
    mas['price_to_ma20_ratio'] = (current_price / mas['ma20'] - 1) * 100 if mas['ma20'] > 0 else 0.0
    mas['ma5_to_ma20_ratio'] = (mas['ma5'] / mas['ma20'] - 1) * 100 if mas['ma20'] > 0 else 0.0
    mas['ma20_to_ma60_ratio'] = (mas['ma20'] / mas['ma60'] - 1) * 100 if mas['ma60'] > 0 else 0.0

    # 정배열 여부 (ma5 > ma20 > ma60)
    mas['is_uptrend_alignment'] = 1 if mas['ma5'] > mas['ma20'] > mas['ma60'] > 0 else 0

    return mas


def calculate_volume_indicators(df: pd.DataFrame) -> Dict[str, float]:
    """거래량 지표 계산"""
    if len(df) < 20:
        return {
            'volume_ma5': 0.0,
            'volume_ma20': 0.0,
            'volume_ratio': 1.0,
            'volume_surge': 0,
            'avg_volume_20d': 0.0
        }

    volumes = df['acml_vol'].astype(float)

    volume_ma5 = volumes.rolling(window=5).mean().iloc[-1]
    volume_ma20 = volumes.rolling(window=20).mean().iloc[-1]
    current_volume = volumes.iloc[-1]

    return {
        'volume_ma5': float(volume_ma5) if not np.isnan(volume_ma5) else 0.0,
        'volume_ma20': float(volume_ma20) if not np.isnan(volume_ma20) else 0.0,
        'volume_ratio': float(current_volume / volume_ma20) if volume_ma20 > 0 else 1.0,
        'volume_surge': 1 if current_volume > volume_ma20 * 2 else 0,
        'avg_volume_20d': float(volume_ma20) if not np.isnan(volume_ma20) else 0.0
    }


# === 일봉 데이터 로드 (캐싱 지원) ===

def load_daily_data_with_cache(stock_code: str, trade_date: str, lookback_days: int = 60) -> Optional[pd.DataFrame]:
    """일봉 데이터 로드 (캐시 우선, 없으면 API 호출)

    Args:
        stock_code: 종목코드 (6자리)
        trade_date: 거래일 (YYYYMMDD)
        lookback_days: 과거 N일 데이터

    Returns:
        DataFrame: 일봉 데이터 (최신순 정렬)
    """
    # 캐시 디렉토리 생성
    cache_dir = Path('cache/daily_data')
    cache_dir.mkdir(parents=True, exist_ok=True)

    # 캐시 파일명
    cache_file = cache_dir / f"{stock_code}_{trade_date}_d{lookback_days}.pkl"

    # 캐시 존재 시 로드
    if cache_file.exists():
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"⚠️ 캐시 로드 실패 ({stock_code}): {e}")

    # API 호출
    try:
        end_date = datetime.strptime(trade_date, '%Y%m%d')
        start_date = end_date - timedelta(days=lookback_days + 30)  # 여유있게

        df = get_inquire_daily_itemchartprice(
            output_dv="2",
            div_code="J",
            itm_no=stock_code,
            inqr_strt_dt=start_date.strftime('%Y%m%d'),
            inqr_end_dt=trade_date,
            period_code="D",
            adj_prc="1"
        )

        if df is None or len(df) == 0:
            return None

        # 필요한 컬럼만 선택 및 데이터 타입 변환
        df = df.copy()
        df['stck_bsop_date'] = df['stck_bsop_date'].astype(str)
        df['stck_oprc'] = pd.to_numeric(df['stck_oprc'], errors='coerce').fillna(0)
        df['stck_hgpr'] = pd.to_numeric(df['stck_hgpr'], errors='coerce').fillna(0)
        df['stck_lwpr'] = pd.to_numeric(df['stck_lwpr'], errors='coerce').fillna(0)
        df['stck_clpr'] = pd.to_numeric(df['stck_clpr'], errors='coerce').fillna(0)
        df['acml_vol'] = pd.to_numeric(df['acml_vol'], errors='coerce').fillna(0)

        # 날짜 기준 정렬 (오래된 것부터)
        df = df.sort_values('stck_bsop_date').reset_index(drop=True)

        # 거래일 이전 데이터만
        df = df[df['stck_bsop_date'] <= trade_date]

        # 최대 lookback_days개만
        df = df.tail(lookback_days)

        # 캐시 저장
        try:
            with open(cache_file, 'wb') as f:
                pickle.dump(df, f)
        except Exception as e:
            print(f"⚠️ 캐시 저장 실패 ({stock_code}): {e}")

        return df

    except Exception as e:
        print(f"⚠️ 일봉 데이터 로드 실패 ({stock_code}, {trade_date}): {e}")
        return None


def extract_daily_features(daily_df: pd.DataFrame) -> Dict[str, float]:
    """일봉 데이터에서 특성 추출"""
    if daily_df is None or len(daily_df) < 5:
        # 데이터 부족 시 기본값 반환
        return {
            # 가격 정보
            'daily_close': 0.0,
            'daily_open': 0.0,
            'daily_high': 0.0,
            'daily_low': 0.0,
            'daily_volume': 0.0,

            # 최근 변화율
            'price_change_1d': 0.0,
            'price_change_5d': 0.0,
            'price_change_20d': 0.0,
            'volume_change_1d': 0.0,

            # RSI
            'rsi_14': 50.0,
            'rsi_overbought': 0,
            'rsi_oversold': 0,

            # MACD
            'macd_line': 0.0,
            'macd_signal': 0.0,
            'macd_histogram': 0.0,
            'macd_positive': 0,

            # 볼린저 밴드
            'bb_upper': 0.0,
            'bb_middle': 0.0,
            'bb_lower': 0.0,
            'bb_position': 50.0,

            # 이동평균선
            'ma5': 0.0,
            'ma10': 0.0,
            'ma20': 0.0,
            'ma60': 0.0,
            'price_to_ma5_ratio': 0.0,
            'price_to_ma20_ratio': 0.0,
            'ma5_to_ma20_ratio': 0.0,
            'ma20_to_ma60_ratio': 0.0,
            'is_uptrend_alignment': 0,

            # 거래량 지표
            'volume_ma5': 0.0,
            'volume_ma20': 0.0,
            'volume_ratio': 1.0,
            'volume_surge': 0,
            'avg_volume_20d': 0.0,

            # 변동성
            'volatility_20d': 0.0,
            'high_low_ratio': 0.0,
        }

    # 가격 시리즈 추출
    closes = daily_df['stck_clpr'].astype(float)
    opens = daily_df['stck_oprc'].astype(float)
    highs = daily_df['stck_hgpr'].astype(float)
    lows = daily_df['stck_lwpr'].astype(float)
    volumes = daily_df['acml_vol'].astype(float)

    # 최신 가격 정보
    latest = daily_df.iloc[-1]
    daily_close = float(latest['stck_clpr'])
    daily_open = float(latest['stck_oprc'])
    daily_high = float(latest['stck_hgpr'])
    daily_low = float(latest['stck_lwpr'])
    daily_volume = float(latest['acml_vol'])

    # 가격 변화율
    price_change_1d = ((closes.iloc[-1] / closes.iloc[-2] - 1) * 100) if len(closes) >= 2 else 0.0
    price_change_5d = ((closes.iloc[-1] / closes.iloc[-6] - 1) * 100) if len(closes) >= 6 else 0.0
    price_change_20d = ((closes.iloc[-1] / closes.iloc[-21] - 1) * 100) if len(closes) >= 21 else 0.0
    volume_change_1d = ((volumes.iloc[-1] / volumes.iloc[-2] - 1) * 100) if len(volumes) >= 2 else 0.0

    # RSI 계산
    rsi_14 = calculate_rsi(closes, period=14)
    rsi_overbought = 1 if rsi_14 > 70 else 0
    rsi_oversold = 1 if rsi_14 < 30 else 0

    # MACD 계산
    macd_line, macd_signal, macd_histogram = calculate_macd(closes)
    macd_positive = 1 if macd_histogram > 0 else 0

    # 볼린저 밴드 계산
    bb_upper, bb_middle, bb_lower, bb_position = calculate_bollinger_bands(closes)

    # 이동평균선 계산
    mas = calculate_moving_averages(closes)

    # 거래량 지표 계산
    volume_indicators = calculate_volume_indicators(daily_df)

    # 변동성 계산
    returns = closes.pct_change().dropna()
    volatility_20d = float(returns.tail(20).std() * 100) if len(returns) >= 20 else 0.0
    high_low_ratio = ((daily_high / daily_low - 1) * 100) if daily_low > 0 else 0.0

    return {
        # 가격 정보
        'daily_close': daily_close,
        'daily_open': daily_open,
        'daily_high': daily_high,
        'daily_low': daily_low,
        'daily_volume': daily_volume,

        # 최근 변화율
        'price_change_1d': price_change_1d,
        'price_change_5d': price_change_5d,
        'price_change_20d': price_change_20d,
        'volume_change_1d': volume_change_1d,

        # RSI
        'rsi_14': rsi_14,
        'rsi_overbought': rsi_overbought,
        'rsi_oversold': rsi_oversold,

        # MACD
        'macd_line': macd_line,
        'macd_signal': macd_signal,
        'macd_histogram': macd_histogram,
        'macd_positive': macd_positive,

        # 볼린저 밴드
        'bb_upper': bb_upper,
        'bb_middle': bb_middle,
        'bb_lower': bb_lower,
        'bb_position': bb_position,

        # 이동평균선
        **mas,

        # 거래량 지표
        **volume_indicators,

        # 변동성
        'volatility_20d': volatility_20d,
        'high_low_ratio': high_low_ratio,
    }


# === 기존 패턴 특성 추출 (V1과 동일) ===

def extract_pattern_features(pattern_data: Dict) -> Optional[Dict]:
    """패턴 데이터에서 ML 특징(feature) 추출 (V1 호환)"""
    # 매매 결과가 없으면 스킵
    trade_result = pattern_data.get('trade_result')
    if trade_result is None or not trade_result.get('trade_executed', False):
        return None

    # 라벨
    profit_rate = trade_result.get('profit_rate', 0)
    label = 1 if profit_rate > 0 else 0

    # 기본 정보
    signal_info = pattern_data.get('signal_info', {})
    pattern_stages = pattern_data.get('pattern_stages', {})

    # 타임스탬프
    timestamp_str = pattern_data.get('timestamp', '')
    try:
        dt = datetime.fromisoformat(timestamp_str)
        hour = dt.hour
        minute = dt.minute
        time_in_minutes = hour * 60 + minute
    except:
        hour = 0
        minute = 0
        time_in_minutes = 0

    # 신호 특징
    signal_type = signal_info.get('signal_type', 'UNKNOWN')
    confidence = signal_info.get('confidence', 0)

    # 패턴 특징 - 상승구간
    uptrend = pattern_stages.get('1_uptrend', {})
    uptrend_candles = uptrend.get('candle_count', 0)
    uptrend_gain = float(uptrend.get('price_gain', '0%').replace('%', ''))
    uptrend_max_volume = int(str(uptrend.get('max_volume', '0')).replace(',', ''))

    uptrend_candles_data = uptrend.get('candles', [])
    if uptrend_candles_data:
        uptrend_avg_body = np.mean([abs(c['close'] - c['open']) for c in uptrend_candles_data])
        uptrend_total_volume = sum([c['volume'] for c in uptrend_candles_data])
    else:
        uptrend_avg_body = 0
        uptrend_total_volume = 0

    # 패턴 특징 - 하락구간
    decline = pattern_stages.get('2_decline', {})
    decline_candles = decline.get('candle_count', 0)
    decline_pct = float(decline.get('decline_pct', '0%').replace('%', ''))

    decline_candles_data = decline.get('candles', [])
    if decline_candles_data:
        decline_avg_volume = np.mean([c['volume'] for c in decline_candles_data])
    else:
        decline_avg_volume = 0

    # 패턴 특징 - 지지구간
    support = pattern_stages.get('3_support', {})
    support_candles = support.get('candle_count', 0)
    support_volatility = float(support.get('price_volatility', '0%').replace('%', ''))
    support_avg_volume_ratio = float(support.get('avg_volume_ratio', '0%').replace('%', ''))

    support_candles_data = support.get('candles', [])
    if support_candles_data:
        support_avg_volume = np.mean([c['volume'] for c in support_candles_data])
    else:
        support_avg_volume = 0

    # 패턴 특징 - 돌파양봉
    breakout = pattern_stages.get('4_breakout', {})
    breakout_candle = breakout.get('candle', {})
    if breakout_candle:
        breakout_volume = breakout_candle.get('volume', 0)
        breakout_body = abs(breakout_candle.get('close', 0) - breakout_candle.get('open', 0))
        breakout_high = breakout_candle.get('high', 0)
        breakout_low = breakout_candle.get('low', 0)
        breakout_range = breakout_high - breakout_low
    else:
        breakout_volume = 0
        breakout_body = 0
        breakout_range = 0

    # 파생 특징
    volume_ratio_decline_to_uptrend = (decline_avg_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    volume_ratio_support_to_uptrend = (support_avg_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    volume_ratio_breakout_to_uptrend = (breakout_volume / uptrend_max_volume) if uptrend_max_volume > 0 else 0
    price_gain_to_decline_ratio = (uptrend_gain / abs(decline_pct)) if decline_pct != 0 else 0
    candle_ratio_support_to_decline = (support_candles / decline_candles) if decline_candles > 0 else 0

    return {
        # 라벨
        'label': label,
        'profit_rate': profit_rate,
        'sell_reason': trade_result.get('sell_reason', ''),

        # 시간 특징
        'hour': hour,
        'minute': minute,
        'time_in_minutes': time_in_minutes,
        'is_morning': 1 if hour < 12 else 0,

        # 신호 특징
        'signal_type': signal_type,
        'confidence': confidence,

        # 패턴 특징 - 상승구간
        'uptrend_candles': uptrend_candles,
        'uptrend_gain': uptrend_gain,
        'uptrend_max_volume': uptrend_max_volume,
        'uptrend_avg_body': uptrend_avg_body,
        'uptrend_total_volume': uptrend_total_volume,

        # 패턴 특징 - 하락구간
        'decline_candles': decline_candles,
        'decline_pct': abs(decline_pct),
        'decline_avg_volume': decline_avg_volume,

        # 패턴 특징 - 지지구간
        'support_candles': support_candles,
        'support_volatility': support_volatility,
        'support_avg_volume_ratio': support_avg_volume_ratio,
        'support_avg_volume': support_avg_volume,

        # 패턴 특징 - 돌파양봉
        'breakout_volume': breakout_volume,
        'breakout_body': breakout_body,
        'breakout_range': breakout_range,

        # 파생 특징
        'volume_ratio_decline_to_uptrend': volume_ratio_decline_to_uptrend,
        'volume_ratio_support_to_uptrend': volume_ratio_support_to_uptrend,
        'volume_ratio_breakout_to_uptrend': volume_ratio_breakout_to_uptrend,
        'price_gain_to_decline_ratio': price_gain_to_decline_ratio,
        'candle_ratio_support_to_decline': candle_ratio_support_to_decline,

        # 메타데이터
        'stock_code': pattern_data.get('stock_code', ''),
        'pattern_id': pattern_data.get('pattern_id', ''),
        'timestamp': timestamp_str,
    }


def extract_features_from_pattern_v2(pattern_data: Dict) -> Optional[Dict]:
    """패턴 데이터에서 ML 특징 추출 (V2: 일봉 데이터 포함)"""
    # 기존 패턴 특성 추출
    pattern_features = extract_pattern_features(pattern_data)
    if pattern_features is None:
        return None

    # 종목코드 및 날짜 추출
    stock_code = pattern_data.get('stock_code', '')
    timestamp_str = pattern_data.get('timestamp', '')

    try:
        dt = datetime.fromisoformat(timestamp_str)
        trade_date = dt.strftime('%Y%m%d')
    except:
        trade_date = ''

    if not stock_code or not trade_date:
        print(f"⚠️ 종목코드 또는 날짜 없음: {stock_code}, {trade_date}")
        # 일봉 특성을 기본값으로 채움
        daily_features = extract_daily_features(None)
    else:
        # 일봉 데이터 로드
        daily_df = load_daily_data_with_cache(stock_code, trade_date, lookback_days=60)

        # 일봉 특성 추출
        daily_features = extract_daily_features(daily_df)

    # 패턴 특성 + 일봉 특성 결합
    combined_features = {**pattern_features, **daily_features}

    return combined_features


def load_all_pattern_data(pattern_log_dir: Path) -> List[Dict]:
    """모든 패턴 로그 파일에서 데이터 로드"""
    all_patterns = []

    jsonl_files = sorted(pattern_log_dir.glob('pattern_data_*.jsonl'))

    print(f"📂 패턴 로그 파일 {len(jsonl_files)}개 발견")

    for jsonl_file in jsonl_files:
        try:
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        pattern = json.loads(line)
                        all_patterns.append(pattern)
        except Exception as e:
            print(f"⚠️ {jsonl_file.name} 로드 오류: {e}")

    print(f"📊 총 {len(all_patterns)}개 패턴 로드 완료")
    return all_patterns


def create_ml_dataset_v2(pattern_log_dir: str = 'pattern_data_log', output_file: str = 'ml_dataset_v2.csv'):
    """ML 데이터셋 생성 (V2: 일봉 데이터 포함)"""
    import sys
    sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 70)
    print("🤖 ML 학습용 데이터셋 생성 시작 (V2 - 일봉 데이터 포함)")
    print("=" * 70)

    # 패턴 데이터 로드
    pattern_log_path = Path(pattern_log_dir)
    if not pattern_log_path.exists():
        print(f"❌ 패턴 로그 디렉토리를 찾을 수 없습니다: {pattern_log_dir}")
        return

    all_patterns = load_all_pattern_data(pattern_log_path)

    # 특징 추출
    print("\n🔧 특징 추출 중 (패턴 + 일봉 데이터)...")
    features_list = []

    for i, pattern in enumerate(all_patterns):
        if (i + 1) % 10 == 0:
            print(f"   처리 중... {i+1}/{len(all_patterns)}")

        features = extract_features_from_pattern_v2(pattern)
        if features is not None:
            features_list.append(features)

    if not features_list:
        print("❌ 매매 결과가 있는 패턴이 없습니다.")
        return

    # DataFrame 생성
    df = pd.DataFrame(features_list)

    # 통계 출력
    print("\n" + "=" * 70)
    print("📊 데이터셋 통계")
    print("=" * 70)
    print(f"총 샘플 수: {len(df)}")
    print(f"승리 샘플: {df['label'].sum()} ({df['label'].mean()*100:.1f}%)")
    print(f"패배 샘플: {len(df) - df['label'].sum()} ({(1-df['label'].mean())*100:.1f}%)")
    print(f"\n특징(feature) 수: {len(df.columns) - 5}")  # 라벨 관련 컬럼 제외

    # CSV 저장
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n✅ 데이터셋 저장 완료: {output_file}")
    print(f"   파일 크기: {Path(output_file).stat().st_size / 1024:.1f} KB")

    # 컬럼 목록 출력
    print("\n📋 특징(feature) 컬럼 목록:")
    feature_cols = [col for col in df.columns if col not in ['label', 'profit_rate', 'sell_reason', 'stock_code', 'pattern_id', 'timestamp']]

    print("\n🔸 기존 패턴 특성 (26개):")
    pattern_cols = [col for col in feature_cols if not col.startswith(('daily_', 'price_change_', 'volume_change_', 'rsi_', 'macd_', 'bb_', 'ma', 'volatility_', 'high_low_'))]
    for i, col in enumerate(pattern_cols, 1):
        print(f"   {i:2d}. {col}")

    print("\n🔸 일봉 및 기술적 지표 특성 (추가):")
    daily_cols = [col for col in feature_cols if col not in pattern_cols]
    for i, col in enumerate(daily_cols, 1):
        print(f"   {i:2d}. {col}")

    print(f"\n📌 총 특성 수: {len(feature_cols)}개 (패턴 {len(pattern_cols)}개 + 일봉 {len(daily_cols)}개)")

    return df


if __name__ == '__main__':
    df = create_ml_dataset_v2()
