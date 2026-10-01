# Checks this PC can run PyTTI. install.bat runs it before downloading anything, so an
# install that cannot work stops in seconds instead of failing an hour later.
# Run by hand: powershell -ExecutionPolicy Bypass -File app\system_check.ps1
#
# Exit codes: 0 = all checks passed, 10 = warnings only, 20 = at least one check failed

$ErrorActionPreference = 'Stop'

# The folder install.bat installs into (this script lives in its app\ subfolder)
$root = Split-Path -Parent $PSScriptRoot

# Longest file path the install creates, relative to $root (a tensorflow header under
# python\Lib\site-packages). Without long path support Windows caps full paths at 259 characters.
$longestInstallPath = 194

# Approximate space needed: the finished python\ folder, and pip's downloads and cache
$installGB = 9
$downloadGB = 6

$script:result = 0

function Write-Check($tag, $color, $msg, $hint) {
    Write-Host '       ' -NoNewline
    Write-Host $tag.PadRight(6) -ForegroundColor $color -NoNewline
    Write-Host $msg
    foreach ($line in $hint) { Write-Host "             $line" -ForegroundColor DarkGray }
}
function Pass($msg)        { Write-Check 'OK' Green $msg }
function Warn($msg, $hint) { Write-Check 'WARN' Yellow $msg $hint; $script:result = [Math]::Max($script:result, 10) }
function Fail($msg, $hint) { Write-Check 'FAIL' Red $msg $hint; $script:result = 20 }

# Runs one check; a check that errors out is reported, and the rest still run
function Check($what, [scriptblock]$body) {
    try { & $body } catch { Warn "Could not check $what" $_.Exception.Message }
}

Check 'Windows version' {
    $os = Get-CimInstance Win32_OperatingSystem
    $name = $os.Caption -replace '^Microsoft ', ''
    $cpuArch = (Get-CimInstance Win32_Processor | Select-Object -First 1).Architecture
    if ([version]$os.Version -lt [version]'10.0') {
        Fail "$name is not supported" 'PyTTI needs Windows 10 or 11.'
    } elseif (-not [Environment]::Is64BitOperatingSystem -or $cpuArch -ne 9) {   # 9 = x64
        Fail "$name on this processor is not supported" 'PyTTI needs 64-bit Windows on an Intel or AMD processor. ARM PCs are not supported.'
    } else {
        Pass "$name, 64-bit"
    }
}

Check 'memory' {
    $gb = [Math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB)
    if ($gb -lt 8) { Warn "$gb GB of RAM" '8 GB or more is recommended.' } else { Pass "$gb GB of RAM" }
}

Check 'graphics card' {
    $smi = (Get-Command nvidia-smi.exe -ErrorAction SilentlyContinue).Source
    if (-not $smi) {
        # Where drivers from before 2019 put it
        $smi = "$env:ProgramFiles\NVIDIA Corporation\NVSMI\nvidia-smi.exe"
        if (-not (Test-Path $smi)) { $smi = $null }
    }

    $gpus = @()
    if ($smi) {
        # Under 'Stop', Windows PowerShell turns a native command's stderr into an exception
        $ErrorActionPreference = 'Continue'
        $lines = & $smi --query-gpu=name,driver_version,memory.total,compute_cap --format=csv,noheader,nounits 2>$null
        # Drivers older than ~510 don't know the compute_cap field
        if ($LASTEXITCODE -ne 0) { $lines = & $smi --query-gpu=name,driver_version,memory.total --format=csv,noheader,nounits 2>$null }
        $ErrorActionPreference = 'Stop'
        if ($LASTEXITCODE -eq 0) {
            $gpus = @($lines | Where-Object { $_ } | ForEach-Object {
                $f = $_ -split ',\s*'
                $vramGB = [Math]::Round([double]$f[2] / 1024)
                [pscustomobject]@{
                    Label  = "$($f[0]), $vramGB GB"
                    VramGB = $vramGB
                    Driver = [version]$f[1]
                    Arch   = if ($f.Count -gt 3) { [version]$f[3] } else { $null }
                }
            })
        }
    }

    if (-not $gpus) {
        $cards = @(Get-CimInstance Win32_VideoController)
        if ($cards | Where-Object { $_.PNPDeviceID -match 'VEN_10DE' }) {   # NVIDIA's PCI vendor ID
            Fail 'NVIDIA graphics card found, but its driver is missing or not working' 'Install the latest driver from https://www.nvidia.com/drivers, restart, then run install.bat again.'
        } else {
            $found = @($cards | ForEach-Object { $_.Name } | Sort-Object -Unique) -join ', '
            Fail 'No NVIDIA graphics card found' @("Found: $(if ($found) { $found } else { 'none' })", 'PyTTI needs an NVIDIA GPU (GTX 10xx through RTX 40xx). AMD and Intel GPUs are not supported.')
        }
        return
    }

    # PyTorch 2.0 + CUDA 11.7 runs on compute capability 5.0 (GTX 9xx) through 8.9 (RTX 40xx)
    $supported = @($gpus | Where-Object { -not $_.Arch -or ($_.Arch -ge [version]'5.0' -and $_.Arch -lt [version]'9.0') })
    foreach ($gpu in $gpus) {
        if ($supported -contains $gpu) {
            if ($gpu.Arch -and $gpu.Arch -lt [version]'6.0') {
                Warn "$($gpu.Label) is older than the GTX 10xx series" 'It may work, but it is untested and will be slow.'
            } elseif ($gpu.VramGB -lt 6) {
                Warn "$($gpu.Label) has little video memory" 'Default settings may run out of memory. Use a smaller size or fewer CLIP models.'
            } else {
                Pass $gpu.Label
            }
            continue
        }
        if ($gpu.Arch -ge [version]'9.0') {
            $problem = "$($gpu.Label) is too new"
            $hint = 'PyTTI uses PyTorch 2.0 with CUDA 11.7, which supports cards up to the RTX 40xx series. RTX 50xx is not supported.'
        } else {
            $problem = "$($gpu.Label) is too old"
            $hint = 'PyTorch 2.0 needs a GTX 9xx series card or newer.'
        }
        # Another card in the PC can still run it
        if ($supported) { Warn $problem $hint } else { Fail $problem $hint }
    }

    $driver = $gpus[0].Driver
    if ($driver -lt [version]'452.39') {
        Fail "NVIDIA driver $driver is too old for CUDA 11" 'Update it from https://www.nvidia.com/drivers, then run install.bat again.'
    } elseif ($driver -lt [version]'516.01') {
        Warn "NVIDIA driver $driver is older than CUDA 11.7 expects (516.01)" 'Updating it from https://www.nvidia.com/drivers is recommended.'
    } else {
        Pass "NVIDIA driver $driver"
    }
}

