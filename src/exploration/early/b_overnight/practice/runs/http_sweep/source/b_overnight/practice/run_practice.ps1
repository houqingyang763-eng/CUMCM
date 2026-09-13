[CmdletBinding(PositionalBinding = $false)]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet(3, 4)]
    [int]$Problem,

    [ValidateSet('completion', 'configured', 'sweep', 'directional', 'joint25')]
    [string]$Strategy,

    [string]$Config,

    [Parameter(Mandatory = $true)]
    [string]$UiReceipt,

    [Parameter(Mandatory = $true)]
    [string]$Output
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$hadRobotId = Test-Path -LiteralPath 'Env:CUMCM_ROBOT_ID'
$previousRobotId = [Environment]::GetEnvironmentVariable('CUMCM_ROBOT_ID', 'Process')
$practiceExitCode = 2
$credential = $null
$teamUserName = $null

try {
    if (-not $Strategy) {
        $Strategy = if ($Problem -eq 3) { 'completion' } else { 'joint25' }
    }
    $Strategy = $Strategy.ToLowerInvariant()
    $allowed = if ($Problem -eq 3) { @('completion', 'configured', 'sweep') } else { @('joint25', 'directional') }
    if ($Strategy -notin $allowed) { throw 'Problem and strategy do not match.' }
    if ($Strategy -eq 'configured' -and -not $Config) { throw 'Configured requires a config file.' }
    if (-not (Test-Path -LiteralPath $UiReceipt -PathType Leaf)) { throw 'UI receipt file is required.' }
    $receiptPath = (Resolve-Path -LiteralPath $UiReceipt).ProviderPath
    $outputPath = $ExecutionContext.SessionState.Path.GetUnresolvedProviderPathFromPSPath($Output)
    if (Test-Path -LiteralPath $outputPath) { throw 'Output must be a new path.' }
    $configPath = $null
    if ($Config) {
        if (-not (Test-Path -LiteralPath $Config -PathType Leaf)) { throw 'Config file is missing.' }
        $configPath = (Resolve-Path -LiteralPath $Config).ProviderPath
    }

    $livePath = Join-Path $PSScriptRoot 'live.py'
    if (-not (Test-Path -LiteralPath $livePath -PathType Leaf)) { throw 'Frozen live.py is missing.' }
    if (-not $env:LOCALAPPDATA) { throw 'Current-user credential location is unavailable.' }
    $credentialPath = Join-Path $env:LOCALAPPDATA 'CUMCM/jammers-credential.clixml'
    $credential = Import-Clixml -LiteralPath $credentialPath
    if (-not ($credential.PSObject.Properties.Name -contains 'UserName')) { throw 'Credential format is invalid.' }
    $teamUserName = $credential.UserName
    if ($teamUserName -isnot [string] -or [string]::IsNullOrWhiteSpace($teamUserName) -or
        [Text.Encoding]::UTF8.GetByteCount($teamUserName) -gt 64 -or $teamUserName -match '[\p{Cc}\p{Cf}]') {
        throw 'Credential username format is invalid.'
    }

    # Pass paths as separate literal arguments. Never construct an executable command string.
    $pythonArguments = @('-3.13', $livePath, '--problem', [string]$Problem, '--strategy', $Strategy,
                         '--ui-receipt', $receiptPath, '--output', $outputPath)
    if ($configPath) { $pythonArguments += @('--config', $configPath) }
    [Environment]::SetEnvironmentVariable('CUMCM_ROBOT_ID', $teamUserName, 'Process')
    $global:LASTEXITCODE = 0
    & py @pythonArguments
    $practiceExitCode = [int]$LASTEXITCODE
}
catch {
    # Do not print the caught exception, imported object, username, password, or environment.
    Write-Error -Message 'Practice launcher stopped: invalid input, private credential, or Python startup failure. No credential details are printed.' -ErrorAction Continue
    $practiceExitCode = 2
}
finally {
    if ($hadRobotId) {
        [Environment]::SetEnvironmentVariable('CUMCM_ROBOT_ID', $previousRobotId, 'Process')
    }
    else {
        Remove-Item -LiteralPath 'Env:CUMCM_ROBOT_ID' -ErrorAction SilentlyContinue
    }
    $teamUserName = $null
    $credential = $null
    $previousRobotId = $null
}

exit $practiceExitCode
