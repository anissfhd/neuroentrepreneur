"""R-SEC-06 : aucun secret dans les fichiers du depot ; .env et donnees ignores par Git."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _scanner():
    spec = importlib.util.spec_from_file_location(
        "check_secrets", ROOT / "scripts" / "check_secrets.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_repository_contains_no_secret():
    assert _scanner().scan(ROOT) == []


def test_scanner_detects_typical_secrets():
    scanner = _scanner()
    # Valeurs fictives construites a l'execution pour ne jamais figurer telles quelles.
    samples = {
        "cle Anthropic": "sk-ant-" + "x" * 30,
        "cle Groq": "gsk_" + "A1" * 20,
        "cle AWS": "AKIA" + "ABCDEFGHIJKLMNOP",
        "secret assigne": "MY_API_KEY" + "=" + "z" * 24,
    }
    for label, text in samples.items():
        assert label in scanner.scan_text(text)
    assert scanner.scan_text("ANTHROPIC_API_KEY=") == []


def test_gitignore_protects_local_files():
    lines = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for entry in (".env", "data/", ".venv/", "*.sqlite", "research/upstream/"):
        assert entry in lines
    assert "!.env.example" in lines


def test_env_example_has_no_value_for_keys():
    for line in (ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.endswith("_API_KEY=") or "API_KEY" not in line:
            continue
        raise AssertionError(f"valeur de cle presente dans .env.example : {line}")
