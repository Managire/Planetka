#!/usr/bin/env bash
set -euo pipefail

ROOT_S2="/Volumes/SSDA/Planetka Assets/S2"
BACKUP_S2="/Volumes/SSDA/S2-backup"
WORKDIR="/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka"
SECRETS_FILE="${HOME}/.planetka/secrets/Cloudflare_API_from_stash_2026-03-17.txt"
PROFILE="planetka-r2"
BUCKET="planetka-data"
PREFIX="planetka-assets/S2"

echo "[1/3] Backup S2 -> ${BACKUP_S2}"
mkdir -p "${BACKUP_S2}"
rsync -a --delete "${ROOT_S2}/" "${BACKUP_S2}/"
echo "[1/3] Backup complete"

echo "[2/3] Clamp z001_d001 and rebuild all higher z/d"
cd "${WORKDIR}"
python3 tools/s2_clamp_rebuild.py --root "${ROOT_S2}" --workers 4
echo "[2/3] Rebuild complete"

echo "[3/3] Upload S2 to Cloudflare R2"
ACCOUNT_ID="$(awk -F'=' '/R2_ACCOUNT_ID/{gsub(/ /,"",$2); print $2; exit}' "${SECRETS_FILE}")"
if [[ -z "${ACCOUNT_ID}" ]]; then
  echo "Failed to read R2_ACCOUNT_ID from ${SECRETS_FILE}" >&2
  exit 1
fi
ENDPOINT_URL="https://${ACCOUNT_ID}.r2.cloudflarestorage.com"

aws s3 sync "${ROOT_S2}/" "s3://${BUCKET}/${PREFIX}/" \
  --profile "${PROFILE}" \
  --endpoint-url "${ENDPOINT_URL}" \
  --delete \
  --exclude "*" \
  --include "*.exr" \
  --include "*.EXR"

echo "[3/3] Upload complete"
echo "All steps completed successfully."

