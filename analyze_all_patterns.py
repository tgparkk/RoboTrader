"""
전체 기간의 모든 패턴 데이터 통합 분석
pattern_data_log/ 디렉토리의 모든 JSONL 파일을 읽어서 종합 분석
"""

import json
import pandas as pd
from pathlib import Path
from datetime import datetime
import sys


def load_all_pattern_data(log_dir: str = "pattern_data_log"):
    """모든 날짜의 패턴 데이터 로드"""
    log_path = Path(log_dir)

    if not log_path.exists():
        print(f"[오류] 로그 디렉토리 없음: {log_path}")
        return []

    # 모든 JSONL 파일 찾기
    jsonl_files = list(log_path.glob("pattern_data_*.jsonl"))

    if not jsonl_files:
        print(f"[오류] JSONL 파일이 없습니다: {log_path}")
        return []

    print(f"\n{'='*80}")
    print(f"[전체 패턴 데이터 로드]")
    print(f"{'='*80}")
    print(f"발견된 파일 수: {len(jsonl_files)}개")

    all_patterns = []
    file_stats = []

    for jsonl_file in sorted(jsonl_files):
        try:
            patterns = []
            with open(jsonl_file, 'r', encoding='utf-8') as f:
                for line_num, line in enumerate(f, 1):
                    if line.strip():
                        try:
                            pattern = json.loads(line)
                            # None 값 필터링
                            if pattern is not None and isinstance(pattern, dict):
                                patterns.append(pattern)
                        except json.JSONDecodeError as e:
                            print(f"    [경고] {jsonl_file.name} 라인 {line_num}: JSON 파싱 실패 - {e}")
                            continue

            all_patterns.extend(patterns)

            # 파일별 통계 (None 값 안전하게 처리)
            traded = []
            for p in patterns:
                trade_result = p.get('trade_result')
                if trade_result and isinstance(trade_result, dict) and trade_result.get('trade_executed'):
                    traded.append(p)

            wins = []
            losses = []
            for p in traded:
                trade_result = p.get('trade_result')
                if trade_result and isinstance(trade_result, dict):
                    profit_rate = trade_result.get('profit_rate', 0)
                    if profit_rate > 0:
                        wins.append(p)
                    else:
                        losses.append(p)

            file_stats.append({
                'file': jsonl_file.name,
                'total': len(patterns),
                'traded': len(traded),
                'wins': len(wins),
                'losses': len(losses),
                'win_rate': (len(wins) / len(traded) * 100) if len(traded) > 0 else 0
            })

            print(f"  {jsonl_file.name}: {len(patterns)}개 패턴 (거래 {len(traded)}개, 승 {len(wins)}개, 패 {len(losses)}개)")

        except Exception as e:
            print(f"  [오류] {jsonl_file.name} 읽기 실패: {e}")

    print(f"\n총 {len(all_patterns)}개 패턴 로드 완료")

    return all_patterns, file_stats


