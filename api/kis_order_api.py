"""
KIS API 주문 관련 함수 (공식 문서 기반)
"""
import time
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, List
from utils.logger import setup_logger
from . import kis_auth as kis
from utils.korean_time import now_kst

logger = setup_logger(__name__)


def get_order_cash(ord_dv: str = "", itm_no: str = "", qty: int = 0, unpr: int = 0,
                   tr_cont: str = "") -> Optional[pd.DataFrame]:
    """주식주문(현금) - 매수/매도"""
    '''
        EXCG_ID_DVSN_CD	거래소ID구분코드	String	N	3	한국거래소 : KRX
        대체거래소 (넥스트레이드) : NXT
        SOR (Smart Order Routing) : SOR
        → 미입력시 KRX로 진행되며, 모의투자는 KRX만 가능
    '''
    url = '/uapi/domestic-stock/v1/trading/order-cash'

    if ord_dv == "buy":
        tr_id = "TTTC0012U"  # 주식 현금 매수 주문 [모의투자] VTTC0802U
    elif ord_dv == "sell":
        tr_id = "TTTC0011U"  # 주식 현금 매도 주문 [모의투자] VTTC0801U
    else:
        logger.error("매수/매도 구분 확인 필요")
        return None

    if not itm_no:
        logger.error("주문종목번호 확인 필요")
        return None

    if qty == 0:
        logger.error("주문수량 확인 필요")
        return None

    if unpr == 0:
        logger.error("주문단가 확인 필요")
        return None

    params = {
        "CANO": kis.getTREnv().my_acct,         # 계좌번호 8자리
        "ACNT_PRDT_CD": kis.getTREnv().my_prod, # 계좌상품코드 2자리
        "PDNO": itm_no,                         # 종목코드(6자리)
        "ORD_DVSN": "00",                       # 주문구분 00:지정가, 01:시장가
        "ORD_QTY": str(int(qty)),               # 주문주식수
        "ORD_UNPR": str(int(unpr)),             # 주문단가
        "EXCG_ID_DVSN_CD": "SOR"                       
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params, postFlag=True)

    if res and res.isOK():
        current_data = pd.DataFrame(res.getBody().output, index=[0])
        return current_data
    else:
        if res:
            logger.error(f"{res.getErrorCode()}, {res.getErrorMessage()}")
        return None


def get_order_rvsecncl(ord_orgno: str = "", orgn_odno: str = "", ord_dvsn: str = "",
                       rvse_cncl_dvsn_cd: str = "", ord_qty: int = 0, ord_unpr: int = 0,
                       qty_all_ord_yn: str = "", tr_cont: str = "") -> Optional[pd.DataFrame]:
    """주식주문(정정취소) - 신 TR ID 사용"""
    url = '/uapi/domestic-stock/v1/trading/order-rvsecncl'
    tr_id = "TTTC0013U"  # 🆕 신 TR ID (구: TTTC0803U)

    if not ord_orgno:
        logger.error("주문조직번호 확인 필요")
        return None

    if not orgn_odno:
        logger.error("원주문번호 확인 필요")
        return None

    if not ord_dvsn:
        logger.error("주문구분 확인 필요")
        return None

    if rvse_cncl_dvsn_cd not in ["01", "02"]:
        logger.error("정정취소구분코드 확인 필요 (정정:01, 취소:02)")
        return None

    if qty_all_ord_yn == "Y" and ord_qty > 0:
        logger.warning("잔량전부 취소/정정주문인 경우 주문수량 0 처리")
        ord_qty = 0

    if qty_all_ord_yn == "N" and ord_qty == 0:
        logger.error("취소/정정 수량 확인 필요")
        return None

    if rvse_cncl_dvsn_cd == "01" and ord_unpr == 0:
        logger.error("주문단가 확인 필요")
        return None

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "KRX_FWDG_ORD_ORGNO": ord_orgno,        # 한국거래소전송주문조직번호
        "ORGN_ODNO": orgn_odno,                 # 원주문번호
        "ORD_DVSN": ord_dvsn,                   # 주문구분
        "RVSE_CNCL_DVSN_CD": rvse_cncl_dvsn_cd, # 정정:01, 취소:02
        "ORD_QTY": str(int(ord_qty)),           # 주문주식수
        "ORD_UNPR": str(int(ord_unpr)),         # 주문단가
        "QTY_ALL_ORD_YN": qty_all_ord_yn        # 잔량전부주문여부
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params, postFlag=True)

    if res and res.isOK():
        current_data = pd.DataFrame(res.getBody().output, index=[0])
        return current_data
    else:
        if res:
            logger.error(f"{res.getErrorCode()}, {res.getErrorMessage()}")
        return None


