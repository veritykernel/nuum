#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

usage() {
  echo "Usage: $0 --scenario path/to/scenario.json [--artifacts-dir DIR] [--state-path FILE] [--print-summary]" >&2
}

SCENARIO=""
ARTIFACTS_DIR=""
STATE_PATH=""
PRINT_SUMMARY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --scenario)
      SCENARIO="$2"
      shift 2
      ;;
    --artifacts-dir)
      ARTIFACTS_DIR="$2"
      shift 2
      ;;
    --state-path)
      STATE_PATH="$2"
      shift 2
      ;;
    --print-summary)
      PRINT_SUMMARY=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown arg: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "${SCENARIO}" ]]; then
  echo "Missing --scenario" >&2
  usage
  exit 1
fi

PYTHONPATH="${ROOT_DIR}/python:${PYTHONPATH:-}"
export PYTHONPATH

CMD=(python3 -m nuum.backtest.cli_runner --scenario "${SCENARIO}")
if [[ -n "${ARTIFACTS_DIR}" ]]; then
  CMD+=(--artifacts-dir "${ARTIFACTS_DIR}")
fi
if [[ -n "${STATE_PATH}" ]]; then
  CMD+=(--state-path "${STATE_PATH}")
fi
if [[ "${PRINT_SUMMARY}" -eq 1 ]]; then
  CMD+=(--print-summary)
fi

exec "${CMD[@]}"
