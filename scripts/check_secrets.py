"""Recherche de secrets dans les fichiers du depot (R-SEC-06).

Usage : python scripts/check_secrets.py   (code de sortie 1 si un motif est detecte)
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS: dict[str, re.Pattern[str]] = {
    "cle Anthropic": re.compile(r"sk-ant-[A-Za-z0-9_\-]{20,}"),
    "cle OpenAI": re.compile(r"sk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "cle Groq": re.compile(r"gsk_[A-Za-z0-9]{32,}"),
    "cle AWS": re.compile(r"AKIA[0-9A-Z]{16}"),
    "jeton GitHub": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "cle privee": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "secret assigne": re.compile(
        r"(?i)\b[A-Z0-9_]*(?:API_KEY|SECRET|TOKEN|PASSWORD)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}"
    ),
}

EXCLUDED_DIRS = {".git", ".venv", "venv", "data", "__pycache__", ".pytest_cache", ".ruff_cache"}
EXCLUDED_SUFFIXES = {".pdf", ".png", ".jpg", ".sqlite", ".db", ".pyc", ".lock"}


def candidate_files(root: Path = ROOT) -> list[Path]:
    """Fichiers suivis ou publiables (non ignores) selon Git, sinon parcours du dossier."""
    try:
        listed = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.splitlines()
        files = [root / name for name in listed]
    except (OSError, subprocess.CalledProcessError):
        files = [
            path
            for path in root.rglob("*")
            if path.is_file() and not EXCLUDED_DIRS.intersection(path.relative_to(root).parts)
        ]
    return [
        path
        for path in files
        if path.suffix.lower() not in EXCLUDED_SUFFIXES and path.name != ".env"
    ]


def scan_text(text: str) -> list[str]:
    return [label for label, pattern in PATTERNS.items() if pattern.search(text)]


def scan(root: Path = ROOT) -> list[tuple[str, str]]:
    findings = []
    for path in candidate_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for label in scan_text(text):
            findings.append((str(path.relative_to(root)), label))
    return findings


def main() -> int:
    findings = scan()
    for path, label in findings:
        print(f"[secret] {path} : {label}")
    if findings:
        return 1
    print("Aucun secret détecté.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
