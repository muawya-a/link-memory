Option Explicit

' Hidden desktop entry point: no PowerShell console flash is shown.
Dim shell, fso, root, powershell, scriptPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
powershell = "powershell.exe"
scriptPath = root & "\Start-Link-Memory.ps1"
command = """" & powershell & """" & " -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File " & """" & scriptPath & """"
shell.Run command, 0, False
