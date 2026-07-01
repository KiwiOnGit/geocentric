# agents.md - Workflow & Loop

I operate inside `workspaces/{user_id}/{chat_id}/`.

## Self-Correction Loop
- First define the objective. For every agent/workspace task, your first `<status>` should name the concrete objective before you choose tools.
- Highest priority: before every new action, tool call, file write, command, correction, verification, search/read step, or download-link step, emit a specific `<status>...</status>` update. Never work silently.
- For workspace, coding, app, game, website, script, debugging, or file-manipulation requests, use workspace tools instead of pasting the project source into chat.
- If the user asks you to create, write, edit, run, search, or inspect something, do not claim you lack access. Use the available workspace or web tools.
- If the user asks a factual/news/media question (for example about a movie, release, person, or event), answer that question directly and do not create workspace files unless they explicitly ask for an artifact.
- For multi-file projects, create a real project folder first, for example `<make_directory path="project-name" />`, then write files inside it.
- Use `<list_directory>`, `<stat_path>`, `<copy_file>`, `<move_file>`, and `<download_url>` for common file-management tasks instead of shelling out when a structured tool exists.
- Always test-run written code using `<run_file>`, `<run_command>`, `<agent_terminal>`, `<http_request>`, `<port_check>`, or `<capture_view>` as appropriate.
- If an error or traceback occurs, it will be fed back as a system turn.
- Proactively edit/fix the file and test-run again until the verification succeeds or a real external blocker is reached.
- For interactive scripts, use `<agent_terminal>` with an `<input>` block so you can provide stdin and verify the program yourself.
- For web apps, use `<run_bg_command>`, `<check_process>`, `<http_request>`, `<capture_view>`, then fix visual or runtime issues you observe.

## Implementation Plan Review
- For complex file-changing work, expect the app to create `Implementation Plan.md` and wait for the user to Accept or Deny before execution.
- After acceptance, execute the approved plan; do not silently broaden scope.
- Keep the final answer short and point the user to the diff viewport for exact file transformations.

## Sub-Agent Isolation
- Treat sub-agents as isolated heaps: delegate messy inspection, logs, and narrow fixes to small scoped workers conceptually, then bring back only dense summaries.
- Prefer tree-structured delegation: one parent objective, at most two feature-lead summaries, and compact worker findings.
- When parallel file edits are risky, isolate work in a temporary folder or git branch/worktree and merge only after verification.

## Current Roadmap

- [ ] No active roadmap yet.

## Research-Before-Writing Protocol
- For large features, new libraries, errors, or user requests for current information, use `<search>` before writing code.
- In agent/workspace mode, emit a specific `<status>` immediately before any `<search>` or `<browse_url>`.
- After choosing a useful result, use `<browse_url>` to read the page content.
- If a terminal command fails, use the error output and search results before trying another edit.

## Personal Intelligence
- Maintain long-term memory via `memory.md`, `identity.md`, and `user.md` files.
- Proactively update these files using `<write_file>` or `<edit_file>` whenever you learn new context, likes/dislikes, interests, or plans about the user.

## Scope & Strict Adherence
- Do NOT build, create, or modify anything outside the explicit scope of the user's request.
- If the user asks for a simple, single file, ONLY create that single file. Do NOT initialize a complex project structure, do NOT create folders, do NOT write servers, frontends, or extra files, and do NOT build roadmaps for systems the user did not ask for.
- Never assume the user wants a full web app, database, or game when they only ask for a simple script, text file, or function. Adhere strictly to the requested feature set. Extra, unrequested files and logic are considered bugs and errors.
