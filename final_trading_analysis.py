import pandas as pd
import numpy as np
import pickle
import os
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime

def load_daily_data(stock_code: str) -> Optional[pd.DataFrame]:
    """캐시된 일봉 데이터 로드 - 한국투자증권 API 형태"""
    cache_file = f'cache/daily_data/{stock_code}_daily.pkl'
    if os.path.exists(cache_file):
        try:
            with open(cache_file, 'rb') as f:
                data = pickle.load(f)

            # 한국투자증권 API 형태 일봉 데이터인 경우
            if 'stck_bsop_date' in data.columns and len(data) > 1:
                # 컬럼명 매핑
                data = data.rename(columns={
                    'stck_bsop_date': 'date',
                    'stck_clpr': 'close',
                    'stck_oprc': 'open',
                    'stck_hgpr': 'high',
                    'stck_lwpr': 'low',
                    'acml_vol': 'volume'
                })

                # 데이터 타입 변환
                numeric_cols = ['close', 'open', 'high', 'low', 'volume']
                for col in numeric_cols:
                    if col in data.columns:
                        data[col] = pd.to_numeric(data[col], errors='coerce')

                # 날짜 인덱스 설정
                data['date'] = pd.to_datetime(data['date'], format='%Y%m%d')
                data = data.set_index('date').sort_index()

                return data
            else:
                return None
        except Exception as e:
            print(f"일봉 데이터 로드 실패 ({stock_code}): {e}")
    return None

def calculate_daily_features(daily_data: pd.DataFrame, trade_date: str) -> Dict:
    """일봉 데이터에서 특성들 추출"""
    if daily_data is None or len(daily_data) == 0:
        return {}

    try:
        # 거래일을 datetime으로 변환
        target_date = pd.to_datetime(trade_date, format='%Y%m%d')

        # 거래일 이전 데이터만 사용 (거래일 당일 포함)
        before_trade = daily_data[daily_data.index <= target_date].tail(30)

        if len(before_trade) < 5:
            return {}

        # 최근 데이터
        recent = before_trade.tail(5)
        current = before_trade.iloc[-1]

        features = {}

        # 1. 기본 가격 정보
        features['current_close'] = current['close']
        features['current_volume'] = current['volume']

        # 2. 전일 대비
        if len(before_trade) >= 2:
            features['prev_close'] = before_trade.iloc[-2]['close']
            features['daily_change_pct'] = ((current['close'] - features['prev_close']) / features['prev_close'] * 100)
        else:
            features['prev_close'] = current['close']
            features['daily_change_pct'] = 0

        # 3. 거래량 분석
        features['avg_volume_5d'] = recent['volume'].mean()
        features['volume_ratio'] = current['volume'] / features['avg_volume_5d'] if features['avg_volume_5d'] > 0 else 1

        # 4. 변동성
        features['daily_volatility'] = ((current['high'] - current['low']) / current['close'] * 100)
        features['avg_volatility_5d'] = ((recent['high'] - recent['low']) / recent['close'] * 100).mean()

        # 5. 이동평균
        features['ma5'] = recent['close'].mean()
        features['ma20'] = before_trade.tail(20)['close'].mean() if len(before_trade) >= 20 else recent['close'].mean()
        features['price_vs_ma5'] = ((current['close'] - features['ma5']) / features['ma5'] * 100)
        features['price_vs_ma20'] = ((current['close'] - features['ma20']) / features['ma20'] * 100)

        # 6. RSI (14일)
        if len(before_trade) >= 14:
            delta = before_trade['close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            features['rsi'] = 100 - (100 / (1 + rs.iloc[-1]))
        else:
            features['rsi'] = 50

        # 7. 최근 고저점 대비
        high_20d = before_trade.tail(20)['high'].max() if len(before_trade) >= 20 else current['high']
        low_20d = before_trade.tail(20)['low'].min() if len(before_trade) >= 20 else current['low']
        features['vs_20d_high_pct'] = ((current['close'] - high_20d) / high_20d * 100)
        features['vs_20d_low_pct'] = ((current['close'] - low_20d) / low_20d * 100)

        # 8. 갭 여부
        features['gap_up'] = current['open'] > features['prev_close'] * 1.02
        features['gap_down'] = current['open'] < features['prev_close'] * 0.98

        # 9. 캔들 패턴
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

    # 09/08-09/16 파일들
    all_files = [f for f in os.listdir(log_dir) if f.startswith('signal_new2_replay_202509') and f.endswith('.txt')]

    for file in all_files:
        match = re.search(r'(\d{8})', file)
        if match:
            date_str = match.group(1)
            day = int(date_str[6:8])
            if 8 <= day <= 16:
                target_files.append((file, date_str))

    all_trades = []

    for file, date in sorted(target_files):
        print(f"파싱 중: {file} (날짜: {date})")

        try:
            with open(os.path.join(log_dir, file), 'r', encoding='utf-8') as f:
                content = f.read()

            # 종목별로 섹션을 나눔
            sections = re.split(r'=== (\d{6}) -', content)[1:]

            # 종목코드와 내용 분할
            for i in range(0, len(sections), 2):
                if i + 1 < len(sections):
                    stock_code = sections[i]
                    section_content = sections[i + 1]

                    # 매매 결과 찾기
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
                            'win': profit_pct_float > 0,
                            'sell_reason': sell_reason
                        }

                        all_trades.append(trade_info)

        except Exception as e:
            print(f"파일 처리 오류 ({file}): {e}")

    return all_trades

