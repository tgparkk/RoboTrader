"""
KIS API 차트 조회 관련 함수 (일별분봉조회)
"""
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple, Any
from utils.logger import setup_logger
from . import kis_auth as kis
from utils.korean_time import now_kst

logger = setup_logger(__name__)


def get_inquire_time_dailychartprice(div_code: str = "J", stock_code: str = "", 
                                   input_hour: str = "", input_date: str = "",
                                   past_data_yn: str = "Y", fake_tick_yn: str = "",
                                   tr_cont: str = "") -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    주식일별분봉조회 API (TR: FHKST03010230)
    
    실전계좌의 경우, 한 번의 호출에 최대 120건까지 확인 가능하며,
    FID_INPUT_DATE_1, FID_INPUT_HOUR_1 이용하여 과거일자 분봉조회 가능합니다.
    
    Args:
        div_code: 조건 시장 분류 코드 (J:KRX, NX:NXT, UN:통합)
        stock_code: 입력 종목코드 (ex: 005930 삼성전자)
        input_hour: 입력 시간1 (ex: 13시 130000)
        input_date: 입력 날짜1 (ex: 20241023)
        past_data_yn: 과거 데이터 포함 여부 (Y/N)
        fake_tick_yn: 허봉 포함 여부 (공백 필수 입력)
        tr_cont: 연속 거래 여부 (공백: 초기 조회, N: 다음 데이터 조회)
        
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (종목요약정보, 분봉데이터)
        - output1: 종목 요약 정보 (전일대비, 누적거래량 등)
        - output2: 분봉 데이터 배열 (시간별 OHLCV 데이터)
    """
    url = '/uapi/domestic-stock/v1/quotations/inquire-time-dailychartprice'
    tr_id = "FHKST03010230"  # 주식일별분봉조회
    
    # 기본값 설정
    if not input_date:
        input_date = now_kst().strftime("%Y%m%d")
    if not input_hour:
        input_hour = "160000"  # 장 마감 시간
    if not fake_tick_yn:
        fake_tick_yn = ""  # 공백 필수 입력
    
    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,      # 조건 시장 분류 코드
        "FID_INPUT_ISCD": stock_code,            # 입력 종목코드
        "FID_INPUT_HOUR_1": input_hour,          # 입력 시간1
        "FID_INPUT_DATE_1": input_date,          # 입력 날짜1
        "FID_PW_DATA_INCU_YN": past_data_yn,     # 과거 데이터 포함 여부
        "FID_FAKE_TICK_INCU_YN": fake_tick_yn    # 허봉 포함 여부
    }
    
    try:
        logger.debug(f"📊 주식일별분봉조회: {stock_code}, 날짜={input_date}, 시간={input_hour}")
        res = kis._url_fetch(url, tr_id, tr_cont, params)
        
        if res and res.isOK():
            body = res.getBody()
            
            # output1: 종목 요약 정보
            output1_data = getattr(body, 'output1', None)
            # output2: 분봉 데이터 배열
            output2_data = getattr(body, 'output2', [])
            
            # DataFrame 변환
            summary_df = pd.DataFrame([output1_data]) if output1_data else pd.DataFrame()
            chart_df = pd.DataFrame(output2_data) if output2_data else pd.DataFrame()
            
            if not chart_df.empty:
                # 데이터 타입 변환 및 정리
                chart_df = _process_chart_data(chart_df)
                
            logger.info(f"✅ {stock_code} 일별분봉조회 성공: {len(chart_df)}건")
            return summary_df, chart_df
            
        else:
            error_msg = res.getErrorMessage() if res else "Unknown error"
            logger.error(f"❌ {stock_code} 일별분봉조회 실패: {error_msg}")
            return None
            
    except Exception as e:
        logger.error(f"❌ {stock_code} 일별분봉조회 오류: {e}")
        return None


def get_recent_minute_data(stock_code: str, minutes: int = 30, 
                          past_data_yn: str = "Y") -> Optional[pd.DataFrame]:
    """
    최근 N분간의 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        minutes: 조회할 분 수 (기본 30분)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        pd.DataFrame: 분봉 데이터
    """
    try:
        current_time = now_kst()
        current_date = current_time.strftime("%Y%m%d")
        current_hour = current_time.strftime("%H%M%S")
        
        result = get_inquire_time_dailychartprice(
            stock_code=stock_code,
            input_date=current_date,
            input_hour=current_hour,
            past_data_yn=past_data_yn
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 분봉 데이터 없음")
            return pd.DataFrame()
        
        # 최근 N분 데이터만 필터링
        if len(chart_df) > minutes:
            chart_df = chart_df.tail(minutes)
        
        logger.debug(f"✅ {stock_code} 최근 {len(chart_df)}분 분봉 데이터 조회 완료")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 최근 분봉 데이터 조회 오류: {e}")
        return None


def get_historical_minute_data(stock_code: str, target_date: str,
                              end_hour: str = "160000", 
                              past_data_yn: str = "Y") -> Optional[pd.DataFrame]:
    """
    특정 날짜의 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        target_date: 조회 날짜 (YYYYMMDD)
        end_hour: 종료 시간 (HHMMSS, 기본값: 장마감 160000)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        pd.DataFrame: 해당 날짜의 분봉 데이터
    """
    try:
        result = get_inquire_time_dailychartprice(
            stock_code=stock_code,
            input_date=target_date,
            input_hour=end_hour,
            past_data_yn=past_data_yn
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} {target_date} 분봉 데이터 없음")
            return pd.DataFrame()
        
        logger.debug(f"✅ {stock_code} {target_date} 분봉 데이터 조회 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} {target_date} 분봉 데이터 조회 오류: {e}")
        return None


def _process_chart_data(chart_df: pd.DataFrame) -> pd.DataFrame:
    """
    분봉 차트 데이터 전처리
    
    Args:
        chart_df: 원본 차트 데이터
        
    Returns:
        pd.DataFrame: 전처리된 차트 데이터
    """
    try:
        if chart_df.empty:
            return chart_df
        
        # 숫자 컬럼들의 데이터 타입 변환
        numeric_columns = [
            'stck_prpr',      # 주식 현재가
            'stck_oprc',      # 주식 시가
            'stck_hgpr',      # 주식 최고가
            'stck_lwpr',      # 주식 최저가
            'cntg_vol',       # 체결 거래량
            'acml_tr_pbmn'    # 누적 거래 대금
        ]
        
        def safe_numeric_convert(value, default=0):
            """안전한 숫자 변환"""
            if pd.isna(value) or value == '':
                return default
            try:
                return float(str(value).replace(',', ''))
            except (ValueError, TypeError):
                return default
        
        # 숫자 컬럼 변환
        for col in numeric_columns:
            if col in chart_df.columns:
                chart_df[col] = chart_df[col].apply(safe_numeric_convert)
        
        # 날짜/시간 컬럼 처리
        if 'stck_bsop_date' in chart_df.columns and 'stck_cntg_hour' in chart_df.columns:
            # 날짜와 시간을 결합하여 datetime 컬럼 생성
            chart_df['datetime'] = pd.to_datetime(
                chart_df['stck_bsop_date'].astype(str) + ' ' + 
                chart_df['stck_cntg_hour'].astype(str).str.zfill(6),
                format='%Y%m%d %H%M%S',
                errors='coerce'
            )
        
        # 컬럼명 표준화 (선택사항)
        column_mapping = {
            'stck_bsop_date': 'date',
            'stck_cntg_hour': 'time',
            'stck_prpr': 'close',
            'stck_oprc': 'open',
            'stck_hgpr': 'high',
            'stck_lwpr': 'low',
            'cntg_vol': 'volume',
            'acml_tr_pbmn': 'amount'
        }
        
        # 존재하는 컬럼만 리네임
        existing_columns = {k: v for k, v in column_mapping.items() if k in chart_df.columns}
        if existing_columns:
            chart_df = chart_df.rename(columns=existing_columns)
        
        # 시간순 정렬 (오래된 것부터)
        if 'datetime' in chart_df.columns:
            chart_df = chart_df.sort_values('datetime').reset_index(drop=True)
        elif 'date' in chart_df.columns and 'time' in chart_df.columns:
            chart_df = chart_df.sort_values(['date', 'time']).reset_index(drop=True)
        
        logger.debug(f"📊 분봉 데이터 전처리 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ 분봉 데이터 전처리 오류: {e}")
        return chart_df  # 오류 시 원본 반환


def get_stock_minute_summary(stock_code: str, minutes: int = 30) -> Optional[Dict[str, Any]]:
    """
    종목의 최근 N분간 요약 정보 계산
    
    Args:
        stock_code: 종목코드
        minutes: 분석할 분 수
        
    Returns:
        Dict: 요약 정보
        {
            'stock_code': 종목코드,
            'period_minutes': 분석 기간(분),
            'data_count': 데이터 개수,
            'first_price': 시작가,
            'last_price': 종료가,
            'high_price': 최고가,
            'low_price': 최저가,
            'price_change': 가격 변화,
            'price_change_rate': 가격 변화율(%),
            'total_volume': 총 거래량,
            'avg_volume': 평균 거래량,
            'total_amount': 총 거래대금,
            'analysis_time': 분석 시간
        }
    """
    try:
        chart_df = get_recent_minute_data(stock_code, minutes)
        
        if chart_df is None or chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 분봉 데이터 없음")
            return None
        
        # 가격 정보 (표준화된 컬럼명 사용)
        if 'close' in chart_df.columns:
            prices = chart_df['close']
            first_price = float(prices.iloc[0]) if len(prices) > 0 else 0
            last_price = float(prices.iloc[-1]) if len(prices) > 0 else 0
        else:
            first_price = last_price = 0
        
        if 'high' in chart_df.columns:
            high_price = float(chart_df['high'].max())
        else:
            high_price = 0
            
        if 'low' in chart_df.columns:
            low_price = float(chart_df['low'].min())
        else:
            low_price = 0
        
        # 거래량 정보
        if 'volume' in chart_df.columns:
            total_volume = int(chart_df['volume'].sum())
            avg_volume = int(chart_df['volume'].mean()) if len(chart_df) > 0 else 0
        else:
            total_volume = avg_volume = 0
        
        # 거래대금 정보
        if 'amount' in chart_df.columns:
            total_amount = int(chart_df['amount'].sum())
        else:
            total_amount = 0
        
        # 가격 변화 계산
        price_change = last_price - first_price
        price_change_rate = (price_change / first_price * 100) if first_price > 0 else 0
        
        summary = {
            'stock_code': stock_code,
            'period_minutes': minutes,
            'data_count': len(chart_df),
            'first_price': first_price,
            'last_price': last_price,
            'high_price': high_price,
            'low_price': low_price,
            'price_change': price_change,
            'price_change_rate': round(price_change_rate, 2),
            'total_volume': total_volume,
            'avg_volume': avg_volume,
            'total_amount': total_amount,
            'analysis_time': now_kst().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        logger.debug(f"✅ {stock_code} {minutes}분 요약: "
                   f"가격변화 {price_change:+.0f}원({price_change_rate:+.2f}%), "
                   f"거래량 {total_volume:,}주")
        
        return summary
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 분봉 요약 계산 오류: {e}")
        return None


def get_inquire_time_itemchartprice(div_code: str = "J", stock_code: str = "", 
                                   input_hour: str = "", past_data_yn: str = "Y",
                                   etc_cls_code: str = "", tr_cont: str = "") -> Optional[Tuple[pd.DataFrame, pd.DataFrame]]:
    """
    주식당일분봉조회 API (TR: FHKST03010200)
    
    실전계좌/모의계좌의 경우, 한 번의 호출에 최대 30건까지 확인 가능합니다.
    당일 분봉 데이터만 제공됩니다. (전일자 분봉 미제공)
    
    주의사항:
    - FID_INPUT_HOUR_1에 미래일시 입력 시 현재가로 조회됩니다.
    - output2의 첫번째 배열의 체결량은 첫체결 발생 전까지 이전 분봉의 체결량이 표시됩니다.
    
    Args:
        div_code: 조건 시장 분류 코드 (J:KRX, NX:NXT, UN:통합)
        stock_code: 입력 종목코드 (ex: 005930 삼성전자)
        input_hour: 입력시간 (HHMMSS)
        past_data_yn: 과거 데이터 포함 여부 (Y/N)
        etc_cls_code: 기타 구분 코드
        tr_cont: 연속 거래 여부 (이 API는 연속조회 불가)
        
    Returns:
        Tuple[pd.DataFrame, pd.DataFrame]: (종목요약정보, 당일분봉데이터)
        - output1: 종목 요약 정보 (전일대비, 누적거래량 등)
        - output2: 당일 분봉 데이터 배열 (최대 30건)
    """
    url = '/uapi/domestic-stock/v1/quotations/inquire-time-itemchartprice'
    tr_id = "FHKST03010200"  # 주식당일분봉조회
    
    # 기본값 설정
    if not input_hour:
        input_hour = now_kst().strftime("%H%M%S")  # 현재 시간
    if not etc_cls_code:
        etc_cls_code = ""  # 기본값
    
    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,      # 조건 시장 분류 코드
        "FID_INPUT_ISCD": stock_code,            # 입력 종목코드
        "FID_INPUT_HOUR_1": input_hour,          # 입력시간
        "FID_PW_DATA_INCU_YN": past_data_yn,     # 과거 데이터 포함 여부
        "FID_ETC_CLS_CODE": etc_cls_code         # 기타 구분 코드
    }
    
    try:
        logger.debug(f"📊 주식당일분봉조회: {stock_code}, 시간={input_hour}")
        res = kis._url_fetch(url, tr_id, tr_cont, params)
        
        if res and res.isOK():
            body = res.getBody()
            
            # output1: 종목 요약 정보
            output1_data = getattr(body, 'output1', None)
            # output2: 당일 분봉 데이터 배열
            output2_data = getattr(body, 'output2', [])
            
            # DataFrame 변환
            summary_df = pd.DataFrame([output1_data]) if output1_data else pd.DataFrame()
            chart_df = pd.DataFrame(output2_data) if output2_data else pd.DataFrame()
            
            if not chart_df.empty:
                # 데이터 타입 변환 및 정리
                chart_df = _process_chart_data(chart_df)
                
            logger.info(f"✅ {stock_code} 당일분봉조회 성공: {len(chart_df)}건 (최대 30건)")
            return summary_df, chart_df
            
        else:
            error_msg = res.getErrorMessage() if res else "Unknown error"
            logger.error(f"❌ {stock_code} 당일분봉조회 실패: {error_msg}")
            return None
            
    except Exception as e:
        logger.error(f"❌ {stock_code} 당일분봉조회 오류: {e}")
        return None


def get_today_minute_data(stock_code: str, target_hour: str = "", 
                         past_data_yn: str = "Y") -> Optional[pd.DataFrame]:
    """
    오늘 특정 시간까지의 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        target_hour: 목표 시간 (HHMMSS, 기본값: 현재시간)
        past_data_yn: 과거 데이터 포함 여부
        
    Returns:
        pd.DataFrame: 당일 분봉 데이터 (최대 30건)
    """
    try:
        if not target_hour:
            target_hour = now_kst().strftime("%H%M%S")
        
        result = get_inquire_time_itemchartprice(
            stock_code=stock_code,
            input_hour=target_hour,
            past_data_yn=past_data_yn
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 당일 분봉 데이터 없음")
            return pd.DataFrame()
        
        logger.debug(f"✅ {stock_code} 당일 {target_hour}까지 분봉 데이터 조회 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 당일 분봉 데이터 조회 오류: {e}")
        return None


def get_realtime_minute_data(stock_code: str) -> Optional[pd.DataFrame]:
    """
    실시간 당일 분봉 데이터 조회 (편의 함수)
    
    Args:
        stock_code: 종목코드
        
    Returns:
        pd.DataFrame: 현재까지의 당일 분봉 데이터
    """
    try:
        current_time = now_kst().strftime("%H%M%S")
        
        result = get_inquire_time_itemchartprice(
            stock_code=stock_code,
            input_hour=current_time,
            past_data_yn="Y"
        )
        
        if result is None:
            return None
            
        summary_df, chart_df = result
        
        if chart_df.empty:
            logger.warning(f"⚠️ {stock_code} 실시간 분봉 데이터 없음")
            return pd.DataFrame()
        
        logger.debug(f"✅ {stock_code} 실시간 분봉 데이터 조회 완료: {len(chart_df)}건")
        return chart_df
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 실시간 분봉 데이터 조회 오류: {e}")
        return None



# 테스트 실행을 위한 예시 함수
if __name__ == "__main__":
    pass