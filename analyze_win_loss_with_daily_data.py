import pandas as pd
import numpy as np
import pickle
import os
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime, timedelta

def extract_stock_code_from_log(log_content: str, buy_price: int, sell_price: int, buy_time: str) -> Optional[str]:
    """로그에서 특정 매매의 종목코드를 추출"""
    lines = log_content.split('\n')

    for i, line in enumerate(lines):
        if f'@{buy_price:,}' in line and buy_time in line and '매수' in line:
            # 해당 라인 주변에서 종목코드 찾기
            for j in range(max(0, i-10), min(len(lines), i+3)):
                stock_match = re.search(r'종목명: (\d{6})', lines[j])
                if stock_match:
                    return stock_match.group(1)
    return None

def load_daily_data(stock_code: str) -> Optional[pd.DataFrame]:
    """캐시된 일봉 데이터 로드"""
    cache_file = f'cache/daily_data/{stock_code}_daily.pkl'
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                return pickle.load(f)
        except Exception as e:
            print(f"일봉 데이터 로드 실패 ({stock_code}): {e}")
    return None

def calculate_daily_features(daily_data: pd.DataFrame, trade_date: str) -> Dict:
    """일봉 데이터에서 특성들 추출"""
    if daily_data is None or len(daily_data) == 0:
        return {}

    try:
        # 거래일 찾기 (YYYYMMDD 형식)
        target_date = pd.to_datetime(trade_date, format='%Y%m%d')
        daily_data['date'] = pd.to_datetime(daily_data.index)

        # 거래일 이전 데이터만 사용
        before_trade = daily_data[daily_data['date'] <= target_date].tail(30)

        if len(before_trade) < 5:
            return {}

        # 최근 데이터
        recent = before_trade.tail(5)
        current = before_trade.iloc[-1]

        features = {}

        # 1. 가격 관련
        features['current_close'] = current['close']
        features['prev_close'] = before_trade.iloc[-2]['close'] if len(before_trade) >= 2 else current['close']
        features['daily_change_pct'] = ((current['close'] - features['prev_close']) / features['prev_close'] * 100)

        # 2. 거래량 관련
        features['current_volume'] = current['volume']
        features['avg_volume_5d'] = recent['volume'].mean()
        features['volume_ratio'] = current['volume'] / features['avg_volume_5d'] if features['avg_volume_5d'] > 0 else 1

        # 3. 변동성
        features['daily_volatility'] = ((current['high'] - current['low']) / current['close'] * 100)
        features['avg_volatility_5d'] = ((recent['high'] - recent['low']) / recent['close'] * 100).mean()

        # 4. 추세
        features['ma5'] = recent['close'].mean()
        features['ma20'] = before_trade.tail(20)['close'].mean() if len(before_trade) >= 20 else recent['close'].mean()
        features['price_vs_ma5'] = ((current['close'] - features['ma5']) / features['ma5'] * 100)
        features['price_vs_ma20'] = ((current['close'] - features['ma20']) / features['ma20'] * 100)

        # 5. RSI (14일)
        if len(before_trade) >= 14:
            delta = before_trade['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            features['rsi'] = 100 - (100 / (1 + rs.iloc[-1]))
        else:
            features['rsi'] = 50

        # 6. 최근 고점/저점 대비
        high_20d = before_trade.tail(20)['high'].max() if len(before_trade) >= 20 else current['high']
        low_20d = before_trade.tail(20)['low'].min() if len(before_trade) >= 20 else current['low']
        features['vs_20d_high_pct'] = ((current['close'] - high_20d) / high_20d * 100)
        features['vs_20d_low_pct'] = ((current['close'] - low_20d) / low_20d * 100)

        return features

    except Exception as e:
        print(f"일봉 특성 계산 오류: {e}")
        return {}

def parse_trading_logs_with_stocks():
    """매매 로그와 종목코드를 함께 파싱"""
    log_dir = 'signal_replay_log'
    target_files = []

    for day in range(8, 17):  # 09/08 ~ 09/16
        if day in [6, 7, 13, 14]:  # 주말 제외
            continue
        day_str = f'{day:02d}'
        filename = f'signal_new2_replay_202509{day_str}_9_00_0.txt'
        if os.path.exists(os.path.join(log_dir, filename)):
            target_files.append(filename)

    all_trades_with_stocks = []

    for file in sorted(target_files):
        date = file.split('_')[2][:8]
        print(f"파싱 중: {file}")

        try:
            with open(os.path.join(log_dir, file), 'r', encoding='utf-8') as f:
                content = f.read()

            # 매매 결과 패턴 매칭
            pattern = r'(\d{2}:\d{2}) 매수\[pullback_pattern\] @([\d,]+) → (\d{2}:\d{2}) 매도\[(profit_\d+\.\d+pct|stop_loss_\d+\.\d+pct)\] @([\d,]+) \(([+-]\d+\.\d+%)\)'
            matches = re.findall(pattern, content)

            for match in matches:
                buy_time, buy_price, sell_time, sell_reason, sell_price, profit_pct = match
                buy_price_int = int(buy_price.replace(',', ''))
                sell_price_int = int(sell_price.replace(',', ''))
                profit_pct_float = float(profit_pct.replace('%', ''))

                # 종목코드 추출
                stock_code = extract_stock_code_from_log(content, buy_price_int, sell_price_int, buy_time)

                trade_info = {
                    'date': date,
                    'stock_code': stock_code,
                    'buy_time': buy_time,
                    'sell_time': sell_time,
                    'buy_price': buy_price_int,
                    'sell_price': sell_price_int,
                    'profit_pct': profit_pct_float,
                    'win': profit_pct_float > 0
                }

                all_trades_with_stocks.append(trade_info)

        except Exception as e:
            print(f"파일 처리 오류 ({file}): {e}")

    return all_trades_with_stocks

def main():
    print("=== 승패 패턴 분석을 위한 일봉 데이터 결합 ===")

    # 매매 로그 파싱
    trades = parse_trading_logs_with_stocks()
    print(f"총 {len(trades)}건의 매매 발견")

    # 일봉 데이터와 결합
    enriched_trades = []
    stock_not_found = 0
    daily_not_found = 0

    for trade in trades:
        if trade['stock_code'] is None:
            stock_not_found += 1
            continue

        # 일봉 데이터 로드
        daily_data = load_daily_data(trade['stock_code'])
        if daily_data is None:
            daily_not_found += 1
            continue

        # 일봉 특성 계산
        daily_features = calculate_daily_features(daily_data, trade['date'])
        if not daily_features:
            continue

        # 결합
        enriched_trade = {**trade, **daily_features}
        enriched_trades.append(enriched_trade)

    print(f"종목코드 미발견: {stock_not_found}건")
    print(f"일봉데이터 없음: {daily_not_found}건")
    print(f"분석 가능한 거래: {len(enriched_trades)}건")

    if len(enriched_trades) == 0:
        print("분석할 데이터가 없습니다.")
        return

    # DataFrame 변환
    df = pd.DataFrame(enriched_trades)

    # 승패 분석
    wins = df[df['win'] == True]
    losses = df[df['win'] == False]

    print(f"\n=== 승패별 일봉 특성 비교 ===")
    print(f"승리: {len(wins)}건, 패배: {len(losses)}건")

    # 수치형 특성들만 선택
    numeric_features = ['daily_change_pct', 'volume_ratio', 'daily_volatility', 'avg_volatility_5d',
                       'price_vs_ma5', 'price_vs_ma20', 'rsi', 'vs_20d_high_pct', 'vs_20d_low_pct']

    print(f"\n{'특성':<20} {'승리 평균':<12} {'패배 평균':<12} {'차이':<12}")
    print("-" * 60)

    for feature in numeric_features:
        if feature in df.columns:
            win_mean = wins[feature].mean() if len(wins) > 0 else 0
            loss_mean = losses[feature].mean() if len(losses) > 0 else 0
            diff = win_mean - loss_mean

            print(f"{feature:<20} {win_mean:>11.2f} {loss_mean:>11.2f} {diff:>11.2f}")

    # CSV 저장
    df.to_csv('trading_analysis_with_daily.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과를 trading_analysis_with_daily.csv에 저장했습니다.")

    # 주요 발견사항
    print(f"\n=== 주요 발견사항 ===")

    # RSI 분석
    if 'rsi' in df.columns:
        win_rsi = wins['rsi'].mean() if len(wins) > 0 else 0
        loss_rsi = losses['rsi'].mean() if len(losses) > 0 else 0
        print(f"RSI - 승리: {win_rsi:.1f}, 패배: {loss_rsi:.1f}")

    # 변동성 분석
    if 'daily_volatility' in df.columns:
        win_vol = wins['daily_volatility'].mean() if len(wins) > 0 else 0
        loss_vol = losses['daily_volatility'].mean() if len(losses) > 0 else 0
        print(f"당일 변동성 - 승리: {win_vol:.1f}%, 패배: {loss_vol:.1f}%")

    # 이동평균 대비 위치
    if 'price_vs_ma20' in df.columns:
        win_ma20 = wins['price_vs_ma20'].mean() if len(wins) > 0 else 0
        loss_ma20 = losses['price_vs_ma20'].mean() if len(losses) > 0 else 0
        print(f"20일선 대비 - 승리: {win_ma20:+.1f}%, 패배: {loss_ma20:+.1f}%")

    return df

if __name__ == "__main__":
    df = main()