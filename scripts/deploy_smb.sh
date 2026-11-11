#!/usr/bin/env bash
# Push custom_components/eac_cyprus/ to a Home Assistant Samba share.
# Reads HA_HOST / HA_SMB_USER / HA_SMB_PASS from .env (gitignored).

set +x  # Never trace sourced credentials or auth-file construction.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi

: "${HA_HOST:?set HA_HOST in .env (e.g. 192.168.1.32)}"
: "${HA_SMB_USER:?set HA_SMB_USER in .env (e.g. homeassistant)}"
: "${HA_SMB_PASS:?set HA_SMB_PASS in .env}"
HA_SMB_WORKGROUP="${HA_SMB_WORKGROUP:-WORKGROUP}"
HA_SMB_SHARE="${HA_SMB_SHARE:-config}"

cd "$ROOT/custom_components/eac_cyprus"

umask 077
SCRIPT=$(mktemp)
AUTH_FILE=""
LOG_FILE=""
trap 'rm -f "$SCRIPT" "$AUTH_FILE" "$LOG_FILE"' EXIT
AUTH_FILE=$(mktemp)
LOG_FILE=$(mktemp)
# smbclient auth-file syntax is line based. Reject newlines before writing it.
for value in "$HA_SMB_USER" "$HA_SMB_PASS" "$HA_SMB_WORKGROUP"; do
  case "$value" in *$'\n'*|*$'\r'*) echo "Invalid multiline SMB credential" >&2; exit 1;; esac
done
printf 'username = %s\npassword = %s\ndomain = %s\n' \
  "$HA_SMB_USER" "$HA_SMB_PASS" "$HA_SMB_WORKGROUP" > "$AUTH_FILE"
unset HA_SMB_PASS

{
  echo "cd custom_components"
  echo "mkdir eac_cyprus"
  echo "cd eac_cyprus"
  echo "lcd ."
  for f in *.py *.json *.yaml; do echo "put $f"; done
  echo "mkdir translations"
  echo "cd translations"
  echo "lcd translations"
  for f in translations/*.json; do echo "put $(basename "$f")"; done
  echo "cd .."
  echo "lcd .."
  echo "mkdir brand"
  echo "cd brand"
  echo "lcd brand"
  for f in brand/*.png; do echo "put $(basename "$f")"; done
} > "$SCRIPT"

if ! smbclient "//$HA_HOST/$HA_SMB_SHARE" -A "$AUTH_FILE" < "$SCRIPT" > "$LOG_FILE" 2>&1; then
  echo "SMB upload failed; check the share and credentials. HA was not restarted." >&2
  exit 1
fi
# Interactive smbclient can exit zero after an individual command fails.
# Existing directories are expected; every other reported SMB failure is fatal.
if awk '/NT_STATUS_/ && !/NT_STATUS_OBJECT_NAME_COLLISION.*making remote directory/ {bad=1} END {exit !bad}' "$LOG_FILE"; then
  echo "SMB command failed; deployment may be incomplete. HA was not restarted." >&2
  exit 1
fi

echo "deployed to //$HA_HOST/$HA_SMB_SHARE/custom_components/eac_cyprus/"
echo "now restart HA: Settings → System → Restart  (or 'ha core restart' via SSH)"
