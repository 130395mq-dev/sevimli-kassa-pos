# ============================================================
#  Sevimli — AVTOMATIK YUKLASH (har 5 daqiqada, ko'rinmas oynada).
#
#  Windows «Планировщик заданий» shu skriptni har 5 daqiqada ishga
#  tushiradi (tools\ornatish.ps1 shunday sozlab qo'yadi). Vazifasi:
#
#    C:\Sevimli\server  (backend, GitHub: sevimli-kassa)     → o'zgarish bo'lsa push → Railway deploy
#    C:\Sevimli\kassa   (frontend, GitHub: sevimli-kassa-pos) → o'zgarish bo'lsa
#                        versiya raqamini o'zi oshiradi (1.16.0 → 1.16.1) → push
#                        → GitHub EXE yig'adi → server oladi → kassalar yangilanadi
#
#  Ya'ni kod papkaga tushdi — tamom, qolganini tizim o'zi qiladi.
#  Egasi hech narsa bosmaydi.
#
#  Ikki tomonlama: GitHub'da (masalan, Claude sessiyasida) qilingan
#  o'zgarishlar ham shu yerga O'ZI TUSHADI — har safar avval
#  `git fetch` + `rebase`, keyin push. `--force` HECH QACHON ishlatilmaydi:
#  ikki tomon bir faylni o'zgartirgan bo'lsa, shu kompyuterdagi nusxa
#  ustun (rebase -X theirs); hal bo'lmasa — bekor qilinadi va logga yoziladi.
#
#  Himoya: oxirgi fayl 2 daqiqa ichida o'zgargan bo'lsa — kutadi
#  (yozish tugallanmagan bo'lishi mumkin). Log: C:\Sevimli\avto_yuklash.log
# ============================================================
$ErrorActionPreference = 'Continue'
$ProgressPreference = 'SilentlyContinue'
$root = 'C:\Sevimli'
$log = Join-Path $root 'avto_yuklash.log'
$lock = Join-Path $root 'avto_yuklash.lock'
#: Oxirgi o'zgarishdan keyin shuncha soniya tinchlik kutiladi
$QUIET = 120
#: Kassa versiyasi FAQAT shu yo'llardagi o'zgarishda oshiriladi
#  (skript yoki hujjat o'zgarsa yangi EXE chiqarish shart emas)
$KASSA_CODE = '^(pos/|shared/|build/|requirements\.txt$|pos_launcher\.py$)'

function Log($m) {
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m"
    Add-Content -Path $log -Value $line -Encoding UTF8
}

# Log juda katta bo'lib ketmasin
try {
    if ((Test-Path $log) -and (Get-Item $log).Length -gt 500KB) {
        Get-Content $log -Tail 400 | Set-Content $log -Encoding UTF8
    }
} catch {}

