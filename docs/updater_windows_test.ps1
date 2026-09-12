<#
  Sevimli Kassa — updater harness (Windows).

  pos/updater.py ichidagi _BAT bilan BIR XIL mantiqni izolyatsiyalangan,
  tashlab yuboriladigan papkalarda tekshiradi. Haqiqiy o'rnatmaga tegmaydi.

  Ishlatish:
    powershell -ExecutionPolicy Bypass -File docs\updater_windows_test.ps1 -Scenario ok
    powershell -ExecutionPolicy Bypass -File docs\updater_windows_test.ps1 -Scenario rollback

  "ok"       -> yangi versiya sog'liq bayrog'ini yozadi -> swap qoladi (v2).
  "rollback" -> bayroq yozilmaydi -> BACKUP dan tiklanadi (v1).

  Bu updater KODINI o'zgartirmaydi; faqat _BAT dagi robocopy + health +
  rollback ketma-ketligini takrorlaydi.
#>

param(
  [ValidateSet("ok", "rollback")]
  [string]$Scenario = "ok"
)

$ErrorActionPreference = "Stop"
$Root   = Join-Path $env:TEMP ("skassa-updtest-" + [guid]::NewGuid().ToString("N").Substring(0,8))
$NEW    = Join-Path $Root "new"
$TARGET = Join-Path $Root "install"
$BACKUP = Join-Path $Root "backup"
$FLAG   = Join-Path $Root "run-ok"

function Info($m) { Write-Host "  $m" -ForegroundColor DarkGray }
function Pass($m) { Write-Host "PASS: $m" -ForegroundColor Green }
function Fail($m) { Write-Host "FAIL: $m" -ForegroundColor Red }

Write-Host "Sevimli Kassa updater harness — ssenariy: $Scenario" -ForegroundColor Cyan

# --- tayyorlash: soxta 'o'rnatilgan' (v1) va 'yangi' (v2) papkalar ---------
New-Item -ItemType Directory -Force -Path $TARGET, $NEW | Out-Null
"v1" | Set-Content -Path (Join-Path $TARGET "app.txt")
"eski" | Set-Content -Path (Join-Path $TARGET "eski-fayl.txt")   # backup/restore uchun
"v2" | Set-Content -Path (Join-Path $NEW "app.txt")
Info "TARGET boshlang'ich: $(Get-Content (Join-Path $TARGET 'app.txt'))"

# --- _BAT 1-qadam: TARGET -> BACKUP (rollback uchun zaxira) ----------------
if (Test-Path $BACKUP) { Remove-Item -Recurse -Force $BACKUP }
robocopy $TARGET $BACKUP /E /R:1 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
Info "BACKUP olindi"

# --- _BAT 2-qadam: sog'liq bayrog'ini o'chirish ---------------------------
if (Test-Path $FLAG) { Remove-Item -Force $FLAG }

# --- _BAT 3-qadam: NEW -> TARGET (real ilovada exe bo'shaguncha kutiladi) --
robocopy $NEW $TARGET /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
$rc = $LASTEXITCODE
if ($rc -ge 8) { Fail "robocopy xato kodi $rc"; exit 1 }
Info "swap bajarildi: TARGET endi = $(Get-Content (Join-Path $TARGET 'app.txt'))"

# --- _BAT 4-qadam: 'yangi versiyani ochish' ------------------------------
# Real ilovada: start "" "%EXE%"; keyin mark_started() FLAG yozadi.
# Harness bu yerda ssenariyga qarab FLAG yozadi (yoki yozmaydi).
if ($Scenario -eq "ok") {
  "v2" | Set-Content -Path $FLAG      # yangi versiya muvaffaqiyatli ishga tushdi
  Info "yangi versiya ishga tushdi (FLAG yozildi)"
} else {
  Info "yangi versiya YIQILDI (FLAG yozilmadi) — rollback kutilmoqda"
}

# --- _BAT 5-qadam: sog'liq tekshiruvi + rollback --------------------------
# Real .bat 20 s kutadi; harness'da darhol tekshiramiz.
if (Test-Path $FLAG) {
  Info "sog'liq OK — swap qoladi"
} else {
  Info "sog'liq YO'Q — BACKUP dan tiklaymiz (ROLLBACK)"
  robocopy $BACKUP $TARGET /E /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
}

# --- natijani tekshirish --------------------------------------------------
$final = (Get-Content (Join-Path $TARGET "app.txt")).Trim()
$eskiBor = Test-Path (Join-Path $TARGET "eski-fayl.txt")
Write-Host ""
if ($Scenario -eq "ok") {
  if ($final -eq "v2") { Pass "yangilanish qoldi (v2)" } else { Fail "kutilgan v2, keldi '$final'" }
} else {
  if ($final -eq "v1" -and $eskiBor) { Pass "rollback ishladi (v1)" } else { Fail "kutilgan v1, keldi '$final'" }
}

# --- tozalash (real .bat ham NEW/BACKUP ni o'chiradi) ---------------------
Remove-Item -Recurse -Force $Root -ErrorAction SilentlyContinue
Info "vaqtinchalik papkalar o'chirildi"
