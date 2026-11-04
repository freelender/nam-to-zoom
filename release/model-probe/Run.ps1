param([ValidateSet('full','compact','decode')][string]$Action,[string]$PortableRoot,[string]$Wav)
$ErrorActionPreference='Stop'
if (-not $PortableRoot) {
    $candidate=Join-Path $PSScriptRoot '../../cross-platform/nam2zoom-v1.9.3-windows-x64'
    if (Test-Path -LiteralPath (Join-Path $candidate 'runtime/python/python.exe')) { $PortableRoot=$candidate }
    else { $PortableRoot=(Read-Host 'Full path to your extracted nam2zoom folder').Trim('"') }
}
$PortableRoot=[IO.Path]::GetFullPath($PortableRoot)
$python=Join-Path $PortableRoot 'runtime/python/python.exe'
if (-not (Test-Path -LiteralPath $python)) { throw 'Complete portable app not found.' }
if (-not $Action) {
    Write-Host 'Temporary tuner probe: report tones replace guitar output. Do not save its patch.' -ForegroundColor Cyan
    Write-Host '1 = Install Full probe; 2 = Install Compact probe; 3 = Decode recorded WAV'
    $Action=switch (Read-Host 'Choose') { '1' {'full'} '2' {'compact'} '3' {'decode'} default {throw 'No action selected'} }
}
if ($Action -eq 'decode') {
    if (-not $Wav) { $Wav=(Read-Host 'Full path to WAV').Trim('"') }
    & $python -B (Join-Path $PSScriptRoot 'decode_model_probe.py') $Wav
    if ($LASTEXITCODE -ne 0) { throw 'Decode failed; send the original WAV for analysis.' }
    exit
}
Write-Host 'Close other MIDI apps; select a stock-only patch before installing.' -ForegroundColor Yellow
$kit=Get-Content -LiteralPath (Join-Path $PSScriptRoot 'probe-kit.json') -Raw | ConvertFrom-Json
$hashes=$kit.variants.$Action
$effect=Join-Path $PSScriptRoot "$Action/build/N2ZBANK.ZD2"
$icon=[IO.Path]::ChangeExtension($effect,'.ZIC')
if ((Get-FileHash -LiteralPath $effect -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hashes.zd2_sha256 -or
    (Get-FileHash -LiteralPath $icon -Algorithm SHA256).Hash.ToLowerInvariant() -ne $hashes.zic_sha256) { throw 'Probe hashes do not match.' }
$data=Join-Path $env:LOCALAPPDATA 'nam2zoom'
$session=Join-Path $data ('model-probe/'+(Get-Date -Format 'yyyyMMdd-HHmmss-fff')+'-'+$Action)
$env:NAM2ZOOM_DATA_DIR=$data
$env:NAM2ZOOM_PEDAL_LOG=Join-Path $data 'logs/pedal_diy.log'
$env:PYTHONPATH=Join-Path $PortableRoot 'tools'
New-Item -ItemType Directory -Force -Path (Join-Path $data 'logs') | Out-Null
Push-Location $PortableRoot
try {
    & $python -B -m nam2zoom install-bank $effect --session $session --approved-zd2-sha256 $hashes.zd2_sha256 --approved-zic-sha256 $hashes.zic_sha256 --ack-risk
    if ($LASTEXITCODE -ne 0) { throw 'Guarded installation failed; read the output.' }
    Write-Host "Backup/session: $session"
    Write-Host 'Use N2Z Bank alone in an unsaved patch. Select a model other than the first. Record 35 seconds; tuner on for 5 seconds, off, then wait 35 seconds; move Model away and back to the selected model, then record 35 seconds more.'
    Write-Host 'Read README.md. Restore your normal bank afterward through Build effect.'
} finally { Pop-Location }