# Bir vaqtda bitta nusxa (qulf 10 daqiqadan eski bo'lsa — eskirgan)
if (Test-Path $lock) {
    if (((Get-Date) - (Get-Item $lock).LastWriteTime).TotalMinutes -lt 10) { exit 0 }
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
New-Item -ItemType File -Path $lock -Force | Out-Null

try {
    # --- Git
    $git = Join-Path $root 'PortableGit\bin\git.exe'
    if (-not (Test-Path $git)) {
        if (Get-Command git -ErrorAction SilentlyContinue) { $git = 'git' }
        else { Log "XATO: git topilmadi ($git)"; exit 1 }
    }

    $repos = @(
        @{ name = 'server'; dir = (Join-Path $root 'server'); kassa = $false },
        @{ name = 'kassa';  dir = (Join-Path $root 'kassa');  kassa = $true }
    )

    foreach ($r in $repos) {
        $dir = $r.dir
        if (-not (Test-Path (Join-Path $dir '.git'))) { continue }
        Set-Location $dir
        $name = $r.name

        # GitHub Actions ish rejasi: masofadan .github ichiga yozib
        # bo'lmaydi — papka ildizidagi nusxa joyiga ko'chiriladi.
        if ($r.kassa) {
            $wfSrc = Join-Path $dir 'github-workflow-build.yml'
            if (Test-Path $wfSrc) {
                $wfDir = Join-Path $dir '.github\workflows'
                New-Item -ItemType Directory -Force -Path $wfDir | Out-Null
                Copy-Item $wfSrc (Join-Path $wfDir 'build.yml') -Force
            }
        }

        # Chala qolgan rebase bo'lsa (oldingi urinish o'rtasida to'xtagan) — bekor
        if ((Test-Path (Join-Path $dir '.git\rebase-merge')) -or (Test-Path (Join-Path $dir '.git\rebase-apply'))) {
            & $git rebase --abort 2>&1 | Out-Null
            Log "$name: chala rebase bekor qilindi"
        }

        # --- 1. Shu kompyuterdagi o'zgarishlarni commit qilamiz
        $changes = @(& $git status --porcelain 2>$null)
        if ($changes.Count -gt 0) {
            # Yozish tugaganini kutamiz: eng yangi fayl 2 daqiqadan eski bo'lsin
            $newest = Get-ChildItem -Path $dir -Recurse -File -ErrorAction SilentlyContinue |
                Where-Object { $_.FullName -notmatch '\\\.git\\|\\dist\\|__pycache__|\\build\\ucrt\\|\\PortableGit\\' } |
                Sort-Object LastWriteTime -Descending | Select-Object -First 1
            if ($newest -and ((Get-Date) - $newest.LastWriteTime).TotalSeconds -lt $QUIET) {
                Log "$name: o'zgarish bor, yozish tugashini kutyapman ($($newest.Name))"
                continue
            }

            $n = $changes.Count
            $msg = "Avto: $(Get-Date -Format 'dd.MM HH:mm') - $n ta fayl"

            if ($r.kassa) {
                # Kod o'zgarganmi (skript/hujjat emas)? Faqat shunda versiya oshadi,
                # aks holda GitHub bekorga yangi EXE yig'ib, kassalarni qayta ochirardi.
                $codeChanged = $false
                foreach ($line in $changes) {
                    $path = $line.Substring(3).Trim().Trim('"') -replace '\\', '/'
                    if ($path -match ' -> ') { $path = ($path -split ' -> ')[-1] }
                    if ($path -match $KASSA_CODE) { $codeChanged = $true; break }
                }
                $vf = Join-Path $dir 'pos\version.py'
                $cur = (Select-String -Path $vf -Pattern 'VERSION\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
                $headTxt = (& $git show HEAD:pos/version.py 2>$null) -join "`n"
                $head = ''
                if ($headTxt -match 'VERSION\s*=\s*"([^"]+)"') { $head = $Matches[1] }
                if ($codeChanged -and $cur -and $cur -eq $head) {
                    # Versiya oshirilmagan bo'lsa — o'zimiz oshiramiz (kichik raqam),
                    # aks holda GitHub yangi Release qilmaydi, kassalar yangilanmaydi.
                    $p = $cur.Split('.')
                    while ($p.Count -lt 3) { $p += '0' }
                    $p[2] = [string]([int]$p[2] + 1)
                    $new = ($p -join '.')
                    $txt = Get-Content $vf -Raw -Encoding UTF8
                    $txt = $txt -replace ('VERSION\s*=\s*"' + [regex]::Escape($cur) + '"'), ('VERSION = "' + $new + '"')
                    [IO.File]::WriteAllText($vf, $txt, (New-Object Text.UTF8Encoding($false)))
                    Log "kassa: versiya $cur -> $new (o'zi oshirildi)"
                    $cur = $new
                }
                if ($codeChanged) { $msg = "Kassa $cur - avto ($n ta fayl)" }
                else { $msg = "Kassa - avto, kod emas ($n ta fayl)" }
            }

            & $git add -A 2>&1 | Out-Null
            & $git commit -q -m $msg 2>&1 | Out-Null
            Log "$name: commit - $msg"
        }

        # --- 2. GitHub'dagi yangiliklarni olamiz (rebase, force yo'q)
        $fetchOut = & $git fetch -q origin main 2>&1
        if ($LASTEXITCODE -ne 0) { Log "$name: fetch bo'lmadi ($fetchOut)"; continue }
        $behind = [int](& $git rev-list --count 'HEAD..origin/main' 2>$null)
        if ($behind -gt 0) {
            # -X theirs: bir faylni ikki tomon o'zgartirgan bo'lsa shu kompyuterdagi nusxa qoladi
            $rb = & $git rebase -X theirs origin/main 2>&1
            if ($LASTEXITCODE -ne 0) {
                & $git rebase --abort 2>&1 | Out-Null
                Log "$name: XATO GitHub bilan birlashtirib bo'lmadi, keyingi safar qayta urinaman: $rb"
                continue
            }
            Log "$name: GitHub'dan $behind ta yangilanish olindi"
        }

        # --- 3. Yuboramiz
        $ahead = [int](& $git rev-list --count 'origin/main..HEAD' 2>$null)
        if ($ahead -le 0) { continue }
        $out = & $git push origin HEAD:main 2>&1
        if ($LASTEXITCODE -eq 0) { Log "$name: GitHub'ga ketdi ($ahead ta commit)" }
        else { Log "$name: XATO push (keyingi safar qayta urinaman): $out" }
    }
} catch {
    Log "XATO: $($_.Exception.Message)"
} finally {
    Remove-Item $lock -Force -ErrorAction SilentlyContinue
}
