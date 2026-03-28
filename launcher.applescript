set myPath to POSIX path of (path to me)
set appDir to do shell script "dirname " & quoted form of myPath
set launchScript to appDir & "/launch_voicedrop.sh"

try
	do shell script quoted form of launchScript
on error errMsg number errNum
	display dialog "VoiceDrop failed to launch." & return & return & errMsg & " (" & errNum & ")" buttons {"OK"} default button "OK"
end try
