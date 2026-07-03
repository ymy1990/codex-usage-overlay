$projectDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$desktopDir = [Environment]::GetFolderPath("Desktop")
$shortcutPath = Join-Path $desktopDir "Codex Usage Overlay.lnk"
$targetPath = Join-Path $projectDir "start_codex_with_overlay.bat"

$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $targetPath
$shortcut.WorkingDirectory = $projectDir
$shortcut.Description = "Start Codex with usage overlay"
$shortcut.IconLocation = (Join-Path $projectDir "assets\codex_usage_overlay_icon.ico")
$shortcut.Save()

Write-Host "Created desktop shortcut: $shortcutPath"
