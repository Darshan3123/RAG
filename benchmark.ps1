<#
.SYNOPSIS
    Universal Resource Profiler (CPU, RAM, Incoming & Outgoing Network Traffic)
.DESCRIPTION
    Monitors any project (via Command execution, Process Name, Listening Port, PID, or Docker Containers)
    and generates an exact hardware sizing report with Min/Peak metrics.
.EXAMPLE
    # Run and profile a command directly until completion:
    .\benchmark.ps1 -Command "python main.py --once"

.EXAMPLE
    # Profile a running application by process name:
    .\benchmark.ps1 -ProcessName "python", "chrome", "node" -DurationSeconds 60

.EXAMPLE
    # Profile by listening port:
    .\benchmark.ps1 -Port 8000 -DurationSeconds 30

.EXAMPLE
    # Profile Docker containers:
    .\benchmark.ps1 -Docker -DurationSeconds 45

.EXAMPLE
    # Profile a specific Process ID until it exits:
    .\benchmark.ps1 -PidToTrack 12345
#>

param(
    [string]$Command,
    [string[]]$ProcessName,
    [int]$Port,
    [int[]]$PidToTrack,
    [switch]$Docker,
    [int]$DurationSeconds = 0,
    [int]$IntervalMs = 1000
)

# Auto-activate local venv if available so python commands resolve cleanly
$venvPath = Join-Path $PSScriptRoot "venv\Scripts"
if (Test-Path (Join-Path $venvPath "python.exe")) {
    $env:PATH = "$venvPath;$env:PATH"
}

function Format-Bytes {
    param([double]$Bytes)
    if ($Bytes -ge 1GB) { return "{0:N2} GB" -f ($Bytes / 1GB) }
    if ($Bytes -ge 1MB) { return "{0:N2} MB" -f ($Bytes / 1MB) }
    if ($Bytes -ge 1KB) { return "{0:N2} KB" -f ($Bytes / 1KB) }
    return "{0:N0} B" -f $Bytes
}

function Parse-DockerNetBytes {
    param([string]$NetStr)
    $parts = $NetStr -split '/'
    if ($parts.Count -lt 2) { return @{ Rx = 0.0; Tx = 0.0 } }

    function Convert-ToBytes([string]$val) {
        $val = $val.Trim()
        $num = [regex]::Match($val, '[\d\.]+').Value
        if (-not $num) { return 0.0 }
        $n = [double]$num
        if ($val -match 'GiB|GB') { return $n * 1GB }
        if ($val -match 'MiB|MB') { return $n * 1MB }
        if ($val -match 'KiB|kB|KB') { return $n * 1KB }
        return $n
    }

    return @{
        Rx = Convert-ToBytes $parts[0]
        Tx = Convert-ToBytes $parts[1]
    }
}

function Get-SystemNetBytes {
    try {
        $stats = Get-NetAdapter -ErrorAction SilentlyContinue | Where-Object Status -eq 'Up' | Get-NetAdapterStatistics -ErrorAction SilentlyContinue
        if ($stats) {
            $rx = ($stats | Measure-Object -Property ReceivedBytes -Sum).Sum
            $tx = ($stats | Measure-Object -Property SentBytes -Sum).Sum
            return @{ Rx = [double]$rx; Tx = [double]$tx }
        }
    } catch {}
    return @{ Rx = 0.0; Tx = 0.0 }
}

Clear-Host
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "        UNIVERSAL PROJECT RESOURCE PROFILER              " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan

$pidsToTrack = @()
$isCommandMode = $false
$targetProcess = $null

