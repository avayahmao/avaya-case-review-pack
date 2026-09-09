$TimeoutLocalSeconds = 15
$TimeoutGitSeconds = 180
$TimeoutMarketplaceSeconds = 180
$TimeoutPluginSeconds = 120
$TimeoutPipSeconds = 300
$TimeoutBridgeSeconds = 60

function ConvertTo-WindowsProcessArgument {
    param([AllowEmptyString()][string]$Value)

    if ($null -eq $Value -or $Value.Length -eq 0) {
        return '""'
    }
    if ($Value -notmatch '[\s"]') {
        return $Value
    }

    $Builder = New-Object System.Text.StringBuilder
    [void]$Builder.Append('"')
    $BackslashCount = 0
    foreach ($Character in $Value.ToCharArray()) {
        if ($Character -eq [char]92) {
            $BackslashCount += 1
            continue
        }
        if ($Character -eq [char]34) {
            [void]$Builder.Append([char]92, (2 * $BackslashCount) + 1)
            [void]$Builder.Append([char]34)
            $BackslashCount = 0
            continue
        }
        if ($BackslashCount -gt 0) {
            [void]$Builder.Append([char]92, $BackslashCount)
            $BackslashCount = 0
        }
        [void]$Builder.Append($Character)
    }
    if ($BackslashCount -gt 0) {
        [void]$Builder.Append([char]92, 2 * $BackslashCount)
    }
    [void]$Builder.Append('"')
    return $Builder.ToString()
}

function Stop-SpawnedProcessTree {
    param([Parameter(Mandatory = $true)][System.Diagnostics.Process]$Process)

    $CleanupTimeoutMilliseconds = 5000
    $CleanupClock = [Diagnostics.Stopwatch]::StartNew()
    $CapturedProcessId = $Process.Id
    try {
        if ($Process.HasExited) {
            return
        }

        $TaskKillPath = Join-Path ([Environment]::GetFolderPath('System')) 'taskkill.exe'
        if (Test-Path -LiteralPath $TaskKillPath -PathType Leaf) {
            $TaskKillStartInfo = New-Object System.Diagnostics.ProcessStartInfo
            $TaskKillStartInfo.FileName = $TaskKillPath
            $TaskKillStartInfo.Arguments = "/PID $CapturedProcessId /T /F"
            $TaskKillStartInfo.UseShellExecute = $false
            $TaskKillStartInfo.CreateNoWindow = $true
            $TaskKillStartInfo.RedirectStandardOutput = $true
            $TaskKillStartInfo.RedirectStandardError = $true
            $TaskKillProcess = New-Object System.Diagnostics.Process
            $TaskKillProcess.StartInfo = $TaskKillStartInfo
            try {
                if ($TaskKillProcess.Start()) {
                    $TaskKillStdOut = $TaskKillProcess.StandardOutput.ReadToEndAsync()
                    $TaskKillStdErr = $TaskKillProcess.StandardError.ReadToEndAsync()
                    $RemainingMilliseconds = [Math]::Max(
                        0,
                        $CleanupTimeoutMilliseconds - [int]$CleanupClock.ElapsedMilliseconds
                    )
                    if (-not $TaskKillProcess.WaitForExit($RemainingMilliseconds)) {
                        try { $TaskKillProcess.Kill() } catch {}
                    }
                }
            } catch {
            } finally {
                try { $TaskKillProcess.Dispose() } catch {}
            }
        }

        try {
            if (-not $Process.HasExited) {
                $Process.Kill()
            }
        } catch {
        }
        $RemainingMilliseconds = [Math]::Max(
            0,
            $CleanupTimeoutMilliseconds - [int]$CleanupClock.ElapsedMilliseconds
        )
        try { [void]$Process.WaitForExit($RemainingMilliseconds) } catch {}
    } catch {
    } finally {
        $CleanupClock.Stop()
    }
}

function Invoke-BoundedCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483)][int]$TimeoutSeconds,
        [switch]$AllowFailure
    )

    $ResolvedCommand = Get-Command $Command -CommandType Application, ExternalScript -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($null -eq $ResolvedCommand) {
        throw "Stage '$Stage' could not start because the command is unavailable."
    }

    $ResolvedPath = [string]$ResolvedCommand.Path
    $ProcessArguments = New-Object System.Collections.Generic.List[string]
    if ([IO.Path]::GetExtension($ResolvedPath).Equals('.ps1', [StringComparison]::OrdinalIgnoreCase)) {
        $PowerShellCommand = Get-Command powershell.exe -CommandType Application -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if ($null -eq $PowerShellCommand) {
            throw "Stage '$Stage' could not start because the PowerShell host is unavailable."
        }
        $ExecutablePath = [string]$PowerShellCommand.Path
        foreach ($PrefixArgument in @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $ResolvedPath)) {
            [void]$ProcessArguments.Add([string]$PrefixArgument)
        }
    } else {
        $ExecutablePath = $ResolvedPath
    }
    foreach ($Argument in $Arguments) {
        [void]$ProcessArguments.Add([string]$Argument)
    }

    $StartInfo = New-Object System.Diagnostics.ProcessStartInfo
    $StartInfo.FileName = $ExecutablePath
    $StartInfo.UseShellExecute = $false
    $StartInfo.CreateNoWindow = $true
    $StartInfo.RedirectStandardOutput = $true
    $StartInfo.RedirectStandardError = $true

    if ($null -ne $StartInfo.PSObject.Properties['ArgumentList']) {
        foreach ($Argument in $ProcessArguments) {
            [void]$StartInfo.ArgumentList.Add($Argument)
        }
    } else {
        $StartInfo.Arguments = @(
            $ProcessArguments | ForEach-Object { ConvertTo-WindowsProcessArgument -Value $_ }
        ) -join ' '
    }

    $CommandLeafName = [IO.Path]::GetFileNameWithoutExtension($ResolvedPath)
    if ($CommandLeafName.Equals('git', [StringComparison]::OrdinalIgnoreCase)) {
        $StartInfo.EnvironmentVariables['GIT_TERMINAL_PROMPT'] = '0'
    }

    $Process = New-Object System.Diagnostics.Process
    $Process.StartInfo = $StartInfo
    try {
        try {
            $Started = $Process.Start()
        } catch {
            throw "Stage '$Stage' could not be started."
        }
        if (-not $Started) {
            throw "Stage '$Stage' could not be started."
        }

        $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
        $StdErrTask = $Process.StandardError.ReadToEndAsync()
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            try { Stop-SpawnedProcessTree -Process $Process } catch {}
            throw "Stage '$Stage' timed out after $TimeoutSeconds seconds."
        }

        $Process.WaitForExit()
        $Result = [pscustomobject]@{
            Stage = $Stage
            ExitCode = $Process.ExitCode
            TimedOut = $false
            StdOut = [string]$StdOutTask.Result
            StdErr = [string]$StdErrTask.Result
        }
        if ($Result.ExitCode -ne 0 -and -not $AllowFailure) {
            throw "Stage '$Stage' failed with exit code $($Result.ExitCode)."
        }
        return $Result
    } finally {
        try { $Process.Dispose() } catch {}
    }
}
