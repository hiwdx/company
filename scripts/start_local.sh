#!/bin/sh
set -eu
cd "$(dirname "$0")/.."
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-local-results/pycache}"
exec python3 -m hiwd_company serve --port 18768 "$@"
