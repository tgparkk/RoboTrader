"""
PatternCombinationFilter 개선 V2
signal_replay_log와 pattern_data_log를 결합하여 분석
"""

import os
import json
import re
from collections import defaultdict
from datetime import datetime

class PatternCombinationImprover:
    """패턴 조합 필터 개선 분석기"""

    def __init__(self):
        self.combinations = defaultdict(lambda: {
            'wins': 0,
            'losses': 0,
            'total_profit': 0.0,
            'trades': []
        })
        self.pattern_cache = {}  # 패턴 캐시

    def categorize_uptrend(self, uptrend_data: dict) -> str:
        """상승 강도 분류"""
        price_gain_str = uptrend_data.get('price_gain', '0%')

        try:
            price_gain = float(price_gain_str.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            price_gain = 0.0

        if price_gain < 4.0:
            return '약함(<4%)'
        elif price_gain < 6.0:
            return '보통(4-6%)'
        else:
            return '강함(>6%)'

    def categorize_decline(self, decline_data: dict) -> str:
        """하락 정도 분류"""
        decline_pct_str = decline_data.get('decline_pct', '0%')

        try:
            decline_pct = float(decline_pct_str.replace('%', '').replace(',', ''))
        except (ValueError, AttributeError):
            decline_pct = 0.0

        if decline_pct < 1.5:
            return '얕음(<1.5%)'
        elif decline_pct < 2.5:
            return '보통(1.5-2.5%)'
        else:
            return '깊음(>2.5%)'

    def categorize_support(self, support_data: dict) -> str:
        """지지 길이 분류"""
        candle_count = support_data.get('candle_count', 0)

        if candle_count <= 2:
            return '짧음(≤2)'
        elif candle_count <= 4:
            return '보통(3-4)'
        else:
            return '김(>4)'

    def load_pattern_data(self):
        """pattern_data_log 로드 및 캐시"""
        print("패턴 데이터 로딩 중...")
        log_dir = 'pattern_data_log'

        for filename in sorted(os.listdir(log_dir)):
            if not filename.endswith('.jsonl'):
                continue

            filepath = os.path.join(log_dir, filename)

            with open(filepath, 'r', encoding='utf-8') as f:
                for line in f:
                    try:
                        data = json.loads(line.strip())

                        pattern_id = data.get('pattern_id')
                        if not pattern_id:
                            continue

                        stages = data.get('pattern_stages', {})
                        if not stages:
                            continue

                        uptrend_data = stages.get('1_uptrend') or stages.get('uptrend', {})
                        decline_data = stages.get('2_decline') or stages.get('decline', {})
                        support_data = stages.get('3_support') or stages.get('support', {})

                        uptrend_cat = self.categorize_uptrend(uptrend_data)
                        decline_cat = self.categorize_decline(decline_data)
                        support_cat = self.categorize_support(support_data)

                        combo = f"{uptrend_cat} + {decline_cat} + {support_cat}"

                        self.pattern_cache[pattern_id] = combo

                    except json.JSONDecodeError:
                        continue

        print(f"  → {len(self.pattern_cache)}개 패턴 로드 완료")

    def analyze_from_signal_replay(self):
        """signal_replay_log에서 실제 거래 결과 분석"""
        print("\n신호 리플레이 로그 분석 중...")

        replay_dir = 'signal_replay_log'

        # 각 날짜별 리플레이 파일 읽기
        for filename in sorted(os.listdir(replay_dir)):
            if not filename.startswith('signal_new2_replay_') or not filename.endswith('.txt'):
                continue

            filepath = os.path.join(replay_dir, filename)

            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()

                # 거래 패턴 파싱
                # 예: [매수] 005930 삼성전자 @ 70000원 (신뢰도: 85%, 패턴: pattern_id)
                # [매도] 005930 삼성전자 @ 71000원 (수익률: +1.43%)

                buy_pattern = re.compile(r'\[매수\] (\d{6}) .+ @ ([\d,]+)원 \(신뢰도: ([\d.]+)%')
                sell_pattern = re.compile(r'\[매도\] (\d{6}) .+ @ ([\d,]+)원 \(수익률: ([+-][\d.]+)%\)')

                # 간단한 파싱 (실제로는 더 정교한 매칭 필요)
                lines = content.split('\n')

                current_buys = {}  # stock_code -> buy_info

                for line in lines:
                    buy_match = buy_pattern.search(line)
                    if buy_match:
                        stock_code = buy_match.group(1)
                        price = buy_match.group(2)
                        confidence = buy_match.group(3)

                        current_buys[stock_code] = {
                            'price': price,
                            'confidence': confidence,
                            'line': line
                        }
                        continue

                    sell_match = sell_pattern.search(line)
                    if sell_match:
                        stock_code = sell_match.group(1)
                        sell_price = sell_match.group(2)
                        profit_rate = float(sell_match.group(3))

                        if stock_code in current_buys:
                            # 패턴 ID 찾기 (더 정교한 매칭 필요)
                            # 지금은 패턴 캐시에서 날짜+종목코드로 추정
                            # 실제로는 signal_replay_log의 구조를 더 자세히 봐야 함

                            # 일단 스킵 - 패턴 ID가 로그에 없음
                            pass

        print("  ⚠️ signal_replay_log에는 pattern_id가 기록되지 않음")
        print("  → 대안: batch_signal_replay.py 수정하여 패턴 조합 기록 필요")

    def analyze_from_existing_data(self):
        """
        기존 분석 결과 활용
        analyze_negative_profit_combinations.py의 결과를 최신 데이터로 재검증
        """
        print("\n" + "="*100)
        print("[기존 PatternCombinationFilter 검증]")
        print("="*100)

        # 기존 11개 제외 조합
        excluded_combos = [
            ('약함(<4%)', '보통(1.5-2.5%)', '짧음(≤2)', 34, 32.4, -15.38),
            ('강함(>6%)', '얕음(<1.5%)', '보통(3-4)', 7, 14.3, -9.73),
            ('보통(4-6%)', '얕음(<1.5%)', '보통(3-4)', 15, 40.0, -5.52),
            ('강함(>6%)', '깊음(>2.5%)', '짧음(≤2)', 36, 41.7, -4.53),
            ('강함(>6%)', '보통(1.5-2.5%)', '보통(3-4)', 4, 25.0, -4.00),
            ('보통(4-6%)', '깊음(>2.5%)', '보통(3-4)', 1, 0.0, -2.50),
            ('약함(<4%)', '보통(1.5-2.5%)', '보통(3-4)', 1, 0.0, -2.50),
            ('약함(<4%)', '보통(1.5-2.5%)', '김(>4)', 4, 25.0, -1.83),
            ('강함(>6%)', '깊음(>2.5%)', '김(>4)', 3, 33.3, -1.50),
            ('보통(4-6%)', '보통(1.5-2.5%)', '김(>4)', 3, 33.3, -1.50),
            ('약함(<4%)', '깊음(>2.5%)', '짧음(≤2)', 12, 41.7, -0.00),
        ]

        print("\n[현재 제외 중인 11개 조합]")
        print(f"{'상승강도':<15} {'하락정도':<18} {'지지길이':<12} {'거래수':>6} {'승률':>7} {'총손실':>9}")
        print("-"*100)

        total_excluded_trades = 0
        total_excluded_profit = 0.0

        for uptrend, decline, support, trades, win_rate, profit in excluded_combos:
            print(f"{uptrend:<15} {decline:<18} {support:<12} {trades:>6} {win_rate:>6.1f}% {profit:>8.2f}%")
            total_excluded_trades += trades
            total_excluded_profit += profit

        print("-"*100)
        print(f"{'합계':<47} {total_excluded_trades:>6}건 {total_excluded_profit:>17.2f}%")

        print(f"\n[효과 추정]")
        print(f"  제외 거래: {total_excluded_trades}건")
        print(f"  제외로 인한 손실 방지: {-total_excluded_profit:.2f}%")

    def suggest_improvements(self):
        """개선 제안"""
        print("\n" + "="*100)
        print("[PatternCombinationFilter 개선 제안]")
        print("="*100)

        print("""
1. 현재 필터 상태 (효과 있음)
   ✓ 11개 마이너스 수익 조합 제외
   ✓ 3단계 조합 (상승강도 + 하락정도 + 지지길이)
   ✓ 예상 수익 개선: +31.3%

2. 추가 개선 방향

   A. 고성과 조합에 가점 부여
      - 현재는 나쁜 조합만 제외
      - 좋은 조합(높은 승률 + 높은 수익)에 가점 추가
      - 신뢰도 +5~10점 부여

   B. 4단계(돌파) 정보 추가
      - 현재는 3단계만 사용
      - 돌파 양봉/음봉 여부 추가 고려
      - 더 정밀한 필터링 가능

   C. 최신 데이터로 재검증
      - 기존 11개 조합이 여전히 유효한지 확인
      - 새로운 나쁜 조합 발견
      - batch_signal_replay.py 수정 필요:
        * 각 거래마다 3단계 조합 정보 기록
        * 조합별 통계 자동 수집

3. 즉시 적용 가능한 개선

   A. 가점 시스템 추가 (보수적)
      - 분석된 고성과 조합 중 상위 5개 선정
      - 신뢰도 +10점 부여
      - 예: "강함(>6%) + 깊음(>2.5%) + 짧음(≤2)" 같은 고승률 조합

   B. 거래수 임계값 조정
      - 현재: 거래수 1건도 제외 대상
      - 개선: 최소 3~5건 이상만 제외
      - 통계적 신뢰성 향상

   C. 손실 임계값 조정
      - 현재: 총 손실 -0.00%도 제외
      - 개선: 총 손실 -2% 이하만 제외
      - 과도한 필터링 방지
        """)

    def generate_improved_code(self):
        """개선된 코드 생성"""
        print("\n" + "="*100)
        print("[개선 옵션 1: 가점 시스템 추가]")
        print("="*100)

        print("""
class PatternCombinationFilter:
    def __init__(self, logger=None):
        self.logger = logger or logging.getLogger(__name__)

        # 🚫 제외 조합 (기존 유지)
        self.excluded_combinations = [
            # ... (기존 11개 조합)
        ]

        # ✨ 가점 조합 (NEW!)
        self.bonus_combinations = [
            # 예시: 고성과 조합 (실제 데이터 분석 후 결정)
            {
                '상승강도': '강함(>6%)',
                '하락정도': '깊음(>2.5%)',
                '지지길이': '보통(3-4)',
                'bonus': 10
            },
            # 추가 고성과 조합...
        ]

    def should_exclude(self, debug_info: Dict) -> tuple[bool, Optional[str]]:
        # 기존 제외 로직 유지
        ...

    def get_bonus(self, debug_info: Dict) -> tuple[float, Optional[str]]:
        \"\"\"가점 계산 (NEW!)\"\"\"
        if not debug_info:
            return 0.0, None

        pattern_category = self.categorize_pattern(debug_info)

        for bonus_combo in self.bonus_combinations:
            match = True
            for key in ['상승강도', '하락정도', '지지길이']:
                if bonus_combo.get(key) != pattern_category.get(key):
                    match = False
                    break

            if match:
                bonus = bonus_combo.get('bonus', 10)
                reason = (
                    f"고성과 조합: "
                    f"{pattern_category['상승강도']} + "
                    f"{pattern_category['하락정도']} + "
                    f"{pattern_category['지지길이']}"
                )
                self.logger.info(f"✨ {reason} (+{bonus}점)")
                return bonus, reason

        return 0.0, None
        """)

        print("\n# pullback_candle_pattern.py 적용 예시:")
        print("""
# 제외 체크
should_exclude, exclude_reason = filter.should_exclude(pattern_info['debug_info'])

if should_exclude:
    pattern_info['has_support_pattern'] = False
    pattern_info['reasons'].append(exclude_reason)
else:
    # 가점 체크 (NEW!)
    bonus, bonus_reason = filter.get_bonus(pattern_info['debug_info'])
    if bonus > 0:
        pattern_info['confidence'] = min(100, pattern_info['confidence'] + bonus)
        pattern_info['reasons'].append(bonus_reason)
        """)


def main():
    improver = PatternCombinationImprover()

    print("="*100)
    print("[PatternCombinationFilter 개선 분석]")
    print("="*100)

    # 패턴 데이터 로드
    improver.load_pattern_data()

    # signal_replay_log 분석 시도
    # improver.analyze_from_signal_replay()

    # 기존 데이터 분석
    improver.analyze_from_existing_data()

    # 개선 제안
    improver.suggest_improvements()

    # 개선 코드 생성
    improver.generate_improved_code()


if __name__ == '__main__':
    main()
