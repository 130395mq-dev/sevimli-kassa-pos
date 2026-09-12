# ============================================================
#  Sevimli — C:\Sevimli dagi ikkala repo'ni GitHub'dan YANGILASH (bir marta).
#
#  Qachon kerak: avto-yuklash skriptining o'zi eskirgan bo'lsa (eski
#  nusxa GitHub'dan hech narsa olmasdi). PowerShell'da bitta buyruq:
#
#    irm https://raw.githubusercontent.com/130395mq-dev/sevimli-kassa-pos/main/tools/yangila.ps1 | iex
#
#  Nima qiladi: C:\Sevimli\kassa va C:\Sevimli\server ni GitHub'dagi main
#  ustiga rebase qiladi (kompyuterdagi commit qilinmagan o'zgarishlar
#  saqlanadi — autostash; ikki tomon bir faylni o'zgartirgan bo'lsa
#  kompyuterdagi nusxa ustun). Hech narsa push qilmaydi, dasturni
#  qayta ochmaydi — qolganini har 5 daqiqalik avto-yuklash qiladi.
# ============================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\Sevimli'

$git = Join-Path $root 'PortableGit\bin\git.exe'
if (-not (Test-Path $git)) {
    if (Get-Command git -ErrorAction SilentlyContinue) { $git = 'git' }
    else { Write-Host "Git topilmadi: $git" -ForegroundColor Red; return }
}

foreach ($name in @('kassa', 'server')) {
    $dir = Join-Path $root $name
    if (-not (Test-Path (Join-Path $dir '.git'))) {
        Write-Host "  ! $dir yo'q — tools\ornatish.ps1 ni ishga tushiring" -ForegroundColor Yellow
        continue
    }
    Write-Host "==> $name  ($dir)" -ForegroundColor Cyan
    & $git -C $dir config core.autocrlf false 2>&1 | Out-Null
    if ((Test-Path (Join-Path $dir '.git\rebase-merge')) -or (Test-Path (Join-Path $dir '.git\rebase-apply'))) {
        & $git -C $dir rebase --abort 2>&1 | Out-Null
        Write-Host "    chala rebase bekor qilindi" -ForegroundColor Yellow
    }
    $before = (& $git -C $dir rev-parse --short HEAD 2>$null)
    & $git -C $dir fetch -q origin main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Host "    XATO: GitHub'dan olib bo'lmadi (internet?)" -ForegroundColor Red; continue }
    $behind = [int](& $git -C $dir rev-list --count 'HEAD..origin/main' 2>$null)
    if ($behind -eq 0) { Write-Host "    allaqachon yangi ($before)" -ForegroundColor Green; continue }
    & $git -C $dir rebase -X theirs --autostash origin/main 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        & $git -C $dir rebase --abort 2>&1 | Out-Null
        Write-Host "    XATO: birlashtirib bo'lmadi — shu yozuvni suratga oling" -ForegroundColor Red
        continue
    }
    $after = (& $git -C $dir log -1 --format='%h %s' 2>$null)
    Write-Host "    OK: $behind ta yangilanish olindi ($before -> $after)" -ForegroundColor Green
}

Write-Host ''
Write-Host "Tayyor. Har 5 daqiqalik avto-yuklash endi yangi skript bilan ishlaydi:" -ForegroundColor Green
Write-Host "  log: $root\avto_yuklash.log" -ForegroundColor Green
