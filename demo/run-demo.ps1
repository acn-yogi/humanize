# run-demo.ps1: thin Windows wrapper. Runs demo/run-demo.sh inside WSL2 (the same environment as
# the harness) from this repository's /mnt/c path, passing every argument through.
#
#   pwsh -NoProfile -File demo\run-demo.ps1 --dry-run --serve
#   pwsh -NoProfile -File demo\run-demo.ps1 --acts 0,1 --ask "intword should carry to the next unit" --budget 5
#
# Model credentials: ANTHROPIC_API_KEY in this session is passed through WSLENV; otherwise the
# Windows Claude Code login is borrowed for the run (WORKBENCH_AUTH=windows-login).
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
$linux = (wsl.exe -e wslpath -a $repo).Trim()
if ($env:ANTHROPIC_API_KEY) {
  $env:WSLENV = "ANTHROPIC_API_KEY/u" + ($(if ($env:WSLENV) { ":" + $env:WSLENV } else { "" }))
  $auth = ""
} else {
  $auth = "WORKBENCH_AUTH=windows-login "
}
$quoted = ($args | ForEach-Object { "'" + ($_ -replace "'", "'\''") + "'" }) -join " "
$cmd = "cd '$linux' && ${auth}demo/run-demo.sh $quoted"
Write-Host "wsl.exe -e bash -lc `"$cmd`""
& wsl.exe -e bash -lc $cmd
exit $LASTEXITCODE
