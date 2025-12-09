#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.." || exit 1

PYTHON="${PYTHON:-python}"

# Allow disabling this step via GREEN_CHECK_AMI=false
if [ "${GREEN_CHECK_AMI:-true}" = "false" ]; then
  echo "[info] GREEN_CHECK_AMI=false -> skipping OSWorld AMI preflight."
  exit 0
fi

# If aws CLI is missing, show a warning and skip (do not fail)
if ! command -v aws >/dev/null 2>&1; then
  echo "[warn] 'aws' CLI not found; skipping OSWorld AMI preflight."
  exit 0
fi

# ---------- 1) Use Python to read IMAGE_ID_MAP and compute the target AMI ----------
eval "$("$PYTHON" - << 'PY'
import os, sys
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / "third_party" / "osworld"))

# Default values printed first so the shell always has them
print("AMI_CHECK_OK=false")
print('AMI_REASON="unknown"')

region = os.environ.get("AWS_REGION", "us-east-1")
screen = os.environ.get("SCREEN_SIZE", "1920x1080").lower()
try:
    w_str, h_str = screen.split("x")
    w, h = int(w_str), int(h_str)
except Exception:
    w, h = 1920, 1080

print(f'AMI_REGION="{region}"')
print(f'AMI_SCREEN="{w}x{h}"')

try:
    from desktop_env.providers.aws.manager import IMAGE_ID_MAP
except Exception:
    print('AMI_CHECK_OK=false')
    print('AMI_REASON="import_error_manager_image_id_map"')
    raise SystemExit(0)

ami = IMAGE_ID_MAP.get(region, {}).get((w, h))
if not ami:
    # There is no mapping for this region + screen combo
    print("AMI_CHECK_OK=false")
    print(f'AMI_REASON="no_mapping_for_region_{region}_screen_{w}x{h}"')
else:
    print("AMI_CHECK_OK=true")
    print('AMI_REASON="ok"')
    print(f'AMI_ID="{ami}"')
PY
)"

# ---------- 2) If we could not retrieve the AMI mapping, fail clearly ----------
if [ "${AMI_CHECK_OK}" != "true" ]; then
  echo "[FATAL] OSWorld IMAGE_ID_MAP appears misconfigured."
  echo "       Region : ${AMI_REGION}"
  echo "       Screen : ${AMI_SCREEN}"
  echo "       Reason : ${AMI_REASON}"
  echo "       Please edit third_party/osworld/desktop_env/providers/aws/manager.py"
  echo "       and ensure IMAGE_ID_MAP contains a public AMI for this region/screen."
  exit 3
fi

echo "[info] OSWorld IMAGE_ID_MAP -> region=${AMI_REGION} screen=${AMI_SCREEN} ami=${AMI_ID}"

# ---------- 3) Use aws ec2 describe-images to verify AMI visibility ----------
if ! CHECK_JSON="$(aws ec2 describe-images --image-ids "${AMI_ID}" --region "${AMI_REGION}" --output json 2>/dev/null)"; then
  echo "[FATAL] aws ec2 describe-images failed for AMI '${AMI_ID}' in region '${AMI_REGION}'."
  echo "       Please check your AWS credentials and region configuration."
  exit 4
fi

# The failure case you saw earlier: "Images": []
if echo "${CHECK_JSON}" | grep -q '"Images": \[\]'; then
  echo "[FATAL] OSWorld AMI '${AMI_ID}' in region '${AMI_REGION}' is not usable (Images=[])."
  echo "       This usually means the AMI is private or you are not authorized."
  echo "       For example, you encountered the 'ami-0b505e9d0d99ba88c' AuthFailure."
  echo "       Please switch IMAGE_ID_MAP back to a public AMI"
  echo "       (e.g. ami-0d23263edb96951d8) or request access from OSWorld maintainers."
  exit 5
fi

echo "[ok] OSWorld AMI '${AMI_ID}' in region '${AMI_REGION}' is visible to this AWS account."