def get_inquire_psbl_rvsecncl_lst(tr_cont: str = "", FK100: str = "", NK100: str = "",
                                  dataframe: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """주식정정취소가능주문조회 (페이징 지원)"""
    url = '/uapi/domestic-stock/v1/trading/inquire-psbl-rvsecncl'
    tr_id = "TTTC8036R"

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "INQR_DVSN_1": "1",                     # 조회구분1 0:조회순서, 1:주문순, 2:종목순
        "INQR_DVSN_2": "0",                     # 조회구분2 0:전체, 1:매도, 2:매수
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if not res or not res.isOK():
        logger.error("정정취소가능주문조회 실패")
        return dataframe

    current_data = pd.DataFrame(res.getBody().output)

    # 기존 데이터와 병합
    if dataframe is not None:
        dataframe = pd.concat([dataframe, current_data], ignore_index=True)
    else:
        dataframe = current_data

    # 페이징 처리
    tr_cont = res.getHeader().tr_cont
    FK100 = res.getBody().ctx_area_fk100
    NK100 = res.getBody().ctx_area_nk100

    if tr_cont in ("D", "E"):  # 마지막 페이지
        logger.debug("정정취소가능주문조회 완료")
        return dataframe
    elif tr_cont in ("F", "M"):  # 다음 페이지 존재
        logger.debug("다음 페이지 조회 중...")
        time.sleep(0.1)  # 시스템 안정성을 위한 지연
        return get_inquire_psbl_rvsecncl_lst("N", FK100, NK100, dataframe)

    return dataframe


def get_inquire_daily_ccld_obj(dv: str = "01", inqr_strt_dt: Optional[str] = None,
                               inqr_end_dt: Optional[str] = None, tr_cont: str = "",
                               FK100: str = "", NK100: str = "") -> Optional[pd.DataFrame]:
    """주식일별주문체결조회 - 요약 정보"""
    url = '/uapi/domestic-stock/v1/trading/inquire-daily-ccld'

    if dv == "01":
        tr_id = "TTTC0081R"  # 🔧 신 TR ID: 3개월 이내 (구: TTTC8001R)
    else:
        tr_id = "CTSC9215R"  # 🔧 신 TR ID: 3개월 이전 (구: CTSC9115R)

    if inqr_strt_dt is None:
        inqr_strt_dt = datetime.today().strftime("%Y%m%d")
    if inqr_end_dt is None:
        inqr_end_dt = datetime.today().strftime("%Y%m%d")

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "INQR_STRT_DT": inqr_strt_dt,           # 조회시작일자
        "INQR_END_DT": inqr_end_dt,             # 조회종료일자
        "SLL_BUY_DVSN_CD": "00",                # 매도매수구분 00:전체
        "INQR_DVSN": "01",                      # 조회구분 00:역순, 01:정순
        "PDNO": "",                             # 종목번호
        "CCLD_DVSN": "00",                      # 체결구분 00:전체
        "ORD_GNO_BRNO": "",                     # 사용안함
        "ODNO": "",                             # 주문번호
        "INQR_DVSN_3": "00",                    # 조회구분3 00:전체
        "INQR_DVSN_1": "0",                     # 조회구분1
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if res and res.isOK():
        current_data = pd.DataFrame(res.getBody().output2, index=[0])
        return current_data
    else:
        logger.error("주식일별주문체결조회 실패")
        return None


def get_inquire_daily_ccld_lst(dv: str = "01", inqr_strt_dt: str = "", inqr_end_dt: str = "",
                               ccld_dvsn: str = "00", tr_cont: str = "", FK100: str = "", NK100: str = "",
                               dataframe: Optional[pd.DataFrame] = None) -> Optional[pd.DataFrame]:
    """주식일별주문체결조회 - 상세 목록 (페이징 지원)

    Args:
        ccld_dvsn: 체결구분 ('00':전체, '01':체결, '02':미체결)
    """
    url = '/uapi/domestic-stock/v1/trading/inquire-daily-ccld'

    if dv == "01":
        tr_id = "TTTC0081R"  # 🔧 신 TR ID: 3개월 이내 (구: TTTC8001R)
    else:
        tr_id = "CTSC9215R"  # 🔧 신 TR ID: 3개월 이전 (구: CTSC9115R)

    if inqr_strt_dt == "":
        inqr_strt_dt = datetime.today().strftime("%Y%m%d")
    if inqr_end_dt == "":
        inqr_end_dt = datetime.today().strftime("%Y%m%d")

    params = {
        "CANO": kis.getTREnv().my_acct,
        "ACNT_PRDT_CD": kis.getTREnv().my_prod,
        "INQR_STRT_DT": inqr_strt_dt,
        "INQR_END_DT": inqr_end_dt,
        "SLL_BUY_DVSN_CD": "00",                # 매도매수구분 00:전체
        "INQR_DVSN": "01",                      # 조회구분 01:정순
        "PDNO": "",                             # 종목번호
        "CCLD_DVSN": ccld_dvsn,                 # 체결구분 00:전체, 01:체결, 02:미체결
        "ORD_GNO_BRNO": "",
        "ODNO": "",
        "INQR_DVSN_3": "00",
        "INQR_DVSN_1": "",
        "CTX_AREA_FK100": FK100,
        "CTX_AREA_NK100": NK100
    }

    res = kis._url_fetch(url, tr_id, tr_cont, params)

    if not res or not res.isOK():
        logger.error("주식일별주문체결조회 실패")
        return dataframe

    current_data = pd.DataFrame(res.getBody().output1)

    # 기존 데이터와 병합
    if dataframe is not None:
        dataframe = pd.concat([dataframe, current_data], ignore_index=True)
    else:
        dataframe = current_data

    # 페이징 처리
    tr_cont = res.getHeader().tr_cont
    FK100 = res.getBody().ctx_area_fk100
    NK100 = res.getBody().ctx_area_nk100

    if tr_cont in ("D", "E"):  # 마지막 페이지
        logger.debug("주식일별주문체결조회 완료")
        return dataframe
    elif tr_cont in ("F", "M"):  # 다음 페이지 존재
        logger.debug("다음 페이지 조회 중...")
        time.sleep(0.1)
        return get_inquire_daily_ccld_lst(dv, inqr_strt_dt, inqr_end_dt, ccld_dvsn, "N", FK100, NK100, dataframe)

    return dataframe