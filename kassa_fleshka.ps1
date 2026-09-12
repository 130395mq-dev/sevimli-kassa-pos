# ============================================================
#  Sevimli Kassa - dasturni FLESHKAGA tayyorlaydi.
#  Fleshkani kompyuterga suqing va shu faylni ishga tushiring.
#  Keyin fleshkani yangi kassaga suqib, SevimliKassa.exe ni bosasiz -
#  dastur o'zini o'rnatadi va login-parol so'raydi.
# ============================================================
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Fail($msg) {
    Write-Host ""
    Write-Host "[XATO] $msg" -ForegroundColor Red
    Write-Host ""
    Read-Host "Yopish uchun Enter bosing"
    exit 1
}

Write-Host "=== Sevimli Kassa: fleshkaga tayyorlash ===" -ForegroundColor Cyan
Write-Host ""

# --- Manba papka ---
$src = Join-Path $root "dist\SevimliKassa"
if (-not (Test-Path "$src\SevimliKassa.exe")) {
    Fail "dist\SevimliKassa topilmadi. Avval KASSA-YANGI-VERSIYA-CHIQARISH.bat bilan yig'ing."
}
$vm = Select-String -Path "pos\version.py" -Pattern 'VERSION\s*=\s*"([^"]+)"'
$version = if ($vm) { $vm.Matches[0].Groups[1].Value } else { "?" }
$sizeMB = [math]::Round(((Get-ChildItem $src -Recurse -File | Measure-Object Length -Sum).Sum / 1MB), 0)
Write-Host "Dastur: versiya $version  (~$sizeMB MB)" -ForegroundColor Green
Write-Host ""

# --- Fleshkani topamiz (olinadigan disklar) ---
$drives = @(Get-CimInstance Win32_LogicalDisk -Filter "DriveType=2" -ErrorAction SilentlyContinue |
            Where-Object { $_.DeviceID })

$target = $null
if ($drives.Count -eq 1) {
    $target = $drives[0].DeviceID
    $free = [math]::Round($drives[0].FreeSpace / 1MB, 0)
    Write-Host "Fleshka topildi: $target  (bo'sh joy: $free MB)" -ForegroundColor Green
} elseif ($drives.Count -gt 1) {
    Write-Host "Bir nechta fleshka topildi:" -ForegroundColor Yellow
    foreach ($d in $drives) {
        $free = [math]::Round($d.FreeSpace / 1MB, 0)
        Write-Host ("   {0}  {1}  (bo'sh: {2} MB)" -f $d.DeviceID, $d.VolumeName, $free)
    }
    $ans = Read-Host "Qaysi diskka yozamiz? (masalan E:)"
    $target = $ans.Trim()
} else {
    Write-Host "Fleshka topilmadi." -ForegroundColor Yellow
    $ans = Read-Host "Disk harfini o'zingiz yozing (masalan E:) yoki bo'sh qoldirib Enter bosing"
    if (-not $ans.Trim()) { Fail "Fleshka suqilmagan. Fleshkani suqib, qaytadan ishga tushiring." }
    $target = $ans.Trim()
}

if (-not $target.EndsWith(":")) { $target = $target + ":" }
if (-not (Test-Path "$target\")) { Fail "$target diski topilmadi." }

$dest = Join-Path "$target\" "SevimliKassa"
Write-Host ""
Write-Host "Nusxalanmoqda -> $dest" -ForegroundColor Cyan
Write-Host "(bir necha daqiqa ketishi mumkin, kuting)" -ForegroundColor DarkGray

try {
    if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
    Copy-Item -Path $src -Destination $dest -Recurse -Force
} catch {
    Fail "Nusxalanmadi: $_"
}

# --- Fleshkaga qisqa yo'riqnoma ---
$readme = @"
SEVIMLI KASSA - yangi kassaga o'rnatish
=======================================
Versiya: $version

1. Shu fleshkani yangi kassa (monoblok) ga suqing.
2. SevimliKassa papkasini oching.
3. SevimliKassa.exe faylini ikki marta bosing.
4. Dastur o'zini kompyuterga o'rnatadi, ish stolida yorliq yaratadi
   va o'zi ochiladi.
5. Panelda yaratilgan KASSA LOGIN va PAROLINI kiriting.
6. Keyin kassir o'z login-paroli bilan kiradi va smena ochadi.

Eslatma: dastur o'rnatilgandan keyin fleshka kerak emas - uni olib
qo'yishingiz mumkin. Keyingi yangilanishlar internetdan o'zi keladi.
"@
Set-Content -Path (Join-Path $dest "OQING.txt") -Value $readme -Encoding UTF8

Write-Host ""
Write-Host "==================================================" -ForegroundColor Green
Write-Host " TAYYOR! Fleshka ishga tayyor." -ForegroundColor Green
Write-Host " Joy:  $dest" -ForegroundColor Green
Write-Host ""
Write-Host " Yangi kassada: SevimliKassa papkasini ochib," -ForegroundColor Green
Write-Host " SevimliKassa.exe ni ikki marta bosing." -ForegroundColor Green
Write-Host "==================================================" -ForegroundColor Green
Write-Host ""
Read-Host "Yopish uchun Enter bosing"