if ($Command) {
    $isCommandMode = $true
    Write-Host "[Mode] Running & Profiling Command: $Command" -ForegroundColor Yellow
    
    # Launch command as background process
    $procInfo = New-Object System.Diagnostics.ProcessStartInfo
    $procInfo.FileName = "powershell.exe"
    $procInfo.Arguments = "-NoProfile -Command $Command"
    $procInfo.UseShellExecute = $false
    
    $targetProcess = [System.Diagnostics.Process]::Start($procInfo)
    $pidsToTrack = @($targetProcess.Id)
    Write-Host "Spawned Process PID: $($targetProcess.Id)" -ForegroundColor Green
} elseif ($PidToTrack) {
    Write-Host "[Mode] Tracking PID(s): $($PidToTrack -join ', ')" -ForegroundColor Yellow
    $pidsToTrack = $PidToTrack
} elseif ($Docker) {
    Write-Host "[Mode] Docker Container Monitoring" -ForegroundColor Yellow
    try {
        $null = docker ps 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Host "ERROR: Docker daemon is not running. Start Docker Desktop first." -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "ERROR: Docker CLI not found." -ForegroundColor Red
        exit 1
    }
} elseif ($Port -gt 0) {
    Write-Host "[Mode] Tracking Process on Port $Port" -ForegroundColor Yellow
    $connections = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue
    if ($connections) {
        $pidsToTrack = $connections | Select-Object -ExpandProperty OwningProcess -Unique
        Write-Host "Found PIDs on Port $Port : $($pidsToTrack -join ', ')" -ForegroundColor Green
    } else {
        Write-Host "WARNING: No active listening process found on port $Port yet." -ForegroundColor Yellow
        Write-Host "Please start your application first, or specify -ProcessName." -ForegroundColor Yellow
    }
} elseif ($ProcessName) {
    Write-Host "[Mode] Tracking Process Names: $($ProcessName -join ', ')" -ForegroundColor Yellow
} else {
    Write-Host "TIP: Auto-detecting Docker containers or default processes..." -ForegroundColor DarkYellow
    $dockerCheck = docker ps 2>&1
    if ($LASTEXITCODE -eq 0 -and ($dockerCheck | Measure-Object -Line).Lines -gt 1) {
        $Docker = $true
        Write-Host "[Mode] Auto-detected running Docker containers!" -ForegroundColor Green
    } else {
        $ProcessName = @("python", "node", "chrome", "msedge")
        Write-Host "[Mode] Auto-monitoring processes: $($ProcessName -join ', ')" -ForegroundColor Yellow
    }
}

# Determine duration
$autoStopOnExit = $false
if ($DurationSeconds -le 0) {
    if ($isCommandMode -or $PidToTrack) {
        $autoStopOnExit = $true
        $DurationSeconds = 3600  # Safety max: 1 hour if not specified
        Write-Host "Duration : Until target process exits (Sampling every $($IntervalMs/1000)s)"
    } else {
        $DurationSeconds = 30
        Write-Host "Duration : $DurationSeconds seconds (Sampling every $($IntervalMs/1000)s)"
    }
} else {
    Write-Host "Duration : $DurationSeconds seconds (Sampling every $($IntervalMs/1000)s)"
}

Write-Host "Press Ctrl+C at any time to stop early and view the report."
Write-Host "----------------------------------------------------------"
Write-Host "Baseline captured. Beginning profiling..." -ForegroundColor DarkCyan

$initialNet = Get-SystemNetBytes
$startTime = Get-Date
$endTime = $startTime.AddSeconds($DurationSeconds)

# Collect baseline CPU times
$prevCpu = @{}
$initialProcs = @()
if ($pidsToTrack.Count -gt 0) {
    $initialProcs = Get-Process -Id $pidsToTrack -ErrorAction SilentlyContinue
} elseif ($ProcessName) {
    foreach ($name in $ProcessName) {
        $initialProcs += Get-Process -Name $name -ErrorAction SilentlyContinue
    }
}
foreach ($p in $initialProcs) {
    try { $prevCpu[$p.Id] = @{ Cpu = $p.CPU; Time = Get-Date } } catch {}
}

$samples = @()

