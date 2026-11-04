param(
    [string]$Python313,
    [string]$Python312,
    [string]$Templates,
    [string]$LiteTemplates,
    [string]$TrainingWheel,
    [ValidatePattern('^[A-Za-z0-9-]+$')]
    [string]$OutputSuffix,
    [switch]$HardwareTestCandidate
)

$ErrorActionPreference = 'Stop'
if ($TrainingWheel) {
    if (-not (Test-Path -LiteralPath $TrainingWheel -PathType Leaf) -or
        (Split-Path $TrainingWheel -Leaf) -notmatch '^neural_amp_modeler-[^-]+-[^-]+-[^-]+-[^-]+\.whl$') {
        throw 'Provide an existing neural_amp_modeler wheel with its original package filename.'
    }
}
$root = Split-Path $PSScriptRoot -Parent
$tooling = Join-Path $root '.tooling'
[xml]$versionConfig = Get-Content -LiteralPath (Join-Path $root 'Directory.Build.props') -Raw
$releaseVersion = [string]$versionConfig.Project.PropertyGroup.Version
if ($releaseVersion -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?$') {
    throw 'Directory.Build.props must specify a version such as 1.0.0 or 1.0.0-preview.1.'
}
$name = "nam2zoom-v$releaseVersion-windows-x64"
if ($OutputSuffix) { $name += "-$OutputSuffix" }
if ($HardwareTestCandidate) { $name += '-hardware-test-' + (Get-Date -Format 'yyyyMMdd-HHmmss') }
$dist = Join-Path $root 'dist'
$payload = Join-Path $dist $name
$archive = Join-Path $dist "$name.zip"
if ((Test-Path -LiteralPath $payload) -or (Test-Path -LiteralPath $archive)) {
    throw "Build output already exists: $name. Move the existing output or bump Version in Directory.Build.props."
}
function Run([string]$exe, [string[]]$arguments) {
    & $exe @arguments
    if ($LASTEXITCODE -ne 0) { throw "$exe failed with exit code $LASTEXITCODE" }
}
if (-not $Python312) {
    $Python312 = Get-ChildItem -LiteralPath (Join-Path $tooling 'python') -Directory |
        Where-Object Name -Like 'cpython-3.12.*-windows-x86_64-none' |
        Sort-Object { [version]($_.Name -replace '^cpython-(\d+\.\d+\.\d+).*', '$1') } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}
if (-not $Python313) {
    $Python313 = Get-ChildItem -LiteralPath (Join-Path $tooling 'python') -Directory |
        Where-Object Name -Like 'cpython-3.13.*-windows-x86_64-none' |
        Sort-Object { [version]($_.Name -replace '^cpython-(\d+\.\d+\.\d+).*', '$1') } -Descending |
        Select-Object -First 1 -ExpandProperty FullName
    if (-not $Python313) { $Python313 = "$env:LOCALAPPDATA\Programs\Python\Python313" }
}
foreach ($pythonHome in @($Python312, $Python313)) {
    if (-not $pythonHome -or -not (Test-Path -LiteralPath (Join-Path $pythonHome 'python.exe'))) {
        throw 'Provide -Python312 and -Python313 runtime roots; run developer setup first.'
    }
}
$work = Join-Path $tooling ('portable-release-' + (Get-Date -Format 'yyyyMMdd-HHmmss'))
New-Item -ItemType Directory -Path $work | Out-Null
if (-not $Templates) {
    $Templates = Join-Path $work 'templates'
    Run (Join-Path $tooling 'stomphacks/.venv/Scripts/python.exe') @(
        (Join-Path $root 'release/create_templates.py'), '--output', $Templates,
        '--work', (Join-Path $work 'template-build'))
}
if (-not (Test-Path -LiteralPath (Join-Path $Templates 'index.json'))) { throw 'Templates missing index.json' }
if (-not $LiteTemplates) {
    $LiteTemplates = Join-Path $work 'templates-lite'
    Run (Join-Path $tooling 'stomphacks/.venv/Scripts/python.exe') @(
        (Join-Path $root 'release/create_templates.py'), '--output', $LiteTemplates,
        '--work', (Join-Path $work 'template-lite-build'), '--profile', 'lite')
}
if (-not (Test-Path -LiteralPath (Join-Path $LiteTemplates 'index.json'))) { throw 'Lite templates missing index.json' }
$env:NAM2ZOOM_TEMPLATE_DIR = (Resolve-Path -LiteralPath $Templates).Path
if ($HardwareTestCandidate) {
    $env:NAM2ZOOM_HARDWARE_TEST_CANDIDATE = '1'
    Write-Host 'Hardware-test candidate: DSP hardware baseline is unverified; structural checks still run.'
} else {
    Remove-Item Env:NAM2ZOOM_HARDWARE_TEST_CANDIDATE -ErrorAction SilentlyContinue
}
Run (Join-Path $tooling 'stomphacks/.venv/Scripts/python.exe') @('-m', 'unittest', 'discover',
    '-s', (Join-Path $root 'tests'), '-p', 'test_templates.py')
