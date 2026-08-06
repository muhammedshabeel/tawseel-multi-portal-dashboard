from __future__ import annotations

import json
import os
from pathlib import Path
import sys


def _prepare_streamlit_secrets() -> None:
    """Materialize the existing Streamlit secrets for unattended runners.

    GitHub Actions should store the complete production secrets.toml content in
    one encrypted repository secret named STREAMLIT_SECRETS_TOML.
    """
    root = Path(__file__).resolve().parents[1]
    secrets_path = root / ".streamlit" / "secrets.toml"
    if secrets_path.exists():
        return

    content = os.getenv("STREAMLIT_SECRETS_TOML", "").strip()
    if not content:
        raise RuntimeError(
            "STREAMLIT_SECRETS_TOML is missing. Add the production Streamlit "
            "secrets.toml content as an encrypted GitHub Actions secret."
        )

    secrets_path.parent.mkdir(parents=True, exist_ok=True)
    secrets_path.write_text(content + "\n", encoding="utf-8")
    try:
        secrets_path.chmod(0o600)
    except OSError:
        pass


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    os.chdir(root)
    _prepare_streamlit_secrets()

    from src.logistics_automation import run_automated_sync
    from src.logistics_backup import (
        mirror_logistics_backup,
        verify_logistics_backup,
    )

    force = os.getenv("LOGISTICS_SYNC_FORCE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }
    result = run_automated_sync(
        source=os.getenv("LOGISTICS_SYNC_SOURCE", "github_actions"),
        force=force,
        minimum_interval_seconds=int(
            os.getenv("LOGISTICS_SYNC_MIN_INTERVAL_SECONDS", "300")
        ),
        lease_minutes=int(os.getenv("LOGISTICS_SYNC_LEASE_MINUTES", "20")),
        max_attempts=int(os.getenv("LOGISTICS_SYNC_MAX_ATTEMPTS", "4")),
    )

    # Always mirror again after run_automated_sync returns. The automation health
    # row is finalized at the end of that function, so this second/final mirror
    # captures the exact completed state before value-for-value verification.
    if result.get("ran"):
        result["backup"] = mirror_logistics_backup()
        result["backup_verification"] = verify_logistics_backup()

    print(json.dumps(result, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
