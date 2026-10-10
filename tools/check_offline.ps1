<#
.SYNOPSIS
    REQ-SET-003: lists the AOI app's listening ports and network connections during a run, then says PASS or FAIL.
.DESCRIPTION
    Starts the app, then every 30 s for -Minutes reads Get-NetTCPConnection and Get-NetUDPEndpoint for the app's
    process and every process it started, and appends one row per sample to the CSV file -Out. A UDP endpoint counts
    as a listening port, and a TCP connection as a listening port in state Listen and as a connection in any other.
    At the end it prints PASS when the app ran the whole time and every sample shows 0 listening ports and
    0 connections, else FAIL with the samples that did not; the exit code is 0 or 1. The app is left running.
    For the 1-hour run on the reference PC (stage S55; docs/install/ports.md). Windows PowerShell 5.1 or later.
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\check_offline.ps1 -Out offline.csv `
        -Exe .\AOI-PoC-Inspector\AOI-PoC-Inspector.exe
.EXAMPLE
    powershell -ExecutionPolicy Bypass -File tools\check_offline.ps1 -Exe "python main.py" -Minutes 5 -Out offline.csv
    (from the repository folder: a command is the program, a space, then its arguments)
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)] [string] $Exe,
    [ValidateRange(1, 1440)] [int] $Minutes = 60,
    [Parameter(Mandatory = $true)] [string] $Out
)
$ErrorActionPreference = 'Stop'
$IntervalSeconds = 30
$Invariant = [System.Globalization.CultureInfo]::InvariantCulture
if (Test-Path -LiteralPath $Out) { throw "$Out exists already: name a new file for this run." }

function Get-ProcessTree([int] $RootId) {
    # The app's process and every process it started, at any depth (a venv's python.exe starts the interpreter).
    $all = @(Get-CimInstance -ClassName Win32_Process | Select-Object ProcessId, ParentProcessId)
    $ids = [System.Collections.Generic.List[int]]::new()
    $ids.Add($RootId)
    for ($i = 0; $i -lt $ids.Count; $i++) {
        foreach ($child in @($all | Where-Object { $_.ParentProcessId -eq $ids[$i] })) {
            if (-not $ids.Contains([int]$child.ProcessId)) { $ids.Add([int]$child.ProcessId) }
        }
    }
    return $ids.ToArray()
}

$file, $arguments = $Exe -split ' ', 2  # a command: the program, then its arguments
if (Test-Path -LiteralPath $Exe -PathType Leaf) { $file, $arguments = (Resolve-Path -LiteralPath $Exe).Path, $null }
$start = @{ FilePath = $file; PassThru = $true; WorkingDirectory = (Get-Location).Path }
if ($arguments) { $start.ArgumentList = $arguments }
$app = Start-Process @start
$started = Get-Date
$end = $started.AddMinutes($Minutes)
Write-Output "Started $Exe (process $($app.Id)); sampling every $IntervalSeconds s for $Minutes min into $Out"

$samples = [System.Collections.Generic.List[object]]::new()
$endedAt = $null
do {
    $ids = @(Get-ProcessTree $app.Id)
    $tcp = @(Get-NetTCPConnection -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })
    $udp = @(Get-NetUDPEndpoint -ErrorAction SilentlyContinue | Where-Object { $ids -contains $_.OwningProcess })
    $listeners = @($tcp | Where-Object { $_.State -eq 'Listen' })
    $details = @($tcp | ForEach-Object {
            "TCP $($_.LocalAddress):$($_.LocalPort) to $($_.RemoteAddress):$($_.RemotePort)" +
            " $($_.State) pid $($_.OwningProcess)"
        }) + @($udp | ForEach-Object { "UDP $($_.LocalAddress):$($_.LocalPort) pid $($_.OwningProcess)" })
    $sample = [pscustomobject]@{
        TimeUtc        = [DateTime]::UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss'+00:00'", $Invariant)
        ProcessIds     = $ids -join ' '
        AppRunning     = -not $app.HasExited
        ListeningPorts = $listeners.Count + $udp.Count
        Connections    = $tcp.Count - $listeners.Count
        Details        = $details -join '; '
    }
    $sample | Export-Csv -LiteralPath $Out -Append -NoTypeInformation -Encoding UTF8
    $samples.Add($sample)
    if ($app.HasExited) { $endedAt = Get-Date; break }
    Start-Sleep -Seconds $IntervalSeconds
} while ((Get-Date) -lt $end)

$failures = @()
if ($endedAt) { $failures += 'the app ended after {0:N1} of {1} min' -f ($endedAt - $started).TotalMinutes, $Minutes }
$open = @($samples | Where-Object { $_.ListeningPorts -gt 0 -or $_.Connections -gt 0 })
if ($open.Count -gt 0) { $failures += "$($open.Count) of $($samples.Count) samples show a port or a connection" }
if ($failures.Count -eq 0) {
    Write-Output "PASS: $($samples.Count) samples in $Minutes min, each with 0 listening ports and 0 connections ($Out)"
    exit 0
}
Write-Output ('FAIL: ' + ($failures -join '; ') + " ($Out)")
$open | Format-List | Out-String -Width 200 | Write-Output
exit 1