try {
    while ((Get-Date) -lt $endTime) {
        $currentTime = Get-Date
        $elapsed = [math]::Round(($currentTime - $startTime).TotalSeconds, 1)

        $processStillRunning = $true
        if ($autoStopOnExit) {
            if ($targetProcess -ne $null) {
                $targetProcess.Refresh()
                if ($targetProcess.HasExited) {
                    $processStillRunning = $false
                }
            } elseif ($pidsToTrack.Count -gt 0) {
                $live = Get-Process -Id $pidsToTrack -ErrorAction SilentlyContinue
                if (-not $live) {
                    $processStillRunning = $false
                }
            }
        }

        if ($Docker) {
            $rawStats = docker stats --no-stream --format "{{.Name}}|{{.CPUPerc}}|{{.MemUsage}}|{{.NetIO}}" 2>$null
            $totalCpu = 0.0
            $totalMemBytes = 0.0
            $totalRxBytes = 0.0
            $totalTxBytes = 0.0

            foreach ($line in ($rawStats -split "`n")) {
                if (-not [string]::IsNullOrWhiteSpace($line)) {
                    $cols = $line.Trim() -split '\|'
                    if ($cols.Count -ge 4) {
                        $cpuVal = [double]($cols[1] -replace '%', '').Trim()
                        $totalCpu += $cpuVal
                        
                        $memPart = ($cols[2] -split '/')[0].Trim()
                        $memNum = [double][regex]::Match($memPart, '[\d\.]+').Value
                        if ($memPart -match 'GiB|GB') { $totalMemBytes += ($memNum * 1GB) }
                        elseif ($memPart -match 'MiB|MB') { $totalMemBytes += ($memNum * 1MB) }
                        elseif ($memPart -match 'KiB|kB|KB') { $totalMemBytes += ($memNum * 1KB) }

                        $net = Parse-DockerNetBytes $cols[3]
                        $totalRxBytes += $net.Rx
                        $totalTxBytes += $net.Tx
                    }
                }
            }

            $samples += [PSCustomObject]@{
                Time = $currentTime
                Cpu = $totalCpu
                MemBytes = $totalMemBytes
                NetRx = $totalRxBytes
                NetTx = $totalTxBytes
            }

            $memMB = [math]::Round($totalMemBytes / 1MB, 1)
            Write-Host -NoNewline ("`r[$elapsed s] CPU: {0,5:N1}% | RAM: {1,7:N1} MB | In: {2,-8} | Out: {3,-8}" -f $totalCpu, $memMB, (Format-Bytes $totalRxBytes), (Format-Bytes $totalTxBytes))
        }
        else {
            $procs = @()
            if ($pidsToTrack.Count -gt 0) {
                $activePids = [System.Collections.Generic.HashSet[int]]::new()
                foreach ($id in $pidsToTrack) { [void]$activePids.Add($id) }

                # Include any child processes spawned by target PIDs
                try {
                    $cimProcs = Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId -ErrorAction SilentlyContinue
                    foreach ($cp in $cimProcs) {
                        if ($activePids.Contains([int]$cp.ParentProcessId)) {
                            [void]$activePids.Add([int]$cp.ProcessId)
                        }
                    }
                } catch {}

                $procs = Get-Process -Id @($activePids) -ErrorAction SilentlyContinue
            } elseif ($ProcessName) {
                foreach ($name in $ProcessName) {
                    $procs += Get-Process -Name $name -ErrorAction SilentlyContinue
                }
            }

            $totalWorkingSet = 0.0
            $totalCpuPercent = 0.0

            if ($procs) {
                $totalWorkingSet = ($procs | Measure-Object -Property WorkingSet64 -Sum).Sum
                foreach ($p in $procs) {
                    try {
                        $currCpu = $p.CPU
                        if ($prevCpu.ContainsKey($p.Id)) {
                            $dCpu = [math]::Max(0.0, $currCpu - $prevCpu[$p.Id].Cpu)
                            $dTime = ($currentTime - $prevCpu[$p.Id].Time).TotalSeconds
                            if ($dTime -gt 0) {
                                # Instantaneous CPU percent (100% = 1 full core utilized)
                                $totalCpuPercent += ($dCpu / $dTime) * 100
                            }
                        }
                        $prevCpu[$p.Id] = @{ Cpu = $currCpu; Time = $currentTime }
                    } catch {}
                }
            }

            $currentNet = Get-SystemNetBytes
            $netRx = [math]::Max(0.0, $currentNet.Rx - $initialNet.Rx)
            $netTx = [math]::Max(0.0, $currentNet.Tx - $initialNet.Tx)

            $samples += [PSCustomObject]@{
                Time = $currentTime
                Cpu = $totalCpuPercent
                MemBytes = $totalWorkingSet
                NetRx = $netRx
                NetTx = $netTx
            }

            $memMB = [math]::Round($totalWorkingSet / 1MB, 1)
            Write-Host -NoNewline ("`r[$elapsed s] CPU: {0,5:N1}% | RAM: {1,7:N1} MB | Sys Net In: {2,-8} | Out: {3,-8}" -f $totalCpuPercent, $memMB, (Format-Bytes $netRx), (Format-Bytes $netTx))
        }

        if (-not $processStillRunning) {
            Write-Host "`nTarget process has finished." -ForegroundColor Cyan
            break
        }

        Start-Sleep -Milliseconds $IntervalMs
    }
}
finally {
    Write-Host "`n"
}

