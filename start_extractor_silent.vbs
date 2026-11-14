Set WshShell = CreateObject("WScript.Shell")
WshShell.Run chr(34) & "C:\Users\meiri\OneDrive\Documents\email article analyzer\start_extractor.bat" & chr(34), 0, False
Set WshShell = Nothing
