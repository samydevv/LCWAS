@echo off
REM Initialize and run the Lotus Chess Analysis Service

REM Check for Python
python --version >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    echo Python is required but not found. Please install Python 3.9 or higher.
    exit /b 1
)

REM Set up virtual environment if it doesn't exist
if not exist venv (
    echo Setting up virtual environment...
    python -m venv venv
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to create virtual environment. Please make sure venv module is installed.
        exit /b 1
    )
    set INSTALL_REQUIREMENTS=true
) else (
    echo Virtual environment already exists.
)

REM Activate virtual environment
echo Activating virtual environment...
call venv\Scripts\activate.bat

REM Check if requirements are already installed
python -c "import fastapi, uvicorn, socketio, redis, celery" >nul 2>&1
if %ERRORLEVEL% NEQ 0 (
    set INSTALL_REQUIREMENTS=true
)

if "%INSTALL_REQUIREMENTS%"=="true" (
    echo Installing requirements...
    pip install -r requirements.txt
    if %ERRORLEVEL% NEQ 0 (
        echo Failed to install requirements.
        exit /b 1
    )
) else (
    echo Requirements already installed, skipping installation.
)

REM Set up Stockfish if needed
if exist app\stockfish\stockfish-windows-x86-64-avx2.exe (
    echo Stockfish already installed, skipping setup.
) else (
    echo Setting up Stockfish...
    python setup_stockfish.py
    if %ERRORLEVEL% NEQ 0 (
        echo Warning: Failed to set up Stockfish automatically.
        echo Please download Stockfish  from https://stockfishchess.org/download/ manually.
    )
)

REM Start the FastAPI server
cd /d %~dp0
echo Starting Lotus Chess Analysis Service...
uvicorn app.main:app --host 0.0.0.0 --port 8000

@REM pause