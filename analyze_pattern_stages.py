"""
4단계 패턴 구간 분석 스크립트
승패별 4개 구간(상승, 하락, 지지, 돌파)의 특성 비교
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys


def load_pattern_data(date: str = None):
    """패턴 데이터 로드"""
    log_dir = Path("pattern_data_log")

    if date is None:
        date = datetime.now().strftime('%Y%m%d')

    log_file = log_dir / f"pattern_data_{date}.jsonl"

    if not log_file.exists():
        print(f"[오류] 로그 파일 없음: {log_file}")
        return []

    patterns = []
    with open(log_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                patterns.append(json.loads(line))

    print(f"[완료] {len(patterns)}개 패턴 로드 완료: {log_file}")
    return patterns


def analyze_stage_characteristics(patterns):
    """4단계 구간 특성 분석"""

    # 승패 분류
    wins = []
    losses = []

    for pattern in patterns:
        trade_result = pattern.get('trade_result')
        if trade_result and trade_result.get('trade_executed'):
            profit_rate = trade_result.get('profit_rate', 0)
            if profit_rate > 0:
                wins.append(pattern)
            else:
                losses.append(pattern)

    print("\n" + "="*80)
    print("[4단계 패턴 구간 분석]")
    print("="*80)
    print(f"전체 패턴: {len(patterns)}개")
    print(f"매매 실행: {len(wins) + len(losses)}개")
    print(f"승리: {len(wins)}개 | 패배: {len(losses)}개")

    if len(wins) + len(losses) > 0:
        win_rate = len(wins) / (len(wins) + len(losses)) * 100
        print(f"승률: {win_rate:.1f}%")

    # 각 구간별 승패 비교
    print("\n" + "="*80)
    print("[구간별 승패 특성 비교]")
    print("="*80)

    for stage_name, stage_key in [
        ('1단계: 상승 구간', '1_uptrend'),
        ('2단계: 하락 구간', '2_decline'),
        ('3단계: 지지 구간', '3_support'),
        ('4단계: 돌파 양봉', '4_breakout')
    ]:
        print(f"\n{'='*80}")
        print(f"[{stage_name}]")
        print(f"{'='*80}")

        analyze_single_stage(wins, losses, stage_key, stage_name)


def analyze_single_stage(wins, losses, stage_key, stage_name):
    """단일 구간 분석"""

    # 승리 패턴의 구간 특성 추출
    win_stage_data = []
    for pattern in wins:
        stage_data = pattern.get('pattern_stages', {}).get(stage_key, {})
        if stage_data:
            win_stage_data.append(stage_data)

    # 패배 패턴의 구간 특성 추출
    loss_stage_data = []
    for pattern in losses:
        stage_data = pattern.get('pattern_stages', {}).get(stage_key, {})
        if stage_data:
            loss_stage_data.append(stage_data)

    if not win_stage_data and not loss_stage_data:
        print("  (데이터 없음)")
        return

    # 주요 지표별 평균 비교
    if stage_key == '1_uptrend':
        compare_metric(win_stage_data, loss_stage_data, 'candle_count', '캔들 수')
        compare_metric(win_stage_data, loss_stage_data, 'price_gain', '가격 상승률 (%)', multiplier=100)
        compare_metric(win_stage_data, loss_stage_data, 'max_volume_ratio_vs_avg', '최대 거래량 비율 (당일 평균 대비)')
        compare_metric(win_stage_data, loss_stage_data, 'max_volume', '최대 거래량 (절대값 참고용)')

    elif stage_key == '2_decline':
        compare_metric(win_stage_data, loss_stage_data, 'candle_count', '캔들 수')
        compare_metric(win_stage_data, loss_stage_data, 'decline_pct', '하락률 (%)', multiplier=100)
        compare_metric(win_stage_data, loss_stage_data, 'avg_volume_ratio', '평균 거래량 비율')

    elif stage_key == '3_support':
        compare_metric(win_stage_data, loss_stage_data, 'candle_count', '캔들 수')
        compare_metric(win_stage_data, loss_stage_data, 'price_volatility', '가격 변동성 (%)', multiplier=100)
        compare_metric(win_stage_data, loss_stage_data, 'avg_volume_ratio', '평균 거래량 비율')

    elif stage_key == '4_breakout':
        compare_metric(win_stage_data, loss_stage_data, 'body_size', '몸통 크기')
        compare_metric(win_stage_data, loss_stage_data, 'volume', '거래량')
        compare_metric(win_stage_data, loss_stage_data, 'volume_ratio_vs_prev', '직전봉 대비 거래량 비율')
        compare_metric(win_stage_data, loss_stage_data, 'body_increase_vs_support', '지지구간 대비 몸통 증가율')


def compare_metric(win_data, loss_data, metric_key, metric_name, multiplier=1):
    """특정 지표 비교"""

    def parse_value(val):
        """문자열 값을 숫자로 변환"""
        if val is None:
            return None
        if isinstance(val, (int, float)):
            return float(val)
        if isinstance(val, str):
            # "17.17%" -> 17.17, "1,563,643" -> 1563643
            val = val.replace('%', '').replace(',', '').strip()
            try:
                return float(val)
            except ValueError:
                return None
        return None

    win_values = [parse_value(d.get(metric_key)) for d in win_data if parse_value(d.get(metric_key)) is not None]
    loss_values = [parse_value(d.get(metric_key)) for d in loss_data if parse_value(d.get(metric_key)) is not None]

    if not win_values and not loss_values:
        return

    win_avg = sum(win_values) / len(win_values) * multiplier if win_values else 0
    loss_avg = sum(loss_values) / len(loss_values) * multiplier if loss_values else 0

    # 차이 계산
    diff = win_avg - loss_avg
    diff_sign = "+" if diff >= 0 else ""

    print(f"  {metric_name}:")
    print(f"    승리 평균: {win_avg:.2f}")
    print(f"    패배 평균: {loss_avg:.2f}")
    print(f"    차이: {diff_sign}{diff:.2f}")


def export_detailed_patterns(patterns, output_file: str = "pattern_stages_detailed.csv"):
    """상세 패턴 데이터를 CSV로 내보내기"""

    records = []
    for pattern in patterns:
        trade_result = pattern.get('trade_result') or {}
        stages = pattern.get('pattern_stages', {})

        # 기본 정보
        record = {
            'pattern_id': pattern['pattern_id'],
            'timestamp': pattern['timestamp'],
            'stock_code': pattern['stock_code'],
            'signal_type': pattern['signal_info']['signal_type'],
            'confidence': pattern['signal_info']['confidence'],
            'trade_executed': trade_result.get('trade_executed', False) if trade_result else False,
            'profit_rate': trade_result.get('profit_rate') if trade_result else None,
            'sell_reason': trade_result.get('sell_reason') if trade_result else None,
        }

        # 1단계: 상승 구간
        uptrend = stages.get('1_uptrend', {})
        record.update({
            'uptrend_candle_count': uptrend.get('candle_count'),
            'uptrend_price_gain': uptrend.get('price_gain'),
            'uptrend_max_volume': uptrend.get('max_volume'),
            'uptrend_volume_avg': uptrend.get('volume_avg'),
        })

        # 2단계: 하락 구간
        decline = stages.get('2_decline', {})
        record.update({
            'decline_candle_count': decline.get('candle_count'),
            'decline_pct': decline.get('decline_pct'),
            'decline_avg_volume_ratio': decline.get('avg_volume_ratio'),
        })

        # 3단계: 지지 구간
        support = stages.get('3_support', {})
        record.update({
            'support_candle_count': support.get('candle_count'),
            'support_price_volatility': support.get('price_volatility'),
            'support_avg_volume_ratio': support.get('avg_volume_ratio'),
        })

        # 4단계: 돌파 양봉
        breakout = stages.get('4_breakout', {})
        record.update({
            'breakout_body_size': breakout.get('body_size'),
            'breakout_volume': breakout.get('volume'),
            'breakout_volume_ratio_vs_prev': breakout.get('volume_ratio_vs_prev'),
            'breakout_body_increase_vs_support': breakout.get('body_increase_vs_support'),
        })

        records.append(record)

    df = pd.DataFrame(records)
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n[완료] 상세 패턴 데이터 저장: {output_file}")

    return df


def main():
    """메인 실행"""

    # 날짜 인자 처리
    if len(sys.argv) > 1:
        date = sys.argv[1]
        print(f"[분석 날짜] {date}")
    else:
        date = None
        print(f"[분석 날짜] 오늘")

    # 패턴 데이터 로드
    patterns = load_pattern_data(date)

    if not patterns:
        print("[오류] 분석할 패턴 데이터가 없습니다.")
        return

    # 구간별 특성 분석
    analyze_stage_characteristics(patterns)

    # CSV 내보내기
    export_detailed_patterns(patterns)

    print("\n" + "="*80)
    print("[개선 힌트]")
    print("="*80)
    print("1. CSV 파일을 엑셀로 열어서 피벗 테이블로 더 상세하게 분석하세요")
    print("2. 승리 패턴의 공통 특성을 찾아서 필터에 반영하세요")
    print("3. 패배 패턴의 약점을 파악하여 차단 조건을 추가하세요")
    print("="*80)


if __name__ == "__main__":
    main()
