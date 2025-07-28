@echo off
chcp 65001 > nul
echo ========================================
echo    RoboTrader 주식 단타 거래 시스템
echo ========================================

:: 현재 디렉토리로 이동
cd /d "%~dp0"

:: Python 가상환경 확인 및 생성
if not exist "venv" (
    echo 가상환경이 없습니다. 생성 중...
    python -m venv venv
    if errorlevel 1 (
        echo Python이 설치되지 않았거나 경로에 없습니다.
        echo Python을 설치하고 PATH에 추가한 후 다시 실행해주세요.
        pause
        exit /b 1
    )
)

:: 가상환경 활성화
echo 가상환경 활성화 중...
call venv\Scripts\activate.bat

:: pip 업그레이드
echo pip 업그레이드 중...
python -m pip install --upgrade pip

:: 의존성 패키지 설치 (UTF-8 인코딩 강제)
echo 의존성 패키지 설치 확인 중...
set PYTHONUTF8=1
pip install -r requirements.txt --no-cache-dir

:: 설정 파일 확인
if not exist "config\key.ini" (
    echo.
    echo ❌ 설정 파일이 없습니다!
    echo config\key.ini 파일을 생성하고 API 키를 설정해주세요.
    echo config\key.ini.example 파일을 참고하세요.
    echo.
    pause
    exit /b 1
)

:: 로그 디렉토리 생성
if not exist "logs" mkdir logs

:: 프로그램 실행
echo.
echo 🚀 RoboTrader 시작 중...
echo 종료하려면 Ctrl+C를 누르세요.
echo.
python main.py

:: 종료 메시지
echo.
echo RoboTrader가 종료되었습니다.
pause