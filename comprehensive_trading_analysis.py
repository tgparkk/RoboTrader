import pandas as pd
import numpy as np
import pickle
import os
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime

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
        # 거래일을 datetime으로 변환 (YYYYMMDD → datetime)
        target_date = pd.to_datetime(trade_date, format='%Y%m%d')

        # 인덱스가 datetime이 아닌 경우 변환
        if not isinstance(daily_data.index, pd.DatetimeIndex):
            daily_data.index = pd.to_datetime(daily_data.index)

        # 거래일 이전 데이터만 사용 (거래일 당일 포함)
        before_trade = daily_data[daily_data.index <= target_date].tail(30)

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

        # 4. 추세 - 이동평균
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

        # 7. 갭 상승/하락 여부
        features['gap_up'] = current['open'] > features['prev_close'] * 1.02  # 2% 이상 갭상승
        features['gap_down'] = current['open'] < features['prev_close'] * 0.98  # 2% 이상 갭하락

        # 8. 캔들 패턴 - 양봉/음봉
        features['is_green'] = current['close'] > current['open']
        features['body_size_pct'] = abs(current['close'] - current['open']) / current['open'] * 100

        return features

    except Exception as e:
        print(f"일봉 특성 계산 오류: {e}")
        return {}

def parse_trades_with_stock_codes():
    """매매 결과와 종목코드를 매칭 - 수정된 날짜 추출 방식"""
    log_dir = 'signal_replay_log'
    target_files = []

    # 파일 목록을 먼저 확인
    all_files = [f for f in os.listdir(log_dir) if f.startswith('signal_new2_replay_202509') and f.endswith('.txt')]

    for file in all_files:
        # 파일명에서 날짜 추출: signal_new2_replay_20250908_9_00_0.txt
        match = re.search(r'(\d{8})', file)
        if match:
            date_str = match.group(1)
            day = int(date_str[6:8])  # 일자
            if 8 <= day <= 16:  # 09/08 ~ 09/16
                target_files.append((file, date_str))

    all_trades = []

    for file, date in sorted(target_files):
        print(f"파싱 중: {file} (날짜: {date})")

        try:
            with open(os.path.join(log_dir, file), 'r', encoding='utf-8') as f:
                content = f.read()

            # 종목별로 섹션을 나눔
            sections = re.split(r'=== (\d{6}) -', content)[1:]  # 첫 번째 빈 섹션 제거

            # 섹션을 종목코드와 내용으로 분할
            for i in range(0, len(sections), 2):
                if i + 1 < len(sections):
                    stock_code = sections[i]
                    section_content = sections[i + 1]

                    # 해당 섹션에서 매매 결과 찾기
                    pattern = r'(\d{2}:\d{2}) 매수\[pullback_pattern\] @([\d,]+) → (\d{2}:\d{2}) 매도\[(profit_\d+\.\d+pct|stop_loss_\d+\.\d+pct)\] @([\d,]+) \(([+-]\d+\.\d+%)\)'
                    matches = re.findall(pattern, section_content)

                    for match in matches:
                        buy_time, buy_price, sell_time, sell_reason, sell_price, profit_pct = match
                        buy_price_int = int(buy_price.replace(',', ''))
                        sell_price_int = int(sell_price.replace(',', ''))
                        profit_pct_float = float(profit_pct.replace('%', ''))

                        trade_info = {
                            'date': date,  # 올바른 날짜 사용
                            'stock_code': stock_code,
                            'buy_time': buy_time,
                            'sell_time': sell_time,
                            'buy_price': buy_price_int,
                            'sell_price': sell_price_int,
                            'profit_pct': profit_pct_float,
                            'win': profit_pct_float > 0
                        }

                        all_trades.append(trade_info)

        except Exception as e:
            print(f"파일 처리 오류 ({file}): {e}")

    return all_trades

