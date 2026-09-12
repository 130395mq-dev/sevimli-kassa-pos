@echo off
chcp 65001 >nul
REM ============================================================
REM   Sevimli Kassa - Windows EXE yigish (onedir)
REM   Mos Python (3.10-3.13) ozi tanlanadi. UCRT fayllari ham
REM   qadaladi (eski Windows'da ilova ochilishi uchun).
REM ============================================================
setlocal
cd /d "%~dp0"

echo.
echo === Sevimli Kassa EXE yigish ===
echo.

REM --- 1) Mos Python topamiz (3.13 -> 3.12 -> 3.11 -> 3.10) ---
set "PYEXE="
py -3.13 --version >nul 2>&1 && set "PYEXE=py -3.13"
if not defined PYEXE py -3.12 --version >nul 2>&1 && set "PYEXE=py -3.12"
if not defined PYEXE py -3.11 --version >nul 2>&1 && set "PYEXE=py -3.11"
if not defined PYEXE py -3.10 --version >nul 2>&1 && set "PYEXE=py -3.10"

if not defined PYEXE (
  echo [XATO] Mos Python topilmadi.
  echo         python.org dan Python 3.13 ornating ^(Add to PATH belgilang^),
  echo         songra shu faylni qayta ishga tushiring.
  pause
  exit /b 1
)

echo Python: %PYEXE%
%PYEXE% --version
echo.

REM --- 2) UCRT fayllarini ochamiz (eski Windows uchun kerak) ---
if exist build\ucrt.zip (
  if exist build\ucrt rmdir /s /q build\ucrt
  powershell -NoProfile -Command "Expand-Archive -Path 'build\ucrt.zip' -DestinationPath 'build\ucrt' -Force"
)

REM --- 3) Kutubxonalar ---
echo [1/4] Kutubxonalar ornatilmoqda...
%PYEXE% -m pip install --upgrade pip >nul
%PYEXE% -m pip install -r requirements.txt || goto err
%PYEXE% -m pip install pyinstaller==6.11.1 || goto err

REM --- 4) Eski natijalarni tozalash (16-bit muammosi oldini oladi) ---
echo [2/4] Eski fayllar tozalanmoqda...
if exist dist rmdir /s /q dist
if exist build\SevimliKassa rmdir /s /q build\SevimliKassa
if exist SevimliKassa.exe del /q SevimliKassa.exe

REM --- 5) Yigish (onedir) ---
echo [3/4] EXE yigilmoqda (bir necha daqiqa)...
%PYEXE% -m PyInstaller build\SevimliKassa.spec --noconfirm --clean || goto err

if not exist "dist\SevimliKassa\SevimliKassa.exe" (
  echo [XATO] Yigilmadi: dist\SevimliKassa\SevimliKassa.exe topilmadi.
  pause
  exit /b 1
)

REM UCRT haqiqatan qadalganini tekshiramiz
if not exist "dist\SevimliKassa\_internal\ucrtbase.dll" (
  echo [OGOHLANTIRISH] ucrtbase.dll qadalmadi - eski Windows'da ochilmasligi mumkin.
)

REM --- 6) ZIP qadoqlash ---
echo [4/4] ZIP qadoqlanmoqda...
if exist dist\SevimliKassa.zip del /q dist\SevimliKassa.zip
powershell -NoProfile -Command "Compress-Archive -Path 'dist\SevimliKassa' -DestinationPath 'dist\SevimliKassa.zip' -Force" || goto err

echo.
echo === TAYYOR ===
echo   Papka:  dist\SevimliKassa\
echo   ZIP:    dist\SevimliKassa.zip
echo.
echo   Keyingi qadam: panel, Versiyalar, yangi versiya, shu ZIP ni yuklang.
echo.
pause
exit /b 0

:err
echo.
echo [XATO] Yigishda xato boldi. Yuqoridagi matnni oqing.
pause
exit /b 1