if ($samples.Count -eq 0) {
    Write-Host "No samples collected." -ForegroundColor Red
    exit 0
}

$cpuStats = $samples | Measure-Object -Property Cpu -Average -Maximum -Minimum
$memStats = $samples | Measure-Object -Property MemBytes -Average -Maximum -Minimum

$minMemMB = [math]::Round($memStats.Minimum / 1MB, 1)
$avgMemMB = [math]::Round($memStats.Average / 1MB, 1)
$peakMemMB = [math]::Round($memStats.Maximum / 1MB, 1)

$minCpu = [math]::Round($cpuStats.Minimum, 1)
$avgCpu = [math]::Round($cpuStats.Average, 1)
$peakCpu = [math]::Round($cpuStats.Maximum, 1)

$firstSample = $samples[0]
$lastSample = $samples[-1]
$totalIncoming = [math]::Max(0, ($lastSample.NetRx - $firstSample.NetRx))
$totalOutgoing = [math]::Max(0, ($lastSample.NetTx - $firstSample.NetTx))

$testDurationSec = [math]::Max(1, [math]::Round(($lastSample.Time - $firstSample.Time).TotalSeconds, 1))
$incomingRate = if ($testDurationSec -gt 0) { $totalIncoming / $testDurationSec } else { 0 }
$outgoingRate = if ($testDurationSec -gt 0) { $totalOutgoing / $testDurationSec } else { 0 }

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "               PROJECT RESOURCE REPORT                   " -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Test Duration          : $testDurationSec seconds"
Write-Host ""
Write-Host "[1] CPU USAGE" -ForegroundColor Yellow
Write-Host ("  Idle / Baseline      : {0:N1}%" -f $minCpu)
Write-Host ("  Average Load         : {0:N1}%" -f $avgCpu)
Write-Host ("  Peak Spike           : {0:N1}%" -f $peakCpu)
Write-Host ""
Write-Host "[2] RAM / MEMORY USAGE" -ForegroundColor Yellow
Write-Host ("  Idle / Baseline      : {0:N1} MB" -f $minMemMB)
Write-Host ("  Average Working Set  : {0:N1} MB" -f $avgMemMB)
Write-Host ("  Peak Consumption     : {0:N1} MB" -f $peakMemMB)
Write-Host ""
Write-Host "[3] NETWORK TRAFFIC" -ForegroundColor Yellow
Write-Host ("  Incoming Traffic (In): {0} ({1}/sec)" -f (Format-Bytes $totalIncoming), (Format-Bytes $incomingRate))
Write-Host ("  Outgoing Traffic(Out): {0} ({1}/sec)" -f (Format-Bytes $totalOutgoing), (Format-Bytes $outgoingRate))
Write-Host ""

$recRamGB = [math]::Ceiling(($peakMemMB * 1.5) / 1024)
if ($recRamGB -lt 2) { $recRamGB = 2 }

$recCpuCores = 2
if ($peakCpu -gt 150) { $recCpuCores = 4 }
if ($peakCpu -gt 350) { $recCpuCores = 8 }

$recBandwidthMbps = [math]::Max(25, [math]::Ceiling(($outgoingRate * 8 / 1MB) * 3))

Write-Host "==========================================================" -ForegroundColor Green
Write-Host "            RECOMMENDED SERVER SPECIFICATION             " -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green
Write-Host "  Recommended RAM       : $recRamGB GB" -ForegroundColor White
Write-Host "  Recommended vCPU      : $recCpuCores vCPU Cores" -ForegroundColor White
Write-Host "  Recommended Bandwidth : $recBandwidthMbps Mbps Port" -ForegroundColor White
Write-Host "==========================================================" -ForegroundColor Green
