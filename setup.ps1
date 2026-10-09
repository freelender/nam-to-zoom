param(
    [string]$TiCgt,
    [string]$TorchIndexUrl
)

$ErrorActionPreference = 'Stop'
$root = $PSScriptRoot
$tooling = Join-Path $root '.tooling'
$stomp = Join-Path $tooling 'stomphacks'
$nam = Join-Path $tooling 'neural-amp-modeler'
$core = Join-Path $tooling 'NeuralAmpModelerCore'
$stompRev = 'ebd5ced93988d595bb42c825dd9bd89626b300e6'
$namRev = '0072676419459f5d39e36f5b9fd4172f28d62cbf'
$coreRev = '0b3d3c97b0859a3a8c92a8628c4dd89a25eb5842'

foreach ($command in @('git', 'uv', 'cmake', 'dotnet')) {
    if (-not (Get-Command $command -ErrorAction SilentlyContinue)) {
        throw "Missing prerequisite: $command. See README.md."
    }
}

$gitExe = (Get-Command git).Source
$gitBash = Join-Path (Split-Path (Split-Path $gitExe -Parent) -Parent) 'bin/bash.exe'
if (-not (Test-Path -LiteralPath $gitBash)) { throw "Git Bash not found at $gitBash" }

New-Item -ItemType Directory -Force -Path $tooling | Out-Null
$reuseTooling = (Get-Item -LiteralPath $tooling -Force).LinkType -eq 'Junction'
if (-not $reuseTooling) {
    $env:UV_CACHE_DIR = Join-Path $tooling 'uv-cache'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $tooling 'python'
}

function Invoke-Checked {
    param([string]$name, [Parameter(ValueFromRemainingArguments=$true)][string[]]$arguments)
    Write-Host "Running: $name $($arguments -join ' ')"
    & $name @arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$name $($arguments -join ' ') failed with exit code $LASTEXITCODE"
    }
}

$expectedTi = Join-Path $tooling 'cgt-8.3.1/ti-cgt-c6000_8.3.1'
if ($TiCgt) {
    $resolvedTi = (Resolve-Path -LiteralPath $TiCgt).Path
    if (-not (Test-Path -LiteralPath (Join-Path $resolvedTi 'bin/cl6x.exe'))) {
        throw "-TiCgt must point to the compiler root containing bin/cl6x.exe"
    }
    if (-not (Test-Path -LiteralPath $expectedTi)) {
        New-Item -ItemType Directory -Force -Path (Split-Path $expectedTi) | Out-Null
        New-Item -ItemType Junction -Path $expectedTi -Target $resolvedTi | Out-Null
    }
}
if (-not (Test-Path -LiteralPath (Join-Path $expectedTi 'bin/cl6x.exe'))) {
    throw "Install TI C6000 CGT 8.3.1, then rerun with -TiCgt <compiler-root>."
}

$vswhere = Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio/Installer/vswhere.exe'
if (-not (Test-Path -LiteralPath $vswhere)) { throw 'Visual Studio vswhere.exe not found' }
$vsRoot = & $vswhere -latest -products '*' -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath | Select-Object -First 1
if (-not $vsRoot) { throw 'Visual Studio C++ workload not found' }
$vsRoot = $vsRoot.Trim()
$vcvars = Join-Path $vsRoot 'VC/Auxiliary/Build/vcvars64.bat'
$ninja = Join-Path $vsRoot 'Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe'
if (-not (Test-Path -LiteralPath $vcvars) -or -not (Test-Path -LiteralPath $ninja)) {
    throw 'Visual Studio C++ environment or Ninja not found'
}

