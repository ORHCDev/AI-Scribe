@echo off
setlocal

REM Change to the directory of this script
cd /d "%~dp0"

echo Activating venv
REM Activate virtual environment if available
if exist "venv\Scripts\activate.bat" goto activate_venv
if exist ".venv\Scripts\activate.bat" goto activate_dotvenv
echo No virtual environment found (.venv or venv). Running with system Python and packages - may cause errors.
goto run_uploader

:activate_venv
call "venv\Scripts\activate.bat"
goto run_uploader

:activate_dotvenv
call ".venv\Scripts\activate.bat"
goto run_uploader

:run_uploader

echo Running daily vector DB upload
REM Navigate to chatbot directory
cd /d "src\FreeScribe.client\chatbot"

REM Log output to a dated file
set LOGFILE=logs\upload_%date:~10,4%%date:~4,2%%date:~7,2%.log
if not exist "logs" mkdir "logs"

echo === Upload started %date% %time% === >> "%LOGFILE%"
python daily_uploader.py >> "%LOGFILE%" 2>&1
echo === Upload finished %date% %time% (exit code %errorlevel%) === >> "%LOGFILE%"

endlocal
