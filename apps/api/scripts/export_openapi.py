"""Export or verify the committed API contract without loading local secrets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from svara_api.config import Settings
from svara_api.main import create_app

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT = REPOSITORY_ROOT / "packages" / "api-contract" / "openapi.json"


def rendered_contract() -> str:
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url="sqlite+aiosqlite:///:memory:",
        voice_provider="mock",
        enable_demo_auth=False,
        seed_demo_data=False,
        clerk_secret_key=None,
        clerk_webhook_signing_secret=None,
        sarvam_api_key=None,
        sarvam_org_id=None,
        sarvam_workspace_id=None,
        sarvam_agent_id=None,
        sarvam_agent_version=None,
    )
    document = create_app(settings).openapi()
    return f"{json.dumps(document, indent=2, sort_keys=True)}\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if the contract is stale")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    output = args.output.resolve()
    expected = rendered_contract()
    if args.check:
        if not output.exists() or output.read_text(encoding="utf-8") != expected:
            print(f"OpenAPI contract is stale: {output}")
            print("Run `pnpm api:export-openapi` from the repository root.")
            return 1
        print(f"OpenAPI contract is current: {output}")
        return 0

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(expected, encoding="utf-8")
    print(f"Wrote OpenAPI contract: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
