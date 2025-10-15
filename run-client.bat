@echo off
setlocal

REM Change to the directory of this script
cd /d "%~dp0"

echo Activating venv
REM Activate virtual environment if available
if exist "venv\Scripts\activate.bat" goto activate_venv
if exist ".venv\Scripts\activate.bat" goto activate_dotvenv
echo No virtual environment found (.venv or venv). Running with system Python and packages - may cause errors.
goto run_client

:activate_venv
call "venv\Scripts\activate.bat"
goto run_client

:activate_dotvenv
call ".venv\Scripts\activate.bat"
goto run_client

:run_client

echo Running client
REM Navigate to FreeScribe client and run the app
cd /d "src\FreeScribe.client"
python client.py

endlocal
