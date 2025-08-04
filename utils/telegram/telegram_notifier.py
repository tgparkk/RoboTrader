"""
텔레그램 알림 서비스
"""
import asyncio
import json
from datetime import datetime
from typing import Optional, Dict, Any
from telegram import Bot, Update
from telegram.ext import Application, CommandHandler, ContextTypes
from telegram.error import TelegramError
from telegram.request import HTTPXRequest

from utils.logger import setup_logger


class TelegramNotifier:
    """텔레그램 알림 서비스"""
    
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.logger = setup_logger(__name__)
        
        # 연결 풀 설정으로 타임아웃 문제 해결
        request = HTTPXRequest(
            connection_pool_size=8,
            connect_timeout=30.0,
            read_timeout=30.0,
            write_timeout=30.0,
            pool_timeout=30.0
        )
        self.bot = Bot(token=bot_token, request=request)
        self.application = None
        self.is_initialized = False
        self.is_polling = False
        
        # 메시지 형식 템플릿
        self.templates = {
            'system_start': "🚀 *거래 시스템 시작*\n시간: {time}\n상태: 초기화 완료",
            'system_stop': "🛑 *거래 시스템 종료*\n시간: {time}\n상태: 정상 종료",
            'order_placed': "📝 *주문 실행*\n종목: {stock_name}({stock_code})\n구분: {order_type}\n수량: {quantity:,}주\n가격: {price:,}원\n주문ID: {order_id}",
            'order_filled': "✅ *주문 체결*\n종목: {stock_name}({stock_code})\n구분: {order_type}\n수량: {quantity:,}주\n가격: {price:,}원\n손익: {pnl:+,.0f}원",
            'order_cancelled': "❌ *주문 취소*\n종목: {stock_name}({stock_code})\n구분: {order_type}\n이유: {reason}",
            'signal_detected': "🔥 *매매 신호*\n종목: {stock_name}({stock_code})\n신호: {signal_type}\n가격: {price:,}원\n근거: {reason}",
            'position_update': "📊 *포지션 현황*\n보유: {position_count}종목\n평가: {total_value:,}원\n손익: {total_pnl:+,.0f}원 ({pnl_rate:+.2f}%)",
            'system_status': "📡 *시스템 상태*\n시간: {time}\n시장: {market_status}\n미체결: {pending_orders}건\n완료: {completed_orders}건\n데이터: 정상 수집",
            'error_alert': "⚠️ *시스템 오류*\n시간: {time}\n모듈: {module}\n오류: {error}",
            'daily_summary': "📈 *일일 거래 요약*\n날짜: {date}\n총 거래: {total_trades}회\n수익률: {return_rate:+.2f}%\n손익: {total_pnl:+,.0f}원"
        }
    
    async def initialize(self) -> bool:
        """텔레그램 봇 초기화"""
        try:
            self.logger.info("텔레그램 봇 초기화 시작...")
            
            # 봇 연결 테스트
            me = await self.bot.get_me()
            self.logger.info(f"봇 연결 성공: @{me.username}")
            
            # 기존 웹훅 제거 (다중 인스턴스 충돌 방지) - 타임아웃 추가
            try:
                await asyncio.wait_for(
                    self.bot.delete_webhook(drop_pending_updates=True),
                    timeout=10.0  # 10초 타임아웃
                )
                self.logger.info("기존 웹훅 정리 완료")
            except asyncio.TimeoutError:
                self.logger.warning("웹훅 정리 타임아웃 (무시하고 계속)")
            except Exception as webhook_error:
                self.logger.warning(f"웹훅 정리 중 오류 (무시 가능): {webhook_error}")
            
            # Application 생성 - 동일한 request 설정 사용
            request = HTTPXRequest(
                connection_pool_size=8,
                connect_timeout=30.0,
                read_timeout=30.0,
                write_timeout=30.0,
                pool_timeout=30.0
            )
            self.application = Application.builder().token(self.bot_token).request(request).build()
            
            # 명령어 핸들러 등록
            self._register_commands()
            
            self.is_initialized = True
            self.logger.info("✅ 텔레그램 봇 초기화 완료")
            
            # 초기화 메시지 전송
            await self.send_system_start()
            
            return True
            
        except Exception as e:
            self.logger.error(f"❌ 텔레그램 봇 초기화 실패: {e}")
            return False
    
    def _register_commands(self):
        """명령어 핸들러 등록"""
        handlers = [
            CommandHandler("status", self._cmd_status),
            CommandHandler("positions", self._cmd_positions),
            CommandHandler("orders", self._cmd_orders),
            CommandHandler("virtual", self._cmd_virtual_stats),
            CommandHandler("help", self._cmd_help),
            CommandHandler("stop", self._cmd_stop),
        ]
        
        for handler in handlers:
            self.application.add_handler(handler)
    
    async def start_polling(self):
        """봇 폴링 시작 (명령어 수신)"""
        if not self.is_initialized:
            self.logger.error("봇이 초기화되지 않았습니다")
            return
        
        if self.is_polling:
            self.logger.warning("이미 폴링이 실행 중입니다")
            return
        
        try:
            self.logger.info("텔레그램 봇 폴링 시작")
            self.is_polling = True
            
            # 웹훅과 대기 중인 업데이트 완전 정리
            try:
                await self.bot.delete_webhook(drop_pending_updates=True)
                # 잠시 대기하여 기존 연결이 완전히 정리되도록 함
                await asyncio.sleep(2)
            except Exception as e:
                self.logger.warning(f"웹훅 정리 중 오류 (무시 가능): {e}")
            
            await self.application.initialize()
            await self.application.start()
            
            # conflict 오류 방지를 위한 설정
            await self.application.updater.start_polling(
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
            )
            
            # 폴링이 계속 실행되도록 대기
            while self.is_polling:
                await asyncio.sleep(1)
                
        except Exception as e:
            # Conflict 오류인 경우 특별 처리
            if "terminated by other getUpdates request" in str(e) or "Conflict" in str(e):
                self.logger.error("다른 봇 인스턴스가 실행 중입니다. 기존 프로세스를 종료해주세요.")
                raise RuntimeError("텔레그램 봇 중복 실행 감지 - 기존 프로세스를 먼저 종료하세요")
            else:
                self.logger.error(f"봇 폴링 오류: {e}")
        finally:
            self.is_polling = False
            try:
                if self.application and hasattr(self.application, 'updater') and self.application.updater.running:
                    await self.application.updater.stop()
                if self.application:
                    await self.application.stop()
                    await self.application.shutdown()
            except Exception as shutdown_error:
                self.logger.error(f"봇 종료 중 오류: {shutdown_error}")
    
    async def send_message(self, message: str, parse_mode: str = "Markdown") -> bool:
        """메시지 전송"""
        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode=parse_mode
            )
            return True
        except TelegramError as e:
            self.logger.error(f"텔레그램 메시지 전송 실패: {e}")
            
            # 마크다운 파싱 오류 시 일반 텍스트로 재시도
            if "parse entities" in str(e).lower() or "can't parse" in str(e).lower():
                try:
                    self.logger.info("마크다운 파싱 오류 - 일반 텍스트로 재전송 시도")
                    # 마크다운 문법 제거
                    plain_message = message.replace('*', '').replace('_', '').replace('`', '')
                    await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=plain_message,
                        parse_mode=None
                    )
                    return True
                except TelegramError as retry_error:
                    self.logger.error(f"일반 텍스트 재전송도 실패: {retry_error}")
            
            return False
    
    # 시스템 이벤트 알림 메서드들
    async def send_system_start(self):
        """시스템 시작 알림"""
        message = self.templates['system_start'].format(
            time=datetime.now().strftime('%H:%M:%S')
        )
        await self.send_message(message)
    
    async def send_system_stop(self):
        """시스템 종료 알림"""
        message = self.templates['system_stop'].format(
            time=datetime.now().strftime('%H:%M:%S')
        )
        await self.send_message(message)
    
    async def send_order_placed(self, stock_code: str, stock_name: str, order_type: str, 
                              quantity: int, price: float, order_id: str):
        """주문 실행 알림"""
        message = self.templates['order_placed'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="매수" if order_type.lower() == "buy" else "매도",
            quantity=quantity,
            price=price,
            order_id=order_id
        )
        await self.send_message(message)
    
    async def send_order_filled(self, stock_code: str, stock_name: str, order_type: str,
                              quantity: int, price: float, pnl: float = 0):
        """주문 체결 알림"""
        message = self.templates['order_filled'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="매수" if order_type.lower() == "buy" else "매도",
            quantity=quantity,
            price=price,
            pnl=pnl
        )
        await self.send_message(message)
    
    async def send_order_cancelled(self, stock_code: str, stock_name: str, 
                                 order_type: str, reason: str):
        """주문 취소 알림"""
        message = self.templates['order_cancelled'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            order_type="매수" if order_type.lower() == "buy" else "매도",
            reason=reason
        )
        await self.send_message(message)
    
    async def send_signal_detected(self, stock_code: str, stock_name: str,
                                 signal_type: str, price: float, reason: str):
        """매매 신호 알림"""
        message = self.templates['signal_detected'].format(
            stock_code=stock_code,
            stock_name=stock_name,
            signal_type=signal_type,
            price=price,
            reason=reason
        )
        await self.send_message(message)
    
    async def send_position_update(self, position_count: int, total_value: float,
                                 total_pnl: float, pnl_rate: float):
        """포지션 현황 알림"""
        message = self.templates['position_update'].format(
            position_count=position_count,
            total_value=total_value,
            total_pnl=total_pnl,
            pnl_rate=pnl_rate
        )
        await self.send_message(message)
    
    async def send_system_status(self, market_status: str, pending_orders: int, 
                               completed_orders: int):
        """시스템 상태 알림"""
        message = self.templates['system_status'].format(
            time=datetime.now().strftime('%H:%M:%S'),
            market_status=market_status,
            pending_orders=pending_orders,
            completed_orders=completed_orders
        )
        await self.send_message(message)
    
    async def send_error_alert(self, module: str, error: str):
        """오류 알림"""
        message = self.templates['error_alert'].format(
            time=datetime.now().strftime('%H:%M:%S'),
            module=module,
            error=str(error)[:100]  # 오류 메시지 길이 제한
        )
        await self.send_message(message)
    
    async def send_daily_summary(self, date: str, total_trades: int, 
                               return_rate: float, total_pnl: float):
        """일일 거래 요약"""
        message = self.templates['daily_summary'].format(
            date=date,
            total_trades=total_trades,
            return_rate=return_rate,
            total_pnl=total_pnl
        )
        await self.send_message(message)
    
    # 명령어 핸들러들
    async def _cmd_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """상태 조회 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        # TODO: 실제 시스템 상태 조회 로직 구현
        status_message = "📊 *시스템 상태*\n\n⏰ 시간: {}\n📈 시장: 장중\n🔄 상태: 정상 동작\n📊 데이터: 수집 중".format(
            datetime.now().strftime('%H:%M:%S')
        )
        
        await update.message.reply_text(status_message, parse_mode="Markdown")
    
    async def _cmd_positions(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """포지션 조회 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        # TODO: 실제 포지션 조회 로직 구현
        positions_message = "💼 *보유 포지션*\n\n현재 보유 중인 포지션이 없습니다."
        
        await update.message.reply_text(positions_message, parse_mode="Markdown")
    
    async def _cmd_orders(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """주문 현황 조회 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        # TODO: 실제 주문 현황 조회 로직 구현
        orders_message = "📋 *주문 현황*\n\n미체결 주문: 0건\n완료된 주문: 0건"
        
        await update.message.reply_text(orders_message, parse_mode="Markdown")
    
    async def _cmd_virtual_stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """가상 매매 통계 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        try:
            # TelegramIntegration을 통해 DB 접근
            if hasattr(self, 'trading_bot_ref') and self.trading_bot_ref:
                db_manager = self.trading_bot_ref.db_manager
                
                # 가상 매매 통계 조회
                stats = db_manager.get_virtual_trading_stats(days=7)
                open_positions = db_manager.get_virtual_open_positions()
                
                # 통계 메시지 생성
                message = f"""📊 *가상 매매 통계 (7일)*

💰 *전체 성과*
• 총 거래: {stats.get('total_trades', 0)}건
• 미체결 포지션: {stats.get('open_positions', 0)}건
• 승률: {stats.get('win_rate', 0):.1f}%
• 총 손익: {stats.get('total_profit', 0):+,.0f}원
• 평균 수익률: {stats.get('avg_profit_rate', 0):+.2f}%

📈 *수익률 범위*
• 최대 수익: {stats.get('max_profit', 0):+,.0f}원
• 최대 손실: {stats.get('max_loss', 0):+,.0f}원

🎯 *전략별 성과*"""
                
                # 전략별 통계 추가
                for strategy, strategy_stats in stats.get('strategies', {}).items():
                    message += f"""
*{strategy}*
• 거래: {strategy_stats.get('total_trades', 0)}건
• 승률: {strategy_stats.get('win_rate', 0):.1f}%
• 손익: {strategy_stats.get('total_profit', 0):+,.0f}원
• 평균: {strategy_stats.get('avg_profit_rate', 0):+.2f}%"""
                
                # 미체결 포지션 정보
                if not open_positions.empty:
                    message += f"\n\n📋 *미체결 포지션 ({len(open_positions)}건)*"
                    for _, pos in open_positions.head(5).iterrows():  # 최대 5개만 표시
                        buy_time_str = pos['buy_time'].strftime('%m/%d %H:%M') if hasattr(pos['buy_time'], 'strftime') else str(pos['buy_time'])[:16]
                        message += f"\n• {pos['stock_name']}({pos['stock_code']}) {pos['quantity']}주 @{pos['buy_price']:,.0f}원 ({buy_time_str})"
                    
                    if len(open_positions) > 5:
                        message += f"\n• ... 외 {len(open_positions) - 5}건"
                
                await update.message.reply_text(message, parse_mode="Markdown")
                
            else:
                await update.message.reply_text("⚠️ 시스템에 연결할 수 없습니다.")
                
        except Exception as e:
            self.logger.error(f"가상 매매 통계 조회 오류: {e}")
            await update.message.reply_text(f"⚠️ 통계 조회 중 오류가 발생했습니다: {str(e)}")
    
    async def _cmd_help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """도움말 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        help_message = """
🤖 *거래 봇 명령어*

/status - 시스템 상태 조회
/positions - 보유 포지션 조회  
/orders - 주문 현황 조회
/virtual - 가상 매매 통계 조회
/help - 도움말 표시
/stop - 시스템 종료

📱 실시간 알림:
• 주문 실행/체결 시
• 매매 신호 감지 시
• 시스템 오류 발생 시
• 가상 매매 실행 시
"""
        
        await update.message.reply_text(help_message, parse_mode="Markdown")
    
    async def _cmd_stop(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """시스템 종료 명령어"""
        if str(update.effective_chat.id) != self.chat_id:
            return
        
        await update.message.reply_text("⚠️ 시스템 종료 명령을 받았습니다. 안전하게 종료 중...")
        
        # TODO: 실제 시스템 종료 로직 구현
        # 이 부분은 메인 시스템과 연동 필요
    
    async def shutdown(self):
        """텔레그램 봇 종료"""
        try:
            self.logger.info("텔레그램 봇 종료 시작")
            
            # 폴링 중단
            self.is_polling = False
            
            # 시스템 종료 메시지 전송
            try:
                await self.send_system_stop()
            except Exception as msg_error:
                self.logger.error(f"종료 메시지 전송 실패: {msg_error}")
            
            # Application 종료
            if self.application:
                try:
                    if hasattr(self.application, 'updater') and self.application.updater.running:
                        await self.application.updater.stop()
                    await self.application.stop()
                    await self.application.shutdown()
                except Exception as app_error:
                    self.logger.error(f"Application 종료 중 오류: {app_error}")
            
            self.logger.info("텔레그램 봇 종료 완료")
            
        except Exception as e:
            self.logger.error(f"텔레그램 봇 종료 중 오류: {e}")


