# Run through record_backup.py, which prepares synthetic inputs and isolated settings.
# All navigation is through the real app. No UI state or success messages are mocked.
Output terminal.mp4
Output terminal.ascii
Require ethernity
Set Shell "bash"
Set FontFamily "Menlo, DejaVu Sans Mono, monospace"
Set FontSize 24
Set Columns 112
Set Rows 36
Set Padding 12
Set Framerate 15
Set CursorBlink false
Set TypingSpeed 60ms
Set Theme {"background":"#171918","foreground":"#EAE6DA","cursor":"#E0B56D"}
Env TERM "xterm-256color"
Hide
Type@1ms "cd work && ethernity"
Enter
Wait+Screen@15s /Choose files/
Sleep 1s
Show
Sleep 3s
Enter
Wait+Screen /Backup files/
Sleep 1s
Type "documents/recovery-notes.txt"
Enter
Sleep 1s
Ctrl+L
Type "documents/vault.conf"
Enter
Wait+Screen /2 selected/
Sleep 2s
Tab@180ms 4
Enter
Wait+Screen /2 files/
Sleep 4s
Tab@180ms 5
Enter
Wait+Screen /Recovery method/
Sleep 1s
Screenshot recovery.png
Sleep 6s
Tab@180ms 4
Enter
Wait+Screen /Destination/
Sleep 1s
Type "paper-backup"
Enter
Sleep 2s
Screenshot print.png
Sleep 5s
Ctrl+R
Wait+Screen /Review backup/
Sleep 1s
Screenshot review.png
Sleep 6s
Enter
Sleep 1s
Hide
Wait+Screen@60s /Backup documents created/
Show
Sleep 1s
Screenshot success.png
Sleep 3s
# Move to Check PDFs without showing intermediate focus-driven scrolling.
Hide
Shift+Tab
Shift+Tab
Shift+Tab
Shift+Tab
Shift+Tab
Shift+Tab
Shift+Tab
Sleep 500ms
Show
Sleep 1s
Enter
Sleep 1s
Hide
Wait+Screen@60s /PDF check passed/
Show
Sleep 1s
Screenshot checked.png
Sleep 6s
Hide
Escape
Type "q"
Sleep 500ms
