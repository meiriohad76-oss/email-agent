@echo off
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
python -m uvicorn email_article_analyzer.main:app --host 127.0.0.1 --port 8000
