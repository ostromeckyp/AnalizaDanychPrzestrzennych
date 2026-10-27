"""Pamięciowy magazyn wyników z TTL.

Co robi: `TTLStore` trzyma gotowe odpowiedzi (np. strefy dla trójki h/draft/margin) przez ograniczony czas.
Dlaczego tak: odpowiedź strefowa jest czysta (zależy tylko od parametrów i wersji modelu), więc wystarczy
  prosty cache w procesie; ten plik jest JEDYNYM miejscem do podmiany na Redis (spec §3), gdyby
  backend miał działać w wielu procesach.
Wejście → wyjście: `set(klucz, wartość)`, `get(klucz)` → wartość albo None (brak lub wygasło).
Jak to obronić: `cachetools.TTLCache` nie jest bezpieczny wątkowo, więc każdy dostęp pod `threading.Lock`
  (FastAPI uruchamia zwykłe handlery w puli wątków).
"""
import threading
from typing import Any

from cachetools import TTLCache


class TTLStore:
    def __init__(self, maxsize: int = 256, ttl_s: float = 3600):
        self._cache: TTLCache = TTLCache(maxsize=maxsize, ttl=ttl_s)
        self._lock = threading.Lock()

    def get(self, key) -> Any | None:
        with self._lock:
            return self._cache.get(key)

    def set(self, key, value) -> None:
        with self._lock:
            self._cache[key] = value
