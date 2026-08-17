from __future__ import annotations

import json
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


HEALTH_URL = "http://127.0.0.1:8094/api/health"
TIMEOUT_SECONDS = 3.0


def main() -> int:
    try:
        request = Request(HEALTH_URL, headers={"Accept": "application/json"})
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            if response.status != 200:
                return 1
            payload = json.loads(response.read().decode("utf-8"))
        return 0 if payload.get("database_ready") is True else 1
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, json.JSONDecodeError):
        return 1


if __name__ == "__main__":
    sys.exit(main())
