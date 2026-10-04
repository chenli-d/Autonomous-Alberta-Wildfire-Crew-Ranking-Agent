"""Load local server configuration without exposing credentials to the UI."""
from pathlib import Path

from dotenv import load_dotenv


def load_local_environment(root=None):
    # Use an explicit repo path, not the working directory or parent-file discovery.
    # Existing process variables take precedence; secrets stay server-side.
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    load_dotenv(root / ".env", override=False, interpolate=False, encoding="utf-8-sig")
