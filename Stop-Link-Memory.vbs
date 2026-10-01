Option Explicit

' Hidden desktop entry point: stop only Link Memory's local processes.
Dim shell, fso, root, powershell, scriptPath, command
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
powershell = "powershell.exe"
scriptPath = root & "\scripts\stop.ps1"
command = """" & powershell & """ -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & scriptPath & """"
shell.Run command, 0, True
