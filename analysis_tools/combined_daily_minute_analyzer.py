"""
일봉 + 분봉 결합 분석기

기존 분석에 일봉 패턴을 추가하여 더 정확한 매매 조건 도출
"""

import pandas as pd
import numpy as np
import pickle
from pathlib import Path
from datetime import datetime
import re
from typing import Dict, List, Optional

class CombinedDailyMinuteAnalyzer:
    """일봉 + 분봉 결합 분석기"""

    def __init__(self):
        self.signal_log_dir = Path("signal_replay_log")
        self.daily_dir = Path("cache/daily")
        self.minute_dir = Path("cache/minute_data")

        self.enhanced_results = []

    def load_daily_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """일봉 데이터 로드"""
        # 해당 날짜의 일봉 파일 찾기
        date_obj = datetime.strptime(date, '%Y%m%d')

        # 여러 형식으로 시도
        possible_files = [
            f"{stock_code}_{date}_daily.pkl",
            f"{stock_code}_{date_obj.strftime('%Y%m%d')}_daily.pkl"
        ]

        for filename in possible_files:
            file_path = self.daily_dir / filename
            if file_path.exists():
                try:
                    with open(file_path, 'rb') as f:
                        df = pickle.load(f)

                    # 컬럼명 표준화
                    if 'stck_bsop_date' in df.columns:
                        df = df.rename(columns={
                            'stck_bsop_date': 'date',
                            'stck_clpr': 'close',
                            'stck_oprc': 'open',
                            'stck_hgpr': 'high',
                            'stck_lwpr': 'low',
                            'acml_vol': 'volume'
                        })

                    # 해당 날짜까지만 필터링 (미래 데이터 제거)
                    df['date'] = pd.to_datetime(df['date'], format='%Y%m%d')
                    target_date = pd.to_datetime(date, format='%Y%m%d')
                    df = df[df['date'] <= target_date].copy()

                    return df
                except Exception as e:
                    continue

        return None

    def load_minute_data(self, stock_code: str, date: str) -> Optional[pd.DataFrame]:
        """분봉 데이터 로드"""
        file_path = self.minute_dir / f"{stock_code}_{date}.pkl"
        if file_path.exists():
            try:
                with open(file_path, 'rb') as f:
                    return pickle.load(f)
            except:
                pass
        return None

    def analyze_daily_pattern(self, daily_df: pd.DataFrame) -> Dict:
        """일봉 패턴 상세 분석"""
        if daily_df is None or len(daily_df) < 10:
            return {'valid': False}

        try:
            # 최근 10일 데이터
            recent_days = daily_df.tail(10).copy()

            # 숫자형 변환
            for col in ['close', 'open', 'high', 'low', 'volume']:
                if col in recent_days.columns:
                    recent_days[col] = pd.to_numeric(recent_days[col], errors='coerce')

            # 1. 가격 추세 분석 (최근 5일)
            recent_5days = recent_days.tail(5)
            prices = recent_5days['close'].values
            price_trend = np.polyfit(range(len(prices)), prices, 1)[0] if len(prices) >= 3 else 0
            price_change_pct = (prices[-1] - prices[0]) / prices[0] * 100 if len(prices) >= 2 else 0

            # 2. 거래량 추세 분석 (최근 5일)
            volumes = recent_5days['volume'].values
            volume_trend = np.polyfit(range(len(volumes)), volumes, 1)[0] if len(volumes) >= 3 else 0
            volume_change_pct = (volumes[-1] - volumes[0]) / volumes[0] * 100 if len(volumes) >= 2 else 0

            # 3. 이동평균 분석
            ma5 = recent_days['close'].rolling(5).mean().iloc[-1]
            ma10 = recent_days['close'].rolling(10).mean().iloc[-1] if len(recent_days) >= 10 else ma5
            current_price = recent_days['close'].iloc[-1]

            ma5_position = (current_price - ma5) / ma5 * 100 if ma5 > 0 else 0
            ma10_position = (current_price - ma10) / ma10 * 100 if ma10 > 0 else 0

            # 4. 거래량 패턴 분석
            avg_volume_5d = recent_5days['volume'].mean()
            avg_volume_10d = recent_days['volume'].mean()
            current_volume = recent_days['volume'].iloc[-1]

            volume_ratio_5d = current_volume / avg_volume_5d if avg_volume_5d > 0 else 1
            volume_ratio_10d = current_volume / avg_volume_10d if avg_volume_10d > 0 else 1

            # 5. 눌림목 이상적 패턴 판단
            ideal_pullback_pattern = (
                price_change_pct > 3.0 and  # 5일간 3% 이상 상승
                volume_change_pct < -15.0 and  # 거래량 15% 이상 감소
                ma5_position > 1.0 and  # 5일 이평선 1% 이상 위
                ma10_position > 0  # 10일 이평선 위
            )

            # 6. 패턴 강도 점수 (0-100)
            strength = 0

            # 가격 상승 점수 (0-40)
            if price_change_pct > 5:
                strength += 40
            elif price_change_pct > 3:
                strength += 30
            elif price_change_pct > 1:
                strength += 20
            elif price_change_pct > 0:
                strength += 10

            # 거래량 감소 점수 (0-30)
            if volume_change_pct < -25:
                strength += 30
            elif volume_change_pct < -15:
                strength += 25
            elif volume_change_pct < -5:
                strength += 15
            elif volume_change_pct < 0:
                strength += 10

            # 이동평균 위치 점수 (0-20)
            if ma5_position > 5:
                strength += 20
            elif ma5_position > 2:
                strength += 15
            elif ma5_position > 0:
                strength += 10

            # 추가 보너스 (0-10)
            if ideal_pullback_pattern:
                strength += 10

            return {
                'valid': True,
                'ideal_pullback_pattern': ideal_pullback_pattern,
                'strength': strength,
                'price_trend': price_trend,
                'price_change_pct': price_change_pct,
                'volume_trend': volume_trend,
                'volume_change_pct': volume_change_pct,
                'ma5_position': ma5_position,
                'ma10_position': ma10_position,
                'volume_ratio_5d': volume_ratio_5d,
                'current_price': current_price,
                'ma5': ma5,
                'ma10': ma10
            }

        except Exception as e:
            return {'valid': False, 'error': str(e)}

    def extract_trades_with_daily_context(self) -> List[Dict]:
        """매매 기록에 일봉 컨텍스트 추가하여 추출"""
        enhanced_trades = []

        for log_file in sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt"))[:5]:  # 처음 5개 파일만
            print(f"Processing {log_file.name}")

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 날짜 추출
                date_match = re.search(r'(\d{8})', log_file.name)
                if not date_match:
                    continue
                trade_date = date_match.group(1)

                # 종목별 섹션 분할
                sections = re.split(r'=== (\d{6}) - \d{8}', content)

                for i in range(1, len(sections), 2):
                    if i + 1 >= len(sections):
                        break

                    stock_code = sections[i]
                    section_content = sections[i + 1]

                    # 매매 데이터 추출
                    trade_matches = re.findall(
                        r'(\d{2}:\d{2}) 매수\[([^\]]+)\] @([\d,]+) → (\d{2}:\d{2}) 매도\[([^\]]+)\] @([\d,]+) \(([^)]+)\)',
                        section_content
                    )

                    for match in trade_matches:
                        buy_time, buy_signal, buy_price_str, sell_time, sell_signal, sell_price_str, pnl_str = match

                        # 기본 거래 정보
                        buy_price = int(buy_price_str.replace(',', ''))
                        sell_price = int(sell_price_str.replace(',', ''))
                        pnl_pct = (sell_price - buy_price) / buy_price * 100

                        # 일봉 데이터 로드 및 분석
                        daily_df = self.load_daily_data(stock_code, trade_date)
                        daily_pattern = self.analyze_daily_pattern(daily_df)

                        # 분봉 데이터 로드
                        minute_df = self.load_minute_data(stock_code, trade_date)

                        # 시간대 분류
                        hour = int(buy_time.split(':')[0])
                        if 9 <= hour < 10:
                            time_category = "opening"
                        elif 10 <= hour < 12:
                            time_category = "morning"
                        elif 12 <= hour < 14:
                            time_category = "afternoon"
                        elif 14 <= hour < 15:
                            time_category = "late"
                        else:
                            time_category = "other"

                        enhanced_trade = {
                            'stock_code': stock_code,
                            'date': trade_date,
                            'buy_time': buy_time,
                            'buy_price': buy_price,
                            'sell_time': sell_time,
                            'sell_price': sell_price,
                            'pnl_pct': pnl_pct,
                            'is_winning': pnl_pct > 0,
                            'time_category': time_category,
                            'hour': hour,

                            # 일봉 패턴 정보 추가
                            'daily_valid': daily_pattern.get('valid', False),
                            'daily_ideal_pattern': daily_pattern.get('ideal_pullback_pattern', False),
                            'daily_strength': daily_pattern.get('strength', 0),
                            'daily_price_change_pct': daily_pattern.get('price_change_pct', 0),
                            'daily_volume_change_pct': daily_pattern.get('volume_change_pct', 0),
                            'daily_ma5_position': daily_pattern.get('ma5_position', 0),
                            'daily_ma10_position': daily_pattern.get('ma10_position', 0),
                        }

                        enhanced_trades.append(enhanced_trade)

            except Exception as e:
                print(f"Error processing {log_file.name}: {e}")
                continue

        return enhanced_trades

    def analyze_enhanced_patterns(self):
        """일봉 + 분봉 결합 패턴 분석"""
        print("일봉 + 분봉 결합 분석 시작...")

        # 매매 기록 추출 (일봉 정보 포함)
        enhanced_trades = self.extract_trades_with_daily_context()

        if not enhanced_trades:
            print("분석할 거래 데이터가 없습니다.")
            return

        print(f"분석 대상 거래: {len(enhanced_trades)}개")

        # DataFrame으로 변환
        df = pd.DataFrame(enhanced_trades)

        # 기본 성과 분석
        total_trades = len(df)
        winning_trades = len(df[df['is_winning'] == True])
        current_win_rate = winning_trades / total_trades * 100

        print(f"\n=== 기본 성과 ===")
        print(f"총 거래: {total_trades}개")
        print(f"현재 승률: {current_win_rate:.1f}% ({winning_trades}승 {total_trades - winning_trades}패)")

        # 일봉 패턴별 분석
        print(f"\n=== 일봉 패턴별 성과 ===")

        # 일봉 데이터가 있는 거래만
        valid_daily = df[df['daily_valid'] == True]
        if len(valid_daily) > 0:
            print(f"일봉 분석 가능: {len(valid_daily)}개")

            # 이상적 일봉 패턴 여부별 성과
            ideal_pattern_trades = valid_daily[valid_daily['daily_ideal_pattern'] == True]
            non_ideal_pattern_trades = valid_daily[valid_daily['daily_ideal_pattern'] == False]

            if len(ideal_pattern_trades) > 0:
                ideal_wins = len(ideal_pattern_trades[ideal_pattern_trades['is_winning'] == True])
                ideal_win_rate = ideal_wins / len(ideal_pattern_trades) * 100
                print(f"이상적 일봉 패턴: {ideal_win_rate:.1f}% ({ideal_wins}/{len(ideal_pattern_trades)})")

            if len(non_ideal_pattern_trades) > 0:
                non_ideal_wins = len(non_ideal_pattern_trades[non_ideal_pattern_trades['is_winning'] == True])
                non_ideal_win_rate = non_ideal_wins / len(non_ideal_pattern_trades) * 100
                print(f"일반 일봉 패턴: {non_ideal_win_rate:.1f}% ({non_ideal_wins}/{len(non_ideal_pattern_trades)})")

            # 일봉 강도별 분석
            valid_daily['strength_range'] = pd.cut(
                valid_daily['daily_strength'],
                bins=[0, 50, 70, 85, 100],
                labels=['약함(0-50)', '보통(50-70)', '강함(70-85)', '매우강함(85+)']
            )

            print(f"\n일봉 강도별 성과:")
            strength_analysis = valid_daily.groupby('strength_range').agg({
                'is_winning': ['count', 'sum', 'mean']
            }).round(3)

            for strength_range in strength_analysis.index:
                if pd.notna(strength_range):
                    count = strength_analysis.loc[strength_range, ('is_winning', 'count')]
                    wins = strength_analysis.loc[strength_range, ('is_winning', 'sum')]
                    win_rate = strength_analysis.loc[strength_range, ('is_winning', 'mean')] * 100
                    print(f"{strength_range}: {win_rate:.1f}% ({wins:.0f}/{count:.0f})")

        # 시간대 + 일봉 패턴 결합 분석
        print(f"\n=== 시간대별 + 일봉 패턴 결합 분석 ===")

        for time_cat in ['opening', 'morning', 'afternoon', 'late']:
            time_trades = valid_daily[valid_daily['time_category'] == time_cat]
            if len(time_trades) == 0:
                continue

            print(f"\n{time_cat} 시간대:")

            # 전체 승률
            total_wins = len(time_trades[time_trades['is_winning'] == True])
            total_rate = total_wins / len(time_trades) * 100
            print(f"  전체: {total_rate:.1f}% ({total_wins}/{len(time_trades)})")

            # 이상적 일봉 패턴만
            ideal_time_trades = time_trades[time_trades['daily_ideal_pattern'] == True]
            if len(ideal_time_trades) > 0:
                ideal_wins = len(ideal_time_trades[ideal_time_trades['is_winning'] == True])
                ideal_rate = ideal_wins / len(ideal_time_trades) * 100
                print(f"  이상적 일봉: {ideal_rate:.1f}% ({ideal_wins}/{len(ideal_time_trades)})")

            # 강한 일봉 패턴만 (70점 이상)
            strong_time_trades = time_trades[time_trades['daily_strength'] >= 70]
            if len(strong_time_trades) > 0:
                strong_wins = len(strong_time_trades[strong_time_trades['is_winning'] == True])
                strong_rate = strong_wins / len(strong_time_trades) * 100
                print(f"  강한 일봉(70+): {strong_rate:.1f}% ({strong_wins}/{len(strong_time_trades)})")

        # 개선 권장사항
        print(f"\n=== 개선 권장사항 (일봉 + 분봉 결합) ===")

        # 가장 효과적인 조합 찾기
        best_combinations = []

        for time_cat in ['opening', 'morning', 'afternoon', 'late']:
            for daily_condition in [
                ('이상적패턴', lambda x: x['daily_ideal_pattern'] == True),
                ('강한패턴70+', lambda x: x['daily_strength'] >= 70),
                ('강한패턴80+', lambda x: x['daily_strength'] >= 80)
            ]:
                condition_name, condition_func = daily_condition

                subset = valid_daily[
                    (valid_daily['time_category'] == time_cat) &
                    valid_daily.apply(condition_func, axis=1)
                ]

                if len(subset) >= 5:  # 최소 5개 샘플
                    wins = len(subset[subset['is_winning'] == True])
                    win_rate = wins / len(subset) * 100

                    best_combinations.append({
                        'time': time_cat,
                        'daily_condition': condition_name,
                        'win_rate': win_rate,
                        'wins': wins,
                        'total': len(subset)
                    })

        # 승률 순으로 정렬
        best_combinations.sort(key=lambda x: x['win_rate'], reverse=True)

        print("최고 성과 조합 (상위 5개):")
        for i, combo in enumerate(best_combinations[:5], 1):
            print(f"{i}. {combo['time']} + {combo['daily_condition']}: "
                  f"{combo['win_rate']:.1f}% ({combo['wins']}/{combo['total']})")

        return enhanced_trades

def main():
    """메인 실행"""
    analyzer = CombinedDailyMinuteAnalyzer()
    results = analyzer.analyze_enhanced_patterns()

    print(f"\n✅ 일봉 + 분봉 결합 분석 완료!")
    print(f"이제 일봉 패턴을 고려한 더 정교한 매매 조건을 설정할 수 있습니다.")

if __name__ == "__main__":
    main()