# Backends

`PaneBackend` is the adapter contract: start a pane with session, workspace, working directory, agent kind, arguments, allowlist, and label; list panes; prompt; read text and status; send return; and close a pane.

The supplied adapter invokes the current pane command-line program using JSON responses. Future terminal adapters only need to preserve this contract. In particular, `read` must expose visible text and an idle or working status, because submission proof depends on both.
