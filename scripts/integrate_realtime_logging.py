#!/usr/bin/env python3
"""
main.py에 실시간 데이터 로깅 기능 통합 스크립트

이 스크립트는 main.py의 _update_intraday_data 메서드와 
IntradayStockManager.batch_update_realtime_data 메서드에 
실시간 데이터 로깅 기능을 추가합니다.
"""

import re
from pathlib import Path


def integrate_logging_to_main():
    """main.py에 실시간 데이터 로깅 기능을 통합"""
    
    main_file = Path("main.py")
    if not main_file.exists():
        print("❌ main.py 파일을 찾을 수 없습니다.")
        return False
    
    # main.py 읽기
    with open(main_file, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. import 추가
    import_pattern = r'from post_market_chart_generator import PostMarketChartGenerator'
    import_replacement = '''from post_market_chart_generator import PostMarketChartGenerator
from core.realtime_data_logger import log_intraday_data'''
    
    if 'from core.realtime_data_logger import log_intraday_data' not in content:
        content = re.sub(import_pattern, import_replacement, content)
        print("✅ main.py에 import 추가")
    
    # 2. _update_intraday_data 메서드에 로깅 추가
    method_pattern = r'(async def _update_intraday_data\(self\):.*?try:.*?# 모든 선정 종목의 실시간 데이터 업데이트\s+await self\.intraday_manager\.batch_update_realtime_data\(\))'
    method_replacement = r'''\1
            
            # 🆕 실시간 데이터 로깅 추가
            await self._log_realtime_data_to_files()'''
    
    if 'await self._log_realtime_data_to_files()' not in content:
        content = re.sub(method_pattern, method_replacement, content, flags=re.DOTALL)
        print("✅ _update_intraday_data에 로깅 호출 추가")
    
    # 3. 새로운 메서드 추가
    new_method = '''
    async def _log_realtime_data_to_files(self):
        """실시간 수집 데이터를 종목별 파일로 저장"""
        try:
            from core.models import StockState
            
            # 모든 선정된 종목들에 대해 데이터 로깅
            selected_stocks = self.trading_manager.get_stocks_by_state(StockState.SELECTED)
            positioned_stocks = self.trading_manager.get_stocks_by_state(StockState.POSITIONED)
            
            all_stocks = selected_stocks + positioned_stocks
            
            for trading_stock in all_stocks:
                try:
                    stock_code = trading_stock.stock_code
                    stock_name = trading_stock.stock_name
                    
                    # 분봉 데이터 가져오기 (최신 1~2개)
                    combined_data = self.intraday_manager.get_combined_chart_data(stock_code)
                    latest_minute_data = None
                    if combined_data is not None and len(combined_data) > 0:
                        # 최근 1개 분봉만 로깅 (중복 방지)
                        latest_minute_data = combined_data.tail(1)
                    
                    # 현재가 데이터 가져오기
                    price_data = self.intraday_manager.get_cached_current_price(stock_code)
                    
                    # 매매신호 분석 (선정된 종목만)
                    signal_data = None
                    if trading_stock in selected_stocks and combined_data is not None and len(combined_data) >= 5:
                        try:
                            buy_signal, buy_reason, buy_info = await self.decision_engine.analyze_buy_decision(trading_stock, combined_data)
                            
                            # 3분봉 신호 분석
                            from core.timeframe_converter import TimeFrameConverter
                            from core.indicators.pullback_candle_pattern import PullbackCandlePattern
                            
                            data_3min = TimeFrameConverter.convert_to_3min_data(combined_data)
                            if data_3min is not None and not data_3min.empty:
                                signals = PullbackCandlePattern.generate_trading_signals(data_3min, use_improved_logic=True, debug=False)
                                
                                current_signals = {}
                                if signals is not None and not signals.empty:
                                    last_idx = len(signals) - 1
                                    current_signals = {
                                        'buy_pullback_pattern': bool(signals.get('buy_pullback_pattern', pd.Series([False])).iloc[last_idx]),
                                        'buy_bisector_recovery': bool(signals.get('buy_bisector_recovery', pd.Series([False])).iloc[last_idx]),
                                        'signal_type': signals.get('signal_type', pd.Series([''])).iloc[last_idx],
                                        'confidence': float(signals.get('confidence', pd.Series([0.0])).iloc[last_idx]),
                                        'target_profit': float(signals.get('target_profit', pd.Series([0.0])).iloc[last_idx])
                                    }
                            
                            signal_data = {
                                'buy_signal': buy_signal,
                                'buy_reason': buy_reason,
                                'data_length': len(combined_data),
                                'signal_type': current_signals.get('signal_type', ''),
                                'confidence': current_signals.get('confidence', 0),
                                'target_profit': current_signals.get('target_profit', 0)
                            }
                            
                        except Exception as signal_err:
                            self.logger.debug(f"⚠️ {stock_code} 신호 분석 오류: {signal_err}")
                    
                    # 실시간 데이터 로깅 (종목별 파일)
                    log_intraday_data(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        minute_data=latest_minute_data,
                        price_data=price_data,
                        signal_data=signal_data
                    )
                    
                except Exception as stock_err:
                    self.logger.debug(f"⚠️ {trading_stock.stock_code} 데이터 로깅 오류: {stock_err}")
            
        except Exception as e:
            self.logger.debug(f"⚠️ 실시간 데이터 로깅 전체 오류: {e}")

'''
    
    # 메서드가 없으면 추가
    if 'async def _log_realtime_data_to_files(self):' not in content:
        # DayTradingBot 클래스 끝나기 전에 메서드 추가
        class_end_pattern = r'(    async def shutdown\(self\):.*?except Exception as e:.*?self\.logger\.error\(f"❌ 시스템 종료 중 오류: \{e\}"\))'
        class_end_replacement = new_method + r'\1'
        
        content = re.sub(class_end_pattern, class_end_replacement, content, flags=re.DOTALL)
        print("✅ _log_realtime_data_to_files 메서드 추가")
    
    # main.py에 쓰기
    with open(main_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ main.py에 실시간 데이터 로깅 기능 통합 완료")
    return True


def create_usage_example():
    """사용 예시 파일 생성"""
    
    example_file = Path("realtime_logging_example.py")
    
    example_content = '''#!/usr/bin/env python3
"""
실시간 데이터 로깅 사용 예시

main.py와 signal_replay.py의 결과를 비교하기 위한 실시간 데이터 수집 및 분석
"""

import asyncio
import pandas as pd
from pathlib import Path
from datetime import datetime

from core.realtime_data_logger import RealtimeDataLogger, get_realtime_logger
from utils.korean_time import now_kst


async def analyze_realtime_vs_replay():
    """실시간 수집 데이터와 signal_replay 결과 비교 분석"""
    
    logger = get_realtime_logger()
    
    # 1. 현재 수집된 데이터 파일 통계 확인
    stats = logger.get_file_stats()
    print(f"📊 실시간 데이터 현황:")
    print(f"  - 총 파일: {stats.get('total_files', 0)}개")
    print(f"  - 파일 타입: {stats.get('file_types', {})}")
    print(f"  - 총 크기: {stats.get('total_size', 0):,} bytes")
    print(f"  - 최근 수정: {stats.get('last_modified', 'N/A')}")
    
    # 2. 일일 요약 리포트 생성
    summary_file = logger.create_daily_summary()
    if summary_file:
        print(f"\\n📋 일일 요약 리포트: {summary_file}")
        
        # 요약 파일 내용 출력
        with open(summary_file, 'r', encoding='utf-8') as f:
            print(f.read())
    
    # 3. signal_replay와 비교할 준비
    today_str = now_kst().strftime("%Y%m%d")
    print(f"\\n🔄 signal_replay 비교 준비:")
    print(f"  장마감 후 다음 명령으로 비교 가능:")
    print(f"  python -m utils.signal_replay --date {today_str} --export txt --txt-path signal_replay_{today_str}.txt")
    
    # 4. 실시간 데이터 파일들 나열
    data_dir = Path("realtime_data") / today_str
    if data_dir.exists():
        print(f"\\n📁 실시간 수집 파일들:")
        for file_path in sorted(data_dir.glob("*.txt")):
            size_kb = file_path.stat().st_size // 1024
            print(f"  - {file_path.name} ({size_kb} KB)")


def compare_data_files(realtime_file: str, replay_file: str):
    """실시간 파일과 replay 파일 비교"""
    
    print(f"\\n🔍 데이터 비교: {realtime_file} vs {replay_file}")
    
    try:
        # 실시간 파일 분석
        if Path(realtime_file).exists():
            with open(realtime_file, 'r', encoding='utf-8') as f:
                realtime_lines = f.readlines()
            print(f"  실시간 데이터: {len(realtime_lines)}줄")
        else:
            print(f"  ❌ 실시간 파일 없음: {realtime_file}")
            return
        
        # replay 파일 분석
        if Path(replay_file).exists():
            with open(replay_file, 'r', encoding='utf-8') as f:
                replay_content = f.read()
            print(f"  replay 데이터: {len(replay_content)}문자")
        else:
            print(f"  ❌ replay 파일 없음: {replay_file}")
            return
        
        # 간단한 비교 (매수신호 횟수 등)
        realtime_signals = sum(1 for line in realtime_lines if '매수신호=True' in line)
        replay_signals = replay_content.count('→ ON [')
        
        print(f"\\n📈 신호 비교:")
        print(f"  실시간 매수신호: {realtime_signals}건")
        print(f"  replay 매수신호: {replay_signals}건")
        print(f"  차이: {abs(realtime_signals - replay_signals)}건")
        
    except Exception as e:
        print(f"❌ 비교 오류: {e}")


if __name__ == "__main__":
    print("🚀 실시간 데이터 로깅 분석 시작")
    
    # 실시간 분석 실행
    asyncio.run(analyze_realtime_vs_replay())
    
    # 사용자 입력 대기 모드
    print("\\n" + "="*50)
    print("📝 비교 분석 (장마감 후 사용):")
    print("1. 실시간 데이터와 signal_replay 결과 비교")
    print("2. 예시: python realtime_logging_example.py")
    print("="*50)
'''
    
    with open(example_file, 'w', encoding='utf-8') as f:
        f.write(example_content)
    
    print(f"✅ 사용 예시 파일 생성: {example_file}")


def main():
    """메인 실행 함수"""
    
    print("🔧 main.py에 실시간 데이터 로깅 기능 통합")
    print("="*50)
    
    # 1. main.py 통합
    success = integrate_logging_to_main()
    if not success:
        print("❌ 통합 실패")
        return
    
    # 2. 사용 예시 생성
    create_usage_example()
    
    print("\\n✅ 통합 완료!")
    print("\\n📋 사용 방법:")
    print("1. main.py 실행 → 실시간 데이터가 realtime_data/ 폴더에 종목별로 저장됨")
    print("2. 장마감 후 signal_replay 실행 → 결과를 txt 파일로 저장")
    print("3. realtime_logging_example.py 실행 → 두 결과 비교 분석")
    print("\\n📁 저장되는 파일:")
    print("- realtime_data/YYYYMMDD/YYYYMMDD_종목코드_종목명_minute.txt")
    print("- realtime_data/YYYYMMDD/YYYYMMDD_종목코드_종목명_price.txt") 
    print("- realtime_data/YYYYMMDD/YYYYMMDD_종목코드_종목명_signals.txt")
    print("- realtime_data/YYYYMMDD/YYYYMMDD_종목코드_종목명_combined.txt")


if __name__ == "__main__":
    main()