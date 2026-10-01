# When to consult the GraphEngine brain (opt-in snippet)

Paste into `CLAUDE.md` / `AGENTS.md` if you want the assistant to reach for
the brain proactively:

```markdown
## Knowledge brain
An GraphEngine MCP server (tools: search_brain, get_node, neighbors,
brain_status) is available. Consult it BEFORE starting non-trivial design,
architecture or research work — it may already hold prior decisions,
constraints and related ideas. Skip it for routine edits, typo fixes and
mechanical refactors. `search_brain` scores are rank-fusion scores, not
similarities. The brain is read-only from here; changes go through the
owner (`ig ingest`, `ig pending`).
```

## If the server runs in write mode (`ig mcp --write`)

```markdown
## Knowledge brain (write mode)
The GraphEngine MCP server also has `remember`, `recall` and `forget`.
- `remember` — keep a durable finding you would otherwise lose. It is recorded
  with source=agent, so provenance stays visible. Do not use it for notes that
  belong in the repo, the PR or the chat.
- `recall` — search whose hits COUNT AS USE (they feed the promotion signal).
  Prefer `recall` over `search_brain` when you actually act on the result;
  `search_brain` for pure exploration.
- `forget` — only with a real reason, and only for a memory that is wrong or
  superseded. It tombstones the node instead of deleting it; the owner can see
  the history. Never use it to "clean up" something you merely dislike.
```

There is deliberately NO per-command hook: noisy PreToolUse nudges are the
known anti-pattern that gets MCP tools abandoned.
