# tools.md - Sandbox Capabilities

## Quick Cheat Sheet

### 1. Web Tools
- `<search>query</search>` (Real-time duckduckgo search)
- `<image_search>query</image_search>` (Bing visual search)

Use web tools for current factual questions. If the user explicitly asks to search, browse, look up, find news, or answer with latest/current/recent information, use `<search>` before answering. Do not turn a movie/news/release lookup into workspace file creation unless the user explicitly asks for a script, app, game, or other artifact.
In agent/workspace mode, emit a specific `<status>...</status>` immediately before every web or workspace tool call.

### 2. Workspace File Operations
- `<write_file filename="path">content</write_file>` (Write file)
- `<read_file filename="path" />` (Read file content)
- `<delete_file filename="path" />` (Delete file)
- `<list_directory path="." />` (List a workspace directory)
- `<stat_path path="path" />` (Inspect file/directory metadata)
- `<make_directory path="path" />` (Create a workspace directory)
- `<copy_file from="source" to="dest" />` (Copy a file inside the workspace)
- `<move_file from="source" to="dest" />` (Move/rename a workspace path)
- `<download_url url="https://example.com/file" file="downloads/file" />` (Download a URL into the workspace with size limits)
- `<run_file filename="path.py" />` (Execute python script)
- `<run_command>shell command</run_command>` (Execute UNIX command)
- `<view_project_tree />` (Inspect the workspace tree before broad edits)

For multi-file builds, create a real folder first with `<make_directory path="project-name" />`, then write files into that folder and verify them with a command or terminal run. Do not paste whole projects into the final chat answer when the user asked you to build files.
Download links must be relative server links such as `/api/download/{chat_id}/path/to/file`. Never include session tokens, bearer tokens, hostnames, or query-string auth in a link.

### 3. Line Editor
```xml
<edit_file filename="path">
  <insert line="N">content</insert>
  <delete line="N" />
  <replace line="N">content</replace>
</edit_file>
```

### 4. Interactive Terminal
```xml
<agent_terminal command="python game.py" timeout="20">
  <input>50
25
37
</input>
</agent_terminal>
```

Use this when a script needs `input()`, menu choices, confirmations, or any other stdin.

### 5. Background Apps and Visual Checks
- `<run_bg_command>python app.py</run_bg_command>` (Start a long-lived app without blocking)
- `<check_process pid="1234" />` (Read recent process logs and status)
- `<kill_process pid="1234" />` (Stop a background process)
- `<capture_view url="http://localhost:5000" file="screenshot.png" />` (Take a browser screenshot into the workspace)
- `<port_check host="127.0.0.1" port="5000" />` (Check whether a port is open)
- `<http_request url="http://127.0.0.1:5000/health" method="GET" />` (Call a local route and inspect the response)

### 6. Project Planning and System Inspection
- `<update_roadmap>markdown checklist</update_roadmap>` (Update `agents.md` `## Current Roadmap`)
- `<install_package name="flask" type="pip" />` (Install Python dependency)
- `<install_package name="vite" type="npm" />` (Install npm dependency)
- `<system_info />` (Inspect OS, Python, CPU, memory, and disk)
- `<list_processes />` (List owned processes for this workspace plus useful local dev processes)

### 7. Review and Diff Expectations
- The desktop app can show an implementation plan before tool execution, staged context files, a context usage ring, system telemetry, and red/green file diffs after edits.
- Keep file edits small and clear so the diff viewport remains useful.
- For risky multi-file work, prefer a temporary branch/worktree or folder and summarize only the verified result back to the parent task.