$env:NAM2ZOOM_LITE_TEMPLATE_DIR = (Resolve-Path -LiteralPath $LiteTemplates).Path
Run (Join-Path $tooling 'stomphacks/.venv/Scripts/python.exe') @('-m', 'unittest', 'discover',
    '-s', (Join-Path $root 'tests'), '-p', 'test_lite_profiles.py')

$kind = if ($HardwareTestCandidate) { 'hardware-test' } else { 'preview' }
New-Item -ItemType Directory -Path $dist -Force | Out-Null
New-Item -ItemType Directory -Path $payload | Out-Null
Run 'dotnet' @('publish', (Join-Path $root 'apps/nam2zoom-desktop/nam2zoom-desktop.csproj'),
    '-c', 'Release', '-r', 'win-x64', '--self-contained', 'true',
    '-p:PublishSingleFile=true', '-p:DebugType=None', '-p:DebugSymbols=false', '-o', $payload)
foreach ($folder in @('tools', 'dsp', 'training')) {
    Copy-Item -LiteralPath (Join-Path $root $folder) -Destination (Join-Path $payload $folder) -Recurse
}
New-Item -ItemType Directory -Path (Join-Path $payload 'release') | Out-Null
Copy-Item -LiteralPath $Templates -Destination (Join-Path $payload 'release/templates') -Recurse
Copy-Item -LiteralPath $LiteTemplates -Destination (Join-Path $payload 'release/templates-lite') -Recurse
Copy-Item -LiteralPath (Join-Path $root 'docs/USER_GUIDE.md') -Destination (Join-Path $payload 'README.md')
Copy-Item -LiteralPath (Join-Path $root 'LICENSE') -Destination $payload
$licenses = Join-Path $payload 'ThirdPartyLicenses'
New-Item -ItemType Directory -Path $licenses | Out-Null
$dotnetHome = Split-Path (Get-Command dotnet).Source -Parent
Copy-Item -LiteralPath (Join-Path $dotnetHome 'LICENSE.txt') -Destination (Join-Path $licenses 'dotnet-LICENSE.txt')
Copy-Item -LiteralPath (Join-Path $dotnetHome 'ThirdPartyNotices.txt') -Destination (Join-Path $licenses 'dotnet-ThirdPartyNotices.txt')
foreach ($package in @('stomphacks', 'neural-amp-modeler', 'NeuralAmpModelerCore')) {
    Copy-Item -LiteralPath (Join-Path $tooling "$package/LICENSE") -Destination (Join-Path $licenses "$package.txt")
}
Get-ChildItem -LiteralPath (Join-Path $tooling 'NeuralAmpModelerCore/Dependencies') -Recurse -File |
    Where-Object { $_.Name -match '^(LICENSE|COPYING|NOTICE)' } | ForEach-Object {
        $relative = $_.FullName.Substring((Join-Path $tooling 'NeuralAmpModelerCore/Dependencies').Length + 1)
        $destination = Join-Path $licenses ('core-' + $relative.Replace('\', '-'))
        Copy-Item -LiteralPath $_.FullName -Destination $destination
    }

$stomp = Join-Path $payload '.tooling/stomphacks'
foreach ($folder in @('tools-pedal', 'tools', 'zoom-zt2')) { New-Item -ItemType Directory -Path (Join-Path $stomp $folder) -Force | Out-Null }
foreach ($file in @('safe_connect.py', 'pedal_diy.py', 'readback.py', 'pedal_common.py', 'file_session.py', 'stock_catalog.py')) {
    Copy-Item -LiteralPath (Join-Path $tooling "stomphacks/tools-pedal/$file") -Destination (Join-Path $stomp 'tools-pedal')
}
Copy-Item -LiteralPath (Join-Path $tooling 'stomphacks/tools/flst_check.py') -Destination (Join-Path $stomp 'tools')
foreach ($file in @('zoomzt2.py', 'decode_preset.py', 'LICENSE')) {
    Copy-Item -LiteralPath (Join-Path $tooling "stomphacks/zoom-zt2/$file") -Destination (Join-Path $stomp 'zoom-zt2')
}
Copy-Item -LiteralPath (Join-Path $tooling 'stomphacks/SAFETY.md') -Destination $stomp

$renderer = Join-Path $payload 'reference/nam_a2/build-core-ninja'
New-Item -ItemType Directory -Path $renderer -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $root 'reference/nam_a2/build-core-ninja/core_render.exe') -Destination $renderer
$runtime = Join-Path $payload 'runtime'
New-Item -ItemType Directory -Path $runtime | Out-Null
foreach ($version in @('312', '313')) {
    $pythonHome = if ($version -eq '312') { $Python312 } else { $Python313 }
    $target = Join-Path $runtime "python$version"
    New-Item -ItemType Directory -Path (Join-Path $target 'Lib') -Force | Out-Null
    foreach ($file in @('python.exe', 'python3.dll', "python$version.dll", 'vcruntime140.dll', 'vcruntime140_1.dll', 'LICENSE.txt')) {
        Copy-Item -LiteralPath (Join-Path $pythonHome $file) -Destination $target
    }
    Copy-Item -LiteralPath (Join-Path $pythonHome 'DLLs') -Destination (Join-Path $target 'DLLs') -Recurse
    Get-ChildItem -LiteralPath (Join-Path $pythonHome 'Lib') | Where-Object { $_.Name -notin @('site-packages', '__pycache__') } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination (Join-Path $target 'Lib') -Recurse
    }
}
$site = Join-Path $tooling 'stomphacks/.venv/Lib/site-packages'
$targetSite = Join-Path $runtime 'python313/Lib/site-packages'
New-Item -ItemType Directory -Path $targetSite | Out-Null
foreach ($package in @('mido', 'rtmidi', 'construct', 'packaging')) {
    Copy-Item -LiteralPath (Join-Path $site $package) -Destination $targetSite -Recurse
}
Get-ChildItem -LiteralPath $site -Directory | Where-Object { $_.Name -match '^(mido|python_rtmidi|construct|packaging)-.*\.dist-info$' } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $targetSite -Recurse
}
if ($TrainingWheel) {
    Copy-Item -LiteralPath $TrainingWheel -Destination $runtime
} else {
    $env:UV_CACHE_DIR = Join-Path $tooling 'portable-uv-cache'
    $env:SETUPTOOLS_SCM_PRETEND_VERSION_FOR_NEURAL_AMP_MODELER = '0.1.dev1'
    Run 'uv' @('build', '--wheel', '--out-dir', $runtime, (Join-Path $tooling 'neural-amp-modeler'))
}
Copy-Item -LiteralPath (Join-Path $root 'release/training-constraints.txt') -Destination $runtime
if (@(Get-ChildItem -LiteralPath $runtime -Filter 'neural_amp_modeler-*.whl' -File).Count -ne 1) {
    throw 'Portable runtime must contain exactly one neural_amp_modeler training wheel.'
}
New-Item -ItemType File -Path (Join-Path $runtime 'portable.marker') | Out-Null
$env:PYTHONPATH = Join-Path $payload 'tools'
Run (Join-Path $runtime 'python313/python.exe') @('-c', "import mido, rtmidi, construct; from nam2zoom.template import fill_template; print('Portable backend imports OK')")
Run (Join-Path $runtime 'python312/python.exe') @('-m', 'venv', (Join-Path $work 'venv-smoke'))
Compress-Archive -LiteralPath $payload -DestinationPath $archive
Write-Host "Portable $kind ZIP: $archive"
