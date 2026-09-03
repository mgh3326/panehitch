# panehitch

Repeatable runs for agent sessions living in terminal panes: spawn, apply an allowlist profile, inject a prompt, prove submission, wait for a marker, collect artifacts, clean up, and write an outcome JSON.

Prompt injection is not submission. A command can place text in a composer without sending it; panehitch inspects the pane, sends return only when a pasted chip or literal prompt proves it is needed, then inspects again. A queued-message notice without a chip is treated as submitted to prevent duplication.

## Quick start

```sh
uv run panehitch templates init example
# Edit example/lane.example.toml and replace REPLACE_WORKSPACE_LABEL.
uv run panehitch run --lane example/lane.example.toml
uv run panehitch inject --target review-pane --file prompt.md
```

The companion tools are [panewire](https://github.com/mgh3326/panewire),
[handoffkeep](https://github.com/mgh3326/handoffkeep), and
[postuntil](https://github.com/mgh3326/postuntil).

For the current backend, the working directory must already be trusted by the selected agent. A first-use trust dialog is recorded as a blocked startup and the run stops without sending a prompt.

## Scope / not yet

v0 deliberately does not include preflight policies, dry-run execution gates, report relays,
hub notifications, transcript capture, pane-environment passthrough, advisory inbox locking,
rate caps, hold ledgers, watermarks, or multi-adapter implementations. Those integrations stay
outside this small public harness until their contracts can be made portable.
