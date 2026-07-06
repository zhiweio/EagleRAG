#!/usr/bin/env bash
# Retry ``uv sync`` for flaky GitHub HTTPS during image builds (git deps).
# Optional ``GITHUB_PROXY`` rewrites https://github.com/ URLs (e.g. ghfast mirror).
set -euo pipefail

if [[ -n "${GITHUB_PROXY:-}" ]]; then
  echo "Configuring git GitHub mirror prefix: ${GITHUB_PROXY}" >&2
  git config --global url."${GITHUB_PROXY}https://github.com/".insteadOf "https://github.com/"
fi

attempts="${UV_SYNC_RETRIES:-5}"
delay="${UV_SYNC_RETRY_DELAY:-15}"

for ((i = 1; i <= attempts; i++)); do
  if uv sync --frozen --no-dev --no-install-project "$@"; then
    exit 0
  fi
  if (( i == attempts )); then
    echo "uv sync failed after ${attempts} attempts" >&2
    exit 1
  fi
  echo "uv sync attempt ${i}/${attempts} failed; retrying in ${delay}s..." >&2
  sleep "${delay}"
done