function Ensure-Checkout([string]$directory, [string]$url, [string]$revision,
                         [string]$patch, [bool]$submodules) {
    if (-not (Test-Path -LiteralPath (Join-Path $directory '.git'))) {
        Invoke-Checked 'git' @('clone', $url, $directory)
        Invoke-Checked 'git' @('-C', $directory, 'checkout', '--detach', $revision)
        if ($patch) { Invoke-Checked 'git' @('-C', $directory, 'apply', $patch) }
    } else {
        $head = (& git -C $directory rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0 -or $head -ne $revision) {
            throw "Existing checkout at $directory is not the pinned revision $revision"
        }
        if ($patch) {
            & git -C $directory apply --reverse --check $patch 2>$null
            if ($LASTEXITCODE -ne 0) {
                & git -C $directory apply --check $patch 2>$null
                if ($LASTEXITCODE -ne 0) {
                    throw "Required local patch conflicts with existing changes in $directory"
                }
                Invoke-Checked 'git' @('-C', $directory, 'apply', $patch)
            }
        }
    }
    if ($submodules -and -not $reuseTooling) {
        $posixDirectory = $directory.Replace('\', '/')
        Invoke-Checked $gitBash @('-lc', "git -C '$posixDirectory' submodule update --init")
    }
}

Ensure-Checkout $stomp 'https://github.com/thammer/stomphacks.git' $stompRev `
    (Join-Path $root 'patches/stomphacks.patch') $false
Ensure-Checkout (Join-Path $stomp 'zoom-zt2') 'https://github.com/mungewell/zoom-zt2.git' `
    'b1f63b0bee6d2d1bc9755958fc8cf15887efbdcf' '' $false
Ensure-Checkout $stomp 'https://github.com/thammer/stomphacks.git' $stompRev `
    (Join-Path $root 'patches/stomphacks-catalogue.patch') $false
Ensure-Checkout $stomp 'https://github.com/thammer/stomphacks.git' $stompRev `
    (Join-Path $root 'patches/stomphacks-ten-models.patch') $false
Ensure-Checkout $stomp 'https://github.com/thammer/stomphacks.git' $stompRev `
    (Join-Path $root 'patches/stomphacks-user-data.patch') $false
Ensure-Checkout $nam 'https://github.com/sdatkinson/neural-amp-modeler.git' $namRev `
    (Join-Path $root 'patches/neural-amp-modeler.patch') $false
Ensure-Checkout $core 'https://github.com/sdatkinson/NeuralAmpModelerCore.git' $coreRev '' $true

$stompPython = Join-Path $stomp '.venv/Scripts/python.exe'
$trainPython = Join-Path $tooling 'nam-train-venv/Scripts/python.exe'
$newStompVenv = -not (Test-Path -LiteralPath $stompPython)
$newTrainVenv = -not (Test-Path -LiteralPath $trainPython)
if (($newStompVenv -or $newTrainVenv) -and -not $reuseTooling) {
    $pythonVersions = @()
    if ($newStompVenv) { $pythonVersions += '3.13' }
    if ($newTrainVenv) { $pythonVersions += '3.12' }
    Invoke-Checked 'uv' (@('python', 'install') + $pythonVersions)
}
if ($newStompVenv) {
    if ($reuseTooling) { throw "Reused tooling has no Stomphacks Python: $stompPython" }
    Invoke-Checked 'uv' @('venv', (Join-Path $stomp '.venv'), '--python', '3.13')
}
if ($newTrainVenv) {
    if ($reuseTooling) { throw "Reused tooling has no NAM training Python: $trainPython" }
    Invoke-Checked 'uv' @('venv', (Join-Path $tooling 'nam-train-venv'), '--python', '3.12')
}
if ($newStompVenv) {
    Invoke-Checked 'uv' @('pip', 'install', '--python', $stompPython,
                          '-r', (Join-Path $stomp 'requirements.txt'))
} else {
    Invoke-Checked $stompPython @('-c', 'import PIL, mido, rtmidi, elftools')
}
if ($newTrainVenv) {
    if ($TorchIndexUrl) {
        Invoke-Checked 'uv' @('pip', 'install', '--python', $trainPython,
                              'torch', '--index-url', $TorchIndexUrl)
    }
    Invoke-Checked 'uv' @('pip', 'install', '--python', $trainPython,
                          '-e', $nam, 'soundfile')
} else {
    Invoke-Checked $trainPython @('-c', 'import nam, torch, scipy, soundfile')
}

$renderBuild = Join-Path $root 'reference/nam_a2/build-core-ninja'
$renderSource = Join-Path $root 'reference/nam_a2'
$command = 'call "{0}" >nul && cmake --fresh -G Ninja -S "{1}" -B "{2}" -DCORE_ROOT="{3}" -DCMAKE_MAKE_PROGRAM="{4}" -DCMAKE_BUILD_TYPE=Release && cmake --build "{2}" --target core_render' -f $vcvars, $renderSource, $renderBuild, $core, $ninja
& $env:ComSpec /d /s /c $command
if ($LASTEXITCODE -ne 0) { throw "core_render build failed with exit code $LASTEXITCODE" }
$renderFlat = Join-Path $renderBuild 'core_render.exe'
if (-not (Test-Path -LiteralPath $renderFlat)) { throw 'core_render.exe was not built' }

$project = Join-Path $root 'apps/nam2zoom-desktop/nam2zoom-desktop.csproj'
Invoke-Checked 'dotnet' @('build', $project, '-c', 'Release')
Invoke-Checked 'dotnet' @('run', '--project', (Join-Path $root 'tests/conversion-quality/ConversionQualitySmoke.csproj'), '-c', 'Release')
Invoke-Checked $stompPython @('-m', 'unittest', 'discover', '-s', (Join-Path $root 'tests'), '-p', 'test_*.py')
Invoke-Checked $trainPython @('-m', 'unittest', 'discover', '-s', (Join-Path $root 'tests'), '-p', 'test_ir.py')
Invoke-Checked $trainPython @('-m', 'unittest', 'discover', '-s', (Join-Path $root 'tests'), '-p', 'test_adaptation_quality.py')
Write-Host "Setup complete. Launch $(Join-Path $root 'apps/nam2zoom-desktop/bin/Release/net10.0-windows/nam2zoom-desktop.exe')"
