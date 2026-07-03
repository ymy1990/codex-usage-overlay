$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex Usage Overlay.lnk"
$targetPath = Join-Path $projectDir "run_overlay.bat"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "Start Codex Usage Overlay"
$shortcut.Save()

Write-Host "Startup shortcut created: $shortcutPath"
