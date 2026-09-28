param(
    [ValidateSet('scan','register','asr')][string]$Action = 'scan',
    [string]$Source,
    [string]$Job,
    [ValidateSet('course_lecture','logic_lecture','research_meeting')][string]$Profile,
    [string]$Collection,
    [ValidateSet('technical_class','mixed_class','humanities','meeting')][string]$Scene,
    [string]$Date,
    [ValidateSet('separate')][string]$Channels,
    [switch]$RewriteOnly
)
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$taskPython = Join-Path $PSScriptRoot 'envs\asr\Scripts\python.exe'
$taskArguments = @('-B', (Join-Path $PSScriptRoot 'src\audio_workflow.py'), $Action)
if ($Action -eq 'register') {
    if (-not $Source) { throw 'register requires -Source' }
    $taskArguments += $Source
    if ($Profile) { $taskArguments += @('--profile', $Profile) }
    if ($Collection) { $taskArguments += @('--collection', $Collection) }
    if ($Scene) { $taskArguments += @('--scene', $Scene) }
    if ($Date) { $taskArguments += @('--date', $Date) }
    if ($Channels) { $taskArguments += @('--channels', $Channels) }
}
if ($Action -eq 'asr') {
    if (-not $Job) { throw 'asr requires -Job' }
    $taskArguments += $Job
    if ($RewriteOnly) { $taskArguments += '--rewrite-only' }
}
& $taskPython @taskArguments
if ($LASTEXITCODE -ne 0) { throw "Audio workflow failed with exit code $LASTEXITCODE" }
