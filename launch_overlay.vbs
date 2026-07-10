Option Explicit

Dim shell, fso, scriptDir, exePath

Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
exePath = fso.BuildPath(scriptDir, "CodexUsageOverlay.exe")

If fso.FileExists(exePath) Then
  shell.Run Chr(34) & exePath & Chr(34), 0, False
Else
  shell.Popup "CodexUsageOverlay.exe was not found. Extract the complete ZIP package before running it.", 0, "Codex Usage Overlay", 16
End If
