@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "FFMPEG_BIN=%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-8.1.2-full_build\bin"
if exist "%FFMPEG_BIN%\ffmpeg.exe" (
    set "PATH=%FFMPEG_BIN%;%PATH%"
) else (
    where ffmpeg >nul 2>nul
    if errorlevel 1 (
        echo [錯誤] 找不到 ffmpeg，請先安裝：winget install Gyan.FFmpeg
        pause
        exit /b 1
    )
)

where python >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 找不到 python，請先安裝 Python 3.9+ 並加入 PATH
    pause
    exit /b 1
)

echo 啟動影片後製儀表板...
echo 瀏覽器會自動開啟，關閉這個黑色視窗即會停止伺服器。
echo.
python app.py

pause
