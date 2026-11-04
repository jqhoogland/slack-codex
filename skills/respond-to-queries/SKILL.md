---
name: respond-to-queries
description: Answer a Slack query selected by Jesse through the local reaction workflow.
---

Answer the selected query using its thread as context and the project instructions.
Save the answer in the local Codex chat. Do not send a Slack reply.

## Submit an Approved Reply

If Jesse asks you to send the reply, send the approved text in the original
Slack thread. After you confirm that Slack accepted the reply, remove
`codex_working` from the original request message and add `white_check_mark`
to that same message. Verify that the working reaction is gone and the
completion check is present. Keep unrelated reactions.

Do not mark the request complete when you have only prepared a draft or when
submission fails. Use the Slack connector where possible. If it cannot remove
reactions, use the Slack app or browser. Do not access the automation's Slack
token. Report any reaction change you cannot complete.


## Archive This Chat After Completion

After this chat completes all requested work, schedule an archive check from
this chat with the app automation tool. Use a heartbeat with destination thread.
This is Jesse's standing instruction. Never schedule it in the parent chat or
scan other chats. Update an existing archive check for this chat if one exists.

Record this chat's ID, the task completion time, and the most recent substantive
user or assistant activity. Schedule the check for 24 hours after the later
of those times. At the check, read this chat again. Archive it with
set_thread_archived only if its task is still complete and there has been no
further substantive activity for 24 hours. A completed model turn alone does
not mean the task is complete. Pending questions, approvals, failures, or
ongoing work prevent archival.

New user messages or further task work reset the 24-hour period. Reschedule
from the later activity time if the task remains complete. If work reopened,
stop the pending check and schedule a new one when that work completes.
The archive check itself does not reset the inactivity period. Disable the
check after successful archival. Stay quiet unless archival fails or needs
user action. Do not delete files or worktrees. If scheduling tools are not
available, report that limit instead of claiming archival is scheduled.
