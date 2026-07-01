#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/KiwiOnGit/geocentric"
INSTALL_ROOT="${GEOCENTRIC_INSTALL_ROOT:-$HOME/.geocentric}"
BIN_DIR=""

if command -v brew >/dev/null 2>&1; then
  BIN_DIR="$(brew --prefix)/bin"
elif [ -d "$HOME/.local/bin" ]; then
  BIN_DIR="$HOME/.local/bin"
else
  BIN_DIR="/usr/local/bin"
fi

log() { printf '\n[%s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '\n[ERROR] %s\n' "$*" >&2; exit 1; }

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    fail "Required command '$1' was not found. Please install it and retry."
  fi
}

choose_bin_dir() {
  if [ -w "$BIN_DIR" ]; then
    mkdir -p "$BIN_DIR"
    return 0
  fi
  mkdir -p "$HOME/.local/bin"
  BIN_DIR="$HOME/.local/bin"
}

ensure_path_entry() {
  local target_dir="$1"
  case ":$PATH:" in
    *":$target_dir:"*) return 0 ;;
  esac
  export PATH="$target_dir:$PATH"
  local rc_file="$HOME/.zshrc"
  if [ ! -f "$rc_file" ]; then
    rc_file="$HOME/.bashrc"
  fi
  if [ -f "$rc_file" ]; then
    grep -Fq "export PATH=\"$target_dir:\$PATH\"" "$rc_file" 2>/dev/null || echo "export PATH=\"$target_dir:\$PATH\"" >> "$rc_file"
  else
    echo "export PATH=\"$target_dir:\$PATH\"" >> "$HOME/.zshrc"
  fi
}

print_banner() {
  cat <<'ASCII'
            .-"""-.
          .'  .--.  '.
         /   /    \   \
        |   |  o  |   |
         \   \    /   /
          '._`--'_.-'
         .-'  .-  '-.
        /   .'   '.  \
       /   /  .-. \   \
      |   |  (   )|   |
       \   \  `-' /   /
        '._`-.__.'_.-'
      .-"""-.  .-"""-.
     /  .--.\/  .--.  \
    /  /    /  /    \  \
   |  |    |  |    |  |
    \  \    \  \    /  /
     '._`-._`-._`-._.'
ASCII
  printf '\n%s\n' "Geocentric installed successfully."
}

main() {
  require_cmd git
  require_cmd curl
  choose_bin_dir
  log "Installing Geocentric into $INSTALL_ROOT"
  rm -rf "$INSTALL_ROOT"
  mkdir -p "$INSTALL_ROOT"
  git clone --depth 1 "$REPO_URL" "$INSTALL_ROOT" || fail "Clone failed."
  cd "$INSTALL_ROOT"
  if [ -f requirements.txt ]; then
    python3 -m pip install --user -r requirements.txt >/dev/null 2>&1 || true
  fi
  ln -sf "$INSTALL_ROOT/run.sh" "$BIN_DIR/geocentric" 2>/dev/null || true
  if [ ! -x "$BIN_DIR/geocentric" ]; then
    printf '#!/usr/bin/env bash\nexec "%s/run.sh" "$@"\n' "$INSTALL_ROOT" > "$BIN_DIR/geocentric"
    chmod +x "$BIN_DIR/geocentric"
  fi
  ensure_path_entry "$BIN_DIR"
  hash -r 2>/dev/null || true
  clear
  print_banner
  printf '\nInstalled binary: %s\n' "$BIN_DIR/geocentric"
  printf 'Run: geocentric\n'
}

main "$@"
