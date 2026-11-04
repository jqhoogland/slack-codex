# Slack Codex

A personal, local Slack reaction worker for macOS. Python polls Slack without a model. Only a new configured reaction can queue a Codex run. The default mapping is `robot_face` to the `respond-to-queries` skill in the Resolution project.

## Installation

Use Python 3.11 or later through uv. Install Codex CLI and sign in with `codex login`.

```sh
uv sync --locked
uv run slack-codex init --project /Users/Jesse/Projects/resolution
uv run slack-codex credential
uv run slack-codex install-service
```

Run these commands from the repository. `init` refuses to replace existing configuration. `credential` requires a local terminal with hidden input. The service installation writes a launchd file but does not load it.

On this Mac, the command is also installed at `/Users/Jesse/.local/bin/slack-codex`.

## Slack App Setup

1. Open [Your Apps](https://api.slack.com/apps). Select **Create New App**, then **From scratch**. Name it **Local Codex Reactions** and select your workspace.
2. Open **OAuth & Permissions**. Under **User Token Scopes**, add `reactions:read` and the history scopes below for the conversation types you need.
3. Leave **Bot Token Scopes** empty. No write scopes, bot user, incoming webhook, event subscription, or Socket Mode token are needed for polling.
4. Select **Install to Workspace** and authorize with your own Slack account. Workspace policy can require a human administrator to approve the app.
5. Return to **OAuth & Permissions**. Copy the **User OAuth Token**, which starts with `xoxp-`.
6. Run `slack-codex credential` in your own terminal. Paste only at the hidden prompt. The command checks `auth.test`, user identity, workspace identity, and the exact scope set from the `x-oauth-scopes` response header. It stores the token in macOS Keychain. Do not put it in chat, a command argument, a file, or an environment variable.

| Conversation Type | User Scope |
|---|---|
| Public channels | `channels:history` |
| Private channels | `groups:history` |
| Direct messages | `im:history` |
| Group direct messages | `mpim:history` |

The initial configuration requests all four history scopes plus `reactions:read`. To reduce access, edit `scopes` in the local configuration before entering a token with the same reduced scope set. Extra scopes are rejected. No Slack write permission is accepted.

A user token can access public conversations and private conversations its user belongs to, within its scopes. Retention, deletion, workspace policy, and changes to membership can prevent retrieval. This program does not join channels or invite a bot. File attachments are included as message metadata when Slack returns them; their contents are not downloaded.

This version accepts a workspace user token without token rotation. It does not request or store a client secret or refresh token. If your workspace requires rotating tokens, stop setup and add the official refresh flow before enabling the service. Expired or revoked tokens cause read failures; they do not grant additional access.

## First Live Check and Review

```sh
slack-codex check
slack-codex poll
```

`check` reports your identity, granted scopes, and matching channel/message/emoji identifiers. `poll` reads all reaction pages and saves the first baseline. Neither command invokes Codex.

Choose one matching message from `check`. Use its channel ID and timestamp as the two arguments to `slack-codex dry-run`. For the default emoji, no emoji argument is needed. For another mapping, add `--emoji` and the Slack emoji name without colons.

The dry run checks that you added that exact reaction. It fetches the selected message, its parent, and all thread pages. It prints the thread and saves the exact prompt, command, configuration digest, and review ID under `reviews/`. No model runs and no Slack writes occur.

Review that result. Only after the user approves it, run `slack-codex approve` with its review ID. Then use `slack-codex resume` to load the service. Code, configuration, and skill changes invalidate approval and require another dry run.

For an explicit test of an existing baseline item, use `slack-codex status` to find its job ID. Run `slack-codex rerun` with that ID, then `slack-codex run-job` with the same ID while the service is paused. This starts one real model run and requires dry-run approval. It does not enable the service. Confirm the saved session opens in the desktop app before accepting the installation as fully verified.

## Multiple Workflows

Edit `~/Library/Application Support/slack-codex/config.json`. Each key under `workflows` is a Slack emoji name without colons. Each mapping has:

| Field | Purpose |
|---|---|
| `project` | Absolute working-folder path |
| `skill` | Absolute path to the workflow's SKILL.md |
| `instructions` | Trusted standing task instructions |
| `sandbox` | `read-only` or `workspace-write` |

Each new emoji gets its own baseline on the first complete scan. Existing reactions for that emoji do not launch agents. A job keeps the workflow configuration from discovery. If that configuration changes, the job stops until a manual rerun captures the new configuration. Changing the skill also requires new dry-run approval.

Pause before changing configuration. The initial skill only answers queries. It writes no Slack replies. The initial sandbox is read-only. Use workspace-write only for a workflow that needs project edits.

## State and Recovery

The trigger key is `(workspace, user, channel, message timestamp, emoji)`. The message timestamp identifies a message only. It is never treated as a reaction time. Multiple duplicate Slack results collapse to one key. Removing and adding the same reaction does not trigger a second run. An explicit manual rerun can repeat work.

Every poll scans all pages. There is no timestamp cutoff and no assumption about reaction order. If a message is very old, a new reaction still queues it after the baseline. A complete scan commits discoveries and baseline flags in one SQLite transaction. A failed scan commits neither.

Cursor pagination is preferred. Legacy page metadata is supported when returned without cursor metadata. A repeated cursor, an incomplete response without a cursor, or the legacy page limit causes an error, rather than a false complete scan. Concurrent Slack changes can shift pages; later full scans can find reactions that remain present. Slack does not provide an atomic snapshot here.

After sleep or a network outage, the next full scan finds remaining reactions. Polling can miss a reaction added and removed between checks. The first baseline suppresses all reactions present during that scan, including reactions added before that initial scan completes.

One worker runs at a time. A local file lock excludes a second service or manual worker. Fetch failures retry up to three times with a delay. HTTP requests have a 30 second timeout, up to three attempts, and honor `Retry-After`. Each Codex run has a configurable timeout, initially 30 minutes.

Before starting a child, SQLite records the run as running. An uncertain launch after a crash becomes `interrupted`. The queue enters a recovery hold. Inspect the run files and any surviving Codex process, then use `slack-codex clear-recovery` while paused. Rerun interrupted jobs explicitly if needed. This protects against duplicate launches at the cost of manual action when a crash occurs between the database commit and process start. It does not claim exactly-once side effects.

Codex failures and timeouts require a manual rerun. They never cause an automatic second model run. Manual reruns reset the fetch-attempt count but retain all past run records.

## Codex Execution and Credentials

The installed CLI was checked at version 0.164.0. The worker uses `codex exec`, stdin, `--json`, `--output-last-message`, an explicit project folder, and an explicit sandbox. It retains the local Codex session and saves its ID from the `thread.started` event. There is no `--ephemeral` flag.

Approval policy is explicitly `on-request`. No bypass or automatic approval flag is used. Unattended runs cannot supply human approval. If a task needs approval, inspect its local session and continue it interactively. The command ignores the user config to avoid inheriting unrelated MCP tools. Apps are disabled for the run. Workspace shell network access is disabled. This still permits Codex itself to contact the model service.

The selected Slack content travels to the model when a real job runs. Polling and dry runs make only Slack requests. The worker never passes the Slack token in prompts, command arguments, or the child environment. Its child environment uses a small allowlist. Slack API errors exclude raw response bodies and credential-bearing URLs.

The token stays in macOS Keychain under service `local.slack-codex`, account `slack-user`. The worker uses the native keyring backend, without a plaintext fallback. macOS may ask you to allow Keychain access. The process still runs as your user: this is not a separate operating-system account or a guarantee that all of your other local credentials are unreadable. Keep the read-only default and do not grant broader access to untrusted work.

## Files and Commands

All runtime data is under `~/Library/Application Support/slack-codex/`, outside the repository. New files use owner-only permissions.

| File or Folder | Contents |
|---|---|
| `config.json` | Emoji mappings, scopes, Slack IDs, CLI path, timeout |
| `state.sqlite3` | Job keys, statuses, attempts, errors, and run history |
| `reviews/` | Live dry-run context and exact launch preview |
| `approval.json` | Approved review and configuration digest |
| `runs/` | Context, prompt, output events, final answer, error log |
| `service.log` | Poll results and controlled operational errors |

The launchd file is `~/Library/LaunchAgents/local.slack-codex.plist`. It contains no token. The service starts after user login only when loaded. This program does not publish a remote repository.

```sh
slack-codex status
slack-codex pause
slack-codex resume
slack-codex uninstall
slack-codex forget-token
tail -n 100 -f "$HOME/Library/Application Support/slack-codex/service.log"
```

`rerun` takes a job ID. `run-job` takes a job ID and runs it once while paused. `approve` takes a review ID. `clear-recovery` removes the queue hold after you check an interrupted run.

Use the session ID in `status` with `codex resume` to inspect a run in the CLI. Desktop app visibility must also be checked with the first approved live run. No claim is made that a local Codex session becomes a separate cloud ChatGPT conversation.

`uninstall` unloads the service and removes its launchd file. It retains the token and audit files. Use `forget-token` to remove the Keychain entry, and revoke the app in Slack to invalidate the token. Remove the repository, command link, and runtime folder only when you no longer need their contents.

## Rate Limits and Socket Mode

The Slack documentation checked on 2026-11-04 lists `reactions.list` at Tier 2 (20+ requests per minute), and `reactions.get` and `conversations.replies` at Tier 3 (50+ requests per minute). Requests are paced by method; HTTP 429 responses override that pacing. The page size is 200. Large reaction histories can require enough pages that a scan takes longer than 60 seconds. The service logs scan time and warns above 55 seconds. It never overlaps scans.

If a live scan is too expensive, use a user `reaction_added` event subscription over Socket Mode. The program would filter the event's `user` and `reaction`, acknowledge it promptly, and use the same SQLite queue. Socket Mode also needs an app-level token with `connections:write`; that is separate from the user history scopes. User event subscriptions avoid per-channel bot invitations. Reconnect gaps still need an explicit recovery plan, such as a reconciliation scan. This version does not request that token or enable events.

## Verification

```sh
uv run python -m unittest discover -s tests -v
```

Tests use fake Slack responses and small local child programs. They spend no model tokens. Live Slack access, desktop session visibility, and a real agent run are separate installation checks.

## Sources

- [Slack reactions.list](https://docs.slack.dev/reference/methods/reactions.list/): attribution, duplicate items, pagination, and Tier 2.
- [Slack reactions.get](https://docs.slack.dev/reference/methods/reactions.get/): selected message and reaction attribution.
- [Slack conversations.replies](https://docs.slack.dev/reference/methods/conversations.replies/): thread pagination and history scopes.
- [Slack conversations.history](https://docs.slack.dev/reference/methods/conversations.history/): user-token visibility.
- [Slack OAuth](https://docs.slack.dev/authentication/installing-with-oauth/): user-scoped tokens.
- [Slack rate limits](https://docs.slack.dev/apis/web-api/rate-limits/): per-method limits and Retry-After.
- [Codex noninteractive mode](https://learn.chatgpt.com/docs/non-interactive-mode): CLI execution, stdin, sandbox flags, and saved output.
