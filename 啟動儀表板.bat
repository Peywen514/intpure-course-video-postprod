@echo off
chcp 65001 >nul
cd /d "%~dp0"

where python >nul 2>nul
if errorlevel 1 (
    echo [錯誤] 找不到 python，請先安裝 Python 3.9+ 並加入 PATH：https://www.python.org/downloads/
    pause
    exit /b 1
)

where ffmpeg >nul 2>nul
if errorlevel 1 (
    rem 不是每台機器 winget 裝的 ffmpeg 版本號都一樣，用萬用字元找，不寫死版本
    for /d %%D in ("%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-*-full_build") do (
        if exist "%%D\bin\ffmpeg.exe" set "PATH=%%D\bin;%PATH%"
    )
    where ffmpeg >nul 2>nul
    if errorlevel 1 (
        echo [錯誤] 找不到 ffmpeg，請先安裝：winget install Gyan.FFmpeg
        echo 安裝完成後請重新開啟一個新的視窗再執行本程式一次。
        pause
        exit /b 1
    )
)

python -c "import stable_whisper" >nul 2>nul
if errorlevel 1 (
    echo 第一次執行，正在安裝所需套件（faster-whisper / stable-ts / auto-editor）...
    echo 需要網路連線，第一次可能要幾分鐘，請耐心等候。
    echo.
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo [錯誤] 套件安裝失敗，請確認網路連線後重新執行本程式一次。
        pause
        exit /b 1
    )
)

echo 啟動影片後製儀表板...
echo 瀏覽器會自動開啟，關閉這個黑色視窗即會停止伺服器。
echo.
python app.py

pause
