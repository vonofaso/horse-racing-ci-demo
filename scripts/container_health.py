"""Container readiness probe: HTTP and PostgreSQL through /health."""

import os
from urllib.request import urlopen


def main() -> None:
    port = int(os.environ.get("APP_PORT", "8000"))
    with urlopen(f"http://127.0.0.1:{port}/health", timeout=3) as response:  # nosec B310
        if response.status != 200:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
