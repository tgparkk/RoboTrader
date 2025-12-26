#!/usr/bin/env python3
"""
동적 손익비 ML 모델로 백테스트 결과 필터링

기존 apply_ml_filter.py와 동일하지만 ml_model_dynamic_pl.pkl 사용
"""

import sys
sys.stdout.reconfigure(encoding='utf-8')

import pickle
import re
import json
import sqlite3
import argparse
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from datetime import datetime
import pandas as pd


# 새 ML 모델 사용
ML_MODEL_PATH = "ml_model_dynamic_pl.pkl"
DEFAULT_THRESHOLD = 0.5


def load_stock_names() -> Dict[str, str]:
    """DB에서 종목 코드-종목명 매핑 로드"""
    try:
        conn = sqlite3.connect('data/robotrader.db')
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT stock_code, stock_name FROM candidate_stocks WHERE stock_name IS NOT NULL")
        stock_map = {code: name for code, name in cursor.fetchall()}
        conn.close()
        return stock_map
    except Exception as e:
        print(f"[경고] 종목명 로드 실패: {e}")
        return {}


def load_ml_model(model_path: str = ML_MODEL_PATH):
    """ML 모델 로드"""
    try:
        with open(model_path, 'rb') as f:
            model_data = pickle.load(f)

        model = model_data['model']
        feature_names = model_data['feature_names']

        print(f"[ML 모델] {model_path} 로드 완료 ({len(feature_names)}개 특성)")
        return model, feature_names

    except Exception as e:
        print(f"[오류] ML 모델 로드 실패: {e}")
        return None, None


def parse_signal_from_log_line(line: str) -> Dict:
    """로그 라인에서 신호 정보 파싱"""
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


def load_pattern_data_for_date(date_str: str) -> Dict[str, Dict]:
    """특정 날짜의 패턴 데이터 로드"""
    pattern_log_file = Path('pattern_data_log') / f'pattern_data_{date_str}.jsonl'

    if not pattern_log_file.exists():
        print(f"   [경고] 패턴 로그 없음: {pattern_log_file}")
        return {}

    patterns = {}
    try:
        encodings = ['utf-8', 'cp949', 'utf-8-sig']
        for encoding in encodings:
            try:
                with open(pattern_log_file, 'r', encoding=encoding) as f:
                    for line in f:
                        if line.strip():
                            try:
                                pattern = json.loads(line)
                                pattern_id = pattern.get('pattern_id', '')
                                if pattern_id:
                                    patterns[pattern_id] = pattern
                            except json.JSONDecodeError:
                                continue
                break
            except UnicodeDecodeError:
                continue
    except Exception as e:
        print(f"   [경고] 패턴 로그 읽기 실패: {e}")

    return patterns


