@echo off
rem Start the llm_localizator web UI from a source checkout.
rem Default ports: 8770 web UI, 8760 marketing site.
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "PORT=8770"
set "MPORT=8760"
set "NOMKT="
set "EXTRA="

:args
if "%~1"=="" goto :parsed
if /i "%~1"=="--help" goto :help
if /i "%~1"=="-h" goto :help
if "%~1"=="/?" goto :help
if /i "%~1"=="--port" (set "PORT=%~2" & shift & shift & goto :args)
if /i "%~1"=="--marketing-port" (set "MPORT=%~2" & shift & shift & goto :args)
if /i "%~1"=="--no-marketing" (set "NOMKT=1" & set "EXTRA=!EXTRA! --no-marketing" & shift & goto :args)
set "EXTRA=!EXTRA! %1"
shift
goto :args

:parsed
set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo Missing %PY%. Run: uv sync
  exit /b 1
)
"%PY%" -c "import llm_localizator" 2>nul || (
  echo llm_localizator is not installed in .venv. Run: uv sync
  exit /b 1
)

call :portfree %PORT% || exit /b 1
if not defined NOMKT (call :portfree %MPORT% || exit /b 1)

start "llm_localizator web :%PORT%" "%PY%" -m llm_localizator.cli.main web --port %PORT% --marketing-port %MPORT% --no-browser%EXTRA%

powershell -NoProfile -Command "$u='http://127.0.0.1:%PORT%/'; for($i=0;$i -lt 40;$i++){ try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 $u | Out-Null; exit 0 } catch { if ($_.Exception.Response) { exit 0 }; Start-Sleep -Milliseconds 500 } }; exit 1"
if errorlevel 1 (
  echo The server did not answer on http://127.0.0.1:%PORT%/ within 20 s. See the "llm_localizator web" window.
  exit /b 1
)
echo Serving on http://127.0.0.1:%PORT%/
if not defined NOMKT echo Marketing site on http://127.0.0.1:%MPORT%/
start "" "http://127.0.0.1:%PORT%/"
exit /b 0

:portfree
netstat -ano | findstr /r /c:":%1 .*LISTENING" >nul
if errorlevel 1 exit /b 0
echo Port %1 is already in use:
netstat -ano | findstr /r /c:":%1 .*LISTENING"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:":%1 .*LISTENING"') do (
  for /f "tokens=1 delims=," %%n in ('tasklist /fi "PID eq %%p" /fo csv /nh') do echo   held by PID %%p %%~n
  goto :portfree_done
)
:portfree_done
exit /b 1

:help
echo Usage: web.bat [--port N] [--marketing-port N] [--no-marketing] [other "llm-localizator web" options]
echo.
echo Starts the llm_localizator review UI on http://127.0.0.1:%PORT%/ (default %PORT%)
echo and the marketing site on http://127.0.0.1:%MPORT%/ (default %MPORT%), loopback only.
echo Needs .venv (run "uv sync" first). Refuses to start when a port is taken.
exit /b 0
