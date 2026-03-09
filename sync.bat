@echo off
cd /d "%~dp0"

for /f %%b in ('git branch --show-current') do set "BRANCH=%%b"
if "%BRANCH%"=="" (
  echo [sync] Could not determine current git branch.
  exit /b 1
)

set "MSG="
if "%~1"=="" (
  set "MSG=Sync update %date% %time%"
) else (
  set "MSG=%~1"
)

set "HAS_CHANGES=0"
for /f %%x in ('git status --porcelain') do (
  set "HAS_CHANGES=1"
  goto :status_done
)
:status_done

if "%HAS_CHANGES%"=="0" (
  echo [sync] No changes to commit.
  exit /b 0
)

echo [sync] Branch: %BRANCH%
echo [sync] Commit: %MSG%

git add -A
if errorlevel 1 (
  echo [sync] git add failed.
  exit /b 1
)

git commit -m "%MSG%"
if errorlevel 1 (
  echo [sync] git commit failed.
  exit /b 1
)

git push origin %BRANCH%
if errorlevel 1 (
  echo [sync] git push failed.
  exit /b 1
)

if not "%JENKINS_TRIGGER_URL%"=="" (
  echo [sync] Triggering Jenkins...
  python "%~dp0scripts\trigger_jenkins.py"
  if errorlevel 1 (
    echo [sync] Jenkins trigger failed.
    exit /b 1
  )
)

echo [sync] Done.
exit /b 0
