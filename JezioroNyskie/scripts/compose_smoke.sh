#!/usr/bin/env bash
# Test dymny docker compose: buduje i uruchamia całość, sprawdza front, proxy /api i fallback SPA, sprząta.
# Kod wyjścia != 0 przy każdym błędzie. Wymaga wolnego portu 8080.
set -euo pipefail
cd "$(dirname "$0")/.."

cleanup() { docker compose down >/dev/null 2>&1 || true; }
trap cleanup EXIT

if lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "FAIL: port 8080 jest zajęty" >&2; exit 1
fi

docker compose up -d --build

# czekamy (<= 120 s) na zdrowy backend
healthy=""
for _ in $(seq 1 60); do
  id=$(docker compose ps -q backend)
  st=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo none)
  if [ "$st" = "healthy" ]; then healthy=1; break; fi
  sleep 2
done
[ -n "$healthy" ] || { echo "FAIL: backend nie jest zdrowy po 120 s" >&2; docker compose logs backend | tail -30 >&2; exit 1; }

curl -fs localhost:8080/ | grep -q 'lang="pl"' || { echo "FAIL: / bez lang=\"pl\"" >&2; exit 1; }
curl -fs localhost:8080/api/meta | grep -q '"n_scenes"' || { echo "FAIL: /api/meta bez n_scenes" >&2; exit 1; }
code=$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/historia)
[ "$code" = "200" ] || { echo "FAIL: /historia -> $code" >&2; exit 1; }
echo "PASS: compose smoke"
