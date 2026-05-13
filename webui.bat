@echo off
setlocal
chcp 65001 >nul
title VN Generator
color 0A

:: ===== Python / venv =====
set "VENV_DIR=.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if exist "%VENV_PYTHON%" (
    set "PYTHON_EXE=%VENV_PYTHON%"
) else (
    set "PYTHON_EXE=python"
)

:: ===== 默认模型（本次启动会话有效）=====
if not defined SCRIPT_MODEL set "SCRIPT_MODEL=[满血A]gemini-3-pro-preview-maxthinking"
if not defined CODE_MODEL set "CODE_MODEL=claude-sonnet-4-6"

:: ===== 图片生成默认配置（本次启动会话有效）=====
if not defined IMAGE_ENABLED set "IMAGE_ENABLED=0"
if not defined IMAGE_PROVIDER set "IMAGE_PROVIDER=none"
if not defined IMAGE_MODEL set "IMAGE_MODEL="
if not defined LOCAL_SD_BASE_URL set "LOCAL_SD_BASE_URL=http://127.0.0.1:7861"

:: ===== 固定默认本地 SD 模型 =====
set "DEFAULT_LOCAL_SD_MODEL=sd1.5\anything-v5.safetensors [7f96a1a9ca]"
set "DEFAULT_LOCAL_SD_URL=http://127.0.0.1:7861"
set "DEFAULT_REMOTE_IMAGE_MODEL=[官]gemini-3.1-flash-image-preview"

echo ========================================
echo    VN Generator
echo ========================================
echo.

call :CHECK_PYTHON
if errorlevel 1 (
    pause
    exit /b 1
)

call :CHECK_ENV_READY
if errorlevel 1 (
    pause
    exit /b 1
)

if not exist "font\" (
    mkdir font
    echo [OK] font directory created
)

echo [i] Working directory: %CD%
echo [i] Python executable: %PYTHON_EXE%
echo.

:MENU
echo ----------------------------------------
echo Current Script Model : %SCRIPT_MODEL%
echo Current Code   Model : %CODE_MODEL%
echo Image Enabled        : %IMAGE_ENABLED%
echo Image Provider       : %IMAGE_PROVIDER%
echo Image Model          : %IMAGE_MODEL%
echo Local SD Base URL    : %LOCAL_SD_BASE_URL%
echo ----------------------------------------
echo 1. Start WebUI
echo 2. Start CLI
echo 3. Select Script Model
echo 4. Select Code Model
echo 5. Toggle Image Generation
echo 6. Select Image Provider
echo 7. Setup / Install Dependencies
echo 8. Show Current Config
echo 9. Open Font Folder
echo A. Edit .env
echo B. Recreate Virtual Environment
echo C. Exit
echo.

choice /c 123456789ABC /n /m "Select (1-9,A-C): "
set "sel=%errorlevel%"

if "%sel%"=="1" goto WEBUI
if "%sel%"=="2" goto CLI
if "%sel%"=="3" goto SCRIPT_MODEL_MENU
if "%sel%"=="4" goto CODE_MODEL_MENU
if "%sel%"=="5" goto TOGGLE_IMAGE
if "%sel%"=="6" goto IMAGE_PROVIDER_MENU
if "%sel%"=="7" goto SETUP
if "%sel%"=="8" goto SHOW_CONFIG
if "%sel%"=="9" goto FONT
if "%sel%"=="10" goto EDITENV
if "%sel%"=="11" goto RECREATE_VENV
if "%sel%"=="12" goto EXIT

goto MENU


:CHECK_PYTHON
if exist "%VENV_PYTHON%" (
    set "PYTHON_EXE=%VENV_PYTHON%"
    "%PYTHON_EXE%" --version >nul 2>&1
    if errorlevel 1 (
        color 0C
        echo [X] Virtual environment Python is broken: %VENV_PYTHON%
        exit /b 1
    )
    for /f "tokens=2" %%i in ('"%PYTHON_EXE%" --version') do echo [OK] Venv Python %%i
    exit /b 0
)