Check 'Visual C++ runtime' {
    # PyTorch and TensorFlow load these from System32. A 32-bit PowerShell sees SysWOW64
    # there instead; Sysnative is the real one.
    $system32 = if ([Environment]::Is64BitProcess) { [Environment]::SystemDirectory } else { "$env:windir\Sysnative" }
    if (@('msvcp140.dll', 'msvcp140_1.dll') | Where-Object { -not (Test-Path (Join-Path $system32 $_)) }) {
        Fail 'Microsoft Visual C++ Redistributable is not installed' 'Install it from https://aka.ms/vs/17/release/vc_redist.x64.exe, then run install.bat again.'
    } else {
        Pass 'Microsoft Visual C++ Redistributable'
    }
}

Check 'Git' {
    if (Get-Command git -ErrorAction SilentlyContinue) {
        Pass "Git $((git --version) -replace '^git version ', '')"
    } else {
        Fail 'Git is not installed or not on PATH' 'Install it from https://git-scm.com, then run install.bat again.'
    }
}

Check 'install folder' {
    $probe = Join-Path $root '.write-test'
    try {
        [IO.File]::WriteAllText($probe, '')
        Remove-Item $probe
    } catch {
        Fail "Can't write to $root" 'Move the pytti folder somewhere you own, such as C:\pytti.'
        return
    }

    $longPaths = (Get-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem' -ErrorAction SilentlyContinue).LongPathsEnabled -eq 1
    $maxRoot = 259 - 1 - $longestInstallPath
    $oneDrive = @($env:OneDrive, $env:OneDriveConsumer, $env:OneDriveCommercial) |
        Where-Object { $_ -and "$root\".StartsWith("$($_.TrimEnd('\'))\", 'OrdinalIgnoreCase') }

    if (-not $longPaths -and $root.Length -gt $maxRoot) {
        Fail "The folder path is too long: $($root.Length) characters, the limit is $maxRoot" @($root, 'Move the pytti folder to a shorter path such as C:\pytti, or turn on Windows long path support.')
    } elseif ($oneDrive) {
        Warn 'The pytti folder is inside OneDrive' 'OneDrive will try to sync the ~8 GB install. Moving the folder out, e.g. to C:\pytti, is recommended.'
    } else {
        Pass "Install folder $root"
    }
}

Check 'disk space' {
    # pip downloads into %TEMP% and caches under %LOCALAPPDATA%, usually the same drive as Windows
    $need = [ordered]@{}
    $need[[IO.Path]::GetPathRoot($root)] += $installGB
    $need[[IO.Path]::GetPathRoot($env:TEMP)] += $downloadGB
    foreach ($drive in $need.Keys) {
        $free = [Math]::Floor((New-Object IO.DriveInfo $drive).AvailableFreeSpace / 1GB)
        $letter = $drive.TrimEnd('\')
        if ($free -lt $need[$drive]) {
            Fail "$free GB free on $letter, the install needs about $($need[$drive]) GB there" "Free up space on $letter, then run install.bat again."
        } else {
            Pass "$free GB free on $letter"
        }
    }
}

exit $script:result
