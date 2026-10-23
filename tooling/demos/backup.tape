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
Set TypingSpeed 75ms
Set Theme {"background":"#171918","foreground":"#EAE6DA","cursor":"#E0B56D"}
Env TERM "xterm-256color"
Hide
Type@1ms "cd work && ethernity"
Enter
Wait+Screen /Choose files/
Wait+Screen /Base folder/
Wait+Screen /Help/
Sleep 500ms
Show
Sleep 4s
Enter
Sleep 1500ms
Type "documents/recovery-notes.txt"
Enter
Sleep 1200ms
Ctrl+L
Type "documents/vault.conf"
Enter
Sleep 1500ms
Tab@180ms 4
Enter
Wait+Screen /2 files/
Sleep 4s
Tab@180ms 5
Enter
Sleep 500ms
Screenshot recovery.png
Sleep 9s
Tab@180ms 5
Enter
Sleep 500ms
Screenshot print.png
Sleep 5s
Tab@180ms 3
Enter
Sleep 1500ms
Type "paper-backup"
Enter
Sleep 3s
Ctrl+R
Wait+Screen /Review backup/
Sleep 500ms
Screenshot review.png
Sleep 10s
Enter
Sleep 2s
Hide
Wait+Screen@60s /Backup documents created/
Show
Sleep 500ms
Screenshot success.png
Sleep 6s
Shift+Tab
Sleep 300ms
Shift+Tab
Sleep 3s
Enter
Sleep 1500ms
Hide
Wait+Screen@60s /PDF check passed/
Show
Sleep 8s
Screenshot checked.png
Sleep 300ms
Hide
Escape
Type "q"
Sleep 500ms
