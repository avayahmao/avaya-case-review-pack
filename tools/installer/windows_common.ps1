$TimeoutLocalSeconds = 15
$TimeoutGitSeconds = 180
$TimeoutMarketplaceSeconds = 180
$TimeoutPluginSeconds = 120
$TimeoutPipSeconds = 300
$TimeoutBridgeSeconds = 60
$StreamDrainTimeoutMilliseconds = 2000

if (-not ('AvayaCaseReviewInstaller.ProcessJob' -as [type])) {
    Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

namespace AvayaCaseReviewInstaller {
    public static class ProcessJob {
        private const UInt32 JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000;

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_BASIC_LIMIT_INFORMATION {
            public Int64 PerProcessUserTimeLimit;
            public Int64 PerJobUserTimeLimit;
            public UInt32 LimitFlags;
            public UIntPtr MinimumWorkingSetSize;
            public UIntPtr MaximumWorkingSetSize;
            public UInt32 ActiveProcessLimit;
            public UIntPtr Affinity;
            public UInt32 PriorityClass;
            public UInt32 SchedulingClass;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct IO_COUNTERS {
            public UInt64 ReadOperationCount;
            public UInt64 WriteOperationCount;
            public UInt64 OtherOperationCount;
            public UInt64 ReadTransferCount;
            public UInt64 WriteTransferCount;
            public UInt64 OtherTransferCount;
        }

        [StructLayout(LayoutKind.Sequential)]
        private struct JOBOBJECT_EXTENDED_LIMIT_INFORMATION {
            public JOBOBJECT_BASIC_LIMIT_INFORMATION BasicLimitInformation;
            public IO_COUNTERS IoInfo;
            public UIntPtr ProcessMemoryLimit;
            public UIntPtr JobMemoryLimit;
            public UIntPtr PeakProcessMemoryUsed;
            public UIntPtr PeakJobMemoryUsed;
        }

        [DllImport("kernel32.dll", CharSet = CharSet.Unicode)]
        private static extern IntPtr CreateJobObject(IntPtr attributes, string name);

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool SetInformationJobObject(
            IntPtr job,
            Int32 infoClass,
            IntPtr info,
            UInt32 length
        );

        [DllImport("kernel32.dll", SetLastError = true)]
        private static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);

        [DllImport("kernel32.dll")]
        private static extern bool CloseHandle(IntPtr handle);

        public static IntPtr CreateKillOnClose() {
            IntPtr job = CreateJobObject(IntPtr.Zero, null);
            if (job == IntPtr.Zero) {
                throw new Win32Exception(Marshal.GetLastWin32Error());
            }
            var information = new JOBOBJECT_EXTENDED_LIMIT_INFORMATION();
            information.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE;
            int length = Marshal.SizeOf(typeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION));
            IntPtr pointer = Marshal.AllocHGlobal(length);
            try {
                Marshal.StructureToPtr(information, pointer, false);
                if (!SetInformationJobObject(job, 9, pointer, (UInt32)length)) {
                    throw new Win32Exception(Marshal.GetLastWin32Error());
                }
                return job;
            } catch {
                CloseHandle(job);
                throw;
            } finally {
                Marshal.FreeHGlobal(pointer);
            }
        }

        public static bool Assign(IntPtr job, IntPtr process) {
            return AssignProcessToJobObject(job, process);
        }

        public static void Close(IntPtr job) {
            if (job != IntPtr.Zero) {
                CloseHandle(job);
            }
        }
    }
}
'@
}

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
    $TreeTerminationSucceeded = $false
    $TargetExitConfirmed = $false
    try {
        if ($Process.HasExited) {
            return $false
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
                    } else {
                        $TreeTerminationSucceeded = $TaskKillProcess.ExitCode -eq 0
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
        try {
            $TargetExitConfirmed = $Process.HasExited -or $Process.WaitForExit($RemainingMilliseconds)
        } catch {
            $TargetExitConfirmed = $false
        }
    } catch {
        $TargetExitConfirmed = $false
    } finally {
        $CleanupClock.Stop()
    }
    return $TreeTerminationSucceeded -and $TargetExitConfirmed
}

function Invoke-BoundedCommand {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory = $true)][string]$Stage,
        [Parameter(Mandatory = $true)][string]$Command,
        [Parameter(Mandatory = $true)][object[]]$Arguments,
        [Parameter(Mandatory = $true)][ValidateRange(1, 2147483)][int]$TimeoutSeconds,
        [System.Collections.IDictionary]$Environment,
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
    if ($null -ne $Environment) {
        foreach ($Name in $Environment.Keys) {
            $StartInfo.EnvironmentVariables[[string]$Name] = [string]$Environment[$Name]
        }
    }

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
    $JobHandle = [IntPtr]::Zero
    try {
        try {
            $JobHandle = [AvayaCaseReviewInstaller.ProcessJob]::CreateKillOnClose()
        } catch {
            throw "Stage '$Stage' could not create an isolated process job."
        }
        try {
            $Started = $Process.Start()
        } catch {
            throw "Stage '$Stage' could not be started."
        }
        if (-not $Started) {
            throw "Stage '$Stage' could not be started."
        }
        try {
            if (-not [AvayaCaseReviewInstaller.ProcessJob]::Assign($JobHandle, $Process.Handle)) {
                throw "assignment failed"
            }
        } catch {
            try { [AvayaCaseReviewInstaller.ProcessJob]::Close($JobHandle) } catch {}
            $JobHandle = [IntPtr]::Zero
            try { $Process.Kill() } catch {}
            throw "Stage '$Stage' could not own its spawned process tree."
        }

        $StdOutTask = $Process.StandardOutput.ReadToEndAsync()
        $StdErrTask = $Process.StandardError.ReadToEndAsync()
        if (-not $Process.WaitForExit($TimeoutSeconds * 1000)) {
            try {
                [AvayaCaseReviewInstaller.ProcessJob]::Close($JobHandle)
            } catch {
            } finally {
                $JobHandle = [IntPtr]::Zero
            }
            $CleanupConfirmed = $false
            try { $CleanupConfirmed = $Process.WaitForExit(5000) } catch {}
            if (-not $CleanupConfirmed) {
                throw "Stage '$Stage' timed out after $TimeoutSeconds seconds; cleanup failed to confirm child process exit."
            }
            throw "Stage '$Stage' timed out after $TimeoutSeconds seconds."
        }

        try {
            [AvayaCaseReviewInstaller.ProcessJob]::Close($JobHandle)
        } catch {
        } finally {
            $JobHandle = [IntPtr]::Zero
        }
        $DrainClock = [Diagnostics.Stopwatch]::StartNew()
        foreach ($OutputTask in @($StdOutTask, $StdErrTask)) {
            $RemainingDrainMilliseconds = [Math]::Max(
                0,
                $StreamDrainTimeoutMilliseconds - [int]$DrainClock.ElapsedMilliseconds
            )
            try {
                if (-not $OutputTask.Wait($RemainingDrainMilliseconds)) {
                    throw "drain timeout"
                }
            } catch {
                throw "Stage '$Stage' output collection did not complete within the cleanup deadline."
            }
        }
        $DrainClock.Stop()
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
        if ($JobHandle -ne [IntPtr]::Zero) {
            try { [AvayaCaseReviewInstaller.ProcessJob]::Close($JobHandle) } catch {}
        }
        try { $Process.Dispose() } catch {}
    }
}
