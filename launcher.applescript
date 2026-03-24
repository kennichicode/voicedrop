set homeDir to POSIX path of (path to home folder)
set appDir to homeDir & "Documents/Claude/Tools/voice-drop"
set scriptCmd to "cd " & quoted form of appDir & "; /opt/homebrew/bin/python3.12 voicedrop.py > /tmp/voicedrop-terminal.out 2>&1"
set checkCmd to "pgrep -f " & quoted form of (appDir & "voicedrop.py") & " >/dev/null 2>&1"

do shell script "if " & checkCmd & "; then exit 0; fi"

tell application "Terminal"
	activate
	do script scriptCmd
end tell

delay 1

tell application "System Events"
	set visible of process "Terminal" to false
end tell
