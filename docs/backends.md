# Backends

`PaneBackend` is the adapter contract: start a pane with session, workspace, working directory, agent kind, arguments, allowlist, and label; list panes; prompt; read text and status; send return; and close a pane.

The supplied adapter invokes the current pane command-line program using JSON responses. `[backend] kind` selects an adapter; v0 supports `herdr`. Future terminal adapters register a new kind while preserving this contract. In particular, `read` must expose visible text and an idle or working status, because missing status fails submission proof closed.
