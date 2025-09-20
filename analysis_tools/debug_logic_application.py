"""
로직 적용 상태 디버깅

개선된 로직이 실제로 적용되고 있는지 확인
"""

import re
from pathlib import Path

def check_logic_application():
    """로직 적용 상태 확인"""
    print("로직 적용 상태 디버깅")
    print("="*50)

    # 최신 로그 파일 확인
    after_dir = Path("signal_replay_log")
    latest_file = sorted(after_dir.glob("*.txt"))[-1]

    print(f"최신 로그 파일: {latest_file.name}")

    try:
        with open(latest_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 일봉 분석 관련 로그 찾기
        daily_analysis_logs = re.findall(r'\[([^\]]+)\] 일봉분석: ([^\\n]+)', content)

        if daily_analysis_logs:
            print(f"\n✅ 일봉 분석 로직 적용됨! ({len(daily_analysis_logs)}개 발견)")
            print("샘플 로그:")
            for i, (stock, log) in enumerate(daily_analysis_logs[:5]):
                print(f"  {i+1}. [{stock}] {log}")
        else:
            print("\n❌ 일봉 분석 로그를 찾을 수 없음")

        # 시간대별 신호 분포 확인
        signals = re.findall(r'(\d{2}:\d{2}) \[([^\]]+)\]', content)

        if signals:
            print(f"\n시간대별 신호 분포:")
            time_counts = {}
            for time_str, signal_type in signals:
                hour = int(time_str.split(':')[0])
                if 9 <= hour < 10:
                    time_cat = "opening"
                elif 10 <= hour < 12:
                    time_cat = "morning"
                elif 12 <= hour < 14:
                    time_cat = "afternoon"
                elif 14 <= hour < 15:
                    time_cat = "late"
                else:
                    time_cat = "other"

                time_counts[time_cat] = time_counts.get(time_cat, 0) + 1

            for time_cat, count in time_counts.items():
                print(f"  {time_cat}: {count}개")

            # 오후시간 신호 확인
            afternoon_signals = [s for s in signals if 12 <= int(s[0].split(':')[0]) < 14]
            print(f"\n오후시간 신호: {len(afternoon_signals)}개")

            if len(afternoon_signals) > 0:
                print("❌ 오후시간 신호가 여전히 발생 중 - 로직이 제대로 적용되지 않았을 수 있음")
            else:
                print("✅ 오후시간 신호 완전 차단됨")

        # 총 승패 확인
        total_match = re.search(r'=== 총 승패: (\d+)승 (\d+)패 ===', content)
        if total_match:
            wins = int(total_match.group(1))
            losses = int(total_match.group(2))
            total = wins + losses
            win_rate = wins / total * 100 if total > 0 else 0
            print(f"\n당일 성과: {wins}승 {losses}패 (승률 {win_rate:.1f}%)")

    except Exception as e:
        print(f"오류: {e}")

def check_code_modification():
    """실제 코드 수정 상태 확인"""
    print("\n코드 수정 상태 확인")
    print("="*30)

    pattern_file = Path("core/indicators/pullback_candle_pattern.py")

    try:
        with open(pattern_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 일봉 분석 함수 존재 확인
        if "analyze_daily_pattern_strength" in content:
            print("✅ 일봉 분석 함수 존재")
        else:
            print("❌ 일봉 분석 함수 없음")

        # 시간대별 조건 확인
        if "12 <= current_time.hour < 14" in content:
            print("✅ 시간대별 조건 존재")
        else:
            print("❌ 시간대별 조건 없음")

        # 일봉 패턴 적용 확인
        if "daily_pattern =" in content:
            print("✅ 일봉 패턴 변수 존재")
        else:
            print("❌ 일봉 패턴 변수 없음")

        # 디버그 로그 확인
        if "일봉분석:" in content:
            print("✅ 일봉 분석 로그 코드 존재")
        else:
            print("❌ 일봉 분석 로그 코드 없음")

    except Exception as e:
        print(f"코드 확인 오류: {e}")

def analyze_time_distribution():
    """시간대별 신호 분포 상세 분석"""
    print("\n시간대별 신호 분포 상세 분석")
    print("="*40)

    before_dir = Path("signal_replay_log_prev")
    after_dir = Path("signal_replay_log")

    # 최신 파일 비교
    before_files = sorted(before_dir.glob("*.txt"))
    after_files = sorted(after_dir.glob("*.txt"))

    if before_files and after_files:
        before_file = before_files[-1]
        after_file = after_files[-1]

        print(f"비교 파일:")
        print(f"  수정 전: {before_file.name}")
        print(f"  수정 후: {after_file.name}")

        for label, file_path in [("수정 전", before_file), ("수정 후", after_file)]:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()

                signals = re.findall(r'(\d{2}:\d{2}) \[([^\]]+)\]', content)
                time_counts = {}

                for time_str, signal_type in signals:
                    hour = int(time_str.split(':')[0])
                    if 9 <= hour < 10:
                        time_cat = "opening"
                    elif 10 <= hour < 12:
                        time_cat = "morning"
                    elif 12 <= hour < 14:
                        time_cat = "afternoon"
                    elif 14 <= hour < 15:
                        time_cat = "late"
                    else:
                        time_cat = "other"

                    time_counts[time_cat] = time_counts.get(time_cat, 0) + 1

                print(f"\n{label}:")
                for time_cat in ['opening', 'morning', 'afternoon', 'late']:
                    count = time_counts.get(time_cat, 0)
                    print(f"  {time_cat}: {count}개")

            except Exception as e:
                print(f"{label} 분석 오류: {e}")

def main():
    check_logic_application()
    check_code_modification()
    analyze_time_distribution()

    print(f"\n💡 분석 결론:")
    print("1. 코드가 제대로 수정되었는지 확인")
    print("2. 일봉 데이터 로드가 정상 작동하는지 확인")
    print("3. 실제 신호 발생 시점에 로직이 적용되는지 확인")

if __name__ == "__main__":
    main()