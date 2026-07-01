# Remote Terminal Access Setup Guide

## Overview
Geocentric now supports remote terminal access over local WiFi. You can control your Mac from Windows, Linux, or another Mac device and execute commands like `/ls`, `/cd`, `/pwd`, `/mkdir`, and `/shell`.

## Installation & Setup

### 1. Create Global Command Symlink (Mac/Linux)

```bash
# Make entry point script executable
chmod +x /path/to/geocentric-main/bin/geocentric

# Create symlink (macOS/Linux)
sudo ln -sf /path/to/geocentric-main/bin/geocentric /usr/local/bin/geocentric

# Verify
which geocentric
geocentric --version
```

**Windows:** The PATH is set automatically via `setx` when `ensure_entrypoint_on_path()` runs.

### 2. Start the Server

On your **Mac host**:

```bash
geocentric serve --host 0.0.0.0 --port 8000
```

The server now listens on all interfaces. Your Mac's IP will typically be:
- **Local WiFi IP**: Check with `ifconfig en0 | grep inet` (macOS) or `ipconfig` (Windows)
- **MDns (macOS only)**: `hostname.local` (e.g., `my-mac.local`)

### 3. Connect from Remote Device

From **Windows/Linux/another Mac**:

```bash
# Set the server address
geocentric /connect 192.168.1.100:8000
# or
geocentric /connect my-mac.local:8000

# Verify connection
geocentric /status
```

## New Remote Commands

Once connected, you can execute commands on the **remote Mac host**:

### `/ls [path]` — List directory
```
/ls
/ls /Users/you/Documents
```

### `/pwd` — Print working directory
```
/pwd
```

### `/cd [path]` — Change directory
```
/cd /Users/you/Documents
```

### `/mkdir [path]` — Create directory
```
/mkdir /Users/you/NewFolder
```

### `/shell [command]` — Execute arbitrary shell command
```
/shell echo "Hello from Mac"
/shell ls -la
/shell git status
```

All commands **preserve ANSI colors**, **support all standard characters**, and **work identically to local shell**.

## Server Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| POST | `/api/shell/execute` | Execute shell command with output |
| POST | `/api/shell/ls` | List directory with metadata |
| POST | `/api/shell/pwd` | Get current working directory |
| POST | `/api/shell/cd` | Change directory (persists for session) |
| POST | `/api/shell/mkdir` | Create directory recursively |

## Security Notes

- **Local Network Only**: Remote commands are available over local WiFi only
- **No Authentication Required**: Commands execute with the permissions of the Geocentric server process
- **Timeout**: Commands have a 30-second timeout to prevent hanging
- **Standard Shell**: Uses `/bin/sh` on macOS/Linux, `cmd.exe` on Windows

## Troubleshooting

### "Connection refused"
- Verify server is running: `geocentric serve --host 0.0.0.0`
- Check firewall: Port 8000 must be accessible on local network
- Verify IP address: Use `ipconfig` (Windows) or `ifconfig` (macOS)

### "Cannot execute command"
- Check user permissions: Server runs with current user's permissions
- Verify path exists: Use `/ls` first to confirm directories
- Check command syntax: Some shells differ between platforms

### Colors not showing
- Use `/shell` command which preserves ANSI codes
- Direct commands like `/ls` render output with emoji icons
