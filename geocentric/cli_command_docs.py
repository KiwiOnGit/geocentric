"""Geocentric Code CLI — detailed slash-command documentation for /whatisthis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class CommandDoc:
    what: str
    why: str
    when: str
    how: str
    examples: tuple[str, ...] = ()


def _d(what: str, why: str, when: str, how: str, *examples: str) -> CommandDoc:
    return CommandDoc(what=what, why=why, when=when, how=how, examples=examples)


COMMAND_DOCS: dict[str, CommandDoc] = {
    "/help": _d(
        "Lists every available slash command grouped by category.",
        "Discovery — you can't use power features if you don't know they exist.",
        "When you're new, forgot a command name, or want to browse capabilities.",
        "Type /help with no arguments.",
        "/help",
    ),
    "/?": _d(
        "Alias for /help.",
        "Quick shortcut familiar from shells and chat apps.",
        "Same as /help.",
        "Type /?",
        "/?",
    ),
    "/whatisthis": _d(
        "Explains what another slash command does, why it exists, when to use it, and how.",
        "Inline documentation without leaving the terminal or polluting AI context.",
        "When you see an unfamiliar command in /help or autocomplete.",
        "Type /whatisthis followed by the command you want explained.",
        "/whatisthis /compact",
        "/whatisthis /rewind",
    ),
    "/clear": _d(
        "Wipes the in-memory conversation history and starts a fresh conversation ID.",
        "Long chats accumulate noise; clearing resets context without restarting the CLI.",
        "When the agent is confused, off-topic, or you want a clean slate mid-session.",
        "Type /clear — no arguments needed.",
        "/clear",
    ),
    "/reset": _d(
        "Same as /clear — wipes chat context and resets the conversation ID.",
        "Muscle-memory alias for users coming from other AI CLIs.",
        "When you want a hard reset of the current chat thread.",
        "Type /reset.",
        "/reset",
    ),
    "/new": _d(
        "Starts a new conversation while keeping your CLI settings and session file.",
        "Separates topics without losing session metadata (name, model, checkpoints).",
        "When switching to a unrelated task but staying in the same CLI session.",
        "Type /new before your first message on the new topic.",
        "/new",
    ),
    "/compact": _d(
        "Compresses older messages into a summary so you stay within context limits.",
        "Context windows are finite; compaction preserves recent work while dropping bulk.",
        "When responses slow down, context warnings appear, or a long session starts drifting.",
        "Optionally add instructions: /compact keep focus on auth refactor",
        "/compact",
        "/compact preserve API design decisions",
    ),
    "/resume": _d(
        "Reopens a previously saved session by its ID.",
        "Sessions persist to disk — you can continue work across CLI restarts or devices.",
        "After closing the CLI, rebooting, or moving to another machine with the session ID.",
        "List sessions with /resume (no args), then /resume abc123def",
        "/resume",
        "/resume abc123def",
    ),
    "/continue": _d(
        "Alias for /resume — reopen a saved session.",
        "Natural language alias for continuing prior work.",
        "Same as /resume.",
        "Type /continue <session-id>",
        "/continue abc123def",
    ),
    "/exit": _d(
        "Saves the session and closes the CLI.",
        "Clean shutdown preserves session state to disk.",
        "When you're done for now.",
        "Type /exit, /quit, or /q.",
        "/exit",
    ),
    "/quit": _d(
        "Alias for /exit.",
        "Familiar quit shorthand.",
        "When you're done.",
        "/quit",
    ),
    "/q": _d(
        "Short alias for /exit.",
        "Fastest way to leave.",
        "When you're done.",
        "/q",
    ),
    "/rename": _d(
        "Gives the current session a human-readable name.",
        "Named sessions are easier to find when listing with /resume.",
        "At the start of a focused work stream (feature branch, bug hunt, etc.).",
        "Type /rename my-auth-refactor or /rename then enter a name at the prompt.",
        "/rename api-migration",
    ),
    "/context": _d(
        "Shows token estimates, message count, effort level, and conversation ID.",
        "Visibility into context usage helps you decide when to /compact or /new.",
        "When the agent seems to 'forget' things or before starting a large task.",
        "Type /context.",
        "/context",
    ),
    "/rewind": _d(
        "Rolls back recent turns or restores a saved checkpoint.",
        "Undo agent mistakes without manually editing files or restarting.",
        "When the last response was wrong and you want to try again from an earlier state.",
        "Type /rewind to undo 1 turn, /rewind 2 for two turns, or /rewind <checkpoint-id>.",
        "/rewind",
        "/rewind 2",
    ),
    "/model": _d(
        "Shows or switches the AI model used for chat.",
        "Different models trade off speed, reasoning depth, and tool-use quality.",
        "When you need faster replies (/model gemma4-fast) or stronger reasoning.",
        "Type /model to list, or /model gemma4-agent:latest to switch.",
        "/model",
        "/model gemma4-agent:latest",
    ),
    "/effort": _d(
        "Sets reasoning intensity: low, medium, high, or max.",
        "Controls the speed-vs-intelligence tradeoff for complex tasks.",
        "Use low for quick edits; high/max before architectural changes or debugging.",
        "Type /effort high or /effort max",
        "/effort medium",
        "/effort max",
    ),
    "/plan": _d(
        "Toggles planning mode — agent thinks step-by-step before editing files.",
        "Prevents reckless edits on multi-file or high-risk changes.",
        "Before refactors, new features, or anything touching critical paths.",
        "Type /plan to toggle on/off. When on, the next task gets a planning preamble.",
        "/plan",
    ),
    "/auto": _d(
        "Toggles auto agent mode (autonomous tool execution vs read-only chat).",
        "Agent mode lets the AI run commands and edit files; off keeps it advisory only.",
        "Turn off when exploring ideas; turn on when you want it to implement.",
        "Type /auto on or /auto off",
        "/auto on",
    ),
    "/mode": _d(
        "Switches between thinking (agentic) and instant (fast reply) modes.",
        "Thinking mode uses tools and deeper reasoning; instant is for quick Q&A.",
        "Use thinking for coding tasks; instant for short questions.",
        "Type /mode thinking or /mode instant",
        "/mode thinking",
    ),
    "/init": _d(
        "Scans the repo and generates a CLAUDE.md project context file.",
        "Gives the agent persistent project rules and structure — the context layer.",
        "Once per project, or after major restructuring.",
        "Type /init in the repo root.",
        "/init",
    ),
    "/memory": _d(
        "Opens memory.md for editing persistent project memory.",
        "Stores facts the agent should remember across sessions (preferences, names, decisions).",
        "When the agent learned something important you want kept long-term.",
        "Type /memory — opens your $EDITOR (nano by default).",
        "/memory",
    ),
    "/add-dir": _d(
        "Grants the agent awareness of an extra directory outside the project root.",
        "Some workflows span multiple folders (monorepos, shared libs).",
        "When the agent needs read context from another path on your machine.",
        "Type /add-dir /path/to/other/project",
        "/add-dir ~/Projects/shared-lib",
    ),
    "/config": _d(
        "Shows current CLI configuration (server, model, agent mode, etc.).",
        "Quick reference for what's saved in ~/.geocentric/cli.json.",
        "When debugging connection issues or verifying settings.",
        "Type /config or /settings.",
        "/config",
    ),
    "/settings": _d(
        "Alias for /config.",
        "Familiar name from other apps.",
        "Same as /config.",
        "/settings",
    ),
    "/agents": _d(
        "Info about subagent workflows (parallel specialized workers).",
        "Single context windows can't search, review, and implement simultaneously.",
        "When a task is too large for one pass — use with /batch or /review.",
        "Type /agents for guidance, then /review or /batch for specific workflows.",
        "/agents",
    ),
    "/tasks": _d(
        "Lists background agent jobs running on the server.",
        "Long-running work can continue while you do other things.",
        "When you started a background job and want to check status.",
        "Type /tasks.",
        "/tasks",
    ),
    "/batch": _d(
        "Arms the next prompt to split work into parallel subtasks.",
        "Large refactors benefit from divide-and-conquer across subagents.",
        "When you have a big scope and want parallel execution.",
        "Type /batch then describe the work, or /batch refactor auth into 3 parallel tasks",
        "/batch split frontend and backend test coverage",
    ),
    "/background": _d(
        "Info about detaching work to background server execution.",
        "Keeps the CLI responsive while heavy jobs run server-side.",
        "When a task will take a long time (tests, builds, large refactors).",
        "Submit work normally with agent mode on; server queues background jobs.",
        "/background",
    ),
    "/mcp": _d(
        "Manage Model Context Protocol connections (GitHub, DBs, Slack, etc.).",
        "MCP turns the agent into a tool-using system connected to live external data.",
        "When you need GitHub issues, database queries, or Slack without copy-pasting.",
        "Type /mcp for setup info. Configure servers in ~/.geocentric/mcp.json.",
        "/mcp",
    ),
    "/plugin": _d(
        "Manage plugins that bundle skills, agents, hooks, and MCP configs.",
        "Teams share full environments as plugins instead of one-off configs.",
        "When extending Geocentric Code with reusable packages.",
        "Type /plugin — loads from ~/.geocentric/plugins/",
        "/plugin",
    ),
    "/reload-plugins": _d(
        "Refreshes plugin definitions without restarting the CLI.",
        "Pick up changes after editing plugin files.",
        "After adding or modifying a plugin.",
        "Type /reload-plugins.",
        "/reload-plugins",
    ),
    "/install-github-app": _d(
        "Guidance for connecting GitHub integration.",
        "Lets the agent read issues, PRs, and repo state live.",
        "When you want the agent to work with GitHub directly.",
        "Type /install-github-app, then follow web UI Settings → GitHub.",
        "/install-github-app",
    ),
    "/install-slack-app": _d(
        "Guidance for connecting Slack integration.",
        "Enables notifications and Slack-aware workflows.",
        "When integrating team chat with agent workflows.",
        "Type /install-slack-app.",
        "/install-slack-app",
    ),
    "/permissions": _d(
        "Shows the current tool permission mode (auto vs ask).",
        "Safety layer — controls how autonomous file edits and commands are.",
        "Before risky work, or when the agent is too aggressive or too passive.",
        "Type /permissions. Toggle autonomy with /agent on|off.",
        "/permissions",
    ),
    "/doctor": _d(
        "Diagnoses Python, server connectivity, venv, and dependency health.",
        "Catches environment problems before they waste your time mid-task.",
        "When the CLI won't connect, models fail to load, or after setup.",
        "Type /doctor.",
        "/doctor",
    ),
    "/debug": _d(
        "Prints runtime debug info: Python version, server URL, session ID, cwd.",
        "Support and troubleshooting snapshot.",
        "When filing /feedback or debugging connection/session issues.",
        "Type /debug.",
        "/debug",
    ),
    "/feedback": _d(
        "Guidance for sending bug reports with logs.",
        "Helps improve Geocentric Code with actionable reports.",
        "When something breaks or behaves unexpectedly.",
        "Type /feedback, include /debug output and log.txt.",
        "/feedback",
    ),
    "/bug": _d(
        "Alias for /feedback.",
        "Shorthand for bug reports.",
        "Same as /feedback.",
        "/bug",
    ),
    "/diff": _d(
        "Shows git diff --stat for current uncommitted changes.",
        "Quick sanity check before reviews or commits.",
        "Before /review, /security-review, or committing agent changes.",
        "Type /diff (requires git repo).",
        "/diff",
    ),
    "/review": _d(
        "Arms a code review pass on recent changes.",
        "Catches bugs, edge cases, and clarity issues before merge.",
        "After the agent edited files, or before opening a PR.",
        "Type /review, optionally describe scope on the next line.",
        "/review",
        "/review focus on error handling in auth module",
    ),
    "/security-review": _d(
        "Arms a security scan pass on the codebase.",
        "Finds auth flaws, injection, secrets exposure, unsafe defaults.",
        "Before shipping, after adding auth/API endpoints, or handling user input.",
        "Type /security-review, then describe scope if needed.",
        "/security-review",
    ),
    "/simplify": _d(
        "Arms a refactor-and-cleanup pass on scoped code.",
        "Reduces complexity, removes dead code, matches project patterns.",
        "When code works but is messy after a fast iteration.",
        "Type /simplify then describe files or area.",
        "/simplify clean up geocentric/interactive_cli.py",
    ),
    "/export": _d(
        "Exports the current session and messages to a JSON file.",
        "Backup, sharing, or offline review of a conversation.",
        "When you want a portable record of the session.",
        "Type /export — writes geocentric-export-<id>.json in cwd.",
        "/export",
    ),
    "/btw": _d(
        "Side-channel question that does NOT add to main conversation history.",
        "Prevents one-off questions from polluting context for the main task.",
        "Quick tangential question without derailing the current work thread.",
        "Type /btw what does this regex mean? then ask on the next line.",
        "/btw quick syntax question",
    ),
    "/voice": _d(
        "Voice dictation input (if supported by your OS).",
        "Hands-free input on supported platforms.",
        "When typing is inconvenient — or use OS dictation and paste.",
        "Type /voice for guidance.",
        "/voice",
    ),
    "/remote-control": _d(
        "Shows how to connect to this CLI from another device over WiFi.",
        "Run the agent on your Mac, control it from a laptop, iPad terminal, or SSH.",
        "When you want to code from bed/couch while models run on your desktop Mac.",
        "Type /remote-control for curl and SSH one-liners.",
        "/remote-control",
    ),
    "/teleport": _d(
        "Shows session ID for resuming on another machine.",
        "Move work between environments without losing state.",
        "When switching from Mac CLI to remote client or another computer.",
        "Type /teleport, note the session ID, then /resume <id> elsewhere.",
        "/teleport",
    ),
    "/skills": _d(
        "Lists installed custom skills (user-defined slash command workflows).",
        "Skills package reusable procedures from .claude/skills/<name>/SKILL.md.",
        "When you or your team added domain-specific workflows.",
        "Type /skills, then invoke with /skill-name.",
        "/skills",
    ),
    "/status": _d(
        "Shows session, model, mode, agent settings, and server connectivity.",
        "At-a-glance health check of your CLI state.",
        "Anytime you want to verify what's active.",
        "Type /status.",
        "/status",
    ),
    "/cost": _d(
        "Shows token usage and limits from the server.",
        "Track consumption against plan limits.",
        "When monitoring usage during long sessions.",
        "Type /cost or /usage.",
        "/cost",
    ),
    "/usage": _d(
        "Alias for /cost — token usage tracking.",
        "Same as /cost.",
        "When checking token consumption.",
        "/usage",
    ),
    "/login": _d(
        "Sign in for workspace sync and authenticated features.",
        "Links your CLI session to a Geocentric account.",
        "When using workspace agent mode with auth-required server.",
        "Type /login or /login email@example.com password",
        "/login",
    ),
    "/logout": _d(
        "Clears the stored auth token.",
        "Sign out of the current account on this CLI.",
        "When switching accounts or on a shared machine.",
        "Type /logout.",
        "/logout",
    ),
    "/mobile": _d(
        "Guidance for using Geocentric on a phone browser.",
        "Mobile access to the web UI on the same LAN.",
        "When away from your desk but on the same WiFi.",
        "Type /mobile.",
        "/mobile",
    ),
    "/desktop": _d(
        "Opens the Geocentric web UI in your default browser.",
        "GUI alternative to the terminal CLI.",
        "When you prefer visual chat or file widgets.",
        "Type /desktop.",
        "/desktop",
    ),
    "/upgrade": _d(
        "Info about plan upgrades.",
        "Higher tiers unlock more tokens and features.",
        "When hitting usage limits.",
        "Type /upgrade.",
        "/upgrade",
    ),
    "/passes": _d(
        "Info about sharing access passes.",
        "Team access management.",
        "When managing shared Geocentric access.",
        "Type /passes.",
        "/passes",
    ),
    "/server": _d(
        "Shows or sets the Geocentric server URL.",
        "The CLI talks to the server over HTTP for models and agent tools.",
        "When switching between localhost and a remote host.",
        "Type /server or /server http://192.168.1.30:8000",
        "/server",
        "/server http://127.0.0.1:8000",
    ),
    "/connect": _d(
        "Connects this CLI to a remote Geocentric server.",
        "Use models running on another machine (your Mac on WiFi).",
        "From a laptop/iPad when your Mac hosts the server.",
        "Type /connect http://192.168.1.30:8000",
        "/connect http://192.168.1.30:8000",
    ),
    "/models": _d(
        "Lists all models available on the connected server.",
        "See what's installed before switching with /model.",
        "When exploring available Ollama or local models.",
        "Type /models.",
        "/models",
    ),
    "/agent": _d(
        "Toggles workspace agent mode (autonomous edits and commands).",
        "Off = chat only; On = full tool-using coding agent.",
        "Turn on for implementation; off for questions and planning.",
        "Type /agent on or /agent off",
        "/agent on",
    ),
    "/search": _d(
        "Toggles web search for the agent.",
        "Lets the model fetch live web results for current events or docs.",
        "When you need up-to-date info beyond training data.",
        "Type /search on or /search off",
        "/search on",
    ),
}


def normalize_command_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    if not name:
        return ""
    if not name.startswith("/"):
        name = f"/{name}"
    return name


def lookup_command_doc(name: str, *, description: str = "", category: str = "") -> Optional[CommandDoc]:
    key = normalize_command_name(name)
    if not key:
        return None
    if key in COMMAND_DOCS:
        return COMMAND_DOCS[key]
    if description:
        return CommandDoc(
            what=description,
            why=f"Part of the {category or 'Geocentric Code'} command set.",
            when="When the task matches this command's purpose (see /help).",
            how=f"Type {key} — run /help for a one-line summary.",
        )
    return None


def explain_command(
    target: str,
    *,
    description: str = "",
    category: str = "",
    skill_path: str = "",
) -> Optional[CommandDoc]:
    key = normalize_command_name(target)
    if not key:
        return None

    doc = lookup_command_doc(key, description=description, category=category)
    if doc:
        return doc

    if skill_path or key.startswith("/"):
        skill_name = key.lstrip("/")
        return CommandDoc(
            what=f"Custom skill workflow: {key}",
            why="Skills are reusable instruction modules — domain expertise packaged as slash commands.",
            when=f"When you need the {skill_name} workflow defined in SKILL.md.",
            how=f"Type {key}, then describe your task on the next line. Install skills in .claude/skills/{skill_name}/SKILL.md",
            examples=(key, f"/whatisthis {key}"),
        )
    return None
