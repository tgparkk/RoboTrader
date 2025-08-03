"""
주식 단타 거래 시스템 메인 실행 파일
"""
import asyncio
import signal
import sys
import os
from datetime import datetime
from pathlib import Path

# 프로젝트 경로 추가
sys.path.append(str(Path(__file__).parent))

from core.models import TradingConfig
from core.data_collector import RealTimeDataCollector
from core.order_manager import OrderManager
from core.telegram_integration import TelegramIntegration
from core.candidate_selector import CandidateSelector
from core.intraday_stock_manager import IntradayStockManager
from db.database_manager import DatabaseManager
from api.kis_api_manager import KISAPIManager
from config.settings import load_trading_config
from utils.logger import setup_logger
from utils.korean_time import now_kst, get_market_status, is_market_open
from post_market_chart_generator import PostMarketChartGenerator


class DayTradingBot:
    """주식 단타 거래 봇"""
    
    def __init__(self):
        self.logger = setup_logger(__name__)
        self.is_running = False
        self.pid_file = Path("bot.pid")
        
        # 프로세스 중복 실행 방지
        self._check_duplicate_process()
        
        # 설정 초기화
        self.config = self._load_config()
        
        # 핵심 모듈 초기화
        self.api_manager = KISAPIManager()
        self.telegram = TelegramIntegration(trading_bot=self)
        self.data_collector = RealTimeDataCollector(self.config, self.api_manager)
        self.order_manager = OrderManager(self.config, self.api_manager, self.telegram)
        self.candidate_selector = CandidateSelector(self.config, self.api_manager)
        self.intraday_manager = IntradayStockManager(self.api_manager)  # 🆕 장중 종목 관리자
        self.db_manager = DatabaseManager()
        self.chart_generator = None  # 🆕 장 마감 후 차트 생성기 (지연 초기화)
        
        # 신호 핸들러 등록
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _check_duplicate_process(self):
        """프로세스 중복 실행 방지"""
        try:
            if self.pid_file.exists():
                # 기존 PID 파일 읽기
                existing_pid = int(self.pid_file.read_text().strip())
                
                # Windows에서 프로세스 존재 여부 확인
                try:
                    import psutil
                    if psutil.pid_exists(existing_pid):
                        process = psutil.Process(existing_pid)
                        if 'python' in process.name().lower() and 'main.py' in ' '.join(process.cmdline()):
                            self.logger.error(f"이미 봇이 실행 중입니다 (PID: {existing_pid})")
                            print(f"오류: 이미 거래 봇이 실행 중입니다 (PID: {existing_pid})")
                            print("기존 프로세스를 먼저 종료해주세요.")
                            sys.exit(1)
                except ImportError:
                    # psutil이 없는 경우 간단한 체크
                    self.logger.warning("psutil 모듈이 없어 정확한 중복 실행 체크를 할 수 없습니다")
                except:
                    # 기존 PID가 존재하지 않으면 PID 파일 삭제
                    self.pid_file.unlink(missing_ok=True)
            
            # 현재 프로세스 PID 저장
            current_pid = os.getpid()
            self.pid_file.write_text(str(current_pid))
            self.logger.info(f"프로세스 PID 등록: {current_pid}")
            
        except Exception as e:
            self.logger.warning(f"중복 실행 체크 중 오류: {e}")
    
    def _load_config(self) -> TradingConfig:
        """거래 설정 로드"""
        config = load_trading_config()
        self.logger.info(f"거래 설정 로드 완료: 후보종목 {len(config.data_collection.candidate_stocks)}개")
        return config
    
    def _signal_handler(self, signum, frame):
        """시그널 핸들러 (Ctrl+C 등)"""
        self.logger.info(f"종료 신호 수신: {signum}")
        self.is_running = False
    
    async def initialize(self) -> bool:
        """시스템 초기화"""
        try:
            self.logger.info("🚀 주식 단타 거래 시스템 초기화 시작")
            
            # 1. API 초기화
            self.logger.info("📡 API 매니저 초기화 시작...")
            if not self.api_manager.initialize():
                self.logger.error("❌ API 초기화 실패")
                return False
            self.logger.info("✅ API 매니저 초기화 완료")
            
            # 2. 시장 상태 확인
            market_status = get_market_status()
            self.logger.info(f"📊 현재 시장 상태: {market_status}")
            
            # 3. 텔레그램 초기화
            await self.telegram.initialize()
            
            # 4. 후보 종목 설정 (동적 선정을 위해 초기화만 수행)
            # TODO: 매일 장전 동적으로 후보 종목 선정 로직 구현
            
            self.logger.info("✅ 시스템 초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 초기화 실패: {e}")
            return False
    
    async def run_daily_cycle(self):
        """일일 거래 사이클 실행"""
        try:
            self.is_running = True
            self.logger.info("📈 일일 거래 사이클 시작")
            
            # 병렬 실행할 태스크들
            tasks = [
                self._data_collection_task(),
                self._order_monitoring_task(),
                self._trading_decision_task(),
                self._system_monitoring_task(),
                self._telegram_task()
            ]
            
            # 모든 태스크 실행
            await asyncio.gather(*tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 일일 거래 사이클 실행 중 오류: {e}")
        finally:
            await self.shutdown()
    
    async def _data_collection_task(self):
        """데이터 수집 태스크"""
        try:
            self.logger.info("📊 데이터 수집 태스크 시작")
            await self.data_collector.start_collection()
        except Exception as e:
            self.logger.error(f"❌ 데이터 수집 태스크 오류: {e}")
    
    async def _order_monitoring_task(self):
        """주문 모니터링 태스크"""
        try:
            self.logger.info("🔍 주문 모니터링 태스크 시작")
            await self.order_manager.start_monitoring()
        except Exception as e:
            self.logger.error(f"❌ 주문 모니터링 태스크 오류: {e}")
    
    async def _trading_decision_task(self):
        """매매 의사결정 태스크"""
        try:

            #await self._check_condition_search()

            self.logger.info("🤖 매매 의사결정 태스크 시작")
            
            last_condition_check = datetime(2000, 1, 1)  # 초기값
            
            while self.is_running:
                #await self._daily_market_update()   

                if not is_market_open():
                    await asyncio.sleep(60)  # 장 마감 시 1분 대기
                    continue
                
                current_time = now_kst()

                # 🆕 장중 조건검색 체크
                if (current_time - last_condition_check).total_seconds() >= 5 * 60:  # 5분
                    await self._check_condition_search()
                    last_condition_check = current_time
                
                # 현재는 기본 로직만 구현 (전략은 나중에 추가)
                await self._simple_trading_logic()
                await asyncio.sleep(60)  # 1분마다 체크
                
        except Exception as e:
            self.logger.error(f"❌ 매매 의사결정 태스크 오류: {e}")
    
    async def _simple_trading_logic(self):
        """간단한 매매 로직 (예시)"""
        try:
            # 후보 종목들의 최신 데이터 확인
            candidate_stocks = self.data_collector.get_candidate_stocks()
            
            for stock in candidate_stocks:
                if len(stock.ohlcv_data) < 5:  # 최소 5개 데이터 필요
                    continue
                
                # 간단한 예시: 최근 5분간 상승률 체크
                recent_data = stock.get_recent_ohlcv(5)
                if len(recent_data) >= 2:
                    price_change = (recent_data[-1].close_price - recent_data[0].close_price) / recent_data[0].close_price
                    
                    # 1% 이상 상승 시 매수 신호 (예시)
                    if price_change > 0.01 and stock.position.value == "none":
                        self.logger.info(f"🔥 매수 신호 감지: {stock.code} - 상승률: {price_change:.2%}")
                        
                        # 텔레그램 신호 알림
                        await self.telegram.notify_signal_detected({
                            'stock_code': stock.code,
                            'stock_name': stock.name,
                            'signal_type': '매수',
                            'price': recent_data[-1].close_price,
                            'reason': f'{price_change:.2%} 상승'
                        })
                        
                        # TODO: 실제 매수 로직 구현
                        
        except Exception as e:
            self.logger.error(f"❌ 매매 로직 실행 오류: {e}")
    
    async def _telegram_task(self):
        """텔레그램 태스크"""
        try:
            self.logger.info("📱 텔레그램 태스크 시작")
            
            # 텔레그램 봇 폴링과 주기적 상태 알림을 병렬 실행
            telegram_tasks = [
                self.telegram.start_telegram_bot(),
                self.telegram.periodic_status_task()
            ]
            
            await asyncio.gather(*telegram_tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 태스크 오류: {e}")
    
    async def _system_monitoring_task(self):
        """시스템 모니터링 태스크"""
        try:

            self.logger.info("📡 시스템 모니터링 태스크 시작")
            
            last_api_refresh = now_kst()
            last_market_check = now_kst()
            last_intraday_update = now_kst()  # 🆕 장중 데이터 업데이트 시간
            last_chart_generation = datetime(2000, 1, 1)  # 🆕 장 마감 후 차트 생성 시간

            while self.is_running:
                current_time = now_kst()
                
                # API 24시간마다 재초기화
                if (current_time - last_api_refresh).total_seconds() >= 86400:  # 24시간
                    await self._refresh_api()
                    last_api_refresh = current_time

                # 매일 오전 8시에 시장 상태 및 후보 종목 갱신
                '''
                if (current_time.hour == 8 and current_time.minute == 0 and 
                    (current_time - last_market_check).total_seconds() >= 60 * 60):  # 1시간 간격으로 체크
                    await self._daily_market_update()
                    last_market_check = current_time
                '''

                # 🆕 장중 종목 실시간 데이터 업데이트 (1분마다)
                if (current_time - last_intraday_update).total_seconds() >= 60:  # 1분
                    if is_market_open():
                        await self._update_intraday_data()
                    last_intraday_update = current_time
                
                # 🆕 장 마감 후 차트 생성 (16:00에 한 번만 실행)
                if (current_time.hour == 16 and current_time.minute == 0 and 
                    (current_time - last_chart_generation).total_seconds() >= 60 * 60):  # 1시간 간격으로 체크
                    await self._generate_post_market_charts()
                    last_chart_generation = current_time
                
                # 30분마다 시스템 상태 로그
                await asyncio.sleep(1800)
                await self._log_system_status()
                
        except Exception as e:
            self.logger.error(f"❌ 시스템 모니터링 태스크 오류: {e}")
            # 텔레그램 오류 알림
            await self.telegram.notify_error("SystemMonitoring", e)
    
    async def _log_system_status(self):
        """시스템 상태 로깅"""
        try:
            current_time = now_kst()
            market_status = get_market_status()
            
            # 주문 요약
            order_summary = self.order_manager.get_order_summary()
            
            # 데이터 수집 상태
            candidate_stocks = self.data_collector.get_candidate_stocks()
            data_counts = {stock.code: len(stock.ohlcv_data) for stock in candidate_stocks}
            
            self.logger.info(
                f"📊 시스템 상태 [{current_time.strftime('%H:%M:%S')}]\n"
                f"  - 시장 상태: {market_status}\n"
                f"  - 미체결 주문: {order_summary['pending_count']}건\n"
                f"  - 완료 주문: {order_summary['completed_count']}건\n"
                f"  - 데이터 수집: {data_counts}"
            )
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 상태 로깅 오류: {e}")
    
    async def _refresh_api(self):
        """API 재초기화"""
        try:
            self.logger.info("🔄 API 24시간 주기 재초기화 시작")
            
            # API 매니저 재초기화
            if not self.api_manager.initialize():
                self.logger.error("❌ API 재초기화 실패")
                await self.telegram.notify_error("API Refresh", "API 재초기화 실패")
                return False
                
            self.logger.info("✅ API 재초기화 완료")
            await self.telegram.notify_system_status("API 재초기화 완료")
            return True
            
        except Exception as e:
            self.logger.error(f"❌ API 재초기화 오류: {e}")
            await self.telegram.notify_error("API Refresh", e)
            return False
    
    async def _daily_market_update(self):
        """일일 시장 상태 및 후보 종목 갱신"""
        try:
            self.logger.info("📊 일일 시장 정보 갱신 시작")
            
            # 시장 상태 갱신
            market_status = get_market_status()
            self.logger.info(f"📈 시장 상태 갱신: {market_status}")
            
            # 후보 종목 동적 선정
            self.logger.info("🔍 후보 종목 동적 선정 시작")
            '''
            candidates = await self.candidate_selector.select_daily_candidates(max_candidates=5)
            
            if candidates:
                # 후보 종목을 설정에 업데이트
                self.candidate_selector.update_candidate_stocks_in_config(candidates)
                
                # 데이터베이스에 저장
                save_success = self.db_manager.save_candidate_stocks(candidates)
                if save_success:
                    self.logger.info(f"📊 후보 종목 데이터베이스 저장 완료: {len(candidates)}개")
                else:
                    self.logger.error("❌ 후보 종목 데이터베이스 저장 실패")
                
                # 데이터 컬렉터에 새로운 후보 종목 추가
                for candidate in candidates:
                    self.data_collector.add_candidate_stock(candidate.code, candidate.name)
                
                # 텔레그램 알림
                candidate_info = "\n".join([
                    f"  - {c.code}({c.name}): {c.score:.1f}점"
                    for c in candidates
                ])
                await self.telegram.notify_system_status(
                    f"🎯 일일 후보 종목 선정 완료:\n{candidate_info}"
                )
                
                self.logger.info(f"✅ 후보 종목 선정 완료: {len(candidates)}개")
            else:
                self.logger.warning("⚠️ 선정된 후보 종목이 없습니다")
                await self.telegram.notify_system_status("⚠️ 오늘은 선정된 후보 종목이 없습니다")
            '''
            await self.telegram.notify_system_status(f"일일 시장 정보 갱신 완료 - 시장 상태: {market_status}")
            
        except Exception as e:
            self.logger.error(f"❌ 일일 시장 정보 갱신 오류: {e}")
            await self.telegram.notify_error("Daily Market Update", e)
    
    async def _check_condition_search(self):
        """장중 조건검색 체크"""
        try:
            self.logger.info("🔍 장중 조건검색 체크 시작")
            
            # 조건검색 seq 리스트 (필요에 따라 여러 조건 추가 가능)
            #condition_seqs = ["0", "1", "2"]  # 예: 0, 1, 2번 조건
            condition_seqs = ["0"]
            
            all_condition_results = []
            
            for seq in condition_seqs:
                try:
                    # 조건검색 결과 조회 (단순 조회만)
                    condition_results = self.candidate_selector.get_condition_search_candidates(seq=seq)
                    
                    if condition_results:
                        all_condition_results.extend(condition_results)
                        self.logger.info(f"✅ 조건검색 {seq}번: {len(condition_results)}개 종목 발견")
                        self.logger.debug(f"🔍 조건검색 {seq}번 결과: {condition_results}")
                    else:
                        self.logger.debug(f"ℹ️ 조건검색 {seq}번: 해당 종목 없음")
                        
                except Exception as e:
                    self.logger.warning(f"⚠️ 조건검색 {seq}번 오류: {e}")
                    continue
            
            # 결과가 있으면 알림 발송
            self.logger.info(f"🔍 조건검색 전체 결과: {len(all_condition_results)}개 종목")
            if all_condition_results:
                await self._notify_condition_search_results(all_condition_results)
                
                # 🆕 장중 선정 종목 관리자에 추가 (과거 분봉 데이터 포함)
                self.logger.info(f"🎯 장중 선정 종목 관리자에 {len(all_condition_results)}개 종목 추가 시작")
                for stock_data in all_condition_results:
                    stock_code = stock_data.get('code', '')
                    stock_name = stock_data.get('name', '')
                    change_rate = stock_data.get('chgrate', '')
                    
                    if stock_code:
                        # 장중 종목 관리자에 추가 (과거 분봉 데이터 자동 수집)
                        selection_reason = f"조건검색 급등주 (등락률: {change_rate}%)"
                        success = self.intraday_manager.add_selected_stock(
                            stock_code=stock_code,
                            stock_name=stock_name,
                            selection_reason=selection_reason
                        )
                        
                        if success:
                            self.logger.info(f"🎯 장중 선정 종목 추가: {stock_code}({stock_name}) - {selection_reason}")
                        
                        # 기존 실시간 데이터 수집에도 추가
                        if not self.data_collector.has_stock(stock_code):
                            self.data_collector.add_candidate_stock(stock_code, stock_name)
                            self.logger.info(f"📊 조건검색 종목 데이터 수집 추가: {stock_code}({stock_name})")
            else:
                self.logger.debug("ℹ️ 장중 조건검색: 발견된 종목 없음")
            
        except Exception as e:
            self.logger.error(f"❌ 장중 조건검색 체크 오류: {e}")
            await self.telegram.notify_error("Condition Search", e)
    
    async def _notify_condition_search_results(self, stock_results):
        """조건검색 결과 알림"""
        try:
            # 알림 메시지 생성
            message_lines = ["🔥 장중 조건검색 급등주 발견!"]
            message_lines.append(f"📊 발견 시간: {now_kst().strftime('%H:%M:%S')}")
            message_lines.append("")
            
            for i, stock_data in enumerate(stock_results[:5], 1):  # 상위 5개만
                code = stock_data.get('code', '')
                name = stock_data.get('name', '')
                price = stock_data.get('price', '')
                change_rate = stock_data.get('chgrate', '')
                
                message_lines.append(
                    f"{i}. {code} {name}\n"
                    f"   💰 현재가: {price}원\n"
                    f"   📈 등락률: {change_rate}%"
                )
            
            if len(stock_results) > 5:
                message_lines.append(f"... 외 {len(stock_results) - 5}개 종목")
            
            alert_message = "\n".join(message_lines)
            
            # 텔레그램 알림 (긴급 알림으로 발송)
            await self.telegram.notify_urgent_signal(alert_message)
            
            # 개별 종목별 상세 정보도 발송 (상위 3개만)
            for stock_data in stock_results[:3]:
                code = stock_data.get('code', '')
                name = stock_data.get('name', '')
                price = stock_data.get('price', '')
                change_rate = stock_data.get('chgrate', '')
                volume = stock_data.get('acml_vol', '')
                
                await self.telegram.notify_signal_detected({
                    'stock_code': code,
                    'stock_name': name,
                    'signal_type': '조건검색',
                    'price': price,
                    'change_rate': change_rate,
                    'volume': volume
                })
            
            self.logger.info(f"📱 조건검색 결과 알림 완료: {len(stock_results)}개 종목")
            
        except Exception as e:
            self.logger.error(f"❌ 조건검색 결과 알림 오류: {e}")

    async def _update_intraday_data(self):
        """장중 종목 실시간 데이터 업데이트 (1분마다)"""
        try:
            # 모든 선정 종목의 실시간 데이터 업데이트
            await self.intraday_manager.batch_update_realtime_data()
            
            # 업데이트 후 요약 정보 확인
            summary = self.intraday_manager.get_all_stocks_summary()
            if summary['total_stocks'] > 0:
                # 주요 종목들의 수익률 정보 (3% 이상 상승 시에만 로깅)
                profitable_stocks = [
                    stock for stock in summary['stocks'] 
                    if stock.get('price_change_rate', 0) > 3.0  # 3% 이상 상승
                ]
                
                if profitable_stocks:
                    profit_info = ", ".join([
                        f"{stock['stock_code']}({stock['price_change_rate']:+.1f}%)" 
                        for stock in profitable_stocks[:3]  # 상위 3개만
                    ])
                    self.logger.info(f"🚀 주요 상승 종목: {profit_info}")
            
        except Exception as e:
            self.logger.error(f"❌ 장중 종목 실시간 데이터 업데이트 오류: {e}")
            await self.telegram.notify_error("Intraday Data Update", e)
    
    async def _generate_post_market_charts(self):
        """장 마감 후 선정 종목 차트 생성 (15:30 이후)"""
        try:
            current_time = now_kst()
            
            # 장 마감 시간 체크 (15:30 이후)
            market_close_hour = 15
            market_close_minute = 30
            
            if current_time.hour < market_close_hour or (current_time.hour == market_close_hour and current_time.minute < market_close_minute):
                self.logger.debug("아직 장 마감 시간이 아님 - 차트 생성 건너뛰기")
                #return
            
            # 주말이나 공휴일 체크
            if current_time.weekday() >= 5:  # 토요일(5), 일요일(6)
                self.logger.debug("주말 - 차트 생성 건너뛰기")
                #return
            
            self.logger.info("🎨 장 마감 후 선정 종목 차트 생성 시작")
            
            # 차트 생성기 지연 초기화
            if self.chart_generator is None:
                self.chart_generator = PostMarketChartGenerator()
                if not self.chart_generator.initialize():
                    self.logger.error("❌ 차트 생성기 초기화 실패")
                    return
            
            # 장중 선정된 종목들 조회
            selected_stocks = []
            
            # IntradayStockManager에서 선정된 종목들 가져오기
            summary = self.intraday_manager.get_all_stocks_summary()
            
            if summary.get('total_stocks', 0) > 0:
                for stock_info in summary.get('stocks', []):
                    stock_code = stock_info.get('stock_code', '')
                    
                    # 종목 상세 정보 조회
                    stock_data = self.intraday_manager.get_stock_data(stock_code)
                    if stock_data:
                        selected_stocks.append({
                            'code': stock_code,
                            'name': stock_data.stock_name,
                            'chgrate': f"+{stock_info.get('price_change_rate', 0):.1f}",
                            'selection_reason': f"장중 선정 종목 ({stock_data.selected_time.strftime('%H:%M')} 선정)"
                        })
            
            if not selected_stocks:
                self.logger.info("ℹ️ 오늘 선정된 종목이 없어 차트 생성을 건너뜁니다")
                return
            
            # 당일 날짜로 차트 생성
            target_date = current_time.strftime("%Y%m%d")
            
            self.logger.info(f"📊 {len(selected_stocks)}개 선정 종목의 {target_date} 차트 생성 중...")
            
            # 각 종목별 차트 생성
            success_count = 0
            chart_files = []
            
            for stock_data in selected_stocks:
                stock_code = stock_data.get('code', '')
                stock_name = stock_data.get('name', '')
                selection_reason = stock_data.get('selection_reason', '')
                
                try:
                    self.logger.info(f"📈 {stock_code}({stock_name}) 차트 생성 중...")
                    
                    # 분봉 데이터 조회
                    chart_df = self.chart_generator.get_historical_chart_data(stock_code, target_date)
                    
                    if chart_df is None or chart_df.empty:
                        self.logger.warning(f"⚠️ {stock_code} 데이터 없음")
                        continue
                    
                    # 차트 생성
                    chart_file = self.chart_generator.create_post_market_candlestick_chart(
                        stock_code=stock_code,
                        stock_name=stock_name,
                        chart_df=chart_df,
                        target_date=target_date,
                        selection_reason=selection_reason
                    )
                    
                    if chart_file:
                        chart_files.append(chart_file)
                        success_count += 1
                        self.logger.info(f"✅ {stock_code} 차트 생성 성공: {chart_file}")
                    else:
                        self.logger.error(f"❌ {stock_code} 차트 생성 실패")
                
                except Exception as e:
                    self.logger.error(f"❌ {stock_code} 차트 생성 중 오류: {e}")
                    continue
            
            # 결과 요약 및 텔레그램 알림
            if success_count > 0:
                summary_message = (f"🎨 장 마감 후 차트 생성 완료\n"
                                 f"📊 생성된 차트: {success_count}/{len(selected_stocks)}개\n"
                                 f"📅 날짜: {target_date}\n"
                                 f"🕰️ 생성 시간: {current_time.strftime('%H:%M:%S')}")
                
                # 생성된 차트 파일 목록 추가
                if chart_files:
                    summary_message += "\n\n📈 생성된 차트:"
                    for i, file in enumerate(chart_files[:5], 1):  # 최대 5개만 표시
                        filename = Path(file).name
                        summary_message += f"\n  {i}. {filename}"
                    
                    if len(chart_files) > 5:
                        summary_message += f"\n  ... 외 {len(chart_files) - 5}개"
                
                await self.telegram.notify_system_status(summary_message)
                self.logger.info(f"🎯 장 마감 후 차트 생성 완료: {success_count}개 성공")
            else:
                error_message = f"⚠️ 장 마감 후 차트 생성 실패\n선정 종목: {len(selected_stocks)}개"
                await self.telegram.notify_system_status(error_message)
                self.logger.warning("⚠️ 장 마감 후 차트 생성 결과 없음")
            
        except Exception as e:
            self.logger.error(f"❌ 장 마감 후 차트 생성 오류: {e}")
            await self.telegram.notify_error("Post Market Chart Generation", e)

    async def shutdown(self):
        """시스템 종료"""
        try:
            self.logger.info("🛑 시스템 종료 시작")
            
            # 데이터 수집 중단
            self.data_collector.stop_collection()
            
            # 주문 모니터링 중단
            self.order_manager.stop_monitoring()
            
            # 텔레그램 통합 종료
            await self.telegram.shutdown()
            
            # API 매니저 종료
            self.api_manager.shutdown()
            
            # PID 파일 삭제
            if self.pid_file.exists():
                self.pid_file.unlink()
                self.logger.info("PID 파일 삭제 완료")
            
            self.logger.info("✅ 시스템 종료 완료")
            
        except Exception as e:
            self.logger.error(f"❌ 시스템 종료 중 오류: {e}")


async def main():
    """메인 함수"""
    bot = DayTradingBot()
    
    # 시스템 초기화
    if not await bot.initialize():
        sys.exit(1)
    
    # 일일 거래 사이클 실행
    await bot.run_daily_cycle()


if __name__ == "__main__":
    try:
        # 로그 디렉토리 생성
        Path("logs").mkdir(exist_ok=True)
        
        # 메인 실행
        asyncio.run(main())
        
    except KeyboardInterrupt:
        print("\n사용자에 의해 중단되었습니다.")
    except Exception as e:
        print(f"시스템 오류: {e}")
        sys.exit(1)