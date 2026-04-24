#!/usr/bin/env bash
set -euo pipefail

# Upload Planetka texture dataset to Cloud R2 (image files only).
# Default mode is preflight. Use --run to execute sync.

PROFILE="${PROFILE:-planetka-r2}"
SOURCE_DIR="${SOURCE_DIR:-/Volumes/SSDA/Planetka Assets}"
BUCKET="${BUCKET:-planetka-data}"
PREFIX="${PREFIX:-planetka-assets}"
SECRETS_FILE="${SECRETS_FILE:-$HOME/.planetka/secrets/Cloudflare_API_from_stash_2026-03-17.txt}"
RUN_UPLOAD=0

SYNC_FILTERS=(
  --exclude "*"
  --include "*.exr"
  --include "*.EXR"
  --include "*.tif"
  --include "*.TIF"
  --include "*.tiff"
  --include "*.TIFF"
  --include "*.png"
  --include "*.PNG"
  --include "*.jpg"
  --include "*.JPG"
  --include "*.jpeg"
  --include "*.JPEG"
  --include "*.webp"
  --include "*.WEBP"
)

usage() {
  cat <<'EOF'
Usage:
  tools/r2_upload_planetka_assets.sh [--run] [--prefix <prefix>] [--source <path>] [--bucket <bucket>] [--profile <aws-profile>]

Examples:
  tools/r2_upload_planetka_assets.sh
  tools/r2_upload_planetka_assets.sh --run --prefix planetka-assets

Environment overrides:
  PROFILE, SOURCE_DIR, BUCKET, PREFIX, SECRETS_FILE
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --run)
      RUN_UPLOAD=1
      shift
      ;;
    --prefix)
      PREFIX="$2"
      shift 2
      ;;
    --source)
      SOURCE_DIR="$2"
      shift 2
      ;;
    --bucket)
      BUCKET="$2"
      shift 2
      ;;
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: aws CLI not found." >&2
  exit 1
fi

if [[ ! -d "$SOURCE_DIR" ]]; then
  echo "ERROR: source directory not found: $SOURCE_DIR" >&2
  exit 1
fi

if [[ ! -f "$SECRETS_FILE" ]]; then
  echo "ERROR: secrets file not found: $SECRETS_FILE" >&2
  exit 1
fi

ACCOUNT_ID="$(awk -F'=' '/R2_ACCOUNT_ID/{gsub(/ /,"",$2); print $2; exit}' "$SECRETS_FILE")"
if [[ -z "$ACCOUNT_ID" ]]; then
  echo "ERROR: failed to parse R2_ACCOUNT_ID from $SECRETS_FILE" >&2
  exit 1
fi
ENDPOINT_URL="https://${ACCOUNT_ID}.r2.cloudflarestorage.com"

echo "=== Planetka R2 Upload Preflight ==="
echo "Profile:        $PROFILE"
echo "Source:         $SOURCE_DIR"
echo "Bucket:         $BUCKET"
echo "Prefix:         $PREFIX"
echo "Endpoint:       $ENDPOINT_URL"
echo

echo "Checking R2 access..."
aws s3 ls "s3://${BUCKET}" --profile "$PROFILE" --endpoint-url "$ENDPOINT_URL" >/dev/null
echo "R2 access OK."
echo

echo "Computing local image dataset size (this may take a while)..."
FILE_COUNT="$(
  find "$SOURCE_DIR" -type f \
    \( -iname "*.exr" -o -iname "*.tif" -o -iname "*.tiff" -o -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.webp" \) \
    | wc -l | awk '{print $1}'
)"
SIZE_BYTES="$(
  find "$SOURCE_DIR" -type f \
    \( -iname "*.exr" -o -iname "*.tif" -o -iname "*.tiff" -o -iname "*.png" -o -iname "*.jpg" -o -iname "*.jpeg" -o -iname "*.webp" \) \
    -print0 \
    | xargs -0 stat -f%z \
    | awk '{sum += $1} END {print sum+0}'
)"
SIZE_GB="$(awk -v b="$SIZE_BYTES" 'BEGIN{printf "%.2f", b/1000000000}')"
echo "Image files:    $FILE_COUNT"
echo "Image size:     ${SIZE_GB} GB"
echo "Filter:         upload only image files (exr/tif/tiff/png/jpg/jpeg/webp)"
echo

echo "Current remote prefix summary:"
aws s3 ls "s3://${BUCKET}/${PREFIX}/" --recursive --summarize --profile "$PROFILE" --endpoint-url "$ENDPOINT_URL" | tail -n 5 || true
echo

if [[ "$RUN_UPLOAD" -eq 0 ]]; then
  echo "Preflight complete. No upload performed."
  echo "When ready, run:"
  echo "  tools/r2_upload_planetka_assets.sh --run --prefix ${PREFIX}"
  exit 0
fi

echo "Starting upload..."
aws s3 sync "${SOURCE_DIR}/" "s3://${BUCKET}/${PREFIX}/" \
  --profile "$PROFILE" \
  --endpoint-url "$ENDPOINT_URL" \
  "${SYNC_FILTERS[@]}"

echo
echo "Upload finished. Remote summary:"
aws s3 ls "s3://${BUCKET}/${PREFIX}/" --recursive --summarize --profile "$PROFILE" --endpoint-url "$ENDPOINT_URL" | tail -n 5
