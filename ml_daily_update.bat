@echo off
REM ML 모델 일일 자동 업데이트 (Windows)
REM
REM Windows 작업 스케줄러에 등록하여 매일 자동 실행
REM 예: 매일 오전 8시 (장 시작 전)

echo ========================================
echo ML 모델 일일 자동 업데이트
echo ========================================
echo.

REM 작업 디렉토리로 이동
cd /d D:\GIT\RoboTrader

REM 가상환경 활성화 (필요한 경우)
REM call venv\Scripts\activate.bat

REM 어제 데이터로 증분 업데이트
python ml_daily_update.py

REM 결과 코드 확인
if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo ✅ ML 모델 업데이트 성공!
    echo ========================================
    echo.
) else (
    echo.
    echo ========================================
    echo ❌ ML 모델 업데이트 실패!
    echo ========================================
    echo.
)

REM 로그 파일에 기록
echo [%date% %time%] ML 업데이트 완료 (결과: %ERRORLEVEL%) >> ml_update_log.txt

REM 작업 스케줄러에서 실행 시 창이 자동으로 닫히지 않도록 주석 처리
REM pause

exit /b %ERRORLEVEL%