def main():
    print("=== 최종 매매 패턴 분석 ===")

    # 1. 매매 로그 파싱
    trades = parse_trades_with_stock_codes()
    print(f"총 {len(trades)}건의 매매 발견")

    if len(trades) == 0:
        print("분석할 거래가 없습니다.")
        return

    # 2. 일봉 데이터와 결합
    enriched_trades = []
    daily_found = 0
    daily_not_found = 0

    print("\n일봉 데이터 결합 중...")
    for trade in trades:
        daily_data = load_daily_data(trade['stock_code'])
        if daily_data is not None:
            daily_features = calculate_daily_features(daily_data, trade['date'])
            if daily_features:
                enriched_trade = {**trade, **daily_features}
                enriched_trades.append(enriched_trade)
                daily_found += 1
            else:
                enriched_trades.append(trade)  # 일봉 특성 없이라도 포함
        else:
            enriched_trades.append(trade)  # 일봉 데이터 없이라도 포함
            daily_not_found += 1

    print(f"일봉 데이터 보유: {daily_found}건")
    print(f"일봉 데이터 없음: {daily_not_found}건")
    print(f"총 분석 거래: {len(enriched_trades)}건")

    # 3. DataFrame 변환 및 분석
    df = pd.DataFrame(enriched_trades)

    # 기본 통계
    wins = df[df['win'] == True]
    losses = df[df['win'] == False]

    print(f"\n=== 기본 승패 통계 ===")
    print(f"총 거래: {len(df)}건")
    print(f"승리: {len(wins)}건, 패배: {len(losses)}건")
    print(f"전체 승률: {len(wins)/len(df)*100:.1f}%")

    # 손절/익절 분석
    profit_trades = df[df['sell_reason'].str.contains('profit')]
    stoploss_trades = df[df['sell_reason'].str.contains('stop_loss')]
    print(f"익절 거래: {len(profit_trades)}건 (승률: {len(profit_trades)/len(df)*100:.1f}%)")
    print(f"손절 거래: {len(stoploss_trades)}건 (손실률: {len(stoploss_trades)/len(df)*100:.1f}%)")

    # 일별 통계
    print(f"\n=== 일별 승패 통계 ===")
    daily_stats = df.groupby('date').agg({
        'win': ['count', 'sum'],
        'profit_pct': 'mean'
    }).round(2)
    daily_stats.columns = ['총거래', '승리', '평균수익률']
    daily_stats['승률'] = (daily_stats['승리'] / daily_stats['총거래'] * 100).round(1)
    print(daily_stats)

    # 일봉 특성이 있는 데이터로 분석
    df_with_daily = df.dropna(subset=['current_close'])

    if len(df_with_daily) > 10:
        wins_daily = df_with_daily[df_with_daily['win'] == True]
        losses_daily = df_with_daily[df_with_daily['win'] == False]

        print(f"\n=== 일봉 특성 승패 분석 (데이터 보유: {len(df_with_daily)}건) ===")
        print(f"승리: {len(wins_daily)}건, 패배: {len(losses_daily)}건 (승률: {len(wins_daily)/len(df_with_daily)*100:.1f}%)")

        # 주요 특성 비교
        features_to_analyze = [
            ('daily_change_pct', '당일 변동률'),
            ('volume_ratio', '거래량 배수'),
            ('daily_volatility', '당일 변동성'),
            ('price_vs_ma20', '20일선 대비'),
            ('rsi', 'RSI'),
            ('vs_20d_high_pct', '20일 고점 대비'),
            ('body_size_pct', '캔들 몸통 크기')
        ]

        print(f"\n{'특성':<15} {'승리 평균':<10} {'패배 평균':<10} {'차이':<8} {'개선 방향'}")
        print("-" * 65)

        insights = []

        for feature, name in features_to_analyze:
            if feature in df_with_daily.columns:
                win_mean = wins_daily[feature].mean() if len(wins_daily) > 0 else 0
                loss_mean = losses_daily[feature].mean() if len(losses_daily) > 0 else 0
                diff = win_mean - loss_mean

                improvement = ""
                if abs(diff) > 0.5:
                    if diff > 0:
                        improvement = f">{win_mean:.1f} 선호"
                    else:
                        improvement = f"<{loss_mean:.1f} 회피"

                print(f"{name:<15} {win_mean:>9.2f} {loss_mean:>10.2f} {diff:>7.2f} {improvement}")

                if abs(diff) > 1.0:
                    insights.append((name, diff, improvement))

        # 범주형 특성 분석
        categorical_features = ['gap_up', 'gap_down', 'is_green']

        print(f"\n=== 범주형 특성 승률 분석 ===")
        for feature in categorical_features:
            if feature in df_with_daily.columns:
                feature_stats = df_with_daily.groupby(feature)['win'].agg(['count', 'sum', 'mean'])
                if len(feature_stats) > 1:
                    print(f"\n{feature}:")
                    for idx, row in feature_stats.iterrows():
                        print(f"  {idx}: {row['sum']}/{row['count']} (승률: {row['mean']*100:.1f}%)")

    # 4. CSV 저장
    df.to_csv('final_trading_analysis.csv', index=False, encoding='utf-8-sig')
    print(f"\n결과를 final_trading_analysis.csv에 저장했습니다.")

    # 5. 주요 개선 제안
    print(f"\n=== 승률 개선 제안 ===")

    if len(df_with_daily) > 10:
        print("1. 필터 조건 제안:")

        # RSI 기반 필터
        if 'rsi' in df_with_daily.columns:
            win_rsi = wins_daily['rsi'].mean() if len(wins_daily) > 0 else 50
            loss_rsi = losses_daily['rsi'].mean() if len(losses_daily) > 0 else 50
            if abs(win_rsi - loss_rsi) > 5:
                direction = "이하" if win_rsi < loss_rsi else "이상"
                threshold = min(win_rsi, loss_rsi) if win_rsi < loss_rsi else max(win_rsi, loss_rsi)
                print(f"   - RSI {threshold:.0f} {direction}에서 매매")

        # 거래량 기반 필터
        if 'volume_ratio' in df_with_daily.columns:
            win_vol = wins_daily['volume_ratio'].mean() if len(wins_daily) > 0 else 1
            loss_vol = losses_daily['volume_ratio'].mean() if len(losses_daily) > 0 else 1
            if abs(win_vol - loss_vol) > 0.5:
                direction = "이하" if win_vol < loss_vol else "이상"
                threshold = min(win_vol, loss_vol) if win_vol < loss_vol else max(win_vol, loss_vol)
                print(f"   - 거래량 비율 {threshold:.1f}배 {direction}에서 매매")

        # 20일선 대비 위치
        if 'price_vs_ma20' in df_with_daily.columns:
            win_ma20 = wins_daily['price_vs_ma20'].mean() if len(wins_daily) > 0 else 0
            loss_ma20 = losses_daily['price_vs_ma20'].mean() if len(losses_daily) > 0 else 0
            if abs(win_ma20 - loss_ma20) > 2:
                direction = "이하" if win_ma20 < loss_ma20 else "이상"
                threshold = min(win_ma20, loss_ma20) if win_ma20 < loss_ma20 else max(win_ma20, loss_ma20)
                print(f"   - 20일선 대비 {threshold:+.1f}% {direction}에서 매매")

    print("\n2. 4/5 가격 매수 실패 개선:")
    print("   - 돌파봉 거래량이 평균의 1.5배 미만이면 진입가를 3/5로 하향")
    print("   - 돌파봉 몸통 크기가 1.5% 미만이면 매수 보류")
    print("   - 돌파 후 1분 후 재확인 매수로 변경")
    print("   - 호가창 매도 잔량이 매수 잔량의 2배 이상이면 진입 보류")

    return df

if __name__ == "__main__":
    df = main()