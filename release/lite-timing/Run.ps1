param(
    [ValidateSet('original','optimized','decode','compare')][string]$Action,
    [string]$Wav,
    [string]$CompareWav,
    [string]$PortableRoot
)
$ErrorActionPreference = 'Stop'
if (-not $PortableRoot) { $PortableRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '../..')) }
$python = Join-Path $PortableRoot 'runtime/python/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Run this kit inside the complete portable package, or supply -PortableRoot.' }
if (-not $Action) {
    Write-Host 'Lite timing: temporary test only. NEVER SAVE the test patch.' -ForegroundColor Cyan
    Write-Host 'Use a stock current patch. The installer backs up patches and disables autosave.'
    Write-Host '1 = Install original; 2 = Install optimized; 3 = Decode WAV; 4 = Compare two WAVs'
    $choice = Read-Host 'Choose'
    $Action = switch ($choice) { '1' {'original'} '2' {'optimized'} '3' {'decode'} '4' {'compare'} default {throw 'No action selected'} }
}
if ($Action -in @('original','optimized')) {
    Write-Host 'Do not save, reboot into, or use other effects alongside this Lite diagnostic.' -ForegroundColor Yellow
    $kit = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'timing-kit.json') -Raw | ConvertFrom-Json
    $hashes = $kit.variants.$Action
    $effect = Join-Path $PSScriptRoot "$Action/build/N2ZBANK.ZD2"
    $icon = [IO.Path]::ChangeExtension($effect, '.ZIC')
    if ((Get-FileHash -LiteralPath $effect -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hashes.zd2_sha256 -or
        (Get-FileHash -LiteralPath $icon -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hashes.zic_sha256) { throw 'Kit hashes do not match.' }
    $data = Join-Path $env:LOCALAPPDATA 'nam2zoom'
    $session = Join-Path $data ('lite-timing/' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '-' + $Action)
    $env:NAM2ZOOM_DATA_DIR = $data
    $env:NAM2ZOOM_PEDAL_LOG = Join-Path $data 'logs/pedal_diy.log'
    New-Item -ItemType Directory -Force -Path (Join-Path $data 'logs') | Out-Null
    $env:PYTHONPATH = Join-Path $PortableRoot 'tools'
    Push-Location $PortableRoot
    try {
        & $python -B -m nam2zoom install-bank $effect --session $session --approved-zd2-sha256 $hashes.zd2_sha256 --approved-zic-sha256 $hashes.zic_sha256 --ack-risk
        if ($LASTEXITCODE -ne 0) { throw 'Guarded installation failed; read the output before proceeding.' }
        Write-Host "Backup/session: $session"
        Write-Host 'Add N2Z Bank to the unsaved empty patch, Model ORIG/OPT, all controls at defaults. Record 40 seconds.'
        Write-Host 'Remove it from the unsaved patch and select a stock patch before the next installation.'
    } finally { Pop-Location }
} else {
    if (-not $Wav) { $Wav = (Read-Host 'Full path to WAV').Trim('"') }
    $arguments = @('-B', (Join-Path $PSScriptRoot 'decode_lite_timing.py'), $Wav)
    if ($Action -eq 'compare') {
        if (-not $CompareWav) { $CompareWav = (Read-Host 'Full path to second WAV').Trim('"') }
        $arguments += @('--compare', $CompareWav)
    }
    & $python @arguments
    if ($LASTEXITCODE -ne 0) { throw 'WAV could not be accepted; read the decoder output.' }
}
