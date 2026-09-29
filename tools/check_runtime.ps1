param(
    [Parameter(Mandatory=$true)][string]$Exe,
    [Parameter(Mandatory=$true)][string]$ResultDirectory
)
$ErrorActionPreference = 'Stop'
if (Test-Path -LiteralPath $ResultDirectory) { throw 'Result directory must be new' }
$exePath = (Resolve-Path -LiteralPath $Exe).Path
$resultPath = [IO.Path]::GetFullPath($ResultDirectory)
$process = Start-Process -FilePath $exePath -ArgumentList @('--check-runtime', ('"' + $resultPath + '"')) -WindowStyle Hidden -PassThru
if (-not $process.WaitForExit(30000)) {
    $process.Kill()
    throw 'EXE runtime check timed out'
}
if ($process.ExitCode -ne 0) { throw "EXE runtime check failed: $($process.ExitCode)" }
$result = Get-Content -LiteralPath (Join-Path $resultPath 'result.json') -Raw | ConvertFrom-Json
if (-not $result.ok -or -not $result.frozen -or -not $result.printer_api -or $result.integrity -ne 'ok') {
    throw 'EXE runtime check did not confirm the required results'
}
$result | ConvertTo-Json