def main():
    print("=== 포괄적인 매매 패턴 분석 ===")

    # 매매 로그 파싱
    trades = parse_trades_with_stock_codes()
    print(f"총 {len(trades)}건의 매매 발견")

    if len(trades) == 0:
        print("분석할 거래가 없습니다.")
        return

    # 일봉 데이터와 결합
    enriched_trades = []
    daily_not_found = 0

    print("\n일봉 데이터 결합 중...")
    for trade in trades:
        # 일봉 데이터 로드
        daily_data = load_daily_data(trade['stock_code'])
        if daily_data is None:
            daily_not_found += 1
            # 일봉 데이터가 없어도 기본 정보는 유지
            enriched_trades.append(trade)
            continue

        # 일봉 특성 계산
        daily_features = calculate_daily_features(daily_data, trade['date'])

        # 결합 - 일봉 특성이 없어도 거래 정보는 유지
        enriched_trade = {**trade, **daily_features}
        enriched_trades.append(enriched_trade)

    print(f"일봉데이터 없음: {daily_not_found}건")
    print(f"총 분석 거래: {len(enriched_trades)}건")

    # DataFrame 변환
    df = pd.DataFrame(enriched_trades)

    # 기본 승패 통계
    wins = df[df['win'] == True]
    losses = df[df['win'] == False]

    print(f"\n=== 기본 통계 ===")
    print(f"총 거래: {len(df)}건")
    print(f"승리: {len(wins)}건, 패배: {len(losses)}건")
    print(f"전체 승률: {len(wins)/len(df)*100:.1f}%")

    # 일별 승패 통계
    print(f"\n=== 일별 승패 ===")
    daily_stats = df.groupby('date').agg({
        'win': ['count', 'sum'],
        'profit_pct': 'mean'
    }).round(2)
    daily_stats.columns = ['총거래', '승리', '평균수익']
    daily_stats['승률'] = (daily_stats['승리'] / daily_stats['총거래'] * 100).round(1)
    print(daily_stats)

    # 종목별 승패 통계 (거래 횟수 2회 이상만)
    print(f"\n=== 종목별 승패 (2회 이상 거래) ===")
    stock_stats = df.groupby('stock_code').agg({
        'win': ['count', 'sum'],
        'profit_pct': 'mean'
    }).round(2)
    stock_stats.columns = ['총거래', '승리', '평균수익']
    stock_stats['승률'] = (stock_stats['승리'] / stock_stats['총거래'] * 100).round(1)
    stock_stats_filtered = stock_stats[stock_stats['총거래'] >= 2].sort_values('승률', ascending=False)
    print(stock_stats_filtered.head(10))

    # 일봉 특성이 있는 데이터만으로 분석
    df_with_daily = df.dropna(subset=['current_close'])

    if len(df_with_daily) > 0:
        wins_daily = df_with_daily[df_with_daily['win'] == True]
        losses_daily = df_with_daily[df_with_daily['win'] == False]

        print(f"\n=== 일봉 특성 분석 (일봉데이터 보유: {len(df_with_daily)}건) ===")
        print(f"승리: {len(wins_daily)}건, 패배: {len(losses_daily)}건 (승률: {len(wins_daily)/len(df_with_daily)*100:.1f}%)")

        # 수치형 특성들
        numeric_features = [
            'daily_change_pct', 'volume_ratio', 'daily_volatility', 'avg_volatility_5d',
            'price_vs_ma5', 'price_vs_ma20', 'rsi', 'vs_20d_high_pct', 'vs_20d_low_pct',
            'body_size_pct'
        ]

        print(f"\n{'특성':<20} {'승리 평균':<12} {'패배 평균':<12} {'차이':<12}")
        print("-" * 60)

        for feature in numeric_features:
            if feature in df_with_daily.columns:
                win_mean = wins_daily[feature].mean() if len(wins_daily) > 0 and not wins_daily[feature].isna().all() else 0
                loss_mean = losses_daily[feature].mean() if len(losses_daily) > 0 and not losses_daily[feature].isna().all() else 0
                diff = win_mean - loss_mean

                print(f"{feature:<20} {win_mean:>11.2f} {loss_mean:>11.2f} {diff:>11.2f}")

        # 범주형 특성 분석
        print(f"\n=== 범주형 특성 분석 ===")
        categorical_features = ['gap_up', 'gap_down', 'is_green']

        for feature in categorical_features:
            if feature in df_with_daily.columns:
                win_true = len(wins_daily[wins_daily[feature] == True])
                win_false = len(wins_daily[wins_daily[feature] == False])
                loss_true = len(losses_daily[losses_daily[feature] == True])
                loss_false = len(losses_daily[losses_daily[feature] == False])

                total_true = win_true + loss_true
                total_false = win_false + loss_false

                win_rate_true = win_true / total_true * 100 if total_true > 0 else 0
                win_rate_false = win_false / total_false * 100 if total_false > 0 else 0

                print(f"{feature}:")
                print(f"  True:  승률 {win_rate_true:.1f}% ({win_true}/{total_true})")
                print(f"  False: 승률 {win_rate_false:.1f}% ({win_false}/{total_false})")

    # CSV 저장
    df.to_csv('comprehensive_trading_analysis.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과를 comprehensive_trading_analysis.csv에 저장했습니다.")

    # 주요 개선 아이디어 제시
    print(f"\n=== 승률 개선 아이디어 ===")

    if len(df_with_daily) > 0:
        # RSI 분석
        if 'rsi' in df_with_daily.columns:
            win_rsi = wins_daily['rsi'].mean() if len(wins_daily) > 0 else 50
            loss_rsi = losses_daily['rsi'].mean() if len(losses_daily) > 0 else 50
            print(f"1. RSI 필터링: 승리 평균 RSI {win_rsi:.1f}, 패배 평균 RSI {loss_rsi:.1f}")

        # 거래량 비율 분석
        if 'volume_ratio' in df_with_daily.columns:
            win_vol = wins_daily['volume_ratio'].mean() if len(wins_daily) > 0 else 1
            loss_vol = losses_daily['volume_ratio'].mean() if len(losses_daily) > 0 else 1
            print(f"2. 거래량 필터링: 승리 평균 거래량비 {win_vol:.2f}, 패배 평균 거래량비 {loss_vol:.2f}")

        # 이동평균 위치 분석
        if 'price_vs_ma20' in df_with_daily.columns:
            win_ma20 = wins_daily['price_vs_ma20'].mean() if len(wins_daily) > 0 else 0
            loss_ma20 = losses_daily['price_vs_ma20'].mean() if len(losses_daily) > 0 else 0
            print(f"3. 이동평균 필터링: 승리시 20일선 대비 {win_ma20:+.1f}%, 패배시 20일선 대비 {loss_ma20:+.1f}%")

    # 4/5 가격 매수 실패 분석
    print(f"\n=== 4/5 가격 매수 실패 개선 아이디어 ===")
    print("1. 돌파봉의 거래량이 부족한 경우 진입가를 3/5로 하향 조정")
    print("2. 돌파봉의 몸통 크기가 작은 경우(< 2%) 진입 보류")
    print("3. 돌파 시점의 호가창 분석을 통한 실시간 진입가 조정")
    print("4. 돌파 후 즉시 매수 대신 1-2분 후 재확인 매수")

    return df

if __name__ == "__main__":
    df = main()