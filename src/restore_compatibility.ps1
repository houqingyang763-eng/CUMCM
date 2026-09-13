# 恢复旧路径兼容入口。不会删除、覆盖或移动任何现有文件。
$ErrorActionPreference = 'Stop'
$compatRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$compatEntries = @(
 @('experiments/b_q3','src/exploration/q3'),
 @('src/exploration/q3/final_methods','src/q3'),
 @('experiments/初步探索归档','src/exploration/early'),
 @('experiments/q4','src/exploration/q4'),
 @('experiments/b_benchmark_scale','src/exploration/benchmark'),
 @('experiments/b_method_families','src/exploration/method_families'),
 @('experiments/research','src/exploration/research'),
 @('experiments/b_adaptive_q3','src/exploration/early/b_adaptive_q3'),
 @('experiments/b_env_probe','src/exploration/early/b_env_probe'),
 @('experiments/b_oracle_q3','src/exploration/early/b_oracle_q3'),
 @('experiments/b_overnight','src/exploration/early/b_overnight')
)
foreach ($entry in $compatEntries) {
 $compatLink = [System.IO.Path]::GetFullPath((Join-Path $compatRoot $entry[0]))
 $compatTarget = [System.IO.Path]::GetFullPath((Join-Path $compatRoot $entry[1]))
 if (-not $compatLink.StartsWith($compatRoot + [System.IO.Path]::DirectorySeparatorChar) -or -not $compatTarget.StartsWith($compatRoot + [System.IO.Path]::DirectorySeparatorChar)) { throw '兼容路径越出仓库' }
 if (-not (Test-Path -LiteralPath $compatTarget -PathType Container)) { throw "缺少目标: $compatTarget" }
 $compatExisting = Get-Item -LiteralPath $compatLink -Force -ErrorAction SilentlyContinue
 if ($compatExisting) {
   if ($compatExisting.LinkType -ne 'Junction') { throw "保留现有目录，不能覆盖: $compatLink" }
   if ($compatExisting.ResolveLinkTarget($true).FullName -ne $compatTarget) { throw "现有联接目标不符，未修改: $compatLink" }
   continue
 }
 New-Item -ItemType Directory -Path (Split-Path -Parent $compatLink) -Force | Out-Null
 New-Item -ItemType Junction -Path $compatLink -Target $compatTarget | Out-Null
 (Get-Item -LiteralPath $compatLink -Force).Attributes = (Get-Item -LiteralPath $compatLink -Force).Attributes -bor [System.IO.FileAttributes]::Hidden
}
Write-Output '11个兼容入口已核对；未覆盖现有数据。'
