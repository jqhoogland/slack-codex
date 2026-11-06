# Slack Codex

Local Slack reaction workflows for Jesse. A deterministic Socket Mode listener
receives user reaction events and saves jobs in SQLite. Listening, reconnect
scans, Linear completion checks, and archive checks use no model tokens.
Only a new matching reaction or an explicit rerun starts an agent.

This is a macOS personal prototype, not a shared supported installation.
See [packaging notes](PACKAGING.md) for proposed shared use and open decisions.

## Workflows

| Reaction | Skill | App Project | Working Folder |
|---|---|---|---|
| 🤖 `robot_face` | [Respond to queries](skills/respond-to-queries/SKILL.md) | Slack | `/Users/Jesse/Projects/resolution` |
| 📥 `inbox_tray` | [Slack to Linear](skills/slack-to-linear/SKILL.md) | Linear | `/Users/Jesse/Projects/slack-codex` |

The query skill carries out clear implied actions and replies in the selected
Slack thread. It asks Jesse about material ambiguity. The intake skill finds
or creates the right Linear issue and posts one short linked receipt. Both
apply Jesse's AI4 rule to replies sent without review of the exact text.

New chats use the selected request as their initial title. Forwarded email
subjects and text appear in a readable excerpt before the full JSON context.
The agent then sets a short task title from the original request and thread.

Each workflow has one agent slot. The two workflows can run at the same time.
More requests for one workflow wait in its queue. Each run has a 30-minute
limit by default. Existing sandbox and tool approval rules still apply. Command approvals use the local permission dialog. Other approval or question
types stop the run for manual handling. App continuation is not yet reliable.

The worker adds `codex_working` on the original selected message. It adds
`white_check_mark` after a query and its required reply succeed. Issue intake
only removes the working marker: creating an issue does not complete the task.
The separate Linear worker checks every five minutes. When the linked issue
is completed, it adds a checkmark and removes `inbox_tray` on the original
message, not the receipt. Canceled issues do not count as completed.

## Add an Emoji Workflow

The `workflows` object in local `config.json` maps Slack emoji names to workflows.
Standard and custom Slack emojis use the same mechanism. Each mapping has its
own skill, standing instructions, working folder, app project, and queue. The
listener does not have a fixed list of supported emojis.

Choose an action:

| Action | Behavior |
| --- | --- |
| `respond` (default) | Carry out the selected request and reply in its thread |
| `linear_intake` | Create or find an issue, post its link, and register completion checks |
| `custom` | Follow only the configured instructions and skill |

For example, add a `bookmark` mapping with `action: "custom"`. Its skill could
extract references, check for duplicates, and save a reading list. It can require
several steps or call other installed skills. It need not reply in Slack.

To add a mapping:

1. Write a skill with the allowed work, steps, outputs, and completion criteria.
   State whether it may send messages or change external records.
2. Pause the service. Copy a desktop workflow entry under the new emoji name,
   without colons. Set `action` to `custom`, `skill` to the new SKILL.md path,
   and `instructions` to the standing task. Set `project` to the working folder.
3. Set `desktop_project_id` and `app_server_project_id` to the intended app
   project IDs. Use `read-only` or `workspace-write` for `sandbox` as needed.
   The desktop placement limitation described below still applies.
4. Run a live `dry-run` with `--emoji` set to the new name, then resume.
   The first scan baselines existing reactions for that emoji. Use `rerun`
   explicitly if an existing baseline item should run.

No runner changes or new Slack event subscriptions are needed for another
emoji. The same message can launch different emoji workflows, each once.
Removing and adding the same emoji again does not rerun it.

A custom workflow runs its steps within one agent chat. This is not a separate
pipeline scheduler with step-level retries or parallel subtask execution.
Completion means the configured workflow is complete; the worker adds its
standard checkmark. If the workflow only creates a task for later work, define
that distinction before enabling it. Linear intake already handles that case.

## Event Delivery

The Slack app is **Local Codex Reactions**, ID `A0CF1GM2FA8`, in Resolution.
Socket Mode is enabled with the user event `reaction_added`. It does not need
a public HTTP endpoint or per-channel bot invitations. An app token with
`connections:write` supplies the event connection. A user OAuth token fetches
messages and threads.

