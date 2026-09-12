# ============================================================
#  Sevimli Kassa — kodni GitHub'ga yuborish.
#  Kompyuterda HECH NARSA yig'ilmaydi: GitHub o'zi Windows'da EXE
#  yig'adi va Release'ga qo'yadi (.github/workflows/build.yml);
#  server (hub) 10 daqiqada bir Release'ga qarab, yangi ZIP'ni o'zi
#  panelning «Versiyalar» ro'yxatiga qo'shadi. Kassalar 30 daqiqada
#  o'zi yangilanadi. Hech qanday kalit, hech qanday qo'l mehnati yo'q.
#
#  Ish stolidagi KASSA-GITHUBGA-YUKLASH.bat shu skriptni ochadi.
#  -Auto  — savol bermaydi, oxirida Enter kutmaydi (avtomatik ishga tushirish).
#  -Note  — izoh (Release'da va panelda ko'rinadi).
# ============================================================
param([switch]$Auto, [string]$Note = '')
$ProgressPreference = 'SilentlyContinue'
$repoUrl = 'https://github.com/130395mq-dev/sevimli-kassa-pos.git'

function Pause-IfNeeded { if (-not $Auto) { Read-Host 'Yopish uchun Enter bosing' | Out-Null } }

$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
if (-not (Test-Path (Join-Path $dir 'pos\version.py'))) {
    Write-Host 'KASSA papkasi topilmadi (pos\version.py yo''q).' -ForegroundColor Red
    Pause-IfNeeded
    return
}
Set-Location $dir

# --- Versiya ---
$vm = Select-String -Path 'pos\version.py' -Pattern 'VERSION\s*=\s*"([^"]+)"'
$version = if ($vm) { $vm.Matches[0].Groups[1].Value } else { '?' }
Write-Host ''
Write-Host "=== Sevimli Kassa $version -> GitHub ===" -ForegroundColor Cyan
Write-Host ''

# --- 1. Git: o'rnatilgan bo'lsa o'sha, bo'lmasa SERVER papkasidagi
#        PortableGit, u ham bo'lmasa yuklab olamiz (bir marta, ~50 MB)
$git = 'git'
if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $serverPg = Join-Path $env:USERPROFILE 'Downloads\sevimli-kassa-SERVER\sevimli-kassa-SERVER\PortableGit\bin\git.exe'
    $pg = Join-Path $dir 'PortableGit'
    $gitexe = Join-Path $pg 'bin\git.exe'
    if (Test-Path $serverPg) {
        $git = $serverPg
    } elseif (Test-Path $gitexe) {
        $git = $gitexe
    } else {
        try {
            Write-Host 'Git yuklab olinmoqda (~50 MB), kuting...' -ForegroundColor Yellow
            $rel = Invoke-RestMethod 'https://api.github.com/repos/git-for-windows/git/releases/latest' -Headers @{ 'User-Agent' = 'sevimli' }
            $asset = $rel.assets | Where-Object { $_.name -match 'PortableGit-.*-64-bit\.7z\.exe$' } | Select-Object -First 1
            $out = Join-Path $dir 'pgit.exe'
            Invoke-WebRequest $asset.browser_download_url -OutFile $out
            Write-Host 'Ochilmoqda...' -ForegroundColor Yellow
            Start-Process -FilePath $out -ArgumentList "-o`"$pg`"", '-y' -Wait -NoNewWindow
            Remove-Item $out -ErrorAction SilentlyContinue
        } catch {
            Write-Host ('Git yuklashda xato: ' + $_.Exception.Message) -ForegroundColor Red
            Pause-IfNeeded
            return
        }
        $git = $gitexe
    }
}
Write-Host ('Git: ' + (& $git --version))

# --- 1b. GitHub Actions ish rejasi: Claude uni papka ildiziga
#         `github-workflow-build.yml` nomi bilan yozadi (masofadan .github
#         ichiga yozib bo'lmaydi) — shu yerda joyiga ko'chiramiz.
$wfSrc = Join-Path $dir 'github-workflow-build.yml'
$wfDir = Join-Path $dir '.github\workflows'
if (Test-Path $wfSrc) {
    New-Item -ItemType Directory -Force -Path $wfDir | Out-Null
    Copy-Item $wfSrc (Join-Path $wfDir 'build.yml') -Force
    Write-Host 'GitHub Actions ish rejasi yangilandi (.github\workflows\build.yml)'
}

# --- 2. Izoh (GitHub Release'da va panelning «Versiyalar» da ko'rinadi)
$note = $Note
if (-not $Auto -and -not $note) {
    $note = Read-Host "Bu versiyada nima o'zgardi? (bo'sh qoldirsangiz ham bo'ladi)"
}
$note = $note.Trim()
if (-not $note) { $note = "Kassa $version" } else { $note = "Kassa $version - $note" }

# --- 3. Repo tayyorlab, yuboramiz
& $git config --global credential.helper manager 2>&1 | Out-Null
if (-not (Test-Path '.git')) { & $git init 2>&1 | Out-Null }
& $git config user.email 'deploy@sevimli.uz' 2>&1 | Out-Null
& $git config user.name 'Sevimli Deploy' 2>&1 | Out-Null
& $git add -A 2>&1 | Out-Null
& $git commit -m $note 2>&1 | Out-Null
& $git branch -M main 2>&1 | Out-Null
$remotes = & $git remote 2>&1
if ($remotes -contains 'origin') { & $git remote remove origin 2>&1 | Out-Null }
& $git remote add origin $repoUrl 2>&1 | Out-Null

Write-Host ''
Write-Host 'Yuklanmoqda... GitHub kirish oynasi chiqsa - tasdiqlang.' -ForegroundColor Cyan
& $git push -u origin main --force
if ($LASTEXITCODE -ne 0) {
    Write-Host ''
    Write-Host 'YUKLANMADI. Yuqoridagi yozuvni suratga oling.' -ForegroundColor Red
    Write-Host "Repo bormi? $repoUrl" -ForegroundColor Yellow
    Pause-IfNeeded
    return
}

Write-Host ''
Write-Host '=====================================================' -ForegroundColor Green
Write-Host "TAYYOR - kod GitHub'ga ketdi (versiya $version)." -ForegroundColor Green
Write-Host 'GitHub endi o''zi EXE yig''adi (8-12 daqiqa), server uni o''zi oladi.' -ForegroundColor Green
Write-Host 'Kuzatish: https://github.com/130395mq-dev/sevimli-kassa-pos/actions' -ForegroundColor Green
Write-Host 'Natija:   panel -> Versiyalar (yangi raqam ~20 daqiqada JORIY bo''ladi)' -ForegroundColor Green
Write-Host '=====================================================' -ForegroundColor Green
Write-Host ''
Write-Host "Eslatma: versiya raqami avval chiqarilgan bo'lsa, yangi Release bo'lmaydi -" -ForegroundColor DarkGray
Write-Host "pos\version.py dagi raqamni oshirib, qayta bosing." -ForegroundColor DarkGray
Pause-IfNeeded
