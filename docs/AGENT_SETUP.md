# Set Up a New Person

This guide is for an agent helping a person install the source checkout on
macOS. Read it before changing local configuration. The current project is an
experimental personal tool, not a general installer.

## Completion Criteria and Known Limits

Do not report setup as complete merely because a job or chat ID exists.
Verify the selected Slack message, the agent output, any authorized external
result, and the chat's placement in the intended desktop project.

Automatic sidebar placement and interactive chat ownership remain unreliable.
The app-server project ID check does not prove placement in the desktop app.
If correct project placement is required, stop before background activation
when that check fails. Preserve the configuration and report the failed check.
Do not edit the desktop app's private state or weaken permissions to work around
this limit. The macOS command approval dialog also needs a live human check.
Other approval and user-question types stop the run for manual handling.

Native Slack Later/to-do updates are not implemented. The supplied skills are
Jesse's examples and must be adapted. The manual Linear linking command accepts
only Resolution Slack URLs; use the in-chat `register_linear_issue` tool for
other workspaces. Do not claim that a token or skill grants access to every
Slack channel. Access is limited to the authorizing user's accessible content
and the granted history scopes.

## 1. Collect the Installation Choices

Ask these questions together, and reuse answers already supplied:

- Which Slack workspace and user should trigger work?
- Which emoji names, task instructions, local folders, and desktop projects
  should be mapped? Use Slack names such as `robot_face`, without colons.
- Which conversation types are required: public channels, private channels,
  direct messages, or group direct messages?
- May each workflow write to external tools or reply in Slack? What must it ask
  about first? Which AI use labels and issue assignment rules apply?
- Are progress reactions and optional Linear completion checks wanted?

Do not copy another person's IDs, credentials, local state, or task history.
Use one installation per macOS account. `--home` changes the main CLI data
folder but does not isolate Keychain accounts, service labels, or the Linear
and archive helper defaults. Multiple installations in one account are not
supported by this guide.

## 2. Check the Computer and Install the Checkout

Confirm macOS, `uv`, Git, and a signed-in Codex CLI. Check `codex --version`,
`codex login status`, and `codex app-server --help`. Do not install or assume
an old CLI version. The prototype was tested against 0.164.0; verify the
experimental protocol on the installed version.

Clone into a stable folder that the person will retain:

```sh
git clone https://github.com/jqhoogland/slack-codex.git
cd slack-codex
uv sync --locked
uv run --with pytest pytest -q
uv run slack-codex --help
```

Run the following commands from that checkout. Use `uv run slack-codex`, not
an assumed global executable. A standalone wheel is not a supported install.
Do not clone into a temporary folder: launchd will reference this checkout.

If `~/Library/Application Support/slack-codex/config.json` already exists,
inspect it and back it up privately. Do not run `init` over an existing setup.
For a new setup, use the user's actual existing working folder:

```sh
uv run slack-codex init --project /absolute/path/to/project
```

The generated configuration is a starting point. It does not enable Socket
Mode or create desktop projects. Complete the next steps before activation.

## 3. Create and Authorize the Personal Slack App