The listener checks workspace, app ID, reacting user ID, emoji, and message
item type. It uses `event.user`, not the message author. It commits matching
events before acknowledging them. Unique message/emoji keys prevent duplicate
runs across event retries, restarts, and removal followed by re-addition.
Message timestamps never serve as reaction timestamps.

A first full scan establishes a baseline for each emoji without launching old
items. Scans on startup and reconnection catch reactions that remain present
after an outage. They run separately from live event handling. There is no
60-second reaction poll. Slack delayed delivery is enabled, but offline delivery
is not guaranteed indefinitely. An added and removed reaction during an outage
can still be missed if Slack cannot deliver its event.

The listener must run on an awake, online Mac. A live test received the Slack
event in about 0.3 seconds. Chat startup also needs message retrieval and Codex
startup. API throttling, a busy workflow slot, or a disconnected Mac can delay it.

## Codex Chats and Permissions

The installed Codex CLI, version 0.164.0, exposes project assignment through
its experimental app-server protocol. The worker uses `codex app-server` over
stdin with `thread/start`, `projectId`, and `turn/start`. The project IDs from
that protocol differ from the app tools' saved-project IDs; configuration stores
both. The required routes are `robot_face` to Slack and `inbox_tray` to Linear.
Each chat is persistent. The app-server project records also carry the matching
`codex.localProjectId` metadata.

The current desktop app does not reliably use app-server membership for its
sidebar. It can put a new chat under the working folder's project instead.
The worker's project ID check does not verify sidebar placement. Existing chats
can be corrected with the app's Move to project action. Automatic sidebar
placement still needs a supported desktop integration. Connected Slack and
Linear tools passed the live read checks.

New configuration defaults to `read-only` with `on-request` approval.
`workspace-write` also uses `on-request`. An existing configuration can explicitly
select `danger-full-access`, which uses `never` and permits unrestricted file and
network access. This is not the default and is not needed to install the listener.
Connected app tools remain available. Unrelated local MCP servers are disabled.

For workflows with `on-request`, command approval requests show a macOS dialog with the reason, command, folder,
and requested permissions. Only an explicit Allow once response grants access.
Decline, a dialog error, or a five-minute timeout grants no access. Requests
that cannot be shown in full stop the run. The worker releases its app-server
subscription before exiting. Other approval and question types still stop the
run for manual handling. The dialog logic has unit tests; its live permission
flow still needs a human check.

Slack text is JSON task data. It never enters shell interpolation. Standing
workflow instructions define authority. The worker passes no Slack or Linear
secret through prompts, arguments, or the agent environment. Credentials stay
in Keychain. The processes still run as Jesse; this is not a separate OS account.

Fetch errors retry at most three times. Once a model run starts, it is never
automatically repeated. A crash or uncertain outcome requires inspection and an
explicit rerun. The chat ID is saved as soon as Codex creates it. Output and
errors are saved for each run.

## Deterministic Chat Archival

Both skills call `schedule_chat_archive` in their own spawned chat. The local
program registers completion only after that turn reports `completed`. It
checks due records every five minutes and archives after 24 hours without new
activity. These checks make no model call and create no heartbeat in the parent
chat. Active chats are never archived.

New activity invalidates the old completion record. The skill registers again
when the new work is complete. This prevents a reopened or blocked task from
being archived just because a model turn ended. The check reads activity twice
before archival, but the app API offers no atomic conditional archive operation.

The local `register_linear_issue` tool similarly saves the verified issue UUID
against the original message. It exposes neither a credential nor a Slack write.

For an interactive continuation without these local tools:

```sh
uv run python chat_archive.py complete CHAT_ID
uv run python chat_archive.py cancel CHAT_ID
uv run python chat_archive.py status
uv run python linear_sync.py link ISSUE_UUID SOURCE_SLACK_PERMALINK
```

Use `complete` only after the chat's task is actually complete. The automatic
path registers after the final turn, so it needs no extra model wakeup.

## Local Files and Controls

Repository: `/Users/Jesse/Projects/slack-codex`.
Runtime data: `~/Library/Application Support/slack-codex/`.
New runtime files have owner-only permissions.

