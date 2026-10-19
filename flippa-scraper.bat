@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "PROJECT=C:\Users\kevin\OneDrive\Desktop\Important\Computer Science\flippa-scraper"
cd /d "%PROJECT%"
if not exist "%PROJECT%\serve.py" goto :missing_project
title flippa-scraper

set "OWN_SERVER=0"
set "SERVER_PID="
set "PYTHONUNBUFFERED=1"
set "URL="
set "BIND_HOST="
set "BIND_PORT="

python -c "import sys" >nul 2>&1
if errorlevel 1 goto :no_python

call :read_url
if errorlevel 1 goto :bad_url

call :port_open
if "%PORT_OPEN%"=="1" goto :port_busy

echo Starting the filter page at %URL%
echo A headless scrape, without this page, is: python scrape.py
start "flippa-scraper" /b python "%PROJECT%\serve.py"
set "OWN_SERVER=1"
call :capture_pid

set /a TRIES=0
:poll
set /a TRIES+=1
call :http_up
if "%HTTP_UP%"=="1" goto :browser
if defined SERVER_PID call :pid_alive
if defined SERVER_PID if "%PID_ALIVE%"=="0" goto :start_failed
if %TRIES% GEQ 20 goto :start_failed
timeout /t 1 /nobreak >nul
goto :poll

:port_busy
echo Port %BIND_PORT% is already in use.
echo Something is already listening on %URL%.
echo This window will not start another server and will not close that program.
echo If that program is this filter page, use the browser window that is already open.
echo Otherwise, free port %BIND_PORT% and run this again.
echo.
pause
exit /b 1

:bad_url
echo.
echo The filter page could not be reached.
echo.
pause
exit /b 1

:missing_project
echo serve.py was not found in:
echo   %PROJECT%
echo Edit the PROJECT line at the top of this file if the folder moved.
echo.
pause
exit /b 1

:no_python
echo Python was not found.
echo flippa-scraper needs Python available as "python" on PATH.
echo.
pause
exit /b 1

:start_failed
echo flippa-scraper did not start.
echo Nothing answered at %URL%.
echo If Python failed, the message is above.
call :kill_owned
echo.
pause
exit /b 1

:browser
call :find_chrome
if not defined CHROME goto :no_chrome
start "" "%CHROME%" "%URL%"
echo flippa-scraper is ready: %URL%
goto :stay

:no_chrome
echo Google Chrome was not found.
echo Checked:
echo   %ProgramFiles%\Google\Chrome\Application\chrome.exe
echo   %ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe
echo   %LocalAppData%\Google\Chrome\Application\chrome.exe
echo.
echo flippa-scraper is ready: %URL%

:stay
if not "%OWN_SERVER%"=="1" goto :visitor
echo Leave this window open. Closing it stops the server.
:keepalive
timeout /t 30 /nobreak >nul
goto :keepalive

:visitor
echo.
echo Press any key to close this window. The server will keep running.
pause
exit /b 0

:read_url
set "URL="
set "BIND_HOST="
set "BIND_PORT="
set "URL_INFO=%TEMP%\flippa-scraper-url.txt"
del "%URL_INFO%" >nul 2>&1
python -c "from serve import print_listen_target; print_listen_target()" > "%URL_INFO%"
if errorlevel 1 (
  del "%URL_INFO%" >nul 2>&1
  exit /b 1
)
for /f "usebackq tokens=1,2,3 delims=|" %%A in ("%URL_INFO%") do (
  set "URL=%%A"
  set "BIND_HOST=%%B"
  set "BIND_PORT=%%C"
)
del "%URL_INFO%" >nul 2>&1
if not defined URL exit /b 1
if not defined BIND_HOST exit /b 1
if not defined BIND_PORT exit /b 1
exit /b 0

:port_open
set "PORT_OPEN=0"
powershell -NoProfile -NonInteractive -Command "try { $c = New-Object System.Net.Sockets.TcpClient; $iar = $c.BeginConnect($env:BIND_HOST, [int]$env:BIND_PORT, $null, $null); if (-not $iar.AsyncWaitHandle.WaitOne(1000, $false)) { exit 1 }; $c.EndConnect($iar); exit 0 } catch { exit 1 } finally { if ($c) { $c.Close() } }" >nul 2>&1
if not errorlevel 1 set "PORT_OPEN=1"
exit /b 0

:http_up
set "HTTP_UP=0"
where curl.exe >nul 2>&1
if errorlevel 1 (
  powershell -NoProfile -NonInteractive -Command "try { $r = [System.Net.HttpWebRequest]::Create($env:URL); $r.Timeout = 2000; $r.Method = 'GET'; $s = $r.GetResponse(); $s.Close(); exit 0 } catch { exit 1 }" >nul 2>&1
  if not errorlevel 1 set "HTTP_UP=1"
) else (
  curl.exe -fsS -o NUL --connect-timeout 1 --max-time 2 "%URL%" >nul 2>&1
  if not errorlevel 1 set "HTTP_UP=1"
)
exit /b 0

:capture_pid
set "SERVER_PID="
del "%TEMP%\flippa-scraper-owner.pid" >nul 2>&1
powershell -NoProfile -NonInteractive -Command "$me = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID); $cmdPid = $me.ParentProcessId; $match = @(); foreach ($i in 1..10) { $match = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.ParentProcessId -eq $cmdPid -and $_.CommandLine -match '(?<![\w])serve\.py(?![\w])' }); if ($match.Count -gt 0) { break }; Start-Sleep -Milliseconds 200 }; if ($match.Count -eq 0) { exit 1 }; [System.IO.File]::WriteAllText([System.IO.Path]::Combine($env:TEMP, 'flippa-scraper-owner.pid'), ([string]$match[0].ProcessId + [char]10), [System.Text.Encoding]::ASCII); exit 0" >nul 2>&1
if exist "%TEMP%\flippa-scraper-owner.pid" set /p SERVER_PID=<"%TEMP%\flippa-scraper-owner.pid"
del "%TEMP%\flippa-scraper-owner.pid" >nul 2>&1
exit /b 0

:pid_alive
set "PID_ALIVE=0"
tasklist /FI "PID eq %SERVER_PID%" /NH 2>nul | findstr /C:"%SERVER_PID%" >nul
if not errorlevel 1 set "PID_ALIVE=1"
exit /b 0

:find_chrome
set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not defined CHROME if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"
exit /b 0

:kill_owned
powershell -NoProfile -NonInteractive -Command "$me = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $PID); $cmdPid = $me.ParentProcessId; Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.ParentProcessId -eq $cmdPid -and $_.CommandLine -match '(?<![\w])serve\.py(?![\w])' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }" >nul 2>&1
exit /b 0