def extract_features_from_pattern(pattern: Dict, feature_names: List[str]) -> Optional[pd.Series]:
    """패턴 데이터에서 ML 피처 추출"""
    try:
        pattern_stages = pattern.get('pattern_stages', {})
        signal_info = pattern.get('signal_info', {})

        def safe_float(value, default=0.0):
            if value is None:
                return default
            if isinstance(value, (int, float)):
                return float(value)
            if isinstance(value, str):
                return float(value.replace('%', '').replace(',', ''))
            return default

        # 1단계: 상승구간
        uptrend = pattern_stages.get('1_uptrend', {})
        uptrend_candles = uptrend.get('candle_count', 0)
        uptrend_gain = safe_float(uptrend.get('price_gain', 0))
        uptrend_max_volume = safe_float(uptrend.get('max_volume', 0))
        uptrend_avg_volume = safe_float(uptrend.get('volume_avg', 0))

        # 2단계: 하락구간
        decline = pattern_stages.get('2_decline', {})
        decline_candles = decline.get('candle_count', 0)
        decline_pct = safe_float(decline.get('decline_pct', 0))
        decline_avg_volume = safe_float(decline.get('avg_volume', 0))

        # 3단계: 지지구간
        support = pattern_stages.get('3_support', {})
        support_candles = support.get('candle_count', 0)
        support_avg_volume = safe_float(support.get('avg_volume', 0))
        support_volatility = safe_float(support.get('price_volatility', 0))

        # 4단계: 돌파양봉
        breakout = pattern_stages.get('4_breakout', {})
        breakout_candle = breakout.get('candle', {})
        breakout_volume = safe_float(breakout_candle.get('volume', 0))
        breakout_close = safe_float(breakout_candle.get('close', 0))

        # 거래량 비율 계산
        support_volume_ratio = support_avg_volume / uptrend_max_volume if uptrend_max_volume > 0 else 0
        decline_volume_ratio = decline_avg_volume / uptrend_avg_volume if uptrend_avg_volume > 0 else 0

        # 패턴 분류
        if support_volume_ratio < 0.15:
            support_volume_class = 0  # very_low
        elif support_volume_ratio < 0.25:
            support_volume_class = 1  # low
        elif support_volume_ratio < 0.50:
            support_volume_class = 2  # normal
        else:
            support_volume_class = 3  # high

        if decline_volume_ratio < 0.3:
            decline_volume_class = 0  # strong_decrease
        elif decline_volume_ratio < 0.6:
            decline_volume_class = 1  # normal_decrease
        else:
            decline_volume_class = 2  # weak_decrease

        # 시간 정보
        signal_time = pattern.get('signal_time', '')
        try:
            dt = datetime.fromisoformat(signal_time)
            hour = dt.hour
            minute = dt.minute
            time_in_minutes = hour * 60 + minute
            is_morning = 1 if hour < 12 else 0
        except:
            hour = minute = time_in_minutes = is_morning = 0

        # 피처 딕셔너리 생성
        features_dict = {
            'uptrend_candles': uptrend_candles,
            'uptrend_gain': uptrend_gain,
            'uptrend_max_volume': uptrend_max_volume,
            'uptrend_avg_volume': uptrend_avg_volume,
            'decline_candles': decline_candles,
            'decline_pct': decline_pct,
            'decline_avg_volume': decline_avg_volume,
            'support_candles': support_candles,
            'support_avg_volume': support_avg_volume,
            'support_volatility': support_volatility,
            'breakout_volume': breakout_volume,
            'breakout_close': breakout_close,
            'support_volume_ratio': support_volume_ratio,
            'decline_volume_ratio': decline_volume_ratio,
            'support_volume_class': support_volume_class,
            'decline_volume_class': decline_volume_class,
            'confidence': signal_info.get('confidence', 0),
            'hour': hour,
            'minute': minute,
            'time_in_minutes': time_in_minutes,
            'is_morning': is_morning
        }

        # feature_names 순서대로 값 추출
        feature_values = [features_dict.get(name, 0) for name in feature_names]
        return pd.Series(feature_values, index=feature_names)

    except Exception as e:
        print(f"   [경고] 피처 추출 실패: {e}")
        return None