| Path | Contents |
|---|---|
| `config.json` | Emoji mappings, user/workspace IDs, projects, limits |
| `state.sqlite3` | Events, jobs, attempts, runs, issue links, archive records |
| `reviews/` | Read-only thread previews |
| `approval.json` | Successful validation record, legacy filename |
| `runs/` | Context, prompt, events, answer, chat ID in SQLite |
| `service.log` | Event connection, job starts, results, errors |
| `logs/linear-completion.log` | Linear completion checks |

Keychain service `local.slack-codex` holds accounts `slack-user`, `slack-app`,
and `linear-read`. The user token grants `reactions:read`, `reactions:write`,
`channels:history`, `groups:history`, `im:history`, and `mpim:history`, plus
Slack's implicit `identify`. The app token grants only `connections:write`.
The Linear key is read-only. Agent replies and issue creation use Jesse's
existing connected apps. The worker user token has no `chat:write` scope.

```sh
slack-codex status
slack-codex pause
slack-codex resume
slack-codex rerun JOB_ID
uv run python linear_sync.py status
uv run python chat_archive.py status
tail -f "$HOME/Library/Application Support/slack-codex/service.log"
```

`pause` and `resume` control both reaction workflows together. They leave the
separate Linear completion service running. A rerun explicitly permits another
run for that message and emoji, and keeps the old run records. When the service
is paused, `slack-codex run-job JOB_ID` runs only that queued job.

To pause or resume the separate completion service:

```sh
launchctl bootout "gui/$(id -u)/local.slack-codex.linear-completion"
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/local.slack-codex.linear-completion.plist"
```

To uninstall, run `slack-codex uninstall`, unload the completion service with the
command above, and remove its plist from `~/Library/LaunchAgents/`. Runtime
records and Keychain credentials are retained. Remove those entries in Keychain
Access and revoke the Slack app and Linear key when they are no longer needed.

## Setup and Verification

For another person, start with the [agent setup guide](docs/AGENT_SETUP.md) and
[configuration example](docs/config.example.json). Do not reuse Jesse's runtime
configuration. The guide includes required checks and conditions that block activation.

Use `uv sync --locked` to install dependencies. `slack-codex init --project PATH`
creates initial configuration. Set `transport` to `socket-mode`, `slack_app_id`,
and each workflow's `execution`, `desktop_project_id`, and
`app_server_project_id` for this installation. Read the app-server `project/list`
response to obtain the last value. Do not substitute an app tools project ID.

Create or reuse the Slack app with the user scopes above. Enable Socket Mode,
then subscribe to `reaction_added` under events on behalf of users. Leave bot
events empty. Store the user token with `slack-codex credential` at its hidden
terminal prompt. Store the app token in the Keychain account described above;
never paste a token into chat, source, logs, or shell arguments.

Use `slack-codex check`, `slack-codex poll`, and
`slack-codex dry-run CHANNEL MESSAGE_TS --emoji EMOJI` for read-only checks.
A successful dry run records validation automatically. No separate user approval
step is required. Code, config, or skill edits require new validation before a
service restart. `slack-codex install-service` writes the launchd file;
`slack-codex resume` loads it. The current Mac already has both services installed.

```sh
uv run --with pytest pytest -q
```

Tests cover attribution, pagination, baseline suppression, event deduplication,
restart recovery, reaction-on-reply context, concurrent workflows, retry bounds,
and deterministic archive timing. Unit tests use no model tokens. Live tests
verified both event types, app-visible chats, connected reads, and local helpers.

Native Slack Later/to-do updates remain unsupported. A checkmark or removal of
an inbox reaction does not itself complete a native Slack Later item. This
project does not claim that integration is active.

## Sources

- [Slack Socket Mode](https://docs.slack.dev/apis/events-api/using-socket-mode/)
- [Slack reaction_added](https://docs.slack.dev/reference/events/reaction_added/)
- [Slack reactions.list](https://docs.slack.dev/reference/methods/reactions.list/)
- [Slack conversations.replies](https://docs.slack.dev/reference/methods/conversations.replies/)
- [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits/)
- [Codex app-server](https://learn.chatgpt.com/docs/app-server)

The local CLI's generated experimental schema is the source for `projectId` and
local dynamic tools. These experimental interfaces can change after an update;
project, sandbox, and approval checks fail closed when the result differs.
