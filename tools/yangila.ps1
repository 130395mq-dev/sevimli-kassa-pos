# ============================================================
#  Sevimli - C:\Sevimli ni GitHub'dan YANGILASH yoki TAYYORLASH (bir buyruq).
#
#  PowerShell'da (oddiy yoki administrator, farqi yo'q):
#
#    irm https://raw.githubusercontent.com/130395mq-dev/sevimli-kassa-pos/main/tools/yangila.ps1 | iex
#
#  Nima qiladi:
#    1. Git'ni topadi (C:\Sevimli\PortableGit, PATH, Program Files, eski
#       Downloads papkasi); topolmasa PortableGit'ni C:\Sevimli ga yuklaydi.
#    2. C:\Sevimli\kassa va C:\Sevimli\server: bor bo'lsa GitHub'dagi main
#       ustiga rebase (commit qilinmagan o'zgarishlar saqlanadi - autostash,
#       ikki tomon bir faylni o'zgartirgan bo'lsa kompyuterdagi nusxa ustun);
#       yo'q bo'lsa GitHub'dan ko'chirib oladi.
#    3. Har 5 daqiqalik "Sevimli Avto Yuklash" vazifasi yo'q bo'lsa qo'yadi.
#  Hech narsa push qilmaydi, kassa dasturini o'rnatmaydi/qayta ochmaydi.
#
#  DIQQAT: fayl BOM'siz saqlanadi - `irm | iex` BOM bilan ishlamaydi.
# ============================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
try { [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 } catch {}

$root  = 'C:\Sevimli'
$owner = '130395mq-dev'
$repos = @(
    @{ name = 'kassa';  url = "https://github.com/$owner/sevimli-kassa-pos.git" },
    @{ name = 'server'; url = "https://github.com/$owner/sevimli-kassa.git" }
)

function Step($m) { Write-Host ""; Write-Host "==> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK: $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    ! $m" -ForegroundColor Yellow }
function Bad($m)  { Write-Host "    XATO: $m" -ForegroundColor Red }

New-Item -ItemType Directory -Force -Path $root | Out-Null

# --- 1. Git ---------------------------------------------------------
Step "Git"
$git = $null
$candidates = @(
    (Join-Path $root 'PortableGit\bin\git.exe'),
    (Join-Path $env:USERPROFILE 'Downloads\sevimli-kassa-SERVER\sevimli-kassa-SERVER\PortableGit\bin\git.exe'),
    'C:\Program Files\Git\bin\git.exe',
    'C:\Program Files (x86)\Git\bin\git.exe',
    (Join-Path $env:LOCALAPPDATA 'Programs\Git\bin\git.exe')
)
foreach ($c in $candidates) { if ($c -and (Test-Path $c)) { $git = $c; break } }
if (-not $git) {
    $cmd = Get-Command git.exe -ErrorAction SilentlyContinue
    if ($cmd) { $git = $cmd.Source }
}
if (-not $git) {
    Write-Host "    Git topilmadi - PortableGit yuklab olinmoqda (~60 MB), kuting..."
    $pg  = Join-Path $root 'PortableGit'
    $url = 'https://github.com/git-for-windows/git/releases/download/v2.47.1.windows.1/PortableGit-2.47.1-64-bit.7z.exe'
    try {
        $rel = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{ 'User-Agent' = 'sevimli' } -TimeoutSec 20
        $asset = $rel.assets | Where-Object { $_.name -match 'PortableGit-.*-64-bit\.7z\.exe$' } | Select-Object -First 1
        if ($asset -and $asset.browser_download_url) { $url = $asset.browser_download_url }
    } catch {}
    $exe = Join-Path $root 'pgit.exe'
    if (Get-Command curl.exe -ErrorAction SilentlyContinue) { & curl.exe -sSL --retry 3 -o $exe $url }
    if (-not (Test-Path $exe) -or (Get-Item $exe).Length -lt 10MB) {
        Invoke-WebRequest $url -OutFile $exe -UserAgent 'sevimli'
    }
    if (-not (Test-Path $exe)) { Bad "Git yuklab olinmadi: $url"; return }
    Start-Process -FilePath $exe -ArgumentList "-o`"$pg`"", '-y' -Wait -NoNewWindow
    Remove-Item $exe -Force -ErrorAction SilentlyContinue
    $git = Join-Path $pg 'bin\git.exe'
    if (-not (Test-Path $git)) { Bad "Git o'rnatilmadi: $pg"; return }
}
& $git config --global credential.helper manager 2>&1 | Out-Null
Ok ("$git  (" + ((& $git --version 2>&1) -join ' ') + ")")

# --- 2. Repo'lar ----------------------------------------------------
foreach ($r in $repos) {
    $name = $r.name
    $dir  = Join-Path $root $name
    Step "$name  ($dir)"
    if (-not (Test-Path (Join-Path $dir '.git'))) {
        if (Test-Path $dir) {
            $bak = "$dir-eski-$(Get-Date -Format 'yyyyMMdd-HHmm')"
            Move-Item $dir $bak -Force
            Warn "papka bor edi, lekin git emas - chetga surildi: $bak"
        }
        Write-Host "    GitHub'dan ko'chirib olinmoqda..."
        & $git -c core.autocrlf=false clone -q $r.url $dir 2>&1 | Out-Null
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path (Join-Path $dir '.git'))) { Bad "ko'chirib olinmadi: $($r.url)"; continue }
        & $git -C $dir config user.email 'deploy@sevimli.uz' 2>&1 | Out-Null
        & $git -C $dir config user.name 'Sevimli Avto' 2>&1 | Out-Null
        & $git -C $dir config core.autocrlf false 2>&1 | Out-Null
        Ok ("ko'chirib olindi: " + ((& $git -C $dir log -1 --format='%h %s' 2>&1) -join ' '))
        continue
    }
    & $git -C $dir config core.autocrlf false 2>&1 | Out-Null
    if ((Test-Path (Join-Path $dir '.git\rebase-merge')) -or (Test-Path (Join-Path $dir '.git\rebase-apply'))) {
        & $git -C $dir rebase --abort 2>&1 | Out-Null
        Warn "chala rebase bekor qilindi"
    }
    $before = ((& $git -C $dir rev-parse --short HEAD 2>$null) -join '')
    & $git -C $dir fetch -q origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Bad "GitHub'dan olib bo'lmadi (internet? kirish?)"; continue }
    $behind = [int]((& $git -C $dir rev-list --count 'HEAD..origin/main' 2>$null) -join '')
    if ($behind -eq 0) { Ok "allaqachon yangi ($before)"; continue }
    & $git -C $dir rebase -X theirs --autostash origin/main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $git -C $dir rebase --abort 2>&1 | Out-Null
        Bad "birlashtirib bo'lmadi - shu oynani suratga oling"
        continue
    }
    $after = ((& $git -C $dir log -1 --format='%h %s' 2>$null) -join ' ')
    Ok "$behind ta yangilanish olindi ($before -> $after)"
}

# --- 3. Har 5 daqiqalik vazifa --------------------------------------
Step "Avtomatik yuklash vazifasi"
$script = Join-Path $root 'kassa\tools\avto_yuklash.ps1'
if (-not (Test-Path $script)) { Bad "$script yo'q - kassa repo'si olinmagan"; return }
& schtasks /Query /TN 'Sevimli Avto Yuklash' 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Ok "vazifa bor: Sevimli Avto Yuklash (har 5 daqiqada)" }
else {
    $tr = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$script`""
    & schtasks /Create /TN 'Sevimli Avto Yuklash' /TR $tr /SC MINUTE /MO 5 /F 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Ok "vazifa qo'yildi: Sevimli Avto Yuklash (har 5 daqiqada)" }
    else { Warn "vazifa qo'yilmadi (schtasks xato) - PowerShell'ni administrator sifatida oching" }
}

Write-Host ''
Write-Host "TAYYOR. Kod: $root\kassa va $root\server. Log: $root\avto_yuklash.log" -ForegroundColor Green