def apply_ml_filter_to_file(input_file: str, output_file: str, threshold: float = DEFAULT_THRESHOLD):
    """ML 필터 적용"""
    print(f"\n[ML 필터] 입력: {input_file}")
    print(f"[ML 필터] 출력: {output_file}")
    print(f"[ML 필터] 임계값: {threshold:.1%}")

    # ML 모델 로드
    model, feature_names = load_ml_model()
    if model is None:
        print("[오류] ML 모델을 로드할 수 없습니다.")
        return False

    # 종목명 로드
    stock_names = load_stock_names()

    # 입력 파일 읽기
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"[오류] 파일 읽기 실패: {e}")
        return False

    # 날짜 추출
    date_match = re.search(r'(\d{8})', input_file)
    if not date_match:
        print("[오류] 파일명에서 날짜를 찾을 수 없습니다.")
        return False

    trade_date = date_match.group(1)

    # 패턴 데이터 로드
    patterns = load_pattern_data_for_date(trade_date)
    print(f"[패턴 로그] {len(patterns)}개 패턴 로드됨")

    # 필터링
    total_signals = 0
    passed_signals = 0
    blocked_signals = 0
    output_lines = []
    blocked_details = []  # 🆕 차단된 신호 상세 정보

    for line in lines:
        signal = parse_signal_from_log_line(line)

        if signal:
            total_signals += 1

            # 패턴 매칭
            pattern_id = f"{signal['stock_code']}_{trade_date}_{signal['hour']:02d}{signal['minute']:02d}00"
            pattern = patterns.get(pattern_id)

            if pattern:
                # ML 예측
                features = extract_features_from_pattern(pattern, feature_names)
                if features is not None:
                    ml_prob = model.predict(features.values.reshape(1, -1), num_iteration=model.best_iteration)[0]

                    if ml_prob >= threshold:
                        passed_signals += 1
                        output_lines.append(line)
                    else:
                        blocked_signals += 1
                        # 🆕 차단된 신호 정보 수집
                        stock_name = stock_names.get(signal['stock_code'], '???')
                        blocked_details.append({
                            'stock_code': signal['stock_code'],
                            'stock_name': stock_name,
                            'time': signal['time'],
                            'profit_rate': signal['profit_rate'],
                            'ml_prob': ml_prob,
                            'is_win': signal['is_win']
                        })
                else:
                    # 피처 추출 실패 시 통과
                    passed_signals += 1
                    output_lines.append(line)
            else:
                # 패턴 없으면 통과
                passed_signals += 1
                output_lines.append(line)
        else:
            # 신호가 아닌 라인은 그대로 출력
            output_lines.append(line)

    # 🆕 차단된 신호 섹션 추가
    if blocked_details:
        output_lines.append("\n")
        output_lines.append("=" * 70 + "\n")
        output_lines.append("🚫 ML 필터에 의해 제외된 신호\n")
        output_lines.append("=" * 70 + "\n")
        output_lines.append(f"총 {len(blocked_details)}건 (ML 승률 임계값: {threshold:.1%} 미만)\n")
        output_lines.append("\n")

        # 차단된 신호를 결과별로 분류
        blocked_wins = [d for d in blocked_details if d['is_win']]
        blocked_losses = [d for d in blocked_details if not d['is_win']]

        if blocked_wins:
            output_lines.append(f"✅ 실제로는 수익이 났지만 제외된 신호: {len(blocked_wins)}건\n")
            for detail in blocked_wins:
                output_lines.append(f"   🟢 {detail['stock_code']}({detail['stock_name']}) {detail['time']} "
                                  f"→ +{detail['profit_rate']:.2f}% (ML 승률: {detail['ml_prob']:.1%})\n")
            output_lines.append("\n")

        if blocked_losses:
            output_lines.append(f"❌ 손실이 났고 정확히 제외된 신호: {len(blocked_losses)}건\n")
            for detail in blocked_losses:
                output_lines.append(f"   🔴 {detail['stock_code']}({detail['stock_name']}) {detail['time']} "
                                  f"→ {detail['profit_rate']:+.2f}% (ML 승률: {detail['ml_prob']:.1%})\n")

        output_lines.append("\n")

    # 결과 저장
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.writelines(output_lines)
    except Exception as e:
        print(f"[오류] 파일 쓰기 실패: {e}")
        return False

    # 통계 출력
    print(f"\n[필터링 결과]")
    print(f"  총 신호: {total_signals}개")
    if total_signals > 0:
        print(f"  통과: {passed_signals}개 ({passed_signals/total_signals*100:.1f}%)")
        print(f"  차단: {blocked_signals}개 ({blocked_signals/total_signals*100:.1f}%)")
    else:
        print(f"  통과: {passed_signals}개")
        print(f"  차단: {blocked_signals}개")

    return True


def main():
    parser = argparse.ArgumentParser(description='동적 손익비 ML 모델로 백테스트 결과 필터링')
    parser.add_argument('input_file', help='입력 파일 경로')
    parser.add_argument('--output', '-o', help='출력 파일 경로 (기본: 입력_ml_filtered.txt)')
    parser.add_argument('--threshold', '-t', type=float, default=DEFAULT_THRESHOLD, help=f'ML 임계값 (기본: {DEFAULT_THRESHOLD})')

    args = parser.parse_args()

    # 출력 파일명 설정
    if args.output:
        output_file = args.output
    else:
        input_path = Path(args.input_file)
        output_file = str(input_path.parent / f"{input_path.stem}_ml_filtered{input_path.suffix}")

    # 필터 적용
    success = apply_ml_filter_to_file(args.input_file, output_file, args.threshold)

    if success:
        print(f"\n[완료] {output_file}")
        sys.exit(0)
    else:
        print(f"\n[실패]")
        sys.exit(1)


if __name__ == "__main__":
    main()
