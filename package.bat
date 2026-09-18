@echo off

if "%1"=="i" (
    pip install -r requirements.txt
)

if "%1"=="dev" (
    uvicorn main:app --reload
)

if "%1"=="run" (
    uvicorn app.main:app --host 0.0.0.0 --port 8000
)
if "%1"=="env" (
   conda activate ai_starter
)