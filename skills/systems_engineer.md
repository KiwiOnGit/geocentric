# Systems Engineering & Linux Administration Skill

## Purpose
Use this skill when tasked with scripting Linux shell tasks, managing environment packages, checking processes, managing file boundaries, or running command center tasks.

## 1. Core Directives
1. **Defensive Shell Scripting**: Always set flags like `set -euo pipefail` inside bash scripts so they fail fast upon encountering any unset variables or errors.
2. **Process Auditing**: Do not spawn background commands blindly. Check active server processes, verify open ports, and ensure background loops have proper timeouts.
3. **Robust Resource Allocation**: Clean up temporary files, terminate dangling processes, and restrict directory write access to within bounds.

## 2. Structural Architecture
A systems script lifecycle should operate as follows:
```
[ 1. Validation ] -> Validate tools/binaries exists, path boundary isolation
         │
[ 2. Environment ] -> Load env, set secure permissions (e.g. chmod 700)
         │
[ 3. Execution ] -> Run commands, log stdout/stderr, trace return codes
         │
[ 4. Clean-up ] -> Terminate background jobs, purge temp caches
```

## 3. High-Quality Code Examples

### Secure Unix Script with Fail-Safe Checks
```bash
#!/usr/bin/env bash
set -euo pipefail

# Define secure script path
WORKSPACE_ROOT="$(pwd)"
LOG_DIR="${WORKSPACE_ROOT}/logs"
mkdir -p "${LOG_DIR}"

log_info() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S')] [INFO] $*" | tee -a "${LOG_DIR}/system.log"
}

log_error() {
    echo "[$(date +'%Y-%m-%dT%H:%M:%S')] [ERROR] $*" >&2 | tee -a "${LOG_DIR}/system.log"
}

# Failure handler
cleanup_on_failure() {
    log_error "Systems Task Failed on line $1. Purging temp session."
    rm -rf "${WORKSPACE_ROOT}/.tmp_session"
}
trap 'cleanup_on_failure $LINENO' ERR

log_info "Initiating systems audit..."
# Perform file/directory processing
# ...
log_info "Systems audit finished successfully."
```
