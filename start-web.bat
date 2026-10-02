@echo off
chcp 65001 >nul
setlocal
set PORT=8080

cd /d "%~dp0"

echo.
echo  正在启动本地网页服务…
echo  地址：http://localhost:%PORT%/
echo.
echo  请用浏览器打开上述地址（约 1 秒后自动打开）。
echo  不要双击 web\index.html，否则 PDF 模块会被浏览器拦截。
echo  关闭本窗口即停止服务。
echo.

start "" cmd /c "timeout /t 1 /nobreak >nul & start http://localhost:%PORT%/"
python -m http.server %PORT% --directory web
if errorlevel 1 (
  echo.
  echo  启动失败：请确认已安装 Python，并已加入 PATH。
  echo  也可手动运行：
  echo    python -m http.server %PORT% --directory web
  echo  然后访问 http://localhost:%PORT%/
  pause
)
