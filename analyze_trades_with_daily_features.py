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
        # 거래일 찾기 (YYYYMMDD 형식을 datetime으로 변환)
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
    """매매 결과와 종목코드를 매칭"""
    log_dir = 'signal_replay_log'
    target_files = []

    for day in range(8, 17):  # 09/08 ~ 09/16
        if day in [6, 7, 13, 14]:  # 주말 제외
            continue
        day_str = f'{day:02d}'
        filename = f'signal_new2_replay_202509{day_str}_9_00_0.txt'
        if os.path.exists(os.path.join(log_dir, filename)):
            target_files.append(filename)

    all_trades = []

    for file in sorted(target_files):
        date = file.split('_')[2][:8]
        print(f"파싱 중: {file}")

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
                            'date': date,
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
    print("=== 일봉 특성과 승패 패턴 분석 ===")

    # 매매 로그 파싱
    trades = parse_trades_with_stock_codes()
    print(f"총 {len(trades)}건의 매매 발견")

    # 일봉 데이터와 결합
    enriched_trades = []
    daily_not_found = 0

    for trade in trades:
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
    print(f"승리: {len(wins)}건, 패배: {len(losses)}건 (승률: {len(wins)/len(df)*100:.1f}%)")

    # 수치형 특성들만 선택
    numeric_features = [
        'daily_change_pct', 'volume_ratio', 'daily_volatility', 'avg_volatility_5d',
        'price_vs_ma5', 'price_vs_ma20', 'rsi', 'vs_20d_high_pct', 'vs_20d_low_pct',
        'body_size_pct'
    ]

    print(f"\n{'특성':<20} {'승리 평균':<12} {'패배 평균':<12} {'차이':<12} {'승률 영향'}")
    print("-" * 75)

    feature_analysis = []

    for feature in numeric_features:
        if feature in df.columns:
            win_mean = wins[feature].mean() if len(wins) > 0 and not wins[feature].isna().all() else 0
            loss_mean = losses[feature].mean() if len(losses) > 0 and not losses[feature].isna().all() else 0
            diff = win_mean - loss_mean

            # 통계적 유의성 체크 (간단한 t-test)
            try:
                from scipy.stats import ttest_ind
                win_values = wins[feature].dropna()
                loss_values = losses[feature].dropna()

                if len(win_values) > 1 and len(loss_values) > 1:
                    t_stat, p_value = ttest_ind(win_values, loss_values)
                    significance = "***" if p_value < 0.01 else "**" if p_value < 0.05 else "*" if p_value < 0.10 else ""
                else:
                    significance = ""
            except:
                significance = ""

            print(f"{feature:<20} {win_mean:>11.2f} {loss_mean:>11.2f} {diff:>11.2f} {significance}")

            feature_analysis.append({
                'feature': feature,
                'win_mean': win_mean,
                'loss_mean': loss_mean,
                'diff': diff,
                'abs_diff': abs(diff)
            })

    # 범주형 특성 분석
    print(f"\n=== 범주형 특성 분석 ===")
    categorical_features = ['gap_up', 'gap_down', 'is_green']

    for feature in categorical_features:
        if feature in df.columns:
            win_true = len(wins[wins[feature] == True])
            win_false = len(wins[wins[feature] == False])
            loss_true = len(losses[losses[feature] == True])
            loss_false = len(losses[losses[feature] == False])

            total_true = win_true + loss_true
            total_false = win_false + loss_false

            win_rate_true = win_true / total_true * 100 if total_true > 0 else 0
            win_rate_false = win_false / total_false * 100 if total_false > 0 else 0

            print(f"{feature}:")
            print(f"  True:  승률 {win_rate_true:.1f}% ({win_true}/{total_true})")
            print(f"  False: 승률 {win_rate_false:.1f}% ({win_false}/{total_false})")

    # 가장 중요한 특성들
    feature_analysis.sort(key=lambda x: x['abs_diff'], reverse=True)
    print(f"\n=== 승패를 가르는 주요 특성 (상위 5개) ===")
    for i, item in enumerate(feature_analysis[:5], 1):
        direction = "승리 유리" if item['diff'] > 0 else "패배 위험"
        print(f"{i}. {item['feature']}: 차이 {item['diff']:.2f} ({direction})")

    # CSV 저장
    df.to_csv('trading_analysis_with_daily_features.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과를 trading_analysis_with_daily_features.csv에 저장했습니다.")

    return df

if __name__ == "__main__":
    df = main()