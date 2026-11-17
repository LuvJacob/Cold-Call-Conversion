"""Write the FastAPI OpenAPI schema to docs/api/openapi.json (or a path given as argv[1]).

Run from apps/api: .venv/bin/python scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

from cold_call_api.main import app

DEFAULT_OUT = Path(__file__).resolve().parents[3] / "docs" / "api" / "openapi.json"


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_OUT
    out.write_text(json.dumps(app.openapi(), indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {out}")


if __name__ == "__main__":
    main()
