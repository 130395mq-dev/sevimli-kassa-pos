# ============================================================
#  Sevimli — BIR MARTALIK O'RNATISH (kompyuterga).
#
#  Nima qiladi:
#    1. C:\Sevimli papkasini yaratadi, Git'ni (portable) shu yerga oladi.
#    2. GitHub'dan ikkala repo'ni ko'chirib oladi:
#         C:\Sevimli\server  ← github.com/130395mq-dev/sevimli-kassa
#         C:\Sevimli\kassa   ← github.com/130395mq-dev/sevimli-kassa-pos
#    3. «Планировщик заданий» ga vazifa qo'yadi: har 5 daqiqada
#       tools\avto_yuklash.ps1 — papkada o'zgarish bo'lsa GitHub'ga o'zi
#       yuboradi (kod yozildi = yangilanish kassalarga ketdi), GitHub'dagi
#       yangiliklarni esa papkaga o'zi tushiradi.
#
#  Qayta ishga tushirish xavfsiz: bor narsani buzmaydi, faqat yangilaydi.
#    4. Kassa dasturining eng so'nggi versiyasini GitHub Release'dan
#       yuklab, o'rnatadi (dastur o'zini %LOCALAPPDATA%\SevimliKassa ga
#       o'rnatadi, ish stolida yorliq, avto-ishga tushish).
#
#  Shundan keyin kompyuterdagi eski papkalar/bat'lar kerak emas —
#  FAQAT C:\Sevimli qoladi (uni o'chirmang).
# ============================================================
# 'Stop' emas: git stderr'ga progress yozadi, 2>&1 bilan u xatoga aylanib qolardi
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$root = 'C:\Sevimli'
$owner = '130395mq-dev'
$repos = @(
    @{ name = 'server'; url = "https://github.com/$owner/sevimli-kassa.git" },
    @{ name = 'kassa';  url = "https://github.com/$owner/sevimli-kassa-pos.git" }
)
$releaseZip = "https://github.com/$owner/sevimli-kassa-pos/releases/latest/download/SevimliKassa.zip"

