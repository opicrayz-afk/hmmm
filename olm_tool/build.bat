@echo off
title Build OLM Tool Pro v11

echo ============================================================
echo   BUILD OLM TOOL PRO v11.0
echo ============================================================
echo.

echo [1/4] Kiem tra moi truong...
python --version >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python.
    pause & exit /b 1
)

where pyinstaller >nul 2>&1
if errorlevel 1 (
    echo [LOI] Chua cai PyInstaller. Chay: pip install pyinstaller
    pause & exit /b 1
)

REM Kiem tra thu muc assets
if not exist "assets" (
    echo [LOI] Thieu thu muc assets\. Tao truoc:
    echo     mkdir assets
    echo     ^(dat icon.png 512x512 vao assets^)
    pause & exit /b 1
)

if not exist "app_icon.ico" (
    echo [WARN] Khong co app_icon.ico. EXE se khong co icon.
    timeout /t 3 /nobreak >nul
)

echo [2/4] Don build cu...
if exist dist rmdir /s /q dist
if exist build rmdir /s /q build
if exist OLMToolPro.spec del /q OLMToolPro.spec

echo [3/4] Build bang PyInstaller (co the mat 2-5 phut)...
pyinstaller ^
  --onefile ^
  --noconsole ^
  --clean ^
  --name "OLMToolPro" ^
  --icon "app_icon.ico" ^
  --add-data "assets;assets" ^
  --add-data "app_icon.ico;." ^
  --hidden-import "playwright" ^
  --hidden-import "playwright.async_api" ^
  --hidden-import "playwright._impl" ^
  --hidden-import "playwright._impl._driver" ^
  --hidden-import "curl_cffi" ^
  --hidden-import "curl_cffi.requests" ^
  --hidden-import "webview" ^
  --hidden-import "webview.platforms.edgechromium" ^
  --hidden-import "webview.platforms.winforms" ^
  --collect-all "playwright" ^
  --collect-submodules "curl_cffi" ^
  --exclude-module "webview.platforms.android" ^
  --exclude-module "webview.platforms.cocoa" ^
  --exclude-module "webview.platforms.gtk" ^
  --exclude-module "webview.platforms.qt" ^
  --exclude-module "webview.platforms.cef" ^
  --exclude-module "tkinter.test" ^
  --exclude-module "test" ^
  --exclude-module "unittest" ^
  --exclude-module "pydoc_data" ^
  --exclude-module "matplotlib" ^
  --exclude-module "numpy" ^
  --exclude-module "scipy" ^
  --exclude-module "pandas" ^
  --exclude-module "pygame" ^
  olm.py

if errorlevel 1 (
    echo.
    echo [LOI] Build that bai!
    pause & exit /b 1
)

echo [4/4] Hoan tat!
echo.
echo File EXE: %CD%\dist\OLMToolPro.exe
echo.

if exist "dist\OLMToolPro.exe" (
    for %%A in ("dist\OLMToolPro.exe") do (
        echo Kich thuoc: %%~zA bytes
    )
)

echo.
echo Ban co muon chay EXE ngay khong? (Y/N)
set /p choice=
if /i "%choice%"=="Y" (
    cd dist
    OLMToolPro.exe
)
pause