def analyze_overall_performance(patterns):
    """전체 성과 분석"""

    # 거래 실행된 패턴만 필터링 (None 값 안전하게 처리)
    traded_patterns = [
        p for p in patterns
        if p is not None
        and isinstance(p, dict)
        and p.get('trade_result', {}) is not None
        and p.get('trade_result', {}).get('trade_executed')
    ]

    if not traded_patterns:
        print("\n[경고] 거래 실행된 패턴이 없습니다.")
        return

    # 승패 분류
    wins = [p for p in traded_patterns if p.get('trade_result', {}).get('profit_rate', 0) > 0]
    losses = [p for p in traded_patterns if p.get('trade_result', {}).get('profit_rate', 0) <= 0]

    # 수익률 계산
    total_profit = sum(p.get('trade_result', {}).get('profit_rate', 0) for p in traded_patterns)
    avg_profit = total_profit / len(traded_patterns) if traded_patterns else 0

    avg_win_profit = sum(p.get('trade_result', {}).get('profit_rate', 0) for p in wins) / len(wins) if wins else 0
    avg_loss_profit = sum(p.get('trade_result', {}).get('profit_rate', 0) for p in losses) / len(losses) if losses else 0

    print(f"\n{'='*80}")
    print(f"[전체 성과 분석]")
    print(f"{'='*80}")
    print(f"전체 패턴 수: {len(patterns):,}개")
    print(f"거래 실행: {len(traded_patterns):,}개")
    print(f"승리: {len(wins):,}개 | 패배: {len(losses):,}개")
    print(f"승률: {len(wins) / len(traded_patterns) * 100:.1f}%")
    print(f"\n[수익률]")
    print(f"평균 수익률: {avg_profit:.2f}%")
    print(f"평균 승리 수익률: {avg_win_profit:.2f}%")
    print(f"평균 패배 손실률: {avg_loss_profit:.2f}%")
    print(f"손익비 (평균승/평균패): {abs(avg_win_profit / avg_loss_profit) if avg_loss_profit != 0 else 0:.2f}")

    # 매도 사유별 통계
    sell_reasons = {}
    for p in traded_patterns:
        reason = p.get('trade_result', {}).get('sell_reason', 'unknown')
        if reason not in sell_reasons:
            sell_reasons[reason] = {'count': 0, 'profit': 0}
        sell_reasons[reason]['count'] += 1
        sell_reasons[reason]['profit'] += p.get('trade_result', {}).get('profit_rate', 0)

    print(f"\n[매도 사유별 통계]")
    for reason, stats in sorted(sell_reasons.items(), key=lambda x: x[1]['count'], reverse=True):
        avg_profit = stats['profit'] / stats['count']
        print(f"  {reason}: {stats['count']:,}건 (평균 {avg_profit:+.2f}%)")


def analyze_stage_characteristics_all(patterns):
    """4단계 구간 특성 종합 분석"""

    # 승패 분류 (None 값 안전하게 처리)
    wins = []
    losses = []

    for pattern in patterns:
        if pattern is None or not isinstance(pattern, dict):
            continue
        trade_result = pattern.get('trade_result')
        if trade_result and isinstance(trade_result, dict) and trade_result.get('trade_executed'):
            profit_rate = trade_result.get('profit_rate', 0)
            if profit_rate > 0:
                wins.append(pattern)
            else:
                losses.append(pattern)

    if not wins and not losses:
        print("\n[경고] 분석할 거래 데이터가 없습니다.")
        return

    print(f"\n{'='*80}")
    print(f"[4단계 패턴 구간 종합 분석]")
    print(f"{'='*80}")
    print(f"승리 거래: {len(wins):,}개")
    print(f"패배 거래: {len(losses):,}개")

    # 각 구간별 승패 비교
    for stage_name, stage_key in [
        ('1단계: 상승 구간', '1_uptrend'),
        ('2단계: 하락 구간', '2_decline'),
        ('3단계: 지지 구간', '3_support'),
        ('4단계: 돌파 양봉', '4_breakout')
    ]:
        print(f"\n{'='*80}")
        print(f"[{stage_name}]")
        print(f"{'='*80}")

        analyze_single_stage(wins, losses, stage_key)


def analyze_single_stage(wins, losses, stage_key):
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

    # 차이 비율 계산 (승리 패턴 대비 패배 패턴의 차이)
    diff_pct = (diff / win_avg * 100) if win_avg != 0 else 0

    print(f"  {metric_name}:")
    print(f"    승리 평균: {win_avg:.2f}")
    print(f"    패배 평균: {loss_avg:.2f}")
    print(f"    차이: {diff_sign}{diff:.2f} ({diff_sign}{diff_pct:.1f}%)")


