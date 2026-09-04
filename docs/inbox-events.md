# Inbox events

`panehitch inject --inbox INBOX --state STATE` reads JSON files from `INBOX`. Each event has string fields `id`, `target`, and `prompt_file`.

```json
{"id":"evt-001","target":"review-pane","prompt_file":"prompts/review.md"}
```

The state file is a JSON list of event IDs. An ID advances to seen only after submission proof succeeds; failed or unconfirmed events remain eligible for a later attempt.
