#!/bin/sh
set -e

HOST=${1:-http://gateway:8080}

mkdir -p load/results

# Вспомогательная функция для управления задержкой orders.
set_orders_delay() {
  python - "$HOST" "$1" <<'PY'
import json
import sys
import urllib.request

host, delay_ms = sys.argv[1], int(sys.argv[2])

payload = json.dumps({"delay_ms": delay_ms}).encode("utf-8")

request = urllib.request.Request(
    host + "/api/orders/_control",
    data=payload,
    headers={"Content-Type": "application/json"},
    method="POST",
)

with urllib.request.urlopen(request, timeout=5) as response:
    print(response.read().decode("utf-8"))
PY
}

echo "Running baseline load"
locust \
  -f load/locustfile.py \
  --headless \
  --users 300 \
  --spawn-rate 50 \
  --run-time 30s \
  --host "$HOST" \
  --csv load/results/baseline

echo "Degrading orders to 10 seconds"
set_orders_delay 10000

sleep 2

echo "Running degraded load"
locust \
  -f load/locustfile.py \
  --headless \
  --users 300 \
  --spawn-rate 50 \
  --run-time 60s \
  --host "$HOST" \
  --csv load/results/degraded

echo "Restoring orders delay"
set_orders_delay 10

echo "Load test finished"