[CmdletBinding()]
param([Parameter(Mandatory = $true)][string]$Output)
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $false
$testRoot = [IO.Path]::GetFullPath($Output)
$privateRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'local_launcher_checks'))
if (-not $testRoot.StartsWith($privateRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Use a private local_launcher_checks subdirectory.' }
if (Test-Path -LiteralPath $testRoot) { throw 'Use a new output directory.' }
[IO.Directory]::CreateDirectory($testRoot) | Out-Null
$oldLocal = $env:LOCALAPPDATA
$oldRobot = [Environment]::GetEnvironmentVariable('CUMCM_ROBOT_ID', 'Process')
$mockUser = 'MOCK_' + [guid]::NewGuid().ToString('N')
$mockPassword = [guid]::NewGuid().ToString('N')
$priorRobot = 'PRIOR_' + [guid]::NewGuid().ToString('N')
$global:ActualPython = (Get-Command py.exe -CommandType Application).Source
$global:MockThrow = $false
$global:MockSecret = $mockUser
$global:FixturePython = Join-Path $testRoot 'standin.py'
$fixture = @'
import hashlib,json,os,sys
from pathlib import Path
Path(os.environ['MOCK_CAPTURE']).write_text(json.dumps({'argv':sys.argv[1:],'robot_sha256':hashlib.sha256(os.environ.get('CUMCM_ROBOT_ID','').encode()).hexdigest()}),encoding='utf-8')
sys.exit(int(os.environ['MOCK_EXIT']))
'@
[IO.File]::WriteAllText($global:FixturePython, $fixture)
function global:py {
    if ($global:MockThrow) { throw $global:MockSecret }
    & $global:ActualPython '-3.13' $global:FixturePython @args
    $global:LASTEXITCODE = $LASTEXITCODE
}
$checks = @()
try {
    $env:LOCALAPPDATA = Join-Path $testRoot 'private_mock_profile'
    $credentialDir = Join-Path $env:LOCALAPPDATA 'CUMCM'
    [IO.Directory]::CreateDirectory($credentialDir) | Out-Null
    $secure = ConvertTo-SecureString $mockPassword -AsPlainText -Force
    [pscredential]::new($mockUser, $secure) | Export-Clixml -LiteralPath (Join-Path $credentialDir 'jammers-credential.clixml')
    $specialDir = Join-Path $testRoot ('args ' + [char]0x6D4B + ' [x] & $() `literal')
    [IO.Directory]::CreateDirectory($specialDir) | Out-Null
    $inputFixture = Join-Path $specialDir 'plain-input-fixture.txt'
    [IO.File]::WriteAllText($inputFixture, 'LOCAL ARGUMENT FIXTURE ONLY; NOT UI EVIDENCE. Never submit to live.py.')
    $configFixture = Join-Path $specialDir 'config [x] & $().json'
    [IO.File]::WriteAllText($configFixture, '{}')
    $launcher = Join-Path $PSScriptRoot 'run_practice.ps1'
    $sha = [Security.Cryptography.SHA256]::Create()
    $expectedHash = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::UTF8.GetBytes($mockUser)))).Replace('-', '').ToLowerInvariant()
    $specs = @(
        @{Name='q3_default_restore'; Problem=3; Code=0; Prior=$true; Strategy=''; Config=$false; Throw=$false; Reject=$false; Existing=$false},
        @{Name='q4_default_clear'; Problem=4; Code=0; Prior=$false; Strategy=''; Config=$false; Throw=$false; Reject=$false; Existing=$false},
        @{Name='q3_sweep_explicit'; Problem=3; Code=0; Prior=$false; Strategy='sweep'; Config=$false; Throw=$false; Reject=$false; Existing=$false},
        @{Name='config_exit37'; Problem=3; Code=37; Prior=$true; Strategy='configured'; Config=$true; Throw=$false; Reject=$false; Existing=$false},
        @{Name='throw_redacted'; Problem=3; Code=2; Prior=$true; Strategy=''; Config=$false; Throw=$true; Reject=$true; Existing=$false},
        @{Name='wrong_problem'; Problem=3; Code=2; Prior=$false; Strategy='directional'; Config=$false; Throw=$false; Reject=$true; Existing=$false},
        @{Name='existing_output'; Problem=3; Code=2; Prior=$false; Strategy=''; Config=$false; Throw=$false; Reject=$true; Existing=$true}
    )
    foreach ($spec in $specs) {
        $destination = Join-Path $specialDir ($spec.Name + ' [new] & $()')
        if ($spec.Existing) { [IO.Directory]::CreateDirectory($destination) | Out-Null }
        if ($spec.Prior) { [Environment]::SetEnvironmentVariable('CUMCM_ROBOT_ID', $priorRobot, 'Process') }
        else { Remove-Item -LiteralPath 'Env:CUMCM_ROBOT_ID' -ErrorAction SilentlyContinue }
        $env:MOCK_CAPTURE = Join-Path $testRoot ($spec.Name + '_capture.json')
        $env:MOCK_EXIT = [string]$spec.Code
        $global:MockThrow = $spec.Throw
        $arguments = @{Problem=$spec.Problem; UiReceipt=$inputFixture; Output=$destination}
        if ($spec.Strategy) { $arguments.Strategy = $spec.Strategy }
        if ($spec.Config) { $arguments.Config = $configFixture }
        $log = Join-Path $testRoot ($spec.Name + '.log')
        & $launcher @arguments *> $log
        $observedExit = $LASTEXITCODE
        if ($observedExit -ne $spec.Code) { throw 'Exit code was not propagated.' }
        $expectedPrevious = if ($spec.Prior) { $priorRobot } else { $null }
        if ($spec.Prior) {
            if ([Environment]::GetEnvironmentVariable('CUMCM_ROBOT_ID', 'Process') -ne $expectedPrevious) { throw 'Environment was not restored.' }
        }
        elseif (Test-Path -LiteralPath 'Env:CUMCM_ROBOT_ID') { throw 'Environment variable was not removed.' }
        $logText = [IO.File]::ReadAllText($log)
        if ($logText.Contains($mockUser) -or $logText.Contains($mockPassword) -or $logText.Contains($priorRobot)) { throw 'Credential fixture leaked into output.' }
        if (-not $spec.Reject) {
            $captured = Get-Content -LiteralPath $env:MOCK_CAPTURE -Raw | ConvertFrom-Json
            $selected = if ($spec.Strategy) { $spec.Strategy } elseif ($spec.Problem -eq 3) { 'completion' } else { 'joint25' }
            $expected = @('-3.13', (Join-Path $PSScriptRoot 'live.py'), '--problem', [string]$spec.Problem, '--strategy', $selected, '--ui-receipt', $inputFixture, '--output', $destination)
            if ($spec.Config) { $expected += @('--config', $configFixture) }
            if (($captured.argv | ConvertTo-Json -Compress) -ne ($expected | ConvertTo-Json -Compress)) { throw 'Literal arguments changed across native Python invocation.' }
            if ($captured.robot_sha256 -ne $expectedHash) { throw 'Temporary username was not passed correctly.' }
        }
        elseif (Test-Path -LiteralPath $env:MOCK_CAPTURE) { throw 'Rejected launch unexpectedly ran Python.' }
        $checks += @{name=$spec.Name; passed=$true; observed_exit=$observedExit; environment_restored=$true; credential_not_echoed=$true}
    }
    $valid = (Get-Command $launcher).Parameters['Strategy'].Attributes | Where-Object { $_ -is [Management.Automation.ValidateSetAttribute] }
    if ('formal' -in $valid.ValidValues -or 'official' -in $valid.ValidValues) { throw 'Formal strategy exposed.' }
    $summary = @{checks=$checks; count=$checks.Count; formal_strategy_absent=$true; shell=$PSVersionTable.PSVersion.ToString(); official_connections=0; launcher_sha256=(Get-FileHash -LiteralPath $launcher -Algorithm SHA256).Hash.ToLowerInvariant()}
    $summary | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $testRoot 'summary.json') -Encoding UTF8
    Write-Output ('Passed ' + $checks.Count + ' local launcher checks; no official connection.')
}
finally {
    [Environment]::SetEnvironmentVariable('LOCALAPPDATA', $oldLocal, 'Process')
    if ($null -ne $oldRobot) { [Environment]::SetEnvironmentVariable('CUMCM_ROBOT_ID', $oldRobot, 'Process') }
    else { Remove-Item -LiteralPath 'Env:CUMCM_ROBOT_ID' -ErrorAction SilentlyContinue }
    Remove-Item Function:\py -ErrorAction SilentlyContinue
    Remove-Item Env:MOCK_CAPTURE,Env:MOCK_EXIT -ErrorAction SilentlyContinue
}
