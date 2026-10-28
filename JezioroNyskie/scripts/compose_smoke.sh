#!/usr/bin/env bash
# Test dymny docker compose: buduje i uruchamia całość, sprawdza front, proxy /api i fallback SPA, sprząta.
# Kod wyjścia != 0 przy każdym błędzie. Wymaga wolnego portu 8080 (własny działający stos projektu nie jest ruszany).
set -euo pipefail
cd "$(dirname "$0")/.."

fail() { echo "FAIL: $*" >&2; exit 1; }

# czy 8080 jest zajęty? lsof, a gdy go brak: próba połączenia przez bash
port_busy() {
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:8080 -sTCP:LISTEN >/dev/null 2>&1
  else
    (exec 3<>/dev/tcp/127.0.0.1/8080) >/dev/null 2>&1
  fi
}

if port_busy; then
  if [ -n "$(docker compose ps -q frontend 2>/dev/null)" ]; then
    fail "port 8080 zajmuje już działający stos tego projektu; zatrzymaj go ręcznie (docker compose down) - skrypt go nie rusza"
  fi
  fail "port 8080 jest zajęty przez inny proces"
fi

# od tej chwili stos jest nasz, więc sprzątamy go przy wyjściu
trap 'docker compose down >/dev/null 2>&1 || true' EXIT
docker compose up -d --build

# czekamy (<= 120 s) na zdrowy backend
healthy=""
for _ in $(seq 1 60); do
  id=$(docker compose ps -q backend)
  st=$(docker inspect -f '{{.State.Health.Status}}' "$id" 2>/dev/null || echo none)
  if [ "$st" = "healthy" ]; then healthy=1; break; fi
  sleep 2
done
if [ -z "$healthy" ]; then docker compose logs backend | tail -30 >&2; fail "backend nie jest zdrowy po 120 s"; fi

# wyjścia do zmiennych (bez `curl | grep -q`, które przy pipefail bywa fałszywie negatywne)
body=$(curl -fs localhost:8080/) || fail "GET / nie powiódł się"
[[ "$body" == *'lang="pl"'* ]] || fail "/ bez lang=\"pl\""
meta=$(curl -fs localhost:8080/api/meta) || fail "GET /api/meta nie powiódł się"
[[ "$meta" == *'"n_scenes"'* ]] || fail "/api/meta bez n_scenes"
code=$(curl -s -o /dev/null -w '%{http_code}' localhost:8080/historia) || true
[ "$code" = "200" ] || fail "/historia -> $code"
echo "PASS: compose smoke"
