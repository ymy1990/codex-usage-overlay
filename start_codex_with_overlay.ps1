$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$overlayScript = Join-Path $projectDir "codex_usage_overlay.py"
$codexAppId = "OpenAI.Codex_2p2nqsd0c76g0!App"

$existingOverlay = Get-CimInstance Win32_Process |
  Where-Object { $_.CommandLine -match [regex]::Escape($overlayScript) -and $_.Name -match "pythonw|python" }

if (-not $existingOverlay) {
  $pythonw = (Get-Command pythonw -ErrorAction SilentlyContinue).Source
  if ($pythonw) {
    Start-Process -FilePath $pythonw -ArgumentList "`"$overlayScript`""
  } else {
    Start-Process -FilePath python -ArgumentList "`"$overlayScript`""
  }
}

Start-Process "shell:AppsFolder\$codexAppId"
