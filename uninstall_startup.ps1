$startupDir = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDir "Codex Usage Overlay.lnk"

if (Test-Path $shortcutPath) {
  Remove-Item $shortcutPath
  Write-Host "Startup shortcut removed: $shortcutPath"
} else {
  Write-Host "Startup shortcut was not found."
}
