set -e

python - <<'PY'
import os
import time
import urllib.request

url = os.environ["GATEWAY_URL"] + "/health"

for _ in range(60):
    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status == 200:
                break
    except Exception:
        pass

    time.sleep(1)
else:
    raise SystemExit("Gateway is not ready")
PY

pytest -v