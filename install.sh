#!/usr/bin/env bash
#
# GigaAgent installer.
#
# Quick start:
#   curl -fsSL https://agent.giga.chat/install.sh | bash
#
# Pick an installation method (default: uv):
#   curl -fsSL .../install.sh | GIGA_AGENT_INSTALL=docker  bash
#   curl -fsSL .../install.sh | GIGA_AGENT_INSTALL=compose bash
#
# Environment variables:
#   GIGA_AGENT_INSTALL   uv | docker | compose        (default: uv)
#   GIGA_AGENT_VERSION   package / image version      (default: latest)
#   GIGA_AGENT_DIR       target dir for uv/compose    (default: ~/.giga-agent)
#   GIGA_AGENT_START     0 to skip auto-start after uv install (default: 1)
#   GIGA_AGENT_EXTRA     package extra for uv install (default: jupyter; "none" to skip)
#
set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
METHOD="${GIGA_AGENT_INSTALL:-uv}"
VERSION="${GIGA_AGENT_VERSION:-latest}"
INSTALL_DIR="${GIGA_AGENT_DIR:-$HOME/.giga-agent}"
AUTO_START="${GIGA_AGENT_START:-1}"
EXTRA="${GIGA_AGENT_EXTRA:-jupyter}"

IMAGE="ghcr.io/ai-forever/giga_agent"
REPO="https://github.com/ai-forever/giga_agent.git"
PY_VERSION="3.12"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  C_BLUE=$'\033[1;34m'; C_YELLOW=$'\033[1;33m'; C_RED=$'\033[1;31m'
  C_GREEN=$'\033[1;32m'; C_RESET=$'\033[0m'
else
  C_BLUE=""; C_YELLOW=""; C_RED=""; C_GREEN=""; C_RESET=""
fi