python --version >nul 2>&1
if errorlevel 1 (
    color 0C
    echo [X] Python not found. Please install Python 3.10+
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version') do echo [OK] System Python %%i
exit /b 0


:CHECK_ENV_READY
if not exist "%VENV_PYTHON%" (
    color 0E
    echo [!] Virtual environment not found.
    choice /c YN /n /m "Create .venv now? (Y/N): "
    if errorlevel 2 (
        color 0A
        echo [i] You can create it later from menu option 7 or B.
        exit /b 0
    )
    call :CREATE_VENV
    if errorlevel 1 exit /b 1
)

set "PYTHON_EXE=%VENV_PYTHON%"

if not exist ".env" (
    color 0E
    echo [!] .env not found. A template will be created.
    (
        echo DASHSCOPE_API_KEY=sk-xxxxx
        echo GEMAI_API_KEY=sk-xxxxx
        echo SCRIPT_MODEL=[满血A]gemini-3-pro-preview-maxthinking
        echo CODE_MODEL=claude-sonnet-4-6
        echo IMAGE_ENABLED=0
        echo IMAGE_PROVIDER=none
        echo IMAGE_MODEL=
        echo LOCAL_SD_BASE_URL=http://127.0.0.1:7861
    ) > .env
    echo [OK] .env template created
) else (
    echo [OK] Environment file ready
)

if not exist "%VENV_DIR%\_deps_installed.flag" (
    color 0E
    echo [!] Dependencies not installed in venv.
    choice /c YN /n /m "Install dependencies now? (Y/N): "
    if errorlevel 2 (
        color 0A
        echo [i] You can install later from menu option 7.
        exit /b 0
    )
    call :INSTALL_DEPS
    if errorlevel 1 exit /b 1
)

exit /b 0


:CREATE_VENV
echo [i] Creating virtual environment...
python -m venv "%VENV_DIR%"
if errorlevel 1 (
    color 0C
    echo [X] Failed to create virtual environment.
    exit /b 1
)
set "PYTHON_EXE=%VENV_PYTHON%"
echo [OK] Virtual environment created: %VENV_DIR%
exit /b 0


:INSTALL_DEPS
if not exist "%VENV_PYTHON%" (
    color 0C
    echo [X] .venv not found. Please create it first.
    exit /b 1
)

set "PYTHON_EXE=%VENV_PYTHON%"

echo [i] Upgrading pip...
"%PYTHON_EXE%" -m pip install --upgrade pip
if errorlevel 1 (
    color 0C
    echo [X] pip upgrade failed.
    exit /b 1
)

echo [i] Installing pinned front-end compatibility packages...
"%PYTHON_EXE%" -m pip install gradio==4.44.1 gradio_client==1.3.0 huggingface_hub==0.25.2 pydantic==2.8.2 fastapi==0.112.2 starlette==0.38.2
if errorlevel 1 (
    color 0C
    echo [X] Failed to install Gradio compatibility packages.
    exit /b 1
)

echo [i] Installing pinned OpenAI/httpx compatibility packages...
"%PYTHON_EXE%" -m pip install "openai>=1.30.0,<2.0.0" "httpx>=0.27.0,<0.28.0"
if errorlevel 1 (
    color 0C
    echo [X] Failed to install openai/httpx compatible versions.
    exit /b 1
)

echo [i] Installing requirements...
"%PYTHON_EXE%" -m pip install -r requirements.txt
if errorlevel 1 (
    color 0C
    echo [X] requirements installation failed.
    exit /b 1
)

echo ok > "%VENV_DIR%\_deps_installed.flag"
echo [OK] Dependencies installed successfully
exit /b 0


:SETUP
cls
echo ========================================
echo   Setup / Install Dependencies
echo ========================================
echo.
echo 1. Create .venv if missing
echo 2. Install / Repair dependencies
echo 3. Back
echo.

choice /c 123 /n /m "Select (1-3): "
set "sel=%errorlevel%"

if "%sel%"=="1" (
    if exist "%VENV_PYTHON%" (
        echo [i] .venv already exists.
    ) else (
        call :CREATE_VENV
    )
    echo.
    pause
    cls
    goto MENU
)

if "%sel%"=="2" (
    if not exist "%VENV_PYTHON%" call :CREATE_VENV
    call :INSTALL_DEPS
    echo.
    pause
    cls
    goto MENU
)

if "%sel%"=="3" goto MENU
goto MENU


:RECREATE_VENV
cls
echo ========================================
echo   Recreate Virtual Environment
echo ========================================
echo.
echo This will delete .venv and create a fresh one.
echo.
choice /c YN /n /m "Continue? (Y/N): "
if errorlevel 2 goto MENU

if exist "%VENV_DIR%" (
    rmdir /s /q "%VENV_DIR%"
)

call :CREATE_VENV
if errorlevel 1 (
    pause
    cls
    goto MENU
)

call :INSTALL_DEPS
echo.
pause
cls
goto MENU


:SCRIPT_MODEL_MENU
cls
echo ========================================
echo   Select Script Model
echo ========================================
echo.
echo Current: %SCRIPT_MODEL%
echo.
echo 1. [满血A]gemini-3-pro-preview-maxthinking
echo 2. gpt-5.1
echo 3. gpt-5.4
echo 4. qwen-max
echo 5. gemma-4-31b
echo 6. Back
echo.

choice /c 123456 /n /m "Select (1-6): "
set "sel=%errorlevel%"

if "%sel%"=="1" set "SCRIPT_MODEL=[满血A]gemini-3-pro-preview-maxthinking"
if "%sel%"=="2" set "SCRIPT_MODEL=gpt-5.1"
if "%sel%"=="3" set "SCRIPT_MODEL=gpt-5.4"
if "%sel%"=="4" set "SCRIPT_MODEL=qwen-max"
if "%sel%"=="5" set "SCRIPT_MODEL=gemma-4-31b"
if "%sel%"=="6" goto MENU

cls
echo [OK] Script model set to: %SCRIPT_MODEL%
echo.
goto MENU


:CODE_MODEL_MENU
cls
echo ========================================
echo   Select Code Model
echo ========================================
echo.
echo Current: %CODE_MODEL%
echo.
echo 1. claude-sonnet-4-6
echo 2. gpt-5.4
echo 3. gpt-5.3-codex
echo 4. gpt-5.2-codex
echo 5. gpt-5.1-codex-max
echo 6. [满血A]gemini-3.1-pro-preview-maxthinking
echo 7. qwen-plus
echo 8. Back
echo.

choice /c 12345678 /n /m "Select (1-8): "
set "sel=%errorlevel%"

if "%sel%"=="1" set "CODE_MODEL=claude-sonnet-4-6"
if "%sel%"=="2" set "CODE_MODEL=gpt-5.4"
if "%sel%"=="3" set "CODE_MODEL=gpt-5.3-codex"
if "%sel%"=="4" set "CODE_MODEL=gpt-5.2-codex"
if "%sel%"=="5" set "CODE_MODEL=gpt-5.1-codex-max"
if "%sel%"=="6" set "CODE_MODEL=[满血A]gemini-3.1-pro-preview-maxthinking"
if "%sel%"=="7" set "CODE_MODEL=qwen-plus"
if "%sel%"=="8" goto MENU

cls
echo [OK] Code model set to: %CODE_MODEL%
echo.
goto MENU


:TOGGLE_IMAGE
cls
echo ========================================
echo   Toggle Image Generation
echo ========================================
echo.
echo Current IMAGE_ENABLED: %IMAGE_ENABLED%
echo Current IMAGE_PROVIDER: %IMAGE_PROVIDER%
echo.

if "%IMAGE_ENABLED%"=="1" (
    choice /c YN /n /m "Disable image generation? (Y/N): "
    if errorlevel 2 goto MENU

    set "IMAGE_ENABLED=0"
    set "IMAGE_PROVIDER=none"
    set "IMAGE_MODEL="
    set "LOCAL_SD_BASE_URL=%DEFAULT_LOCAL_SD_URL%"

    cls
    echo [OK] Image generation disabled
    echo.
    goto MENU
) else (
    choice /c YN /n /m "Enable image generation? (Y/N): "
    if errorlevel 2 goto MENU

    set "IMAGE_ENABLED=1"
    cls
    echo [OK] Image generation enabled
    echo [i] Next step: choose provider
    echo.
    goto IMAGE_PROVIDER_MENU
)


:IMAGE_PROVIDER_MENU
cls
echo ========================================
echo   Select Image Provider
echo ========================================
echo.
echo Current: %IMAGE_PROVIDER%
echo.
echo 1. none
echo 2. local_sd
echo 3. remote_api
echo 4. Back
echo.

choice /c 1234 /n /m "Select (1-4): "
set "sel=%errorlevel%"

if "%sel%"=="1" (
    set "IMAGE_ENABLED=0"
    set "IMAGE_PROVIDER=none"
    set "IMAGE_MODEL="
    set "LOCAL_SD_BASE_URL=%DEFAULT_LOCAL_SD_URL%"
    cls
    echo [OK] Image provider set to: none
    echo [OK] Image generation disabled
    echo.
    goto MENU
)

if "%sel%"=="2" (
    set "IMAGE_ENABLED=1"
    set "IMAGE_PROVIDER=local_sd"
    set "IMAGE_MODEL=%DEFAULT_LOCAL_SD_MODEL%"
    set "LOCAL_SD_BASE_URL=%DEFAULT_LOCAL_SD_URL%"
    cls
    echo [OK] Image provider set to: local_sd
    echo [OK] Image model fixed to: %IMAGE_MODEL%
    echo [OK] Local SD Base URL fixed to: %LOCAL_SD_BASE_URL%
    echo.
    goto MENU
)

if "%sel%"=="3" (
    set "IMAGE_ENABLED=1"
    set "IMAGE_PROVIDER=remote_api"
    goto REMOTE_IMAGE_MODEL_MENU
)

if "%sel%"=="4" goto MENU
goto MENU


:REMOTE_IMAGE_MODEL_MENU
cls
echo ========================================
echo   Select Remote Image Model
echo ========================================
echo.
echo Current Remote Model: %IMAGE_MODEL%
echo.
echo 1. [官]gemini-3.1-flash-image-preview
echo 2. gpt-image-2
echo 3. Back
echo.

choice /c 123 /n /m "Select (1-3): "
set "sel=%errorlevel%"

if "%sel%"=="1" (
    set "IMAGE_MODEL=[官]gemini-3.1-flash-image-preview"
    cls
    echo [OK] Remote image provider set to: remote_api
    echo [OK] Remote image model set to: %IMAGE_MODEL%
    echo.
    goto MENU
)

if "%sel%"=="2" (
    set "IMAGE_MODEL=gpt-image-2"
    cls
    echo [OK] Remote image provider set to: remote_api
    echo [OK] Remote image model set to: %IMAGE_MODEL%
    echo.
    goto MENU
)

if "%sel%"=="3" goto IMAGE_PROVIDER_MENU
goto IMAGE_PROVIDER_MENU


:SHOW_CONFIG
cls
echo ========================================
echo   Current Runtime Config
echo ========================================
echo Script Model     : %SCRIPT_MODEL%
echo Code Model       : %CODE_MODEL%
echo Image Enabled    : %IMAGE_ENABLED%
echo Image Provider   : %IMAGE_PROVIDER%
echo Image Model      : %IMAGE_MODEL%
echo Local SD Base URL: %LOCAL_SD_BASE_URL%
echo Python Executable: %PYTHON_EXE%
echo Venv Exists      :
if exist "%VENV_PYTHON%" (
    echo   YES
) else (
    echo   NO
)
echo ========================================
echo.
pause
cls
goto MENU


:CHECK_API
if not exist "%VENV_PYTHON%" (
    color 0C
    echo.
    echo [X] Virtual environment not found.
    echo [i] Please create it first from menu option 7 or B.
    echo.
    goto MENU
)

set "PYTHON_EXE=%VENV_PYTHON%"

"%PYTHON_EXE%" -c "import os, openai; from dotenv import load_dotenv; load_dotenv(); key_gemai=os.getenv('GEMAI_API_KEY'); key_qwen=os.getenv('DASHSCOPE_API_KEY'); script_model=os.getenv('SCRIPT_MODEL','[满血A]gemini-3-pro-preview-maxthinking'); code_model=os.getenv('CODE_MODEL','claude-sonnet-4-6'); image_enabled=os.getenv('IMAGE_ENABLED','0')=='1'; image_provider=os.getenv('IMAGE_PROVIDER','none'); script_is_qwen=('qwen' in script_model.lower()); code_is_qwen=('qwen' in code_model.lower()); assert ((key_qwen if script_is_qwen else key_gemai)), 'SCRIPT API KEY missing'; assert ((key_qwen if code_is_qwen else key_gemai)), 'CODE API KEY missing'; script_client=openai.OpenAI(api_key=(key_qwen if script_is_qwen else key_gemai), base_url=('https://dashscope.aliyuncs.com/compatible-mode/v1' if script_is_qwen else 'https://api.gemai.cc/v1')); code_client=openai.OpenAI(api_key=(key_qwen if code_is_qwen else key_gemai), base_url=('https://dashscope.aliyuncs.com/compatible-mode/v1' if code_is_qwen else 'https://api.gemai.cc/v1')); script_client.chat.completions.create(model=script_model, messages=[{'role':'user','content':'Hi'}], max_tokens=3, timeout=15); code_client.chat.completions.create(model=code_model, messages=[{'role':'user','content':'Hi'}], max_tokens=3, timeout=15); assert (not (image_enabled and image_provider=='remote_api')) or key_gemai, 'REMOTE IMAGE API KEY missing'; print('API CHECK OK')"
if errorlevel 1 (
    color 0E
    echo.
    echo [!] API check failed.
    echo [i] Current Script Model: %SCRIPT_MODEL%
    echo [i] Current Code   Model: %CODE_MODEL%
    echo [i] You may continue to start UI and test manually.
    echo.
    choice /c YN /n /m "Continue startup anyway? (Y/N): "
    if errorlevel 2 (
        color 0A
        cls
        goto MENU
    )
)
goto :eof


:WEBUI
cls
echo [i] Checking API...
call :CHECK_API
cls
echo [i] Starting WebUI...
echo [i] URL: http://127.0.0.1:7860
echo [i] Script Model: %SCRIPT_MODEL%
echo [i] Code Model  : %CODE_MODEL%
echo [i] Image Enabled: %IMAGE_ENABLED%
echo [i] Image Provider: %IMAGE_PROVIDER%
echo [i] Image Model: %IMAGE_MODEL%
echo [i] Local SD URL: %LOCAL_SD_BASE_URL%
echo [i] Python: %PYTHON_EXE%
echo [i] Press Ctrl+C to stop
echo.

"%PYTHON_EXE%" webui.py

echo.
echo [i] WebUI exited. Copy the error text above if needed.
pause
cls
goto MENU


:CLI
cls
echo [i] Checking API...
call :CHECK_API
cls
echo [i] Starting CLI mode...
echo [i] Script Model  : %SCRIPT_MODEL%
echo [i] Code Model    : %CODE_MODEL%
echo [i] Image Enabled : %IMAGE_ENABLED%
echo [i] Image Provider: %IMAGE_PROVIDER%
echo [i] Image Model   : %IMAGE_MODEL%
echo [i] Local SD URL  : %LOCAL_SD_BASE_URL%
echo [i] Python        : %PYTHON_EXE%
echo.
"%PYTHON_EXE%" main.py
echo.
pause
cls
goto MENU


:FONT
if not exist "font\" mkdir font
start "" explorer "%CD%\font"
goto MENU


:EDITENV
if not exist ".env" (
    (
        echo DASHSCOPE_API_KEY=sk-xxxxx
        echo GEMAI_API_KEY=sk-xxxxx
        echo SCRIPT_MODEL=[满血A]gemini-3-pro-preview-maxthinking
        echo CODE_MODEL=claude-sonnet-4-6
        echo IMAGE_ENABLED=0
        echo IMAGE_PROVIDER=none
        echo IMAGE_MODEL=
        echo LOCAL_SD_BASE_URL=http://127.0.0.1:7861
    ) > .env
)
start "" notepad ".env"
goto MENU


:EXIT
endlocal
exit /b 0