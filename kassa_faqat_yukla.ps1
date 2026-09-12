# ============================================================
#  Sevimli Kassa - TAYYOR ZIP ni panelga yuklaydi (yig'maydi).
#  Maxfiy kalit bilan to'g'ridan-to'g'ri yuklanadi:
#  login yo'q, cookie yo'q, CSRF yo'q - shuning uchun ishonchli.
# ============================================================
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$panel = "https://hub-production-0882.up.railway.app"
$token = "dik_Q08BZFfKcs5n30b6uQSuR-YeJCH29exXZsF3DPlnHqK9"
$desk  = [Environment]::GetFolderPath('Desktop')
$logFile = Join-Path $desk "kassa-yuklash-log.txt"
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

Write-Host "=== Sevimli Kassa: tayyor ZIP ni panelga yuklash ===" -ForegroundColor Cyan

# --- Versiya ---
$vm = Select-String -Path "pos\version.py" -Pattern 'VERSION\s*=\s*"([^"]+)"'
if (-not $vm) { Fail "pos\version.py dan versiya o'qilmadi" }
$version = $vm.Matches[0].Groups[1].Value

# --- ZIP ---
$zip = Join-Path $root "dist\SevimliKassa.zip"
if (-not (Test-Path $zip)) {
    Fail "dist\SevimliKassa.zip topilmadi. Avval KASSA-YANGI-VERSIYA-CHIQARISH.bat bilan yig'ing."
}
$mb = [math]::Round((Get-Item $zip).Length / 1MB, 1)
Write-Host "Versiya: $version"
Write-Host "ZIP:     $zip ($mb MB)"
Write-Host ""

# --- HIMOYA: ZIP kod fayllaridan eski bo'lsa, yuklashga YO'L QO'YMAYMIZ.
#
# Aks holda panelga yangi RAQAM, lekin ESKI kod tushadi. Kassa uni o'rnatadi,
# versiyasi o'zgarmaydi va «versiya mos emas» deb to'xtaydi. Bu xato bir
# necha marta bo'lgan — shuning uchun shu yerda qat'iy tekshiramiz.
$zipTime = (Get-Item $zip).LastWriteTime
$newest = Get-ChildItem -Path "pos" -Recurse -Filter *.py -ErrorAction SilentlyContinue |
          Sort-Object LastWriteTime -Descending | Select-Object -First 1
if ($newest -and $newest.LastWriteTime -gt $zipTime) {
    Write-Host "[TO'XTATILDI] ZIP eskirgan!" -ForegroundColor Red
    Write-Host ""
    Write-Host "  '$($newest.Name)' fayli ZIP yig'ilgandan KEYIN o'zgargan:" -ForegroundColor Yellow
    Write-Host "     fayl: $($newest.LastWriteTime.ToString('HH:mm:ss'))" -ForegroundColor Yellow
    Write-Host "     ZIP:  $($zipTime.ToString('HH:mm:ss'))" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Ya'ni bu ZIP ichida ESKI kod. Uni yuklasak, kassa" -ForegroundColor Yellow
    Write-Host "  «versiya mos emas» deb to'xtaydi." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  KERAK: KASSA-YANGI-VERSIYA-CHIQARISH.bat ni ishga tushiring —" -ForegroundColor Green
    Write-Host "  u qayta yig'adi va o'zi yuklaydi." -ForegroundColor Green
    Fail "Eski ZIP yuklanmadi (himoya ishladi)."
}

cmd /c "curl --version >nul 2>&1"
if ($LASTEXITCODE -ne 0) { Fail "curl.exe topilmadi." }

$op  = Join-Path $env:TEMP "sk_javob.json"
$err = Join-Path $env:TEMP "sk_xato.txt"
foreach ($f in @($op, $err)) { if (Test-Path $f) { Remove-Item -Force $f } }

Write-Host "Yuborilmoqda ($mb MB) - internet tezligiga qarab bir necha daqiqa..." -ForegroundColor Cyan

# Bitta so'rov: maxfiy kalit sarlavhada, fayl multipart'da.
# --max-time 1800 : sekin internetда ham uzilib qolmasin.
# -sS : jim, lekin XATO bo'lsa ko'rsatadi (xato matni $err ga yoziladi).
$code = & curl.exe @(
    '-sS',
    '-H', "X-Release-Token: $token",
    '-F', "version=$version",
    '-F', "notes=Avtomatik chiqarildi",
    '-F', "file=@$zip;type=application/zip",
    '--max-time', '1800',
    '--connect-timeout', '30',
    '-o', $op,
    '-w', '%{http_code}',
    "$panel/api/v1/release/upload"
) 2> $err

Write-Host ""

if (-not (Test-Path $op)) {
    Write-Host "[XATO] Serverdan javob kelmadi (HTTP $code)." -ForegroundColor Red
    if ((Test-Path $err) -and (Get-Item $err).Length -gt 0) {
        Write-Host "curl xabari:" -ForegroundColor Yellow
        Get-Content $err | ForEach-Object { Write-Host "   $_" -ForegroundColor Yellow }
        Copy-Item $err (Join-Path $desk "yuklash-xatosi.txt") -Force
        Write-Host "Xato matni Ish stoliga saqlandi: yuklash-xatosi.txt" -ForegroundColor Yellow
    }
    Fail "Yuklanmadi. Internetni tekshiring yoki menga ayting."
}

$body = Get-Content $op -Raw
if ($code -eq "200" -and $body -match '"ok"\s*:\s*true') {
    Write-Host "==================================================" -ForegroundColor Green
    Write-Host " TAYYOR! Versiya $version panelga yuklandi." -ForegroundColor Green
    Write-Host " Kassalar 30 daqiqa ichida o'zi yangilanadi." -ForegroundColor Green
    Write-Host " Panel: $panel/versiyalar/" -ForegroundColor Green
    Write-Host "==================================================" -ForegroundColor Green
} else {
    Write-Host "[DIQQAT] Yuklanmadi (HTTP $code)." -ForegroundColor Yellow
    if ($body -match '"error"\s*:\s*"([^"]+)"') {
        Write-Host ("Panel xabari: " + $Matches[1]) -ForegroundColor Yellow
        if ($Matches[1] -match "allaqachon") {
            Write-Host ""
            Write-Host " Demak bu versiya panelda ALLAQACHON bor - qayta yuklash shart emas." -ForegroundColor Green
        }
    } else {
        Write-Host "Javob: $body" -ForegroundColor Yellow
        Copy-Item $op (Join-Path $desk "panel-javobi.txt") -Force
        Write-Host "Javob Ish stoliga saqlandi: panel-javobi.txt" -ForegroundColor Yellow
    }
}
Write-Host ""
Write-Host "Jarayon bayoni: $logFile" -ForegroundColor DarkGray
try { Stop-Transcript | Out-Null } catch {}
Read-Host "Yopish uchun Enter bosing"
