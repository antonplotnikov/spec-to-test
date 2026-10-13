#!/bin/bash
# Start Spec-to-Test in its own window (see desktop.py).
#
# Used by Spec-to-Test.app (see build_app.sh); it can also be run by hand.
# On the first run it creates .venv and installs requirements-desktop.txt
# (plus requirements-ai.txt when .env enables the Anthropic provider). When
# Node.js is installed it also sets up the Automation tab: the Python extras
# (requirements-automation.txt) and the Playwright toolchain (automation/runner).
#
# Usage: macos/start.sh [--setup-only]
set -euo pipefail

# Apps start with a minimal PATH; add the usual Homebrew/python.org locations.
export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/Current/bin:$PATH"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"
LOG_FILE="$HOME/Library/Logs/Spec-to-Test/server.log"
mkdir -p "$(dirname "$LOG_FILE")"

fail() {
    echo "$1" >&2
    osascript -e 'on run argv' -e 'display alert "Spec-to-Test could not start" message (item 1 of argv) as critical' -e 'end run' "$1" >/dev/null 2>&1 || true
    exit 1
}

notify() {
    osascript -e "display notification \"$1\" with title \"Spec-to-Test\"" >/dev/null 2>&1 || true
}

# First run (or new dependencies): set up the virtual environment.
if ! "$VENV/bin/python" -c 'import streamlit, webview' >/dev/null 2>&1; then
    if [[ ! -x "$VENV/bin/python" ]]; then
        python=""
        for candidate in python3.13 python3.12 python3.11 python3; do
            if command -v "$candidate" >/dev/null 2>&1 &&
                "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
                python="$candidate"
                break
            fi
        done
        [[ -n "$python" ]] || fail "Python 3.11 or newer was not found. Install it from python.org or with 'brew install python@3.12'."
        "$python" -m venv "$VENV" >>"$LOG_FILE" 2>&1 || fail "Could not create $VENV. See $LOG_FILE"
    fi
    notify "Installing dependencies (about a minute)…"
    {
        "$VENV/bin/python" -m pip install --upgrade pip &&
            "$VENV/bin/python" -m pip install -r "$ROOT/requirements-desktop.txt"
    } >>"$LOG_FILE" 2>&1 || fail "Installing dependencies failed. See $LOG_FILE"
fi

# Optional AI features: install the SDKs only when .env asks for a provider that needs one
# (Ollama is called over plain HTTP and needs none).
if [[ -f "$ROOT/.env" ]] && grep -Eq '^[[:space:]]*AI_PROVIDER[[:space:]]*=[[:space:]]*"?(anthropic|claude|openai)' "$ROOT/.env" &&
    ! "$VENV/bin/python" -c 'import anthropic, openai' >/dev/null 2>&1; then
    "$VENV/bin/python" -m pip install -r "$ROOT/requirements-ai.txt" >>"$LOG_FILE" 2>&1 || true
fi

# Automation tab: needs Node.js. Apps opened from Finder have a minimal PATH,
# so also look where nvm and Homebrew put it (build_app.sh records the path).
find_node() {
    if [[ -n "${SPEC_TO_TEST_NODE:-}" && -x "$SPEC_TO_TEST_NODE" ]]; then
        echo "$SPEC_TO_TEST_NODE"
        return
    fi
    command -v node 2>/dev/null && return
    ls -1d "$HOME"/.nvm/versions/node/v*/bin/node 2>/dev/null | sort -V | tail -1
}
node_bin="$(find_node || true)"
if [[ -n "$node_bin" ]]; then
    export SPEC_TO_TEST_NODE="$node_bin"
    if ! "$VENV/bin/python" -c 'import mcp, anthropic' >/dev/null 2>&1; then
        notify "Installing Automation components…"
        "$VENV/bin/python" -m pip install -r "$ROOT/requirements-automation.txt" >>"$LOG_FILE" 2>&1 ||
            echo "Automation: Python extras could not be installed (the tab will say what is missing)." >>"$LOG_FILE"
    fi
    runner="$ROOT/automation/runner"
    if [[ ! -f "$runner/node_modules/@playwright/mcp/cli.js" || ! -f "$runner/node_modules/@playwright/test/cli.js" ]]; then
        notify "Installing the Playwright toolchain…"
        (
            cd "$runner" &&
                export PATH="$(dirname "$node_bin"):$PATH" &&
                npm ci --ignore-scripts --no-audit --no-fund &&
                npx playwright install chromium
        ) >>"$LOG_FILE" 2>&1 ||
            echo "Automation: the Playwright toolchain could not be installed (the tab will say what is missing)." >>"$LOG_FILE"
    fi
fi

[[ "${1:-}" == "--setup-only" ]] && exit 0

# Inside the app, use the bundle's copy of the interpreter so macOS shows the
# process as Spec-to-Test (Dock icon, name, single instance). It runs the venv
# via __PYVENV_LAUNCHER__, like the python.org/Homebrew launcher does.
if [[ -n "${SPEC_TO_TEST_PYTHON:-}" ]] &&
    __PYVENV_LAUNCHER__="$VENV/bin/python" "$SPEC_TO_TEST_PYTHON" -c 'import streamlit, webview' >/dev/null 2>&1; then
    export __PYVENV_LAUNCHER__="$VENV/bin/python"
    exec "$SPEC_TO_TEST_PYTHON" "$ROOT/macos/desktop.py"
fi
exec "$VENV/bin/python" "$ROOT/macos/desktop.py"
