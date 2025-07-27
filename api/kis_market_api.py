"""
KIS API 시세 조회 관련 함수 (공식 문서 기반)
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

def get_inquire_price(div_code: str = "J", itm_no: str = "", tr_cont: str = "",
                      FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """주식현재가 시세"""
    url = '/uapi/domestic-stock/v1/quotations/inquire-price'
    tr_id = "FHKST01010100"  # 주식현재가 시세

    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,     # J:주식/ETF/ETN, W:ELW
        "FID_INPUT_ISCD": itm_no                # 종목번호(6자리)
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        current_data = pd.DataFrame(getattr(body, 'output', []), index=[0])
        return current_data
    else:
        logger.error("주식현재가 조회 실패")
        return None


def get_inquire_ccnl(div_code: str = "J", itm_no: str = "", tr_cont: str = "",
                     FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """주식현재가 체결 (최근 30건)"""
    url = '/uapi/domestic-stock/v1/quotations/inquire-ccnl'
    tr_id = "FHKST01010300"  # 주식현재가 체결

    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,     # J:주식/ETF/ETN, W:ELW
        "FID_INPUT_ISCD": itm_no                # 종목번호(6자리)
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        current_data = pd.DataFrame(getattr(body, 'output', []))
        return current_data
    else:
        logger.error("주식현재가 체결 조회 실패")
        return None


def get_inquire_daily_price(div_code: str = "J", itm_no: str = "", period_code: str = "D",
                            adj_prc_code: str = "1", tr_cont: str = "",
                            FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """주식현재가 일자별 (최근 30일)"""
    url = '/uapi/domestic-stock/v1/quotations/inquire-daily-price'
    tr_id = "FHKST01010400"  # 주식현재가 일자별

    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,     # J:주식/ETF/ETN, W:ELW
        "FID_INPUT_ISCD": itm_no,               # 종목번호(6자리)
        "FID_PERIOD_DIV_CODE": period_code,     # D:일, W:주, M:월
        "FID_ORG_ADJ_PRC": adj_prc_code         # 0:수정주가반영, 1:수정주가미반영
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        current_data = pd.DataFrame(getattr(body, 'output', []))
        return current_data
    else:
        logger.error("주식현재가 일자별 조회 실패")
        return None



def get_inquire_daily_itemchartprice(output_dv: str = "1", div_code: str = "J", itm_no: str = "",
                                     inqr_strt_dt: Optional[str] = None, inqr_end_dt: Optional[str] = None,
                                     period_code: str = "D", adj_prc: str = "1", tr_cont: str = "",
                                     FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """국내주식기간별시세(일/주/월/년)"""
    url = '/uapi/domestic-stock/v1/quotations/inquire-daily-itemchartprice'
    tr_id = "FHKST03010100"  # 국내주식기간별시세

    if inqr_strt_dt is None:
        inqr_strt_dt = (now_kst() - timedelta(days=50)).strftime("%Y%m%d")
    if inqr_end_dt is None:
        inqr_end_dt = now_kst().strftime("%Y%m%d")

    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,     # J:주식/ETF/ETN, W:ELW
        "FID_INPUT_ISCD": itm_no,               # 종목번호(6자리)
        "FID_INPUT_DATE_1": inqr_strt_dt,       # 조회시작일자
        "FID_INPUT_DATE_2": inqr_end_dt,        # 조회종료일자
        "FID_PERIOD_DIV_CODE": period_code,     # D:일봉, W:주봉, M:월봉, Y:년봉
        "FID_ORG_ADJ_PRC": adj_prc              # 0:수정주가, 1:원주가
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        if output_dv == "1":
            current_data = pd.DataFrame(getattr(body, 'output1', []), index=[0])
        else:
            current_data = pd.DataFrame(getattr(body, 'output2', []))
        return current_data
    else:
        logger.error("국내주식기간별시세 조회 실패")
        return None


def get_inquire_daily_price_2(div_code: str = "J", itm_no: str = "", tr_cont: str = "",
                               FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """주식현재가 시세2"""
    url = '/uapi/domestic-stock/v1/quotations/inquire-price-2'
    tr_id = "FHPST01010000"  # 주식현재가 시세2

    params = {
        "FID_COND_MRKT_DIV_CODE": div_code,     # J:주식/ETF/ETN, W:ELW
        "FID_INPUT_ISCD": itm_no                # 종목번호(6자리)
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        body = res.getBody()
        current_data = pd.DataFrame(getattr(body, 'output', []), index=[0])
        return current_data
    else:
        logger.error("주식현재가 시세2 조회 실패")
        return None


def get_volume_rank(fid_cond_mrkt_div_code: str = "J",
                   fid_cond_scr_div_code: str = "20171",
                   fid_input_iscd: str = "0000",
                   fid_div_cls_code: str = "1",
                   fid_blng_cls_code: str = "0",
                   fid_trgt_cls_code: str = "111111111",
                   fid_trgt_exls_cls_code: str = "0000000000",
                   fid_input_price_1: str = "",
                   fid_input_price_2: str = "",
                   fid_vol_cnt: str = "",
                   fid_input_date_1: str = "",
                   tr_cont: str = "") -> Optional[pd.DataFrame]:
    """
    거래량순위 조회 (TR: FHPST01710000)

    Args:
        fid_cond_mrkt_div_code: 조건 시장 분류 코드 (J: 주식)
        fid_cond_scr_div_code: 조건 화면 분류 코드 (20171)
        fid_input_iscd: 입력 종목코드 (0000:전체, 0001:거래소, 1001:코스닥)
        fid_div_cls_code: 분류 구분 코드 (0:전체, 1:보통주, 2:우선주)
        fid_blng_cls_code: 소속 구분 코드 (0:평균거래량, 1:거래증가율, 2:평균거래회전율, 3:거래금액순, 4:평균거래금액회전율)
        fid_trgt_cls_code: 대상 구분 코드 (9자리, 111111111:모든 증거금)
        fid_trgt_exls_cls_code: 대상 제외 구분 코드 (10자리, 0000000000:모든 종목 포함)
        fid_input_price_1: 입력 가격1 (가격 ~)
        fid_input_price_2: 입력 가격2 (~ 가격)
        fid_vol_cnt: 거래량 수 (거래량 ~)
        fid_input_date_1: 입력 날짜1 (공란 입력)
        tr_cont: 연속 거래 여부

    Returns:
        거래량순위 종목 데이터 (최대 30건)
    """
    url = '/uapi/domestic-stock/v1/quotations/volume-rank'
    tr_id = "FHPST01710000"  # 거래량순위

    params = {
        "FID_COND_MRKT_DIV_CODE": fid_cond_mrkt_div_code,
        "FID_COND_SCR_DIV_CODE": fid_cond_scr_div_code,
        "FID_INPUT_ISCD": fid_input_iscd,
        "FID_DIV_CLS_CODE": fid_div_cls_code,
        "FID_BLNG_CLS_CODE": fid_blng_cls_code,
        "FID_TRGT_CLS_CODE": fid_trgt_cls_code,
        "FID_TRGT_EXLS_CLS_CODE": fid_trgt_exls_cls_code,
        "FID_INPUT_PRICE_1": fid_input_price_1,
        "FID_INPUT_PRICE_2": fid_input_price_2,
        "FID_VOL_CNT": fid_vol_cnt,
        "FID_INPUT_DATE_1": fid_input_date_1
    }

    try:
        res = kis._url_fetch(url, tr_id, tr_cont, params)

        if res and res.isOK():
            body = res.getBody()
            output_data = getattr(body, 'output', None) or getattr(body, 'Output', [])
            if output_data:
                current_data = pd.DataFrame(output_data)
                logger.info(f"거래량순위 조회 성공: {len(current_data)}건")
                return current_data
            else:
                logger.warning("거래량순위 조회: 데이터 없음")
                return pd.DataFrame()
        else:
            logger.error("거래량순위 조회 실패")
            return None
    except Exception as e:
        logger.error(f"거래량순위 조회 오류: {e}")
        return None


def get_fluctuation_rank(fid_cond_mrkt_div_code: str = "J",
                        fid_cond_scr_div_code: str = "20170",
                        fid_input_iscd: str = "0000",
                        fid_rank_sort_cls_code: str = "0",
                        fid_input_cnt_1: str = "0",
                        fid_prc_cls_code: str = "0",
                        fid_input_price_1: str = "",
                        fid_input_price_2: str = "",
                        fid_vol_cnt: str = "",
                        fid_trgt_cls_code: str = "0",
                        fid_trgt_exls_cls_code: str = "0",
                        fid_div_cls_code: str = "0",
                        fid_rsfl_rate1: str = "",
                        fid_rsfl_rate2: str = "",
                        tr_cont: str = "") -> Optional[pd.DataFrame]:
    """
    등락률 순위 조회 (TR: FHPST01700000)

    Args:
        fid_cond_mrkt_div_code: 조건 시장 분류 코드 (J: 주식)
        fid_cond_scr_div_code: 조건 화면 분류 코드 (20170)
        fid_input_iscd: 입력 종목코드 (0000:전체, 0001:코스피, 1001:코스닥, 2001:코스피200)
        fid_rank_sort_cls_code: 순위 정렬 구분 코드 (0:상승율순, 1:하락율순, 2:시가대비상승율, 3:시가대비하락율, 4:변동율)
        fid_input_cnt_1: 입력 수1 (0:전체, 누적일수 입력)
        fid_prc_cls_code: 가격 구분 코드 (0:저가대비/고가대비, 1:종가대비)
        fid_input_price_1: 입력 가격1 (가격 ~)
        fid_input_price_2: 입력 가격2 (~ 가격)
        fid_vol_cnt: 거래량 수 (거래량 ~)
        fid_trgt_cls_code: 대상 구분 코드 (0:전체)
        fid_trgt_exls_cls_code: 대상 제외 구분 코드 (0:전체)
        fid_div_cls_code: 분류 구분 코드 (0:전체)
        fid_rsfl_rate1: 등락 비율1 (비율 ~)
        fid_rsfl_rate2: 등락 비율2 (~ 비율)
        tr_cont: 연속 거래 여부

    Returns:
        등락률 순위 종목 데이터 (최대 30건)
    """
    url = '/uapi/domestic-stock/v1/ranking/fluctuation'
    tr_id = "FHPST01700000"  # 등락률 순위

    # 🆕 등락률 범위 자동 설정 로직
    if fid_rsfl_rate1 and not fid_rsfl_rate2:
        # fid_rsfl_rate1만 있는 경우 상한을 자동 설정
        try:
            min_rate = float(fid_rsfl_rate1)
            if fid_rank_sort_cls_code == "0":  # 상승률순
                fid_rsfl_rate2 = "30.0"  # 최대 30% 상승까지
            else:  # 하락률순
                fid_rsfl_rate2 = "0.0"   # 최대 0%까지 (하락)
            logger.debug(f"📊 등락률 범위 자동 설정: {fid_rsfl_rate1}% ~ {fid_rsfl_rate2}%")
        except ValueError:
            # 변환 실패시 기본값 사용
            fid_rsfl_rate2 = "30.0" if fid_rank_sort_cls_code == "0" else "0.0"
    elif not fid_rsfl_rate1 and not fid_rsfl_rate2:
        # 둘 다 없는 경우 전체 범위
        fid_rsfl_rate1 = ""
        fid_rsfl_rate2 = ""

    params = {
        "fid_rsfl_rate2": fid_rsfl_rate2,
        "fid_cond_mrkt_div_code": fid_cond_mrkt_div_code,
        "fid_cond_scr_div_code": fid_cond_scr_div_code,
        "fid_input_iscd": fid_input_iscd,
        "fid_rank_sort_cls_code": fid_rank_sort_cls_code,
        "fid_input_cnt_1": fid_input_cnt_1,
        "fid_prc_cls_code": fid_prc_cls_code,
        "fid_input_price_1": fid_input_price_1,
        "fid_input_price_2": fid_input_price_2,
        "fid_vol_cnt": fid_vol_cnt,
        "fid_trgt_cls_code": fid_trgt_cls_code,
        "fid_trgt_exls_cls_code": fid_trgt_exls_cls_code,
        "fid_div_cls_code": fid_div_cls_code,
        "fid_rsfl_rate1": fid_rsfl_rate1
    }

    try:
        # 🔧 시간대별 컨텍스트 정보 추가
        current_time = now_kst()
        time_context = f"현재시간:{current_time.strftime('%H:%M:%S')}"
        is_market_open = 9 <= current_time.hour < 16
        time_context += f" 장운영:{'Y' if is_market_open else 'N'}"

        #logger.info(f"🔍 등락률순위 API 호출 - {time_context}")
        #logger.debug(f"📋 요청파라미터: 시장={fid_input_iscd}, 등락률={fid_rsfl_rate1}~{fid_rsfl_rate2}%, 정렬={fid_rank_sort_cls_code}")

        res = kis._url_fetch(url, tr_id, tr_cont, params)

        if res and res.isOK():
            try:
                # 🔧 응답 구조 상세 분석
                body = res.getBody()
                logger.debug(f"📄 응답 body 타입: {type(body)}")

                # rt_cd, msg_cd, msg1 확인
                rt_cd = getattr(body, 'rt_cd', 'Unknown')
                msg_cd = getattr(body, 'msg_cd', 'Unknown')
                msg1 = getattr(body, 'msg1', 'Unknown')

                #logger.info(f"📡 API 응답상태: rt_cd={rt_cd}, msg_cd={msg_cd}, msg1='{msg1}'")

                # output 확인
                if hasattr(body, 'output'):
                    output_data = getattr(body, 'output', [])
                    if output_data:
                        current_data = pd.DataFrame(output_data)
                        #logger.info(f"✅ 등락률 순위 조회 성공: {len(current_data)}건")
                        return current_data
                    else:
                        logger.warning(f"⚠️ 등락률 순위: output이 빈 리스트 (조건 만족 종목 없음)")
                        logger.info(f"🔍 필터조건: 시장={fid_input_iscd}, 등락률={fid_rsfl_rate1}~{fid_rsfl_rate2}%, 정렬={fid_rank_sort_cls_code}")
                        return pd.DataFrame()
                else:
                    logger.error(f"❌ 응답에 output 필드 없음 - body 구조: {dir(body)}")
                    return pd.DataFrame()

            except AttributeError as e:
                logger.error(f"❌ 등락률 순위 응답 구조 오류: {e}")
                logger.debug(f"응답 구조: {type(res.getBody())}")
                return pd.DataFrame()
        else:
            if res:
                rt_cd = getattr(res, 'rt_cd', getattr(res.getBody(), 'rt_cd', 'Unknown') if res.getBody() else 'Unknown')
                msg1 = getattr(res, 'msg1', getattr(res.getBody(), 'msg1', 'Unknown') if res.getBody() else 'Unknown')
                logger.error(f"❌ 등락률 순위 조회 실패 - rt_cd:{rt_cd}, msg:'{msg1}'")

                # 🔧 일반적인 오류 원인 안내
                if rt_cd == '1':
                    if '시간' in str(msg1) or 'time' in str(msg1).lower():
                        logger.warning("💡 힌트: 장 운영 시간 외에는 일부 API가 제한될 수 있습니다")
                    elif '조회' in str(msg1) or 'inquiry' in str(msg1).lower():
                        logger.warning("💡 힌트: API 호출 한도 초과이거나 조회 조건이 너무 제한적일 수 있습니다")

            else:
                logger.error("❌ 등락률 순위 조회 실패 - 응답 없음 (네트워크 또는 인증 문제)")
            return None
    except Exception as e:
        logger.error(f"❌ 등락률 순위 조회 예외: {e}")
        return None


def get_disparity_rank(fid_cond_mrkt_div_code: str = "J",
                      fid_cond_scr_div_code: str = "20178",
                      fid_input_iscd: str = "0000",
                      fid_rank_sort_cls_code: str = "0",
                      fid_hour_cls_code: str = "20",
                      fid_div_cls_code: str = "0",
                      fid_input_price_1: str = "",
                      fid_input_price_2: str = "",
                      fid_trgt_cls_code: str = "0",
                      fid_trgt_exls_cls_code: str = "0",
                      fid_vol_cnt: str = "",
                      tr_cont: str = "") -> Optional[pd.DataFrame]:
    """
    이격도 순위 조회 (TR: FHPST01780000)

    Args:
        fid_cond_mrkt_div_code: 조건 시장 분류 코드 (J: 주식)
        fid_cond_scr_div_code: 조건 화면 분류 코드 (20178)
        fid_input_iscd: 입력 종목코드 (0000:전체, 0001:거래소, 1001:코스닥, 2001:코스피200)
        fid_rank_sort_cls_code: 순위 정렬 구분 코드 (0:이격도상위순, 1:이격도하위순)
        fid_hour_cls_code: 시간 구분 코드 (5:이격도5, 10:이격도10, 20:이격도20, 60:이격도60, 120:이격도120)
        fid_div_cls_code: 분류 구분 코드 (0:전체, 1:관리종목, 2:투자주의, 3:투자경고, 4:투자위험예고, 5:투자위험, 6:보통주, 7:우선주)
        fid_input_price_1: 입력 가격1 (가격 ~)
        fid_input_price_2: 입력 가격2 (~ 가격)
        fid_trgt_cls_code: 대상 구분 코드 (0:전체)
        fid_trgt_exls_cls_code: 대상 제외 구분 코드 (0:전체)
        fid_vol_cnt: 거래량 수 (거래량 ~)
        tr_cont: 연속 거래 여부

    Returns:
        이격도 순위 종목 데이터 (최대 30건)
    """
    url = '/uapi/domestic-stock/v1/ranking/disparity'
    tr_id = "FHPST01780000"  # 이격도 순위

    params = {
        "FID_INPUT_PRICE_2": fid_input_price_2,          # 입력 가격2
        "FID_COND_MRKT_DIV_CODE": fid_cond_mrkt_div_code, # 조건 시장 분류 코드
        "FID_COND_SCR_DIV_CODE": fid_cond_scr_div_code,   # 조건 화면 분류 코드
        "FID_DIV_CLS_CODE": fid_div_cls_code,             # 분류 구분 코드
        "FID_RANK_SORT_CLS_CODE": fid_rank_sort_cls_code, # 순위 정렬 구분 코드
        "FID_HOUR_CLS_CODE": fid_hour_cls_code,           # 시간 구분 코드
        "FID_INPUT_ISCD": fid_input_iscd,                 # 입력 종목코드
        "FID_TRGT_CLS_CODE": fid_trgt_cls_code,           # 대상 구분 코드
        "FID_TRGT_EXLS_CLS_CODE": fid_trgt_exls_cls_code, # 대상 제외 구분 코드
        "FID_INPUT_PRICE_1": fid_input_price_1,           # 입력 가격1
        "FID_VOL_CNT": fid_vol_cnt                        # 거래량 수
    }

    try:
        logger.debug(f"🔍 이격도순위 API 호출 - 시장:{fid_input_iscd}, 이격도:{fid_hour_cls_code}일")
        logger.debug(f"📋 파라미터: {params}")

        res = kis._url_fetch(url, tr_id, tr_cont, params)

        if res and res.isOK():
            body = res.getBody()
            output_data = getattr(body, 'output', [])
            if output_data:
                current_data = pd.DataFrame(output_data)
                #logger.info(f"✅ 이격도 순위 조회 성공: {len(current_data)}건 (이격도{fid_hour_cls_code}일)")
                return current_data
            else:
                logger.warning("이격도 순위 조회: 데이터 없음")
                return pd.DataFrame()
        else:
            logger.error("이격도 순위 조회 실패")
            return None
    except Exception as e:
        logger.error(f"이격도 순위 조회 오류: {e}")
        return None


def get_quote_balance_rank(fid_cond_mrkt_div_code: str = "J",
                          fid_cond_scr_div_code: str = "20172",
                          fid_input_iscd: str = "0000",
                          fid_rank_sort_cls_code: str = "0",
                          fid_div_cls_code: str = "0",
                          fid_trgt_cls_code: str = "0",
                          fid_trgt_exls_cls_code: str = "0",
                          fid_input_price_1: str = "",
                          fid_input_price_2: str = "",
                          fid_vol_cnt: str = "",
                          tr_cont: str = "") -> Optional[pd.DataFrame]:
    """
    호가잔량 순위 조회 (TR: FHPST01720000)

    Args:
        fid_cond_mrkt_div_code: 조건 시장 분류 코드 (J: 주식)
        fid_cond_scr_div_code: 조건 화면 분류 코드 (20172)
        fid_input_iscd: 입력 종목코드 (0000:전체, 0001:코스피, 1001:코스닥, 2001:코스피200)
        fid_rank_sort_cls_code: 순위 정렬 구분 코드 (0:순매수잔량순, 1:순매도잔량순, 2:매수비율순, 3:매도비율순)
        fid_div_cls_code: 분류 구분 코드 (0:전체)
        fid_trgt_cls_code: 대상 구분 코드 (0:전체)
        fid_trgt_exls_cls_code: 대상 제외 구분 코드 (0:전체)
        fid_input_price_1: 입력 가격1 (가격 ~)
        fid_input_price_2: 입력 가격2 (~ 가격)
        fid_vol_cnt: 거래량 수 (거래량 ~)
        tr_cont: 연속 거래 여부

    Returns:
        호가잔량 순위 종목 데이터 (최대 30건)
    """
    url = '/uapi/domestic-stock/v1/ranking/quote-balance'
    tr_id = "FHPST01720000"  # 호가잔량 순위

    params = {
        "fid_vol_cnt": fid_vol_cnt,
        "fid_cond_mrkt_div_code": fid_cond_mrkt_div_code,
        "fid_cond_scr_div_code": fid_cond_scr_div_code,
        "fid_input_iscd": fid_input_iscd,
        "fid_rank_sort_cls_code": fid_rank_sort_cls_code,
        "fid_div_cls_code": fid_div_cls_code,
        "fid_trgt_cls_code": fid_trgt_cls_code,
        "fid_trgt_exls_cls_code": fid_trgt_exls_cls_code,
        "fid_input_price_1": fid_input_price_1,
        "fid_input_price_2": fid_input_price_2
    }

    try:
        res = kis._url_fetch(url, tr_id, tr_cont, params)

        if res and res.isOK():
            body = res.getBody()
            output_data = getattr(body, 'output', [])
            if output_data:
                current_data = pd.DataFrame(output_data)
                logger.info(f"호가잔량 순위 조회 성공: {len(current_data)}건")
                return current_data
            else:
                logger.warning("호가잔량 순위 조회: 데이터 없음")
                return pd.DataFrame()
        else:
            logger.error("호가잔량 순위 조회 실패")
            return None
    except Exception as e:
        logger.error(f"호가잔량 순위 조회 오류: {e}")
        return None


# 테스트 실행을 위한 예시 함수
if __name__ == "__main__":
    pass

# =============================================================================
# 🎯 시장상황 분석을 위한 API 함수들
# =============================================================================

def get_index_data(index_code: str = "0001") -> Optional[Dict[str, Any]]:
    """
    국내업종 현재지수 API (TR: FHPUP02100000)
    코스피/코스닥 지수 정보를 조회합니다.

    Args:
        index_code: 업종코드 ("0001": 코스피, "1001": 코스닥)

    Returns:
        Dict: 지수 정보 (지수값, 전일대비율, 거래량 등)
    """
    url = '/uapi/domestic-stock/v1/quotations/inquire-index-price'
    tr_id = "FHPUP02100000"  # 국내업종 현재지수

    params = {
        "FID_COND_MRKT_DIV_CODE": "U",      # U: 업종
        "FID_INPUT_ISCD": index_code         # 업종코드 (0001: 코스피, 1001: 코스닥)
    }

    try:
        logger.debug(f"📊 지수 정보 조회: {index_code}")
        res = kis._url_fetch(url, tr_id, "", params)

        if res and res.isOK():
            body = res.getBody()
            output_data = getattr(body, 'output', None)

            if output_data:
                if isinstance(output_data, list) and len(output_data) > 0:
                    result = output_data[0]
                    if isinstance(result, dict):
                        logger.debug(f"✅ {index_code} 지수 조회 성공")
                        return result
                elif isinstance(output_data, dict):
                    logger.debug(f"✅ {index_code} 지수 조회 성공")
                    return output_data

                logger.warning(f"⚠️ {index_code} 지수 데이터 형식 오류")
                return None
            else:
                logger.warning(f"⚠️ {index_code} 지수 데이터 없음")
                return None
        else:
            logger.error(f"❌ {index_code} 지수 조회 실패")
            return None

    except Exception as e:
        logger.error(f"❌ 지수 조회 오류 ({index_code}): {e}")
        return None


def get_investor_flow_data() -> Optional[Dict[str, Any]]:
    """
    외국인/기관 매매종목가집계 API (TR: FHPTJ04400000)
    외국인과 기관의 순매수/순매도 현황을 조회합니다.

    Returns:
        Dict: 투자자별 매매 현황 (외국인/기관 순매수금액 등)
    """
    url = '/uapi/domestic-stock/v1/quotations/inquire-investor-vsvolume'
    tr_id = "FHPTJ04400000"  # 외국인/기관 매매종목가집계

    # 현재 날짜 사용
    current_date = now_kst().strftime("%Y%m%d")

    params = {
        "FID_COND_MRKT_DIV_CODE": "J",      # J: 주식
        "FID_INPUT_DATE_1": current_date,    # 조회일자
        "FID_INPUT_ISCD": ""                 # 종목코드 (전체: 공백)
    }

    try:
        logger.debug(f"💰 투자자별 매매 현황 조회: {current_date}")
        res = kis._url_fetch(url, tr_id, "", params)

        if res and res.isOK():
            body = res.getBody()
            output1_data = getattr(body, 'output1', None)  # 투자자별 총계
            output2_data = getattr(body, 'output2', None)  # 종목별 상세

            result = {}

            # output1: 투자자별 총계 (외국인, 기관 등)
            if output1_data:
                if isinstance(output1_data, list):
                    result['investor_summary'] = output1_data
                else:
                    result['investor_summary'] = [output1_data]

            # output2: 종목별 상세 (필요시 사용)
            if output2_data:
                if isinstance(output2_data, list):
                    result['stock_details'] = output2_data
                else:
                    result['stock_details'] = [output2_data]

            logger.debug("✅ 투자자별 매매 현황 조회 성공")
            return result

        else:
            logger.error("❌ 투자자별 매매 현황 조회 실패")
            return None

    except Exception as e:
        logger.error(f"❌ 투자자별 매매 현황 오류: {e}")
        return None


def get_market_overview() -> Optional[Dict[str, Any]]:
    """
    종합 시장 개요 정보 조회
    코스피/코스닥 지수와 투자자 동향을 종합적으로 제공합니다.

    Returns:
        Dict: 종합 시장 정보
    """
    try:
        logger.debug("📊 종합 시장 개요 조회 시작")

        # 코스피 지수 조회
        kospi_data = get_index_data("0001")

        # 코스닥 지수 조회
        kosdaq_data = get_index_data("1001")

        # 투자자별 매매 현황 조회
        investor_data = get_investor_flow_data()

        result = {
            'kospi': kospi_data,
            'kosdaq': kosdaq_data,
            'investor_flows': investor_data,
            'timestamp': now_kst().isoformat()
        }

        logger.debug("✅ 종합 시장 개요 조회 완료")
        return result

    except Exception as e:
        logger.error(f"❌ 종합 시장 개요 조회 오류: {e}")
        return None


# =============================================================================
# 🎯 잔고 및 포지션 조회 API
# =============================================================================

def get_stock_balance(output_dv: str = "01", tr_cont: str = "",
                     FK100: str = "", NK100: str = "") -> Optional[Tuple[pd.DataFrame, Dict]]:
    """
    주식잔고조회 (TR: TTTC8434R)

    Args:
        output_dv: 출력구분 ("01": 일반조회)
        tr_cont: 연속거래키
        FK100: 연속조회검색조건100
        NK100: 연속조회키100

    Returns:
        Tuple[pd.DataFrame, Dict]: (보유종목 데이터, 계좌요약 정보)
        계좌요약에는 dnca_tot_amt(매수가능금액) 포함
    """
    url = '/uapi/domestic-stock/v1/trading/inquire-balance'
    tr_id = "TTTC8434R"  # 주식잔고조회

    # KIS 환경 정보 안전 조회
    tr_env = kis.getTREnv()
    if tr_env is None:
        logger.error("❌ KIS 환경 정보 없음 - 인증이 필요합니다")
        return None

    params = {
        "CANO": tr_env.my_acct,           # 계좌번호
        "ACNT_PRDT_CD": tr_env.my_prod,  # 계좌상품코드
        "AFHR_FLPR_YN": "N",              # 시간외단일가여부
        "OFL_YN": "",                     # 오프라인여부
        "INQR_DVSN": "02",                # 조회구분(01:대출일별, 02:종목별)
        "UNPR_DVSN": "01",                # 단가구분(01:기준가, 02:현재가)
        "FUND_STTL_ICLD_YN": "N",         # 펀드결제분포함여부
        "FNCG_AMT_AUTO_RDPT_YN": "N",     # 융자금액자동상환여부
        "PRCS_DVSN": "00",                # 처리구분(00:전일매매포함, 01:전일매매미포함)
        "CTX_AREA_FK100": "",          # 연속조회검색조건100
        "CTX_AREA_NK100": ""           # 연속조회키100
    }

    try:
        logger.debug("💰 주식잔고조회 API 호출")
        res = kis._url_fetch(url, tr_id, tr_cont, params)

        if res and res.isOK():
            body = res.getBody()

            # output1: 개별 종목 잔고
            output1_data = getattr(body, 'output1', [])
            # output2: 잔고요약 (매수가능금액 등 포함)
            output2_data = getattr(body, 'output2', [])

            # 🎯 계좌요약 정보 처리 (output2_data)
            account_summary = {}
            if output2_data:
                summary = output2_data[0] if isinstance(output2_data, list) else output2_data

                def safe_int_convert(value: Any, default: int = 0) -> int:
                    """안전한 정수 변환"""
                    if value is None or value == '':
                        return default
                    try:
                        return int(str(value).replace(',', ''))
                    except (ValueError, TypeError):
                        return default

                # 💰 매수가능금액 등 주요 정보 추출 (API 문서 기준)
                account_summary = {
                    'dnca_tot_amt': safe_int_convert(summary.get('dnca_tot_amt', '0')),           # 예수금총금액
                    'nxdy_excc_amt': safe_int_convert(summary.get('nxdy_excc_amt', '0')),        # 🎯 익일정산금액 (실제 매수가능금액!)
                    'prvs_rcdl_excc_amt': safe_int_convert(summary.get('prvs_rcdl_excc_amt', '0')), # 가수도정산금액 (D+2 예수금)
                    'tot_evlu_amt': safe_int_convert(summary.get('tot_evlu_amt', '0')),          # 총평가액
                    'evlu_pfls_smtl_amt': safe_int_convert(summary.get('evlu_pfls_smtl_amt', '0')), # 평가손익합계
                    'pchs_amt_smtl_amt': safe_int_convert(summary.get('pchs_amt_smtl_amt', '0')),   # 매입금액합계
                    'evlu_amt_smtl_amt': safe_int_convert(summary.get('evlu_amt_smtl_amt', '0')),   # 평가금액합계
                    'raw_summary': summary  # 원본 데이터 보관
                }

                logger.debug(f"✅ 계좌요약: 💰매수가능={account_summary['nxdy_excc_amt']:,}원, "
                           f"총평가액={account_summary['tot_evlu_amt']:,}원, "
                           f"평가손익={account_summary['evlu_pfls_smtl_amt']:+,}원")

            if output1_data:
                balance_df = pd.DataFrame(output1_data)
                logger.debug(f"✅ 주식잔고조회 성공: {len(balance_df)}개 종목")
                return balance_df, account_summary
            else:
                logger.info("📊 보유 종목 없음")
                return pd.DataFrame(), account_summary
        else:
            logger.error("❌ 주식잔고조회 실패")
            return None

    except Exception as e:
        logger.error(f"❌ 주식잔고조회 오류: {e}")
        return None


def get_account_balance() -> Optional[Dict]:
    """
    계좌잔고조회 - 요약 정보 (매수가능금액 포함)

    Returns:
        계좌 요약 정보 (dnca_tot_amt 매수가능금액 포함)
    """
    try:
        result = get_stock_balance()
        if result is None:
            return None

        balance_data, account_summary = result

        # 🎯 매수가능금액을 포함한 기본 정보
        base_info = {
            'total_stocks': 0,
            'total_value': account_summary.get('tot_evlu_amt', 0),
            'total_profit_loss': account_summary.get('evlu_pfls_smtl_amt', 0),
            'available_amount': account_summary.get('prvs_rcdl_excc_amt', 0),  # 🎯 가수도정산금액 (실제 매수가능금액!)
            'cash_balance': account_summary.get('nxdy_excc_amt', 0),          # 🎯 익일정산금액 (D+1 예수금)
            'purchase_amount': account_summary.get('pchs_amt_smtl_amt', 0),
            'next_day_amount': account_summary.get('nxdy_excc_amt', 0),
            'deposit_total': account_summary.get('dnca_tot_amt', 0),          # 🆕 예수금총금액 (참고용)
            'stocks': []
        }

        if balance_data.empty:
            logger.info(f"💰 매수가능금액: {base_info['available_amount']:,}원 (보유종목 없음)")
            return base_info

        # 보유 종목 요약 생성
        stocks = []
        total_value = 0
        total_profit_loss = 0

        def safe_int_balance(value: Any, default: int = 0) -> int:
            """안전한 정수 변환"""
            if value is None or value == '':
                return default
            try:
                return int(str(value).replace(',', ''))
            except (ValueError, TypeError):
                return default

        def safe_float_balance(value: Any, default: float = 0.0) -> float:
            """안전한 실수 변환"""
            if value is None or value == '':
                return default
            try:
                return float(str(value).replace(',', ''))
            except (ValueError, TypeError):
                return default

        for _, row in balance_data.iterrows():
            stock_code = row.get('pdno', '')  # 종목코드
            stock_name = row.get('prdt_name', '')  # 종목명
            quantity = safe_int_balance(row.get('hldg_qty', '0'))  # 보유수량
            avg_price = safe_float_balance(row.get('pchs_avg_pric', '0'))  # 매입평균가
            current_price = safe_float_balance(row.get('prpr', '0'))  # 현재가
            eval_amt = safe_int_balance(row.get('evlu_amt', '0'))  # 평가금액
            profit_loss = safe_int_balance(row.get('evlu_pfls_amt', '0'))  # 평가손익
            profit_loss_rate = safe_float_balance(row.get('evlu_pfls_rt', '0'))  # 평가손익률

            if quantity > 0:  # 실제 보유 종목만
                stock_info = {
                    'stock_code': stock_code,
                    'stock_name': stock_name,
                    'quantity': quantity,
                    'avg_price': avg_price,
                    'current_price': current_price,
                    'eval_amount': eval_amt,
                    'profit_loss': profit_loss,
                    'profit_loss_rate': profit_loss_rate
                }
                stocks.append(stock_info)
                total_value += eval_amt
                total_profit_loss += profit_loss

        # 🎯 base_info 업데이트
        base_info.update({
            'total_stocks': len(stocks),
            'total_value': total_value,
            'total_profit_loss': total_profit_loss,
            'total_profit_loss_rate': (total_profit_loss / total_value * 100) if total_value > 0 else 0.0,
            'stocks': stocks,
            'inquiry_time': now_kst().strftime('%Y-%m-%d %H:%M:%S')
        })

        logger.debug(f"💰 계좌요약: {len(stocks)}개 종목, 총 {total_value:,}원, "
                   f"손익 {total_profit_loss:+,}원 ({base_info['total_profit_loss_rate']:+.2f}%), "
                   f"💰매수가능={base_info['available_amount']:,}원")

        return base_info

    except Exception as e:
        logger.error(f"계좌잔고 요약 오류: {e}")
        return None


def get_existing_holdings() -> List[Dict]:
    """
    기존 보유 종목 조회 (CandleTradeManager용)

    Returns:
        보유 종목 리스트
    """
    try:
        account_balance = get_account_balance()

        if not account_balance or account_balance['total_stocks'] == 0:
            return []

        return account_balance['stocks']

    except Exception as e:
        logger.error(f"기존 보유 종목 조회 오류: {e}")
        return []


# =============================================================================
# 🎯 종목 정보 조회 API
# =============================================================================

def get_stock_info(stock_code: str = "", start_date: str = "", end_date: str = "", 
                   tr_cont: str = "") -> Optional[pd.DataFrame]:
    """
    예탁원정보(상장정보일정) API (TR: HHKDB669107C0)
    종목의 상장정보, 총발행주식수 등을 조회합니다.

    Args:
        stock_code: 종목코드 (6자리, 공백시 전체 조회)
        start_date: 조회시작일자 (YYYYMMDD)
        end_date: 조회종료일자 (YYYYMMDD)
        tr_cont: 연속거래여부 (공백: 초기조회, N: 다음데이터조회)

    Returns:
        pd.DataFrame: 종목 상장정보 (총발행주식수 포함)
    """
    url = '/uapi/domestic-stock/v1/ksdinfo/list-info'
    tr_id = "HHKDB669107C0"  # 예탁원정보(상장정보일정)

    # 기본 날짜 설정 (최근 3일)
    if not start_date:
        start_date = (now_kst() - timedelta(days=5)).strftime("%Y%m%d")
    if not end_date:
        end_date = now_kst().strftime("%Y%m%d")

    params = {
        "SHT_CD": stock_code,      # 종목코드 (공백: 전체)
        "T_DT": end_date,          # 조회종료일자
        "F_DT": start_date,        # 조회시작일자
        "CTS": ""                  # CTS (공백)
    }

    try:
        logger.debug(f"📋 종목정보 조회: {stock_code or '전체'} ({start_date}~{end_date})")
        res = kis._url_fetch(url, tr_id, tr_cont, params)

        if res and res.isOK():
            body = res.getBody()
            output1_data = getattr(body, 'output1', [])
            
            if output1_data:
                stock_info_df = pd.DataFrame(output1_data)
                logger.debug(f"✅ 종목정보 조회 성공: {len(stock_info_df)}건")
                return stock_info_df
            else:
                logger.warning("⚠️ 종목정보 조회: 데이터 없음")
                return pd.DataFrame()
        else:
            logger.error("❌ 종목정보 조회 실패")
            return None

    except Exception as e:
        logger.error(f"❌ 종목정보 조회 오류: {e}")
        return None


def get_stock_market_cap(stock_code: str) -> Optional[Dict[str, Any]]:
    """
    종목의 시가총액 조회 (get_inquire_price의 hts_avls 필드 사용)
    
    Args:
        stock_code: 종목코드 (6자리)
        
    Returns:
        Dict: 시가총액 정보
        {
            'stock_code': 종목코드,
            'stock_name': 종목명,
            'current_price': 현재가,
            'market_cap': 시가총액 (원),
            'market_cap_billion': 시가총액 (억원)
        }
    """
    def safe_int(value: Any, default: int = 0) -> int:
        """안전한 정수 변환"""
        if value is None or value == '':
            return default
        try:
            return int(str(value).replace(',', ''))
        except (ValueError, TypeError):
            return default
    
    def safe_str(value: Any, default: str = '') -> str:
        """안전한 문자열 변환"""
        if value is None:
            return default
        return str(value).strip()
    
    try:
        # 1. 현재가 조회
        current_price_data = get_inquire_price(itm_no=stock_code)
        if current_price_data is None or current_price_data.empty:
            logger.error(f"❌ {stock_code} 현재가 조회 실패")
            return None
            
        current_price_raw = current_price_data.iloc[0].get('stck_prpr', '0')
        current_price = safe_int(current_price_raw)
        stock_name = safe_str(current_price_data.iloc[0].get('prdt_name', ''))
        
        if current_price == 0:
            logger.error(f"❌ {stock_code} 현재가 정보 없음 (값: {current_price_raw})")
            return None
        
        # 2. 시가총액 조회 (hts_avls 필드 사용)
        market_cap_raw = current_price_data.iloc[0].get('hts_avls', '0')
        market_cap_billion = safe_int(market_cap_raw)  # hts_avls는 이미 억원 단위
        
        if market_cap_billion == 0:
            logger.error(f"❌ {stock_code} 시가총액 정보 없음 (값: {market_cap_raw})")
            return None
            
        # 3. 시가총액 단위 변환 (원 단위로 변환)
        market_cap = market_cap_billion * 100_000_000  # 억원 → 원 단위
        
        result = {
            'stock_code': stock_code,
            'stock_name': stock_name,
            'current_price': current_price,
            'market_cap': market_cap,
            'market_cap_billion': market_cap_billion,
            'query_time': now_kst().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        logger.debug(f"✅ {stock_code}({stock_name}) 시가총액: {market_cap_billion:,.0f}억원 "
                   f"(현재가 {current_price:,}원)")
        
        return result
        
    except Exception as e:
        logger.error(f"❌ {stock_code} 시가총액 계산 오류: {e}")
        return None