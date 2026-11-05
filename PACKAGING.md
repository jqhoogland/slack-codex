# Shared Use Proposal

This is a personal macOS prototype. Keep it in a private repository until the
team agrees on ownership, support, and distribution. Do not treat a passing
unit test suite as proof that the desktop integration is ready for shared use.

## Separate the Runner From the Skills

The runner owns Slack events, credentials, SQLite state, queues, status
reactions, Linear completion checks, and chat archival. Keep these tasks
separate from model instructions. Listening must continue to use no model tokens.

Skills define the work for each reaction. Make the emoji mapping, target
project, working folder, and personal instructions configuration values.
Each person should authorize their own Slack account and keep tokens in their
own Keychain. Do not distribute Jesse's runtime configuration or task history.

## Possible Monorepo Location

The existing `ops/README.md` puts developing workflow skills in `ops/skills/`
and stable shared skills in `plugins/ops/skills/`. Follow that split if this
becomes a shared ops workflow.

A proposed location for the Python runner is
`resolution/ops/slack_agents/`, beside other operations code. This is a proposal,
not an agreed convention for general agent tools. Ask whether the runner should
instead be a reusable developer tool with an ops plugin as one client.
The existing `resolution/ops/hiring/gmail_to_linear/` integration is a useful
comparison, but this runner is broader than hiring.

## Before Shared Installation

- Verify automatic desktop project placement and interactive chat ownership.
- Test a real permission dialog, including decline and timeout behavior.
- Handle all supported approval and user-question types, not only commands.
- Replace personal paths and preferences in the skills with setup inputs.
- Add a supported install and upgrade path. The current setup uses a source
  checkout with `uv sync`; a standalone wheel is not a supported distribution.
- Agree on the Slack app owner, workspace approval process, and access policy.
- Assign a maintainer and define support for Codex protocol changes.
- Agree on licensing before distributing code or the bundled logo assets.

Native Slack Later updates are still unsupported. Keep that limit explicit.
The experimental Codex app-server interface also needs version checks and a
small compatibility test before each upgrade.
