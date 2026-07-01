@echo off
setlocal enabledelayedexpansion

set REPO_ROOT=%~dp0
if "%REPO_ROOT:~-1%"=="\" set REPO_ROOT=%REPO_ROOT:~0,-1%
set VENV_DIR=%REPO_ROOT%\.venv
set PYTHONPATH=%REPO_ROOT%;%PYTHONPATH%

:: 1. Find the best Python executable (check 'py' first, then fall back to 'python')
set PYTHON_EXE=
where py >nul 2>nul
if !errorlevel! equ 0 (
    set PYTHON_EXE=py
) else (
    where python >nul 2>nul
    if !errorlevel! equ 0 (
        set PYTHON_EXE=python
    )
)

:: If Python was not found, show error and exit
if "!PYTHON_EXE!" == "" (
    echo =========================================================================
    echo ❌ ERROR: Python is not installed or not in your system PATH.
    echo Please install Python 3.10+ and check the box that says:
    echo "Add Python to PATH" during installation.
    echo.
    echo Download link: https://www.python.org/downloads/
    echo =========================================================================
    pause
    exit /b 1
)

:: 2. Create virtual environment if it does not exist
if not exist "%VENV_DIR%" (
    echo Creating Python virtual environment in %VENV_DIR% using !PYTHON_EXE!...
    !PYTHON_EXE! -m venv "%VENV_DIR%"
    if !errorlevel! neq 0 (
        echo =========================================================================
        echo ❌ ERROR: Failed to create Python virtual environment.
        echo =========================================================================
        pause
        exit /b 1
    )
)

:: 3. Check if we need to install/update dependencies
set INSTALL_DEPS=0
set NEED_CUDA_UPGRADE=0
if not exist "%VENV_DIR%\.dependencies_installed" set INSTALL_DEPS=1

if exist "%VENV_DIR%\Scripts\python.exe" (
    "%VENV_DIR%\Scripts\python" -c "import torch" >nul 2>nul
    if !errorlevel! neq 0 (
        echo Torch not found or import failed, triggering dependency installation...
        set INSTALL_DEPS=1
    ) else (
        where nvidia-smi >nul 2>nul
        if !errorlevel! equ 0 (
            "%VENV_DIR%\Scripts\python" -c "import torch; assert torch.cuda.is_available()" >nul 2>nul
            if !errorlevel! neq 0 (
                echo ⚠️ NVIDIA GPU detected but PyTorch is currently CPU-only.
                set INSTALL_DEPS=1
                set NEED_CUDA_UPGRADE=1
            )
        )
    )
) else (
    echo ❌ ERROR: Virtual environment exists but is missing python.exe.
    rmdir /s /q "%VENV_DIR%"
    pause
    exit /b 1
)

if !INSTALL_DEPS! equ 1 (
    echo Installing/updating dependencies...
    "%VENV_DIR%\Scripts\python" -m pip install --upgrade pip
    if !NEED_CUDA_UPGRADE! equ 1 (
        "%VENV_DIR%\Scripts\pip" uninstall -y torch
    )
    where nvidia-smi >nul 2>nul
    if !errorlevel! equ 0 (
        echo 🟢 NVIDIA GPU detected. Installing PyTorch with CUDA 12.1 support...
        "%VENV_DIR%\Scripts\pip" install "torch>=2.4.0" --index-url https://download.pytorch.org/whl/cu121
        if !errorlevel! neq 0 (
            echo ⚠️ CUDA PyTorch install failed; attempting CPU PyTorch fallback...
            "%VENV_DIR%\Scripts\pip" install "torch>=2.4.0" --index-url https://download.pytorch.org/whl/cpu
        )
    )
    "%VENV_DIR%\Scripts\pip" install -r "%REPO_ROOT%\requirements.txt"
    if !errorlevel! equ 0 (
        echo. > "%VENV_DIR%\.dependencies_installed"
    ) else (
        echo ❌ ERROR: Failed to install project requirements.
        pause
        exit /b 1
    )
)

if not defined GEOCENTRIC_PORT set GEOCENTRIC_PORT=8000
if not defined GEOCENTRIC_HOST set GEOCENTRIC_HOST=0.0.0.0

echo =========================================================================
echo   Geocentric Launcher
echo =========================================================================
echo   [1] GUI  — Start server and open the web app (default)
echo   [2] CLI  — Geocentric Code terminal agent (local models, no server needed)
echo   [3] Connect — Terminal CLI to a remote Geocentric host
echo =========================================================================
set /p LAUNCH_MODE="Choose mode [1]: "
if "!LAUNCH_MODE!"=="" set LAUNCH_MODE=1

if /i "!LAUNCH_MODE!"=="2" goto launch_cli
if /i "!LAUNCH_MODE!"=="cli" goto launch_cli
if /i "!LAUNCH_MODE!"=="3" goto launch_connect
if /i "!LAUNCH_MODE!"=="connect" goto launch_connect
goto launch_gui

:launch_cli
echo =========================================================================
echo Opening Geocentric CLI (local, in-process — no server needed)...
echo =========================================================================
"%VENV_DIR%\Scripts\python" -m geocentric.cli interactive
goto end

:launch_connect
set /p REMOTE_SERVER="Remote server URL (e.g. http://192.168.1.10:!GEOCENTRIC_PORT!): "
if "!REMOTE_SERVER!"=="" set REMOTE_SERVER=http://127.0.0.1:!GEOCENTRIC_PORT!
echo =========================================================================
echo 🔗 Connecting CLI to !REMOTE_SERVER!
echo =========================================================================
"%VENV_DIR%\Scripts\python" -m geocentric.cli connect --server "!REMOTE_SERVER!"
goto end

:launch_gui
echo =========================================================================
echo 🚀 Starting Geocentric GUI on http://localhost:!GEOCENTRIC_PORT!
echo     Remote CLI clients: run.bat -^> Connect -^> http://YOUR-LAN-IP:!GEOCENTRIC_PORT!
echo =========================================================================
"%VENV_DIR%\Scripts\python" -m geocentric.cli serve --non-interactive --host !GEOCENTRIC_HOST! --port !GEOCENTRIC_PORT!
goto end

:end
pause