function Step($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK: $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    ! $m" -ForegroundColor Yellow }

Write-Host "=== Sevimli — bir martalik o'rnatish ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $root | Out-Null

# --- 1. Git ---------------------------------------------------------
Step "Git"
$git = Join-Path $root 'PortableGit\bin\git.exe'
if (-not (Test-Path $git)) {
    # Eski papkadagi PortableGit bo'lsa — nusxalaymiz (yuklamaymiz)
    $old = Join-Path $env:USERPROFILE 'Downloads\sevimli-kassa-SERVER\sevimli-kassa-SERVER\PortableGit'
    if (Test-Path (Join-Path $old 'bin\git.exe')) {
        Write-Host "    Eski PortableGit nusxalanmoqda..."
        Copy-Item $old (Join-Path $root 'PortableGit') -Recurse -Force
    } else {
        Write-Host "    Git yuklab olinmoqda (~60 MB), kuting..."
        # Aniq versiya (barqaror manzil); API ishlasa — eng yangisi
        $url = 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/PortableGit-2.47.1-64-bit.7z.exe'
        try {
            $rel = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{ 'User-Agent' = 'sevimli' } -TimeoutSec 20
            $asset = $rel.assets | Where-Object { $_.name -match 'PortableGit-.*-64-bit\.7z\.exe$' } | Select-Object -First 1
            if ($asset -and $asset.browser_download_url) { $url = $asset.browser_download_url }
        } catch { Warn "GitHub API javob bermadi - aniq versiya olinadi" }
        $exe = Join-Path $root 'pgit.exe'
        & curl.exe -sSL --retry 3 -o $exe $url
        if (-not (Test-Path $exe) -or (Get-Item $exe).Length -lt 10MB) {
            Invoke-WebRequest $url -OutFile $exe -UserAgent 'sevimli'
        }
        if (-not (Test-Path $exe)) { throw "Git yuklab olinmadi: $url" }
        Start-Process -FilePath $exe -ArgumentList "-o`"$root\PortableGit`"", '-y' -Wait -NoNewWindow
        Remove-Item $exe -Force -ErrorAction SilentlyContinue
    }
}
if (-not (Test-Path $git)) { throw "Git o'rnatilmadi" }
& $git config --global credential.helper manager 2>&1 | Out-Null
Ok (& $git --version)

# --- 2. Repo'lar ----------------------------------------------------
foreach ($r in $repos) {
    $dir = Join-Path $root $r.name
    Step "Repo: $($r.name)  ($($r.url))"
    # core.autocrlf=false KLON PAYTIDAYOQ: aks holda fayllar CRLF bilan
    # tushadi, keyin sozlama o'zgarganda git hammasini «o'zgargan» deb
    # ko'rsatadi va avto-yuklash minglab faylni bekorga commit qiladi.
    if (Test-Path (Join-Path $dir '.git')) {
        Set-Location $dir
        & $git config core.autocrlf false 2>&1 | Out-Null
        & $git pull --rebase origin main 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0) {
            & $git rebase --abort 2>&1 | Out-Null
            Warn "yangilab bo'lmadi: $dir (avto-yuklash keyin qayta urinadi)"
        } else { Ok "yangilandi: $dir" }
    } else {
        if (Test-Path $dir) { Remove-Item $dir -Recurse -Force }
        & $git -c core.autocrlf=false clone -q $r.url $dir
        if ($LASTEXITCODE -ne 0) { throw "Ko'chirib olinmadi: $($r.url)" }
        Ok "ko'chirib olindi: $dir"
    }
    Set-Location $dir
    & $git config user.email 'deploy@sevimli.uz' 2>&1 | Out-Null
    & $git config user.name 'Sevimli Avto' 2>&1 | Out-Null
    & $git config core.autocrlf false 2>&1 | Out-Null
}
Set-Location $root

# --- 2b. Skriptlar (shu papkadagi nusxa) → C:\Sevimli\kassa\tools ---------
#  Birinchi o'rnatishda repo'da tools/ hali bo'lmasligi mumkin — shu
#  skript yonidagi nusxalarni joyiga qo'yib, GitHub'ga yuboramiz.
Step "Skriptlar (tools\)"
$here = ''
if ($MyInvocation.MyCommand.Path) { $here = Split-Path -Parent $MyInvocation.MyCommand.Path }
if (-not $here) { $here = Join-Path $root 'kassa\tools' }   # `irm ... | iex` orqali ochilganda
$toolsDir = Join-Path $root 'kassa\tools'
New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
$copied = $false
foreach ($f in @('avto_yuklash.ps1', 'ornatish.ps1')) {
    $src = Join-Path $here $f
    if (-not (Test-Path $src)) { $src = Join-Path $here ("tools__" + $f) }
    if (Test-Path $src) {
        $dst = Join-Path $toolsDir $f
        if (-not (Test-Path $dst) -or ((Get-FileHash $src).Hash -ne (Get-FileHash $dst).Hash)) {
            Copy-Item $src $dst -Force
            $copied = $true
        }
    }
}
if ($copied) {
    Set-Location (Join-Path $root 'kassa')
    & $git add -A 2>&1 | Out-Null
    & $git commit -q -m 'Avto yuklash skriptlari (tools/)' 2>&1 | Out-Null
    & $git push origin HEAD:main 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "tools/ GitHub'ga yuborildi" } else { Warn "tools/ GitHub'ga yuborilmadi (keyin avto yuboradi)" }
    Set-Location $root
} else { Ok "tools/ joyida" }

# GitHub'ga yozish huquqi bormi (bir marta kirish oynasi chiqishi mumkin)
Step "GitHub'ga kirish tekshiruvi"
Set-Location (Join-Path $root 'kassa')
$dry = & $git push --dry-run origin main 2>&1
if ($LASTEXITCODE -eq 0) { Ok "GitHub'ga yozish mumkin" }
else { Warn "GitHub'ga yozib bo'lmadi: $dry  (birinchi avto-yuklashda kirish oynasi chiqadi)" }
Set-Location $root

# --- 3. Avtomatik yuklash vazifasi ----------------------------------
Step "Avtomatik yuklash (har 5 daqiqada)"
$script = Join-Path $root 'kassa\tools\avto_yuklash.ps1'
if (-not (Test-Path $script)) { throw "tools\avto_yuklash.ps1 topilmadi" }
$tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
& schtasks /Create /TN 'Sevimli Avto Yuklash' /TR $tr /SC MINUTE /MO 5 /F | Out-Null
if ($LASTEXITCODE -eq 0) { Ok "vazifa qo'yildi: «Sevimli Avto Yuklash» (log: $root\avto_yuklash.log)" }
else { Warn "vazifa qo'yilmadi (schtasks xato)" }

# --- 4. Kassa dasturi (GitHub Release'dan) --------------------------
Step "Kassa dasturi — eng so'nggi versiya GitHub'dan"
$tmp = Join-Path $env:TEMP 'SevimliKassa-yangi'
$zip = Join-Path $env:TEMP 'SevimliKassa.zip'
if (Test-Path $tmp) { Remove-Item $tmp -Recurse -Force }
Write-Host "    Yuklab olinmoqda (~50 MB)..."
& curl.exe -sSL --retry 3 -o $zip $releaseZip
if (-not (Test-Path $zip) -or (Get-Item $zip).Length -lt 10MB) {
    Invoke-WebRequest $releaseZip -OutFile $zip -UserAgent 'sevimli'
}
if (-not (Test-Path $zip)) { throw "Kassa ZIP yuklab olinmadi: $releaseZip" }
Expand-Archive -Path $zip -DestinationPath $tmp -Force
$exe = Get-ChildItem -Path $tmp -Recurse -Filter 'SevimliKassa.exe' | Select-Object -First 1
if (-not $exe) { throw "ZIP ichida SevimliKassa.exe yo'q" }
# Dastur birinchi ochilganda o'zini %LOCALAPPDATA%\SevimliKassa ga
# o'rnatadi, yorliq yaratadi va o'rnatilgan nusxani ochadi.
Get-Process SevimliKassa -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Start-Sleep -Seconds 1
Start-Process -FilePath $exe.FullName
Ok "kassa dasturi ishga tushdi — o'zini o'rnatadi (ish stolida «Sevimli Kassa» yorlig'i)"
Remove-Item $zip -Force -ErrorAction SilentlyContinue

Write-Host ""
Write-Host "=====================================================" -ForegroundColor Green
Write-Host " TAYYOR." -ForegroundColor Green
Write-Host " Kod:      C:\Sevimli\server  va  C:\Sevimli\kassa" -ForegroundColor Green
Write-Host " Avto:     har 5 daqiqada o'zgarish GitHub'ga ketadi" -ForegroundColor Green
Write-Host " Kassa:    GitHub'dan o'rnatildi, keyin o'zi yangilanadi" -ForegroundColor Green
Write-Host " Endi eski papkalar va ish stolidagi .bat'lar KERAK EMAS." -ForegroundColor Green
Write-Host " Faqat C:\Sevimli ni o'chirmang." -ForegroundColor Green
Write-Host "=====================================================" -ForegroundColor Green
