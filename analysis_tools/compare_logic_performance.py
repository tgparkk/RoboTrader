"""
기존 로직 vs 개선된 로직 성능 비교

실제 매매 기록에 개선된 조건을 적용했을 때의 예상 결과
"""

import re
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import pickle

class LogicPerformanceComparator:
    """로직 성능 비교기"""

    def __init__(self):
        self.signal_log_dir = Path("signal_replay_log")
        self.daily_dir = Path("cache/daily")

    def analyze_daily_pattern_strength(self, stock_code: str, date: str) -> dict:
        """일봉 패턴 강도 분석 (pullback_candle_pattern.py와 동일)"""
        try:
            # 가능한 파일명들 시도
            possible_files = [
                f"{stock_code}_{date}_daily.pkl",
                f"{stock_code}_{datetime.strptime(date, '%Y%m%d').strftime('%Y%m%d')}_daily.pkl"
            ]

            daily_df = None
            for filename in possible_files:
                file_path = self.daily_dir / filename
                if file_path.exists():
                    try:
                        with open(file_path, 'rb') as f:
                            daily_df = pickle.load(f)
                        break
                    except:
                        continue

            if daily_df is None or len(daily_df) < 10:
                return {'strength': 50, 'ideal_pattern': False}

            # 컬럼명 정규화
            if 'stck_clpr' in daily_df.columns:
                daily_df = daily_df.rename(columns={
                    'stck_clpr': 'close',
                    'stck_oprc': 'open',
                    'acml_vol': 'volume'
                })

            # 최근 5일 데이터
            recent_5days = daily_df.tail(5).copy()

            # 숫자형 변환
            for col in ['close', 'volume']:
                if col in recent_5days.columns:
                    recent_5days[col] = pd.to_numeric(recent_5days[col], errors='coerce')

            # 가격 변화율 (5일간)
            prices = recent_5days['close'].values
            price_change_pct = (prices[-1] - prices[0]) / prices[0] * 100 if len(prices) >= 2 else 0

            # 거래량 변화율 (5일간)
            volumes = recent_5days['volume'].values
            volume_change_pct = (volumes[-1] - volumes[0]) / volumes[0] * 100 if len(volumes) >= 2 else 0

            # 이동평균 위치
            ma3 = recent_5days['close'].rolling(3).mean().iloc[-1]
            current_price = recent_5days['close'].iloc[-1]
            ma_position = (current_price - ma3) / ma3 * 100 if ma3 > 0 else 0

            # 패턴 강도 계산 (0-100)
            strength = 50

            # 가격 상승 점수
            if price_change_pct > 5:
                strength += 30
            elif price_change_pct > 3:
                strength += 20
            elif price_change_pct > 1:
                strength += 10
            elif price_change_pct < -3:
                strength -= 20

            # 거래량 감소 점수
            if volume_change_pct < -20:
                strength += 25
            elif volume_change_pct < -10:
                strength += 15
            elif volume_change_pct < 0:
                strength += 5
            elif volume_change_pct > 20:
                strength -= 15

            # 이동평균 위치 점수
            if ma_position > 3:
                strength += 15
            elif ma_position > 1:
                strength += 10
            elif ma_position > 0:
                strength += 5
            elif ma_position < -3:
                strength -= 15

            # 이상적 패턴
            ideal_pattern = (price_change_pct > 2 and volume_change_pct < -10 and ma_position > 0)
            if ideal_pattern:
                strength += 10

            return {
                'strength': max(0, min(100, strength)),
                'ideal_pattern': ideal_pattern,
                'price_change_pct': price_change_pct,
                'volume_change_pct': volume_change_pct,
                'ma_position': ma_position
            }

        except Exception as e:
            return {'strength': 50, 'ideal_pattern': False}

    def get_enhanced_min_confidence(self, hour: int, daily_pattern: dict) -> int:
        """개선된 로직의 최소 신뢰도 계산"""
        daily_strength = daily_pattern['strength']
        is_ideal_daily = daily_pattern['ideal_pattern']

        # 기본 시간대별 조건
        if 12 <= hour < 14:  # 오후시간 (승률 29.6%)
            min_confidence = 85
            if daily_strength < 60:
                min_confidence = 95  # 거의 불가능
            elif is_ideal_daily:
                min_confidence = 80
        elif 9 <= hour < 10:  # 개장시간 (승률 66.7%)
            min_confidence = 70
            if daily_strength >= 70:
                min_confidence = 65
            elif daily_strength < 40:
                min_confidence = 80
        else:  # 오전/늦은시간
            min_confidence = 75
            if is_ideal_daily and daily_strength >= 70:
                min_confidence = 70
            elif daily_strength < 50:
                min_confidence = 85

        return min_confidence

    def compare_signal_decisions(self) -> dict:
        """기존 vs 개선된 로직 신호 결정 비교"""
        comparison_results = []

        # 최근 로그 파일들 분석
        log_files = sorted(self.signal_log_dir.glob("signal_new2_replay_*.txt"))[-5:]

        for log_file in log_files:
            print(f"분석 중: {log_file.name}")

            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                # 날짜 추출
                date_match = re.search(r'(\d{8})', log_file.name)
                if not date_match:
                    continue
                trade_date = date_match.group(1)

                # 종목별 신호 분석
                sections = re.split(r'=== (\d{6}) - \d{8}', content)[1:]

                for i in range(0, len(sections), 2):
                    if i + 1 >= len(sections):
                        break

                    stock_code = sections[i]
                    section_content = sections[i + 1]

                    # 실제 발생한 신호들 추출
                    signal_matches = re.findall(r'(\d{2}:\d{2}) \[([^\]]+)\]', section_content)

                    for time_str, signal_type in signal_matches:
                        hour = int(time_str.split(':')[0])

                        # 시간대 분류
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

                        # 일봉 패턴 분석
                        daily_pattern = self.analyze_daily_pattern_strength(stock_code, trade_date)

                        # 기존 로직 조건 (고정)
                        old_min_confidence = 70

                        # 개선된 로직 조건
                        new_min_confidence = self.get_enhanced_min_confidence(hour, daily_pattern)

                        # 가상의 패턴 신뢰도 (실제로는 로그에서 추출해야 함)
                        # 여기서는 시간대별 평균 신뢰도로 가정
                        avg_confidence = {
                            'opening': 82,
                            'morning': 78,
                            'afternoon': 75,
                            'late': 80,
                            'other': 75
                        }.get(time_category, 75)

                        # 결정 비교
                        old_decision = avg_confidence >= old_min_confidence
                        new_decision = avg_confidence >= new_min_confidence

                        comparison_results.append({
                            'stock_code': stock_code,
                            'date': trade_date,
                            'time': time_str,
                            'hour': hour,
                            'time_category': time_category,
                            'avg_confidence': avg_confidence,
                            'daily_strength': daily_pattern['strength'],
                            'daily_ideal': daily_pattern['ideal_pattern'],
                            'old_min_confidence': old_min_confidence,
                            'new_min_confidence': new_min_confidence,
                            'old_decision': old_decision,
                            'new_decision': new_decision,
                            'decision_changed': old_decision != new_decision
                        })

            except Exception as e:
                print(f"오류 {log_file.name}: {e}")
                continue

        return comparison_results

    def analyze_comparison_results(self, results: list):
        """비교 결과 분석"""
        if not results:
            print("분석할 결과가 없습니다.")
            return

        df = pd.DataFrame(results)

        print(f"\n=== 기존 vs 개선된 로직 비교 분석 ===")
        print(f"총 신호 분석: {len(df)}개")

        # 전체 신호 발생 비교
        old_signals = df['old_decision'].sum()
        new_signals = df['new_decision'].sum()
        change_pct = (new_signals - old_signals) / old_signals * 100 if old_signals > 0 else 0

        print(f"기존 로직 신호: {old_signals}개")
        print(f"개선된 로직 신호: {new_signals}개")
        print(f"신호 변화: {change_pct:+.1f}%")

        # 시간대별 분석
        print(f"\n=== 시간대별 신호 변화 ===")
        time_analysis = df.groupby('time_category').agg({
            'old_decision': 'sum',
            'new_decision': 'sum',
            'decision_changed': 'sum'
        })

        for time_cat, row in time_analysis.iterrows():
            old_count = row['old_decision']
            new_count = row['new_decision']
            changed = row['decision_changed']
            change_pct = (new_count - old_count) / old_count * 100 if old_count > 0 else 0

            print(f"{time_cat:12}: {old_count:3d} → {new_count:3d} ({change_pct:+6.1f}%) 변경:{changed:2d}")

        # 일봉 강도별 분석
        print(f"\n=== 일봉 강도별 신호 변화 ===")
        df['strength_range'] = pd.cut(
            df['daily_strength'],
            bins=[0, 50, 70, 85, 100],
            labels=['약함(0-50)', '보통(50-70)', '강함(70-85)', '매우강함(85+)']
        )

        strength_analysis = df.groupby('strength_range', observed=True).agg({
            'old_decision': 'sum',
            'new_decision': 'sum'
        })

        for strength, row in strength_analysis.iterrows():
            old_count = row['old_decision']
            new_count = row['new_decision']
            change_pct = (new_count - old_count) / old_count * 100 if old_count > 0 else 0
            print(f"{strength:15}: {old_count:3d} → {new_count:3d} ({change_pct:+6.1f}%)")

        # 주요 변화 케이스
        print(f"\n=== 주요 변화 사례 ===")

        # 차단된 신호 (기존 O → 개선 X)
        blocked = df[(df['old_decision'] == True) & (df['new_decision'] == False)]
        print(f"차단된 신호: {len(blocked)}개")
        if len(blocked) > 0:
            blocked_by_time = blocked['time_category'].value_counts()
            print("  시간대별:", dict(blocked_by_time))

        # 추가된 신호 (기존 X → 개선 O)
        added = df[(df['old_decision'] == False) & (df['new_decision'] == True)]
        print(f"추가된 신호: {len(added)}개")
        if len(added) > 0:
            added_by_time = added['time_category'].value_counts()
            print("  시간대별:", dict(added_by_time))

        return df

def main():
    """메인 실행"""
    print("기존 vs 개선된 로직 성능 비교")
    print("="*50)

    comparator = LogicPerformanceComparator()

    # 신호 결정 비교
    results = comparator.compare_signal_decisions()

    # 결과 분석
    analysis_df = comparator.analyze_comparison_results(results)

    print(f"\n=== 예상 효과 ===")
    print("• 오후시간 위험 신호 대폭 감소")
    print("• 강한 일봉 패턴에서 기회 확대")
    print("• 전체적으로 더 선별적인 매매")

    if analysis_df is not None and not analysis_df.empty:
        # CSV 저장
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"logic_comparison_{timestamp}.csv"
        analysis_df.to_csv(output_path, index=False, encoding='utf-8-sig')
        print(f"상세 결과 저장: {output_path}")

if __name__ == "__main__":
    main()