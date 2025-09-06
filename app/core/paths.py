"""Core paths used by the application.

This module centralizes filesystem locations for uploads, artifacts, and web UI.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
UPLOADS_DIR = ROOT / "uploads"
ARTIFACTS_DIR = ROOT / "artifacts"
WEB_DIR = ROOT / "web"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
WEB_DIR.mkdir(parents=True, exist_ok=True)


