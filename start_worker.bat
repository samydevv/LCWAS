@echo off
REM Start Redis server in background
start /B redis-server

REM Start Celery worker
cd /d %~dp0
celery -A app.tasks worker --loglevel=info --pool=solo

pause
