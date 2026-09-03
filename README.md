# panehitch

Repeatable runs for agent sessions living in terminal panes: spawn, apply an allowlist profile, inject a prompt, prove submission, wait for a marker, collect artifacts, clean up, and write an outcome JSON.

Prompt injection is not submission. A command can place text in a composer without sending it; panehitch inspects the pane, sends return only when a pasted chip or literal prompt proves it is needed, then inspects again. A queued-message notice without a chip is treated as submitted to prevent duplication.

## Quick start

```sh
uv run panehitch templates init example
uv run panehitch run --lane example/lane.example.toml
uv run panehitch inject --target review-pane --file prompt.md
```

The companion tools are [panewire](https://github.com/mgh3326/panewire),
[handoffkeep](https://github.com/mgh3326/handoffkeep), and
[postuntil](https://github.com/mgh3326/postuntil).
