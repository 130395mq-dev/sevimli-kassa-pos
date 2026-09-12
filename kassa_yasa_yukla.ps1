# ============================================================
#  Sevimli Kassa - yangi versiyani YIG'IB, panelga YUKLAYDI.
#  Versiya raqami pos\version.py dan olinadi.
#  Yuklashni kassa_faqat_yukla.ps1 bajaradi (kod bitta joyda).
# ============================================================
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$logFile = Join-Path ([Environment]::GetFolderPath('Desktop')) "kassa-yigish-log.txt"
try { Start-Transcript -Path $logFile -Force | Out-Null } catch {}

function Fail($msg) {
    Write-Host ""
    Write-Host "[XATO] $msg" -ForegroundColor Red
    Write-Host ""
    Write-Host "Jarayon bayoni: $logFile" -ForegroundColor DarkGray
    try { Stop-Transcript | Out-Null } catch {}
    Read-Host "Yopish uchun Enter bosing"
    exit 1
}

Write-Host "=== Sevimli Kassa: yig'ish va panelga yuklash ===" -ForegroundColor Cyan

$vm = Select-String -Path "pos\version.py" -Pattern 'VERSION\s*=\s*"([^"]+)"'
if (-not $vm) { Fail "pos\version.py dan versiya o'qilmadi" }
$version = $vm.Matches[0].Groups[1].Value
Write-Host "Versiya: $version"

# --- Mos Python (py launcher, keyin python) ---
$py = $null
foreach ($v in "3.13", "3.12", "3.11", "3.10") {
    cmd /c "py -$v --version >nul 2>&1"
    if ($LASTEXITCODE -eq 0) { $py = "py -$v"; break }
}
if (-not $py) {
    cmd /c "python --version >nul 2>&1"
    if ($LASTEXITCODE -eq 0) { $py = "python" }
}
if (-not $py) { Fail "Mos Python topilmadi. python.org dan 3.13 o'rnating (Add to PATH)." }
Write-Host "Python: $py"

# --- UCRT (eski Windows uchun) ---
if (Test-Path "build\ucrt.zip") {
    if (Test-Path "build\ucrt") { Remove-Item -Recurse -Force "build\ucrt" }
    try { Expand-Archive -Path "build\ucrt.zip" -DestinationPath "build\ucrt" -Force } catch {}
}

Write-Host "[1/4] Kutubxonalar o'rnatilmoqda..." -ForegroundColor Cyan
cmd /c "$py -m pip install --upgrade pip >nul 2>&1"
cmd /c "$py -m pip install -r requirements.txt"
if ($LASTEXITCODE -ne 0) { Fail "requirements o'rnatilmadi (internetni tekshiring)" }
cmd /c "$py -m pip install pyinstaller==6.11.1"
if ($LASTEXITCODE -ne 0) { Fail "pyinstaller o'rnatilmadi" }

Write-Host "[2/4] Eski fayllar tozalanmoqda..." -ForegroundColor Cyan
if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build\SevimliKassa") { Remove-Item -Recurse -Force "build\SevimliKassa" }

Write-Host "[3/4] EXE yig'ilmoqda (bir necha daqiqa, kuting)..." -ForegroundColor Cyan
cmd /c "$py -m PyInstaller build\SevimliKassa.spec --noconfirm --clean"
if ($LASTEXITCODE -ne 0) { Fail "PyInstaller yig'ishda xato" }
if (-not (Test-Path "dist\SevimliKassa\SevimliKassa.exe")) { Fail "dist\SevimliKassa\SevimliKassa.exe topilmadi" }

Write-Host "[4/4] ZIP qadoqlanmoqda..." -ForegroundColor Cyan
if (Test-Path "dist\SevimliKassa.zip") { Remove-Item -Force "dist\SevimliKassa.zip" }
Compress-Archive -Path "dist\SevimliKassa" -DestinationPath "dist\SevimliKassa.zip" -Force
$mb = [math]::Round((Get-Item "dist\SevimliKassa.zip").Length / 1MB, 1)
Write-Host "ZIP tayyor: dist\SevimliKassa.zip ($mb MB)" -ForegroundColor Green
Write-Host ""

try { Stop-Transcript | Out-Null } catch {}

# --- Endi yuklash (alohida skript bajaradi) ---
$up = Join-Path $root "kassa_faqat_yukla.ps1"
if (-not (Test-Path $up)) {
    Write-Host "[XATO] kassa_faqat_yukla.ps1 topilmadi." -ForegroundColor Red
    Read-Host "Yopish uchun Enter bosing"
    exit 1
}
# Alohida jarayonda ishga tushiramiz — yig'ish jarayonining holati
# (transcript, chiqish kodi) yuklashga xalaqit bermasin.
powershell -NoProfile -ExecutionPolicy Bypass -File "$up"
