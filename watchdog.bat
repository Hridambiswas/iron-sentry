@echo off
:: watchdog.bat — Iron-Sentry Windows Task Scheduler Watchdog
:: Restarts main.py if it crashes. Schedule this in Task Scheduler.
:: Trigger: At system startup + repeat every 5 minutes

:LOOP
echo [%date% %time%] Starting Iron-Sentry...
cd /d C:\Users\KIIT0001\Desktop\iron_sentry
python main.py >> iron_sentry_watchdog.log 2>&1
echo [%date% %time%] Process exited. Restarting in 10s...
timeout /t 10 /nobreak >nul
goto LOOP