info() { printf '%s==>%s %s\n' "$C_BLUE" "$C_RESET" "$*"; }
ok()   { printf '%s[✓]%s %s\n' "$C_GREEN" "$C_RESET" "$*"; }
warn() { printf '%s[!]%s %s\n' "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%s[x]%s %s\n' "$C_RED" "$C_RESET" "$*" >&2; exit 1; }
have() { command -v "$1" >/dev/null 2>&1; }

# Build the pip requirement spec, honoring version + extra selection.
pkg_spec() {
  local name="giga-agent"
  if [ "$EXTRA" != "none" ] && [ -n "$EXTRA" ]; then
    name="giga-agent[$EXTRA]"
  fi
  if [ "$VERSION" = "latest" ]; then
    printf '%s' "$name"
  else
    printf '%s==%s' "$name" "$VERSION"
  fi
}

# Generate a random secret key without depending on openssl.
gen_secret() {
  if have openssl; then
    openssl rand -hex 32
  else
    LC_ALL=C tr -dc 'a-f0-9' < /dev/urandom | head -c 64
  fi
}

# ---------------------------------------------------------------------------
# Method: uv (easy, no Docker daemon required)
# ---------------------------------------------------------------------------
install_uv_method() {
  info "Installing GigaAgent via uv into $INSTALL_DIR"
  have curl || err "curl is required but was not found."

  if ! have uv; then
    info "uv not found — installing it..."
    curl -LsSf https://astral.sh/uv/install.sh | sh
    # uv's installer drops binaries in ~/.local/bin (or XDG bin).
    export PATH="$HOME/.local/bin:${XDG_BIN_HOME:-$HOME/.local/bin}:$PATH"
    have uv || err "uv installation finished but 'uv' is still not on PATH. Open a new shell and re-run."
    ok "uv installed."
  fi

  mkdir -p "$INSTALL_DIR"
  cd "$INSTALL_DIR"

  info "Ensuring Python $PY_VERSION is available..."
  uv python install "$PY_VERSION"

  info "Creating virtual environment (.venv)..."
  uv venv --python "$PY_VERSION" .venv

  info "Installing $(pkg_spec) (this can take a few minutes)..."
  # shellcheck disable=SC1091
  source .venv/bin/activate
  uv pip install "$(pkg_spec)"
  ok "GigaAgent installed in $INSTALL_DIR"

  if [ "$AUTO_START" != "0" ]; then
    info "Starting GigaAgent dev server on http://localhost:9090 (Ctrl-C to stop)..."
    print_first_run_notes
    exec giga_agent dev
  fi

  cat <<EOF

${C_GREEN}Done!${C_RESET} Auto-start disabled. To start GigaAgent:

    cd "$INSTALL_DIR"
    source .venv/bin/activate
    giga_agent dev

Then open ${C_BLUE}http://localhost:9090${C_RESET}
EOF
  print_first_run_notes
}

# ---------------------------------------------------------------------------
# Method: docker (easy, standalone image)
# ---------------------------------------------------------------------------
install_docker_method() {
  info "Running GigaAgent standalone Docker image"
  have docker || err "Docker is required. Install Docker Desktop/Engine, then re-run."
  docker info >/dev/null 2>&1 || err "Docker is installed but the daemon is not running. Start Docker and re-run."

  local tag="$VERSION"
  [ "$tag" = "latest" ] && tag="latest"

  info "Pulling $IMAGE:$tag ..."
  docker pull "$IMAGE:$tag"

  print_first_run_notes
  info "Starting container on http://localhost:9090 (Ctrl-C to stop)..."
  exec docker run --rm -it \
    -p 9090:9090 \
    -v giga-agent-data:/data/.giga_agent \
    "$IMAGE:$tag"
}

# ---------------------------------------------------------------------------
# Method: compose (full stack: nginx + Postgres + Redis + Qdrant)
# ---------------------------------------------------------------------------
install_compose_method() {
  info "Installing full stack via Docker Compose into $INSTALL_DIR"
  have docker || err "Docker is required. Install Docker Desktop/Engine, then re-run."
  docker info >/dev/null 2>&1 || err "Docker is installed but the daemon is not running. Start Docker and re-run."
  docker compose version >/dev/null 2>&1 || err "The Docker Compose v2 plugin is required ('docker compose')."
  have git || err "git is required for the compose method."

  if [ -d "$INSTALL_DIR/.git" ]; then
    info "Updating existing checkout in $INSTALL_DIR ..."
    git -C "$INSTALL_DIR" pull --ff-only || warn "Could not fast-forward; using existing checkout."
  else
    info "Cloning repository into $INSTALL_DIR ..."
    git clone --depth 1 "$REPO" "$INSTALL_DIR"
  fi
  cd "$INSTALL_DIR"

  if [ ! -f .env ]; then
    info "Creating .env with a generated secret key..."
    cp .env.example .env
    local secret; secret="$(gen_secret)"
    if grep -q '^GIGA_AGENT_SECRET_KEY=' .env; then
      # Portable in-place edit (GNU/BSD sed).
      sed "s|^GIGA_AGENT_SECRET_KEY=.*|GIGA_AGENT_SECRET_KEY=\"$secret\"|" .env > .env.tmp && mv .env.tmp .env
    else
      printf 'GIGA_AGENT_SECRET_KEY="%s"\n' "$secret" >> .env
    fi
    # local_docker sandbox needs the absolute project path.
    if grep -q '^GIGA_AGENT_HOST_PROJECT_PATH=' .env; then
      sed "s|^GIGA_AGENT_HOST_PROJECT_PATH=.*|GIGA_AGENT_HOST_PROJECT_PATH=\"$INSTALL_DIR\"|" .env > .env.tmp && mv .env.tmp .env
    fi
    ok "Wrote $INSTALL_DIR/.env"
  else
    info "Using existing .env"
  fi

  info "Building and starting containers (this can take a while on first run)..."
  docker compose up -d --build

  cat <<EOF

${C_GREEN}Done!${C_RESET} Full stack is starting.
Open ${C_BLUE}http://localhost:8123${C_RESET}

Manage it from $INSTALL_DIR:
    docker compose logs -f      # follow logs
    docker compose down         # stop
    docker compose up -d        # start again
EOF
  print_first_run_notes
}

# ---------------------------------------------------------------------------
# Shared notes
# ---------------------------------------------------------------------------
print_first_run_notes() {
  cat <<EOF

${C_YELLOW}First-run login${C_RESET} (created only when the database has no users):
    email:    admin@example.com
    password: giga_agent_admin

Before your first chat, open Settings and add a model connector,
then choose a language model. See the docs for details:
https://ai-forever.github.io/giga_agent/
EOF
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
  info "GigaAgent installer (method: $METHOD, version: $VERSION)"
  case "$METHOD" in
    uv)      install_uv_method ;;
    docker)  install_docker_method ;;
    compose) install_compose_method ;;
    *) err "Unknown GIGA_AGENT_INSTALL='$METHOD'. Use one of: uv | docker | compose." ;;
  esac
}

main "$@"