Use [Slack app management](https://api.slack.com/apps) to create an app in the
selected workspace. Respect any workspace approval requirement. Do not approve
an administrator's decision on their behalf.

Under OAuth & Permissions, add these **User Token Scopes**, not bot scopes:

| Scope | Purpose |
| --- | --- |
| `reactions:read` | Read the user's reactions and receive reaction events |
| `channels:history` | Public channel message context, if requested |
| `groups:history` | Private channel context, if requested |
| `im:history` | Direct message context, if requested |
| `mpim:history` | Group direct message context, if requested |
| `reactions:write` | Optional progress and completion reactions |

Request only the history scopes for the selected conversation types. Initially
omit `reactions:write` unless status reactions were requested. Do not request
`chat:write` for the listener. Agent replies use the person's separately
connected Slack tool, which needs its own access and task authorization.

Enable Socket Mode. Under Basic Information, create an App-Level Token with
only `connections:write`. Subscribe to `reaction_added` under events on behalf
of users in Event Subscriptions. Leave bot event subscriptions empty. Enable
delayed events if available. Save changes.

Install the app to the workspace and authorize it as the intended user. After
scope changes, reinstall or reauthorize as Slack requires. Obtain the **User
OAuth Token**, starting with `xoxp-`, from OAuth & Permissions. The App-Level
Token starts with `xapp-`. Record the app ID from Basic Information; it is not
a secret. User tokens avoid per-channel bot invitations but do not grant
content access beyond the user's permissions.

See [Socket Mode setup](https://docs.slack.dev/apis/events-api/using-socket-mode/)
and [reaction listing](https://docs.slack.dev/reference/methods/reactions.list/).

## 4. Configure Skills and Desktop Projects

Create or select the intended projects in the Codex desktop app. Record their
IDs with the app's `list_projects` tool. Do not infer IDs from project names.

The worker also needs the **different app-server project IDs**. From the
checkout, list them without starting a model:

```sh
uv run python - <<'PY'
import json
import shutil
from codex_rpc import Rpc
with Rpc(shutil.which('codex')) as rpc:
    print(json.dumps(rpc.call('project/list', {}), indent=2))
PY
```

Follow `nextCursor` if the response is paginated. Match project names and roots.
If the required project is absent, resolve that in the desktop app before
continuing. Do not create a second project merely to get an ID.

Make personal copies of the example skills outside the checkout. Replace
Jesse's name, paths, assignee defaults, AI-label skill references, and internal
link choices. Confirm connected Slack and Linear access in the intended agent
account. Keep source Slack content as untrusted data. Preserve the rule against
retrieving the automation's credentials. For a new general workflow, use
`action: "custom"` and specify its steps and allowed outputs in its skill.

Edit the local `config.json` using the shape in
[config.example.json](config.example.json). Every `REPLACE_` value is an example
marker, not a usable setting. `project` and `skill` must be absolute paths to
an existing directory and file. `codex` must be an absolute executable path.

Set `scopes` to exactly the granted user scopes, except Slack's implicit
`identify`. The program checks for an exact match. If status reactions are off,
set `status_reactions` to false and omit `reactions:write`. Start with
`read-only` and `on-request` approval. Use `workspace-write` only where needed.
Do not select `danger-full-access` to make unattended execution pass.

For status reactions, ensure the workspace has `codex_working` under that
exact name. The current runner hardcodes it. Add the supplied GIF only if the
person wants that asset and has permission to add custom emojis. Otherwise
leave status reactions off. Standard `white_check_mark` needs no custom upload.

## 5. Enter Credentials Locally

Never ask for secrets in chat or put them in commands, prompts, source files,
logs, or screenshots. The person must enter them in a local interactive terminal.
Do not capture terminal input. Do not copy another account's Keychain entries.

First store the user OAuth token using the hidden prompt:

```sh
uv run slack-codex credential
```

This verifies identity and scope matching, writes `user_id` and `team_id` into
the configuration, and stores the token in macOS Keychain. If identity is wrong,
stop and correct the authorization rather than overriding the check.

Store the app token with this hidden prompt from the same checkout:

```sh
uv run python -c 'import getpass; from keyring.backends.macOS import Keyring; token = getpass.getpass("Slack app token (hidden): ").strip(); assert token.startswith("xapp-"), "Expected an app token"; Keyring().set_password("local.slack-codex", "slack-app", token); print("Stored app token.")'
```

Keychain service `local.slack-codex` uses accounts `slack-user`, `slack-app`, and,
optionally, `linear-read`. Keychain access may prompt the person. Do not log
secret values or pass them to the child agent.

## 6. Verify Before Enabling Background Work

```sh
uv run slack-codex check
uv run slack-codex poll
uv run slack-codex status
```

The first scan establishes a baseline without starting old reactions. On a
private test message, add the selected emoji. Obtain its channel ID and exact
message timestamp from its Slack link. For `p1234567890123456`, the timestamp
is `1234567890.123456`; keep it as a string. Do not treat it as reaction time.

Run `uv run slack-codex dry-run CHANNEL MESSAGE_TS --emoji EMOJI` with the real
values. Inspect the selected message, containing thread, prompt, skill, folder,
and app project. A dry run performs reads and records validation, not model work.
It is required again after code, configuration, or skill changes.

With the service still stopped, run `poll` and inspect `status`. For an explicit
model test, use `rerun JOB_ID` and then `run-job JOB_ID`. These commands permit
another run and can repeat writes. Use a harmless, clearly authorized task and
inspect prior results first. Test a reaction on a reply as well as a root message.

Check all of the following:

- The correct user's reaction starts exactly one matching workflow.
- The selected reply and the complete parent thread reach the agent.
- The agent uses the selected skill and stays within its allowed work.
- The chat appears under the intended desktop project, not merely in storage.
- A required permission request is visible and decline prevents that action.
- The result and authorized Slack reply succeed; failed work gets no checkmark.
- A restart or reaction remove/re-add does not repeat the run.

A job marked blocked or failed is not a successful install. Inspect its saved
run before any rerun. If the placement or interactive handoff check fails,
report the known limit and leave automatic agent dispatch disabled. There is
no supported zero-token desktop assignment workaround in this guide.

## 7. Install and Control the Background Service

Only after the required checks pass:

```sh
uv run slack-codex install-service
uv run slack-codex resume
uv run slack-codex status
```

The first command writes `~/Library/LaunchAgents/local.slack-codex.plist`.
The second loads it in the current macOS user's session. Check `service.log`
for a Socket Mode connection, then test one new reaction. The Mac must be
awake and online. Reconnect scans catch reactions that remain present; they
cannot recover every reaction added and removed while offline.

```sh
uv run slack-codex pause
uv run slack-codex resume
tail -f "$HOME/Library/Application Support/slack-codex/service.log"
```

A queued request waits for its emoji's single worker slot. Other emoji workflows
can run at the same time. Removing and adding the same reaction never resets
the once-per-message/emoji key. Use an explicit rerun only after inspection.

## 8. Optional Linear Completion Checks

Issue intake uses the person's connected Linear tool. Completion checks use a
separate read-only personal Linear API key. Ask the person to create one for
the intended teams, then enter it locally:

```sh
uv run python linear_sync.py credential
uv run python linear_sync.py check
uv run python linear_sync.py status
```

Set `linear_completion_enabled` to true in `config.json` if completion sync is
wanted. Set `status_reactions` to true and grant `reactions:write` for the Slack
updates. The intake agent must call `register_linear_issue` after verifying an
issue. Confirm that the saved link points to the original selected message.

Run `uv run python linear_sync.py serve` in the foreground for a test. This
checks every five minutes. Mark a disposable test issue complete and verify
that the original message receives a checkmark and loses the inbox reaction.
Cancellation does not count as completion. Do not mark a real issue complete
just to test the installation.

For persistence, create a separate user launchd plist named
`local.slack-codex.linear-completion`, using the main service plist as a model.
Set ProgramArguments to the absolute `.venv/bin/python`, the absolute
`linear_sync.py` path, and `serve`. Use the checkout as WorkingDirectory and
private log paths in the runtime folder. Load it with `launchctl bootstrap`
only after the foreground test. The main service does not install this helper
or pause it. Keep this separate service in the handoff notes.

## 9. Handoff, Upgrade, and Uninstall

Give the person the exact checkout, config, skill, log, and plist paths. Record
the scopes actually granted, the two project IDs for each workflow, test
results, and remaining failures. Do not include credentials in the report.
Runtime state is under `~/Library/Application Support/slack-codex/` and includes
SQLite jobs, run output, and private thread previews. Keep it out of Git.

Before upgrading, pause the services and inspect active jobs. Save a private
backup of configuration and state. Update the checkout without discarding local
changes, run `uv sync --locked` and the tests, then repeat dry-run and desktop
placement checks. Do not relaunch uncertain agent runs automatically.

To remove the main service, run `uv run slack-codex uninstall`. This retains
runtime history and credentials. Stop and remove the separate Linear plist if
installed. `forget-token` removes only `slack-user`; remove `slack-app` and
`linear-read` separately in Keychain Access when requested. Revoke credentials
in Slack and Linear when no longer needed. Ask before deleting saved history.
