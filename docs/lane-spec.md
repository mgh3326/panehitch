# Lane specification

A lane is a TOML file. Required top-level values are `label`, `cwd`, and `timeout_s`. Its tables are `agent`, `tools`, `prompt`, `completion`, `artifacts`, `herdr`, and `report`.

`agent.kind` is one of `claude`, `codex`, or `gemini`; `agent.args` is a string list. `tools.allow` is a string list applied at pane start. `prompt.file` contains the task, while `prompt.header` carries an idempotency notice. `completion.marker` is a regular expression searched in pane output. `artifacts.globs` are copied from `cwd` to the unique run directory. `herdr.session` and `workspace` select the pane context, and `report.dir` owns outcomes.

Each outcome has `schema_version` set to `panehitch-cycle/v1`, a terminal status, timestamp fields, `pane_id`, `tab_id`, and `run_dir`.
