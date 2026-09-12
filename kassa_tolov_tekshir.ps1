# ============================================================
#  To'lov turlarini tekshirish - panelда qanday turlar borligini
#  va MoySklad'ga bog'langanini ko'rsatadi. Hech narsani o'zgartirmaydi,
#  faqat O'QIYDI.
# ============================================================
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$panel = "https://hub-production-0882.up.railway.app"
$desk = [Environment]::GetFolderPath('Desktop')

function Fail($msg) {
    Write-Host ""
    Write-Host "[XATO] $msg" -ForegroundColor Red
    Read-Host "Yopish uchun Enter bosing"
    exit 1
}

Write-Host "=== To'lov turlari tekshirilmoqda ===" -ForegroundColor Cyan

$cj = Join-Path $env:TEMP "sk_c2.txt"
$lp = Join-Path $env:TEMP "sk_l2.html"
$pm = Join-Path $env:TEMP "sk_pm.html"
foreach ($f in @($cj, $lp, $pm)) { if (Test-Path $f) { Remove-Item -Force $f } }

function Get-Csrf($file) {
    if (-not (Test-Path $file)) { return $null }
    $m = Select-String -Path $file -Pattern 'name="csrfmiddlewaretoken"\s+value="([^"]+)"'
    if ($m) { return $m.Matches[0].Groups[1].Value }
    return $null
}

# Admin panelga kiramiz
& curl.exe @('-s', '-c', $cj, "$panel/admin/login/", '-o', $lp)
$tok = Get-Csrf $lp
if (-not $tok) { Fail "Admin sahifasi ochilmadi (internetni tekshiring)" }

& curl.exe @('-s', '-b', $cj, '-c', $cj,
    '-H', "Referer: $panel/admin/login/",
    '-H', "X-CSRFToken: $tok",
    '-X', 'POST', "$panel/admin/login/",
    '--data-urlencode', "csrfmiddlewaretoken=$tok",
    '--data-urlencode', 'username=admin',
    '--data-urlencode', 'password=admin',
    '--data-urlencode', 'next=/admin/sales/paymentmethod/',
    '-L', '-o', $pm)

if (-not (Test-Path $pm)) { Fail "Ro'yxat olinmadi" }

# Ro'yxatni Ish stoliga saqlaymiz - Claude o'qib ko'radi
Copy-Item $pm (Join-Path $desk "tolov-turlari.html") -Force

Write-Host ""
Write-Host "Panelда topilgan to'lov turlari:" -ForegroundColor Green
Write-Host "----------------------------------------"
$html = Get-Content $pm -Raw
$rx = [regex]'paymentmethod/(\d+)/change/"[^>]*>([^<]+)<'
$seen = @{}
foreach ($m in $rx.Matches($html)) {
    $id = $m.Groups[1].Value
    $nm = $m.Groups[2].Value.Trim()
    if (-not $seen.ContainsKey($id)) {
        $seen[$id] = $nm
        Write-Host ("  ID {0,-4} {1}" -f $id, $nm)
    }
}
if ($seen.Count -eq 0) {
    Write-Host "  (ro'yxat o'qilmadi - fayl Ish stolida: tolov-turlari.html)" -ForegroundColor Yellow
}
Write-Host "----------------------------------------"
Write-Host ""
Write-Host "To'liq ro'yxat Ish stoliga saqlandi: tolov-turlari.html" -ForegroundColor Green
Write-Host "Shuni Claude o'zi o'qib, to'g'ri-notog'riligini aytadi." -ForegroundColor Green
Write-Host ""
Read-Host "Yopish uchun Enter bosing"
