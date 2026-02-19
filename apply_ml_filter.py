#!/usr/bin/env python3
"""
🤖 백테스트 결과에 ML 필터 적용

signal_replay 결과 파일을 읽어서 ML 모델로 승률을 예측하고,
임계값 이하의 신호를 필터링합니다.
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pickle
import re
import json
import psycopg2
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pandas as pd


def load_stock_names() -> Dict[str, str]:
    """DB에서 종목 코드-종목명 매핑 로드"""
    try:
        conn = psycopg2.connect(host='172.23.208.1', port=5433, dbname='robotrader', user='postgres')
        cursor = conn.cursor()

        cursor.execute("SELECT DISTINCT stock_code, stock_name FROM candidate_stocks WHERE stock_name IS NOT NULL")
        stock_map = {code: name for code, name in cursor.fetchall()}

        conn.close()
        print(f"✅ 종목명 로드 완료: {len(stock_map)}개")
        return stock_map
    except Exception as e:
        print(f"⚠️  종목명 로드 실패: {e}")
        return {}


def load_ml_model(model_path: str = "ml_model.pkl"):
    """ML 모델 로드"""
    try:
        with open(model_path, 'rb') as f:
            model_data = pickle.load(f)

        model = model_data['model']
        feature_names = model_data['feature_names']

        print(f"✅ ML 모델 로드 완료 ({len(feature_names)}개 특성)")
        return model, feature_names

    except Exception as e:
        print(f"❌ ML 모델 로드 실패: {e}")
        return None, None


def parse_signal_from_log_line(line: str) -> Dict:
    """
    로그 라인에서 신호 정보 파싱

    예시 라인:
    "   🟢 174900 09:21 매수 → +3.50%"
    "   🟢 174900(종목명) 09:21 매수 → +3.50%"
    """
    # 신호 패턴 매칭 (종목명 있을 수도, 없을 수도)
    pattern = r'[🔴🟢]\s+(\d{6})(?:\([^)]+\))?\s+(\d{2}):(\d{2})\s+매수\s+→\s+([-+]\d+\.\d+)%'
    match = re.search(pattern, line)

    if not match:
        return None

    stock_code = match.group(1)
    hour = int(match.group(2))
    minute = int(match.group(3))
    profit_rate = float(match.group(4))

    return {
        'stock_code': stock_code,
        'hour': hour,
        'minute': minute,
        'time': f"{hour:02d}:{minute:02d}",
        'profit_rate': profit_rate,
        'is_win': profit_rate > 0
    }


def load_pattern_data_for_date(date_str: str, use_dynamic: bool = False) -> Dict[str, Dict]:
    """
    특정 날짜의 패턴 데이터 로드

    Args:
        date_str: 날짜 (YYYYMMDD)
        use_dynamic: 동적 손익비 모델 사용 여부

    Returns:
        Dict[pattern_id, pattern_data]
    """
    # ⭐ 동적 손익비 모델 사용 시 별도 폴더에서 로드
    log_dir = 'pattern_data_log_dynamic' if use_dynamic else 'pattern_data_log'
    pattern_log_file = Path(log_dir) / f'pattern_data_{date_str}.jsonl'

    if not pattern_log_file.exists():
        print(f"   ⚠️  패턴 로그 없음: {pattern_log_file}")
        return {}

    patterns = {}
    try:
        with open(pattern_log_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    try:
                        record = json.loads(line)
                        pattern_id = record.get('pattern_id', '')
                        if pattern_id:
                            patterns[pattern_id] = record
                    except:
                        pass

        print(f"   📊 패턴 데이터 로드: {len(patterns)}개")
        return patterns

    except Exception as e:
        print(f"   ⚠️  패턴 데이터 로드 실패: {e}")
        return {}


def find_matching_pattern(patterns: Dict[str, Dict], signal: Dict) -> Optional[Dict]:
    """
    신호와 매칭되는 패턴 찾기 (±5분 범위에서 가장 가까운 시간 선택)

    시뮬레이션 로그의 매수 시간 ±5분 범위 내에서 패턴을 찾고,
    그 중 시간 차이가 가장 작은 패턴을 선택합니다.
    """
    stock_code = signal['stock_code']
    hour = signal['hour']
    minute = signal['minute']

    # 대상 시간 (분 단위로 변환)
    target_minutes = hour * 60 + minute

    matched_patterns = []

    for pattern_id, pattern_data in patterns.items():
        parts = pattern_id.split('_')
        if len(parts) >= 3:
            p_code = parts[0]

            if p_code == stock_code:
                # signal_time으로 매칭
                signal_time_str = pattern_data.get('signal_time', '')
                if signal_time_str:
                    try:
                        # "2025-12-08 10:12:00" -> datetime
                        st = datetime.strptime(signal_time_str, '%Y-%m-%d %H:%M:%S')
                        pattern_minutes = st.hour * 60 + st.minute

                        # 시간 차이 계산 (절대값)
                        time_diff = abs(pattern_minutes - target_minutes)

                        # ±5분 범위 내에 있으면 후보에 추가
                        if time_diff <= 5:
                            log_timestamp = pattern_data.get('log_timestamp', signal_time_str)
                            matched_patterns.append({
                                'pattern_data': pattern_data,
                                'log_timestamp': log_timestamp,
                                'pattern_id': pattern_id,
                                'time_diff': time_diff
                            })
                    except:
                        pass

    if not matched_patterns:
        return None

    # 1순위: 시간 차이가 가장 작은 것 (오름차순)
    # 2순위: 동일 시간 차이면 가장 최근 로그 (내림차순)
    # 타임스탬프를 datetime으로 변환하여 정확한 시간 비교
    def sort_key(x):
        time_diff = x['time_diff']
        try:
            # log_timestamp를 datetime으로 변환하여 비교
            log_dt = datetime.strptime(x['log_timestamp'], '%Y-%m-%d %H:%M:%S')
            # 내림차순 정렬을 위해 음수 타임스탬프 사용
            return (time_diff, -log_dt.timestamp())
        except:
            # 파싱 실패 시 문자열 비교로 대체 (내림차순)
            return (time_diff, -ord(x['log_timestamp'][0]) if x['log_timestamp'] else 0)
    
    matched_patterns.sort(key=sort_key)

    return matched_patterns[0]['pattern_data']


def safe_float(value, default=0.0):
    """안전하게 float로 변환"""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        # "3.52%" -> 3.52
        # "162,154" -> 162154
        value = value.replace(',', '').replace('%', '').strip()
        try:
            return float(value)
        except:
            return default
    return default


def calculate_avg_volume_from_candles(candles: list) -> float:
    """캔들 리스트에서 평균 거래량 계산"""
    if not candles:
        return 0.0
    volumes = [c.get('volume', 0) for c in candles]
    return sum(volumes) / len(volumes) if volumes else 0.0


def calculate_avg_body_pct(candles: list) -> float:
    """캔들 리스트에서 평균 몸통 비율 계산"""
    if not candles:
        return 0.0
    body_pcts = []
    for c in candles:
        open_p = c.get('open', 0)
        close_p = c.get('close', 0)
        if open_p > 0:
            body_pct = abs((close_p - open_p) / open_p * 100)
            body_pcts.append(body_pct)
    return sum(body_pcts) / len(body_pcts) if body_pcts else 0.0


def extract_features_from_pattern(pattern_data: Dict) -> Dict:
    """
    패턴 데이터에서 ML 특성 추출 (12개 핵심 특징)
    
    현재 모델 특징:
    1. decline_pct
    2. volume_ratio_breakout_to_uptrend
    3. breakout_body_ratio
    4. uptrend_gain
    5. uptrend_max_volume
    6. decline_candles
    7. support_candles
    8. support_volatility
    9. decline_depth
    10. uptrend_gain_per_candle
    11. volume_concentration
    12. uptrend_volume_std
    """
    import numpy as np
    
    # 패턴 구간 정보
    pattern_stages = pattern_data.get('pattern_stages', {})

    # ===== 상승 구간 =====
    uptrend = pattern_stages.get('1_uptrend', {})
    uptrend_candles = uptrend.get('candle_count', 0)
    uptrend_gain = safe_float(uptrend.get('price_gain', 0.0))
    uptrend_max_volume_str = uptrend.get('max_volume', '0')
    uptrend_max_volume = safe_float(uptrend_max_volume_str)
    uptrend_candles_list = uptrend.get('candles', [])

    # uptrend_volume_std 계산
    uptrend_volume_std = 0
    if uptrend_candles_list and len(uptrend_candles_list) > 1:
        volumes = [c.get('volume', 0) for c in uptrend_candles_list]
        uptrend_volume_std = float(np.std(volumes))

    # volume_concentration 계산
    volume_concentration = 0
    if uptrend_candles_list and uptrend_max_volume > 0:
        uptrend_volume_avg = sum(c.get('volume', 0) for c in uptrend_candles_list) / len(uptrend_candles_list)
        if uptrend_volume_avg > 0:
            volume_concentration = uptrend_max_volume / uptrend_volume_avg

    # uptrend_gain_per_candle 계산
    uptrend_gain_per_candle = uptrend_gain / uptrend_candles if uptrend_candles > 0 else 0

    # ===== 하락 구간 =====
    decline = pattern_stages.get('2_decline', {})
    decline_candles = decline.get('candle_count', 0)
    decline_pct = abs(safe_float(decline.get('decline_pct', 0.0)))
    decline_candles_list = decline.get('candles', [])

    # decline_depth 계산
    decline_depth = 0
    if uptrend_candles_list and decline_candles_list:
        uptrend_max_price = max(c.get('high', 0) for c in uptrend_candles_list)
        decline_min_price = min(c.get('low', float('inf')) for c in decline_candles_list)
        if uptrend_max_price > 0 and decline_min_price < float('inf'):
            decline_depth = (uptrend_max_price - decline_min_price) / uptrend_max_price

    # ===== 지지 구간 =====
    support = pattern_stages.get('3_support', {})
    support_candles = support.get('candle_count', 0)
    support_volatility = safe_float(support.get('price_volatility', 0.0))

    # ===== 돌파 구간 =====
    breakout = pattern_stages.get('4_breakout', {})
    if breakout and breakout.get('candle'):
        breakout_candle = breakout.get('candle', {})
        breakout_volume = breakout_candle.get('volume', 0)

        # 몸통 크기 계산
        open_p = breakout_candle.get('open', 0)
        close_p = breakout_candle.get('close', 0)
        if open_p > 0:
            breakout_body = abs((close_p - open_p) / open_p * 100)
        else:
            breakout_body = 0.0

        # 범위 크기 계산
        high_p = breakout_candle.get('high', 0)
        low_p = breakout_candle.get('low', 0)
        if low_p > 0:
            breakout_range = (high_p - low_p) / low_p * 100
        else:
            breakout_range = 0.0
    else:
        breakout_volume, breakout_body, breakout_range = 0, 0.0, 0.0

    # breakout_body_ratio 계산
    breakout_body_ratio = breakout_body / breakout_range if breakout_range > 0 else 0

    # volume_ratio_breakout_to_uptrend 계산
    volume_ratio_breakout_to_uptrend = (
        breakout_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
    )

    # ===== 12개 특징 구성 =====
    features = {
        'decline_pct': decline_pct,
        'volume_ratio_breakout_to_uptrend': volume_ratio_breakout_to_uptrend,
        'breakout_body_ratio': breakout_body_ratio,
        'uptrend_gain': uptrend_gain,
        'uptrend_max_volume': uptrend_max_volume,
        'decline_candles': decline_candles,
        'support_candles': support_candles,
        'support_volatility': support_volatility,
        'decline_depth': decline_depth,
        'uptrend_gain_per_candle': uptrend_gain_per_candle,
        'volume_concentration': volume_concentration,
        'uptrend_volume_std': uptrend_volume_std,
    }

    return features


def predict_win_probability(
    model,
    feature_names,
    signal: Dict,
    pattern_data: Optional[Dict] = None
) -> Tuple[float, str]:
    """
    신호의 승률 예측

    Returns:
        (승률, 상태 메시지)
    """
    try:
        if pattern_data is None:
            return 0.5, "패턴없음"

        # 패턴 데이터에서 특성 추출
        features = extract_features_from_pattern(pattern_data)

        # DataFrame으로 변환
        feature_values = [features.get(fname, 0) for fname in feature_names]
        X = pd.DataFrame([feature_values], columns=feature_names)

        # 예측 - 실시간 거래와 동일한 방식 (LightGBM predict with best_iteration)
        try:
            # LightGBM Booster 객체인 경우 (ml_model.pkl)
            win_prob = model.predict(
                X.values,
                num_iteration=model.best_iteration
            )[0]
        except (AttributeError, TypeError):
            # sklearn wrapper인 경우 (하위 호환성)
            try:
                win_prob = model.predict_proba(X)[0][1]
            except:
                win_prob = model.predict(X.values)[0]

        return win_prob, "정상"

    except Exception as e:
        import traceback
        traceback.print_exc()
        return 0.5, f"오류:{str(e)[:20]}"


def recalculate_statistics(lines: List[str]) -> Dict:
    """
    필터링된 라인에서 통계 재계산 (주석 처리된 라인 제외)

    Returns:
        통계 딕셔너리 {total_trades, wins, losses, total_profit, win_profit, loss_amount}
    """
    wins = 0
    losses = 0
    total_profit = 0.0
    win_profit = 0.0
    loss_amount = 0.0

    # 거래 목록 섹션 찾기 (12시 이전 매수 종목 섹션)
    in_trade_list = False

    for line in lines:
        # 거래 목록 섹션 시작
        if '12시 이전 매수 종목' in line or '🌅' in line:
            in_trade_list = True
            continue

        # 거래 목록 섹션 종료 (상세 섹션 시작)
        if in_trade_list and line.strip().startswith('===') and ' - ' in line:
            break

        if not in_trade_list:
            continue

        # 주석 처리된 라인은 제외
        if line.strip().startswith('#'):
            continue

        # 승리/패배 파싱
        win_match = re.search(r'매수\s+→\s+\+([0-9.]+)%', line)
        loss_match = re.search(r'매수\s+→\s+-([0-9.]+)%', line)

        if win_match:
            wins += 1
            profit_pct = float(win_match.group(1))
            profit_amount = 1000000 * profit_pct / 100
            win_profit += profit_amount
            total_profit += profit_amount
        elif loss_match:
            losses += 1
            loss_pct = float(loss_match.group(1))
            loss_amt = 1000000 * loss_pct / 100
            loss_amount += loss_amt
            total_profit -= loss_amt

    return {
        'total_trades': wins + losses,
        'wins': wins,
        'losses': losses,
        'total_profit': total_profit,
        'win_profit': win_profit,
        'loss_amount': loss_amount
    }


def update_statistics_section(lines: List[str], stats: Dict) -> List[str]:
    """
    파일 상단의 통계 섹션을 업데이트

    Args:
        lines: 원본 라인 리스트
        stats: 재계산된 통계

    Returns:
        업데이트된 라인 리스트
    """
    updated_lines = []
    in_morning_section = False  # 12시 이전 섹션 추적

    for i, line in enumerate(lines):
        # 12시 이전 매수 종목 섹션 시작
        if '12시 이전 매수 종목:' in line:
            in_morning_section = True
            win_rate = (stats['wins'] / stats['total_trades'] * 100) if stats['total_trades'] > 0 else 0
            updated_lines.append(
                f"=== 🌅 12시 이전 매수 종목: {stats['wins']}승 {stats['losses']}패 (승률 {win_rate:.1f}%) ===\n"
            )
        # 12시 이전 섹션 종료 (거래 라인 시작)
        elif in_morning_section and (line.strip().startswith('🔴') or line.strip().startswith('🟢') or line.strip().startswith('#')):
            in_morning_section = False
            updated_lines.append(line)
        # 총 거래 라인 업데이트
        elif line.startswith('총 거래:'):
            updated_lines.append(
                f"총 거래: {stats['total_trades']}건 ({stats['wins']}승 {stats['losses']}패)\n"
            )
        # 총 수익금 라인 업데이트 (상단 및 12시 이전 섹션)
        elif line.startswith('총 수익금:'):
            profit_rate = (stats['total_profit'] / (stats['total_trades'] * 1000000) * 100) if stats['total_trades'] > 0 else 0
            updated_lines.append(
                f"총 수익금: {stats['total_profit']:+,.0f}원 ({profit_rate:+.1f}%)\n"
            )
        # 승리 수익 라인 업데이트
        elif '승리 수익:' in line:
            updated_lines.append(
                f"  ㄴ 승리 수익: {stats['win_profit']:+,.0f}원 (실제 수익률 합계)\n"
            )
        # 손실 금액 라인 업데이트
        elif '손실 금액:' in line:
            updated_lines.append(
                f"  ㄴ 손실 금액: {-stats['loss_amount']:+,.0f}원 (실제 손실률 합계)\n"
            )
        # 총 승패 라인 업데이트
        elif line.startswith('=== 총 승패:'):
            updated_lines.append(
                f"=== 총 승패: {stats['wins']}승 {stats['losses']}패 ===\n"
            )
        # selection_date 이후 승패 라인 업데이트
        elif line.startswith('=== selection_date 이후 승패:'):
            updated_lines.append(
                f"=== selection_date 이후 승패: {stats['wins']}승 {stats['losses']}패 ===\n"
            )
        else:
            updated_lines.append(line)

    return updated_lines


def apply_ml_filter_to_file(
    input_file: str,
    output_file: str,
    model,
    feature_names,
    threshold: float = 0.5,
    use_dynamic: bool = False
) -> Tuple[int, int]:
    """
    백테스트 결과 파일에 ML 필터 적용

    Returns:
        (총 신호 수, 필터링된 신호 수)
    """
    print(f"\n📄 처리 중: {input_file}")

    # 종목명 매핑 로드
    stock_names = load_stock_names()

    # 날짜 추출 (파일명에서)
    # 예: signal_replay_log_ml/signal_replay_20251103_9_00_0_temp.txt
    input_path = Path(input_file)
    filename = input_path.stem  # signal_replay_20251103_9_00_0_temp

    # 날짜 추출 (YYYYMMDD 형식)
    date_match = re.search(r'(\d{8})', filename)
    if date_match:
        date_str = date_match.group(1)
        patterns = load_pattern_data_for_date(date_str, use_dynamic=use_dynamic)
    else:
        print("   ⚠️  날짜를 추출할 수 없습니다. 패턴 데이터 없이 진행합니다.")
        patterns = {}

    with open(input_file, 'r', encoding='utf-8-sig') as f:
        lines = f.readlines()

    output_lines = []
    total_signals = 0
    filtered_signals = 0
    no_pattern_count = 0

    for line in lines:
        # 신호 라인인지 확인
        signal = parse_signal_from_log_line(line)

        if signal:
            total_signals += 1
            stock_code = signal['stock_code']
            stock_name = stock_names.get(stock_code, '???')

            # 패턴 데이터 찾기
            pattern_data = find_matching_pattern(patterns, signal) if patterns else None

            # ML 예측
            win_prob, status = predict_win_probability(model, feature_names, signal, pattern_data)

            if status == "패턴없음":
                no_pattern_count += 1

            # 기존 라인에서 종목 코드 부분을 "코드(종목명)" 형식으로 교체
            # 예: "   🟢 174900 09:21 매수 → +3.50%" -> "   🟢 174900(코스맥스) 09:21 매수 → +3.50%"
            # 정규식 그룹 참조 문제를 피하기 위해 replace 사용
            pattern = re.search(r'([🔴🟢]\s+)' + stock_code + r'(\s+)', line)
            if pattern:
                modified_line = line[:pattern.start()] + pattern.group(1) + f"{stock_code}({stock_name})" + pattern.group(2) + line[pattern.end():].rstrip()
            else:
                modified_line = line.rstrip()

            # 임계값 이상만 통과
            if win_prob >= threshold:
                # 예측 승률 추가
                modified_line += f" [ML: {win_prob:.1%}]"
                if status != "정상":
                    modified_line += f" ({status})"
                modified_line += "\n"
                output_lines.append(modified_line)
            else:
                filtered_signals += 1
                # 필터링된 신호는 주석 처리
                comment = f"# [ML 필터링: {win_prob:.1%}"
                if status != "정상":
                    comment += f" ({status})"
                comment += f"]    {modified_line}\n"
                output_lines.append(comment)
        else:
            # 신호가 아닌 라인은 그대로 유지
            output_lines.append(line)

    # 통계 재계산
    print(f"\n   📊 통계 재계산 중...")
    recalc_stats = recalculate_statistics(output_lines)

    # 통계 섹션 업데이트
    output_lines = update_statistics_section(output_lines, recalc_stats)

    # 필터링된 결과 저장
    with open(output_file, 'w', encoding='utf-8-sig') as f:
        f.writelines(output_lines)

    print(f"\n   필터링 전 신호: {total_signals}개")
    print(f"   필터링 후 신호: {total_signals - filtered_signals}개")
    print(f"   차단: {filtered_signals}개 ({filtered_signals/total_signals*100 if total_signals > 0 else 0:.1f}%)")
    if no_pattern_count > 0:
        print(f"   패턴없음: {no_pattern_count}개 ({no_pattern_count/total_signals*100 if total_signals > 0 else 0:.1f}%)")

    print(f"\n   📈 필터링 후 통계:")
    print(f"   총 거래: {recalc_stats['total_trades']}건 ({recalc_stats['wins']}승 {recalc_stats['losses']}패)")
    win_rate = (recalc_stats['wins'] / recalc_stats['total_trades'] * 100) if recalc_stats['total_trades'] > 0 else 0
    print(f"   승률: {win_rate:.1f}%")
    print(f"   총 수익: {recalc_stats['total_profit']:+,.0f}원")

    return total_signals, filtered_signals


def main():
    import argparse
    from config.ml_settings import MLSettings

    parser = argparse.ArgumentParser(description="백테스트 결과에 ML 필터 적용")
    parser.add_argument('input_file', help="입력 파일 (signal_replay 결과)")
    parser.add_argument('--output', '-o', help="출력 파일 (기본: 입력파일에 _ml_filtered 추가)")
    parser.add_argument('--threshold', '-t', type=float, default=None, help=f"승률 임계값 (기본: config/ml_settings.py의 ML_THRESHOLD = {MLSettings.ML_THRESHOLD})")
    parser.add_argument('--model', '-m', default="ml_model.pkl", help="ML 모델 파일")

    args = parser.parse_args()

    # threshold가 지정되지 않으면 설정 파일에서 가져오기
    if args.threshold is None:
        args.threshold = MLSettings.ML_THRESHOLD

    # 출력 파일명 결정
    if args.output:
        output_file = args.output
    else:
        input_path = Path(args.input_file)
        output_file = str(input_path.parent / f"{input_path.stem}_ml_filtered{input_path.suffix}")

    print("=" * 70)
    print("🤖 ML 필터 적용")
    print("=" * 70)
    print(f"입력: {args.input_file}")
    print(f"출력: {output_file}")
    print(f"임계값: {args.threshold:.1%}")
    print(f"모델: {args.model}")

    # ML 모델 로드
    model, feature_names = load_ml_model(args.model)

    if model is None:
        print("\n❌ ML 모델을 로드할 수 없습니다.")
        return

    # 동적 손익비 모델 여부 감지 (파일명으로 판단)
    use_dynamic = 'dynamic' in args.model.lower()
    if use_dynamic:
        print(f"   📊 동적 손익비 모델 감지 → pattern_data_log_dynamic 폴더 사용")

    # 필터링 적용
    total, filtered = apply_ml_filter_to_file(
        args.input_file,
        output_file,
        model,
        feature_names,
        args.threshold,
        use_dynamic=use_dynamic
    )

    print("\n" + "=" * 70)
    print(f"✅ 완료: {output_file}")
    print("=" * 70)


if __name__ == "__main__":
    main()