def clean_numeric_value(value):
    """문자열 숫자를 파이썬 숫자로 변환 (%, 쉼표 제거)"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        # % 제거
        value = value.replace('%', '')
        # 쉼표 제거
        value = value.replace(',', '')
        try:
            return float(value)
        except:
            return None
    return None


def export_all_patterns_csv(patterns, output_file: str = "all_patterns_analysis.csv"):
    """전체 패턴 데이터를 CSV로 내보내기"""

    records = []
    for pattern in patterns:
        # None 값 스킵
        if pattern is None or not isinstance(pattern, dict):
            continue
        trade_result = pattern.get('trade_result') or {}
        stages = pattern.get('pattern_stages', {})

        # 기본 정보
        record = {
            'pattern_id': pattern['pattern_id'],
            'timestamp': pattern['timestamp'],
            'date': pattern['timestamp'][:10] if 'timestamp' in pattern else '',
            'stock_code': pattern['stock_code'],
            'signal_type': pattern['signal_info']['signal_type'],
            'confidence': pattern['signal_info']['confidence'],
            'trade_executed': trade_result.get('trade_executed', False),
            'profit_rate': trade_result.get('profit_rate'),
            'sell_reason': trade_result.get('sell_reason'),
        }

        # 1단계: 상승 구간
        uptrend = stages.get('1_uptrend', {})
        record.update({
            'uptrend_candle_count': clean_numeric_value(uptrend.get('candle_count')),
            'uptrend_price_gain': clean_numeric_value(uptrend.get('price_gain')),
            'uptrend_max_volume': clean_numeric_value(uptrend.get('max_volume')),
            'uptrend_max_volume_ratio': clean_numeric_value(uptrend.get('max_volume_ratio_vs_avg')),
        })

        # 2단계: 하락 구간
        decline = stages.get('2_decline', {})
        record.update({
            'decline_candle_count': clean_numeric_value(decline.get('candle_count')),
            'decline_pct': clean_numeric_value(decline.get('decline_pct')),
            'decline_avg_volume_ratio': clean_numeric_value(decline.get('avg_volume_ratio')),
        })

        # 3단계: 지지 구간
        support = stages.get('3_support', {})
        record.update({
            'support_candle_count': clean_numeric_value(support.get('candle_count')),
            'support_price_volatility': clean_numeric_value(support.get('price_volatility')),
            'support_avg_volume_ratio': clean_numeric_value(support.get('avg_volume_ratio')),
        })

        # 4단계: 돌파 양봉
        breakout = stages.get('4_breakout', {})
        record.update({
            'breakout_body_size': clean_numeric_value(breakout.get('body_size')),
            'breakout_volume': clean_numeric_value(breakout.get('volume')),
            'breakout_volume_ratio_vs_prev': clean_numeric_value(breakout.get('volume_ratio_vs_prev')),
            'breakout_body_increase_vs_support': clean_numeric_value(breakout.get('body_increase_vs_support')),
        })

        records.append(record)

    df = pd.DataFrame(records)
    df.to_csv(output_file, index=False, encoding='utf-8-sig')
    print(f"\n[완료] 전체 패턴 데이터 저장: {output_file}")
    print(f"총 {len(df):,}개 레코드")

    return df


def generate_improvement_recommendations(patterns):
    """개선 권장사항 생성"""

    # 승패 분류 (None 값 안전하게 처리)
    wins = []
    losses = []

    for pattern in patterns:
        if pattern is None or not isinstance(pattern, dict):
            continue
        trade_result = pattern.get('trade_result')
        if trade_result and isinstance(trade_result, dict) and trade_result.get('trade_executed'):
            profit_rate = trade_result.get('profit_rate', 0)
            if profit_rate > 0:
                wins.append(pattern)
            else:
                losses.append(pattern)

    if not wins or not losses:
        return

    print(f"\n{'='*80}")
    print(f"[개선 권장사항]")
    print(f"{'='*80}")

    # 1단계: 상승구간 거래량 분석
    win_uptrend_volumes = []
    loss_uptrend_volumes = []

    for p in wins:
        vol_ratio = p.get('pattern_stages', {}).get('1_uptrend', {}).get('max_volume_ratio_vs_avg')
        if vol_ratio:
            win_uptrend_volumes.append(vol_ratio)

    for p in losses:
        vol_ratio = p.get('pattern_stages', {}).get('1_uptrend', {}).get('max_volume_ratio_vs_avg')
        if vol_ratio:
            loss_uptrend_volumes.append(vol_ratio)

    if win_uptrend_volumes and loss_uptrend_volumes:
        win_avg_vol = sum(win_uptrend_volumes) / len(win_uptrend_volumes)
        loss_avg_vol = sum(loss_uptrend_volumes) / len(loss_uptrend_volumes)

        print(f"\n1. 상승구간 최대 거래량 비율 필터")
        print(f"   - 승리 평균: {win_avg_vol:.2f}배")
        print(f"   - 패배 평균: {loss_avg_vol:.2f}배")

        if loss_avg_vol > win_avg_vol * 1.5:
            threshold = (win_avg_vol + loss_avg_vol) / 2
            print(f"   ✓ 권장: {threshold:.1f}배 이상인 경우 제외 또는 신뢰도 하향")

    # 2단계: 하락률 분석
    win_declines = []
    loss_declines = []

    for p in wins:
        decline = p.get('pattern_stages', {}).get('2_decline', {}).get('decline_pct')
        if decline:
            # 문자열일 수 있으므로 파싱
            if isinstance(decline, str):
                decline = float(decline.replace('%', '').strip())
            win_declines.append(decline)

    for p in losses:
        decline = p.get('pattern_stages', {}).get('2_decline', {}).get('decline_pct')
        if decline:
            if isinstance(decline, str):
                decline = float(decline.replace('%', '').strip())
            loss_declines.append(decline)

    if win_declines and loss_declines:
        win_avg_decline = sum(win_declines) / len(win_declines)
        loss_avg_decline = sum(loss_declines) / len(loss_declines)

        print(f"\n2. 하락률 필터")
        print(f"   - 승리 평균: {win_avg_decline:.2f}%")
        print(f"   - 패배 평균: {loss_avg_decline:.2f}%")

        if loss_avg_decline > win_avg_decline * 1.3:
            threshold = (win_avg_decline + loss_avg_decline) / 2
            print(f"   ✓ 권장: {threshold:.1f}% 이상 하락한 경우 신뢰도 하향")

    # 3단계: 지지구간 변동성 분석
    win_volatilities = []
    loss_volatilities = []

    for p in wins:
        volatility = p.get('pattern_stages', {}).get('3_support', {}).get('price_volatility')
        if volatility:
            if isinstance(volatility, str):
                volatility = float(volatility.replace('%', '').strip())
            win_volatilities.append(volatility)

    for p in losses:
        volatility = p.get('pattern_stages', {}).get('3_support', {}).get('price_volatility')
        if volatility:
            if isinstance(volatility, str):
                volatility = float(volatility.replace('%', '').strip())
            loss_volatilities.append(volatility)

    if win_volatilities and loss_volatilities:
        win_avg_vol = sum(win_volatilities) / len(win_volatilities)
        loss_avg_vol = sum(loss_volatilities) / len(loss_volatilities)

        print(f"\n3. 지지구간 변동성 필터")
        print(f"   - 승리 평균: {win_avg_vol:.2f}%")
        print(f"   - 패배 평균: {loss_avg_vol:.2f}%")

        if loss_avg_vol > win_avg_vol * 2:
            threshold = (win_avg_vol + loss_avg_vol) / 2
            print(f"   ✓ 권장: {threshold:.2f}% 이상 변동성인 경우 제외")

    print(f"\n{'='*80}")
    print(f"[추가 분석 팁]")
    print(f"{'='*80}")
    print(f"1. all_patterns_analysis.csv 파일을 엑셀로 열어보세요")
    print(f"2. 피벗 테이블로 날짜별, 종목별 승률 분석을 해보세요")
    print(f"3. 신뢰도 구간별(80-85, 85-90, 90-95, 95-100) 승률을 비교해보세요")
    print(f"4. 매도사유별로 수익률 분포를 확인해보세요")
    print(f"{'='*80}")


def main():
    """메인 실행"""

    print(f"\n{'='*80}")
    print(f"전체 기간 패턴 데이터 종합 분석")
    print(f"{'='*80}")

    # 모든 패턴 데이터 로드
    result = load_all_pattern_data()
    if not result:
        return

    all_patterns, file_stats = result

    if not all_patterns:
        print("[오류] 분석할 패턴 데이터가 없습니다.")
        return

    # 전체 성과 분석
    analyze_overall_performance(all_patterns)

    # 4단계 구간 특성 분석
    analyze_stage_characteristics_all(all_patterns)

    # CSV 내보내기
    export_all_patterns_csv(all_patterns)

    # 개선 권장사항 생성
    generate_improvement_recommendations(all_patterns)


if __name__ == "__main__":
    main()
