#!/bin/zsh
set -u

ROOT_DIR="/Users/tomasgriger/Library/Application Support/Blender/5.0/extensions/user_default/Planetka"
SCRIPT_PATH="$ROOT_DIR/tools/planetka_multiversion_stress_case.py"
RENDER_DIR="/Volumes/SSDA/Renders"
LOG_DIR="$RENDER_DIR/stress_logs"
SUITE_TS="$(date +%Y%m%d_%H%M%S)"
SUITE_LOG="$LOG_DIR/planetka_multiversion_suite_${SUITE_TS}.log"
SUITE_STATUS="$LOG_DIR/planetka_multiversion_suite_${SUITE_TS}.tsv"
API_KEY_FILE="/tmp/planetka_api_key.txt"

mkdir -p "$LOG_DIR"

if [[ ! -f "$API_KEY_FILE" ]]; then
  echo "Missing API key file: $API_KEY_FILE" | tee -a "$SUITE_LOG"
  exit 1
fi

API_KEY="$(cat "$API_KEY_FILE")"
if [[ -z "$API_KEY" ]]; then
  echo "API key is empty." | tee -a "$SUITE_LOG"
  exit 1
fi

echo -e "run_tag\tblender\tengine\tradius\tstatus\treport\tlog" > "$SUITE_STATUS"
echo "[SUITE] started at $(date -Iseconds)" | tee -a "$SUITE_LOG"
echo "[SUITE] status file: $SUITE_STATUS" | tee -a "$SUITE_LOG"

get_blender_bin() {
  case "$1" in
    "4_5") echo "/Applications/Blender4.5.app/Contents/MacOS/Blender" ;;
    "5_0") echo "/Applications/Blender5.0.app/Contents/MacOS/Blender" ;;
    "5_1") echo "/Applications/Blender5.1.app/Contents/MacOS/Blender" ;;
    "5_2") echo "/Applications/Blender5.2.app/Contents/MacOS/Blender" ;;
    *) echo "" ;;
  esac
}

versions=("4_5" "5_0" "5_1" "5_2")
engines=("EEVEE" "CYCLES")
radii=("2" "6000")

run_index=0
for version in "${versions[@]}"; do
  blender_bin="$(get_blender_bin "$version")"
  if [[ ! -x "$blender_bin" ]]; then
    echo "[SUITE] missing Blender binary for $version: $blender_bin" | tee -a "$SUITE_LOG"
    continue
  fi

  for radius in "${radii[@]}"; do
    for engine in "${engines[@]}"; do
      run_index=$((run_index + 1))
      seed=$((20260408 + run_index))
      run_tag="b${version}_r${radius}_${engine:l}_${SUITE_TS}"
      run_log="$LOG_DIR/${run_tag}.log"
      report_path="$RENDER_DIR/planetka_multiversion_stress_report_${run_tag}.json"
      echo "[SUITE] run=$run_index tag=$run_tag blender=$version engine=$engine radius=$radius seed=$seed" | tee -a "$SUITE_LOG"

      (
        cd "$ROOT_DIR" || exit 1
        PLANETKA_AUTH_API_KEY="$API_KEY" \
        PLANETKA_RENDER_DIR="$RENDER_DIR" \
        PLANETKA_RANDOM_PLACE_COUNT=100 \
        PLANETKA_STRESS_SEED="$seed" \
        PLANETKA_RENDER_ENGINE="$engine" \
        PLANETKA_EARTH_RADIUS_BU="$radius" \
        PLANETKA_RUN_TAG="$run_tag" \
        PLANETKA_TEXTURE_BASE_PATH="planetka-remote" \
        "$blender_bin" --background --factory-startup --python "$SCRIPT_PATH"
      ) > "$run_log" 2>&1
      exit_code=$?

      if [[ $exit_code -eq 0 ]]; then
        status="PASS"
      else
        status="FAIL($exit_code)"
      fi
      echo -e "${run_tag}\t${version}\t${engine}\t${radius}\t${status}\t${report_path}\t${run_log}" >> "$SUITE_STATUS"
      echo "[SUITE] done tag=$run_tag status=$status" | tee -a "$SUITE_LOG"
    done
  done
done

echo "[SUITE] finished at $(date -Iseconds)" | tee -a "$SUITE_LOG"
echo "[SUITE] summary: $SUITE_STATUS" | tee -a "$SUITE_LOG"
