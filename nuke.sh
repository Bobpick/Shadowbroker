#!/usr/bin/env bash
# Compatibility wrapper — implementation lives in scripts/operator/
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/scripts/operator/nuke.sh" "$@"
