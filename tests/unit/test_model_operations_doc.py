"""M5 : la procedure d'exploitation ne decrit que des commandes et des messages qui existent.

Verifications hors ligne : chaque option citee est acceptee par le script (``--help``, qui
n'appelle rien) ; toute commande payante porte la mention « PAYANT » ; les commandes de
campagne citees sont acceptees par l'orchestrateur ; les libelles cites existent dans le code.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / "docs" / "MODEL_OPERATIONS.md"
CATALOG = "src/neurocoach/llm_catalog.py"
CHECK = "scripts/check_llm.py"
COMMAND = re.compile(r"scripts[\\/](\w+)\.py((?:\s+[^\s#`]+)*)")


def _code_lines() -> list[str]:
    lines, inside = [], False
    for line in DOC.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("```"):
            inside = not inside
            continue
        if inside:
            lines.append(line)
    return lines


def _commands() -> list[tuple[str, list[str], str]]:
    found = []
    text = DOC.read_text(encoding="utf-8")
    for line in text.splitlines():
        for match in COMMAND.finditer(line):
            found.append((match.group(1), match.group(2).split(), line))
    return found


@cache
def _help(script: str) -> str:
    env = {**os.environ, "NEUROCOACH_LLM_PROVIDER": "fake", "NEUROCOACH_FORBID_REAL_LLM": "1"}
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / f"{script}.py"), "--help"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_every_documented_script_and_option_exists():
    commands = _commands()
    assert {name for name, _, _ in commands} >= {"check_llm", "run_campaign", "dev"}
    dev = (ROOT / "scripts" / "dev.py").read_text(encoding="utf-8")
    for name, tokens, line in commands:
        assert (ROOT / "scripts" / f"{name}.py").is_file(), line
        if name == "dev":
            assert tokens, line
            assert f'"{tokens[0]}": cmd_' in dev, line
            continue
        options = [t for t in tokens if t.startswith("--")]
        for option in options:
            assert re.search(rf"(?<![\w-]){re.escape(option)}(?![\w-])", _help(name)), (
                option,
                line,
            )


def test_every_paid_command_is_marked_paid():
    for line in _code_lines():
        if "--real-api" in line or "--ping" in line:
            assert line.rstrip().endswith("# PAYANT"), line
    # Et aucune commande payante hors d'un bloc de code (copie accidentelle).
    prose = [
        line
        for line in DOC.read_text(encoding="utf-8").splitlines()
        if "--real-api" in line and line not in _code_lines()
    ]
    assert prose == []


def _campaign():
    spec = importlib.util.spec_from_file_location(
        "run_campaign", ROOT / "scripts" / "run_campaign.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_campaign"] = module
    spec.loader.exec_module(module)
    return module


def test_documented_campaign_commands_are_accepted(tmp_path, monkeypatch):
    """Analyse des arguments seulement : aucun sous-processus, aucun appel."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_LLM")
    campaign = _campaign()
    lines = [line for line in _code_lines() if "run_campaign.py" in line]
    assert lines
    ledger = tmp_path / "comparaison-2026-11.jsonl"
    for line in lines:
        argv = line.split("run_campaign.py", 1)[1].split("#", 1)[0].split()
        argv = [str(ledger) if a.endswith(".jsonl") else a for a in argv]
        if "--resume" in argv:
            ledger.write_text('{"event": "run", "run": "x", "status": "done"}\n', encoding="utf-8")
        elif ledger.exists():
            ledger.unlink()
        args = campaign.parse(argv)
        if args.real_api:
            assert args.total_usd > 0 and args.ledger == ledger
            assert args.campaign == "comparaison-2026-11"


@pytest.mark.parametrize(
    ("snippet", "source"),
    [
        ("Modèles IA chargés", "ui/app.py"),
        ("Configuration demandée : identique à la configuration chargée.", "ui/app.py"),
        ("Configuration des modèles modifiée, mais pas encore active", CATALOG),
        ("Dernière configuration chargée par l'application : identique.", CHECK),
        ("Configuration demandée différente de la dernière chargée", CHECK),
        ("Aucun historique : l'application n'a pas encore démarré avec cette base.", CHECK),
        ("Modèle inconnu pour le rôle", CATALOG),
        ("Appels réels interdits dans ce processus", "src/neurocoach/agent/llm.py"),
        ("Le service de langage ne répond pas.", "src/neurocoach/domain/errors.py"),
        ("configuration commune pour tous les rôles", CHECK),
    ],
)  # fmt: skip
def test_documented_messages_exist_in_the_code(snippet, source):
    assert snippet in DOC.read_text(encoding="utf-8")
    assert snippet in (ROOT / source).read_text(encoding="utf-8")


def test_documented_dates_and_prices_match_the_catalog():
    from neurocoach.llm_catalog import load_catalog

    catalog = load_catalog()
    mini = catalog.get("gpt-5-mini")
    text = DOC.read_text(encoding="utf-8")
    assert f"{mini.retirement_date:%d/%m/%Y}" == "11/12/2026"
    assert "retrait de l'API le 11/12/2026" in text
    assert (
        mini.replacement == "gpt-5.6-terra" and "remplacement recommandé : `gpt-5.6-terra`" in text
    )
    # Pires cas du --ping cites : 500 jetons d'entree, 4 000 de sortie.
    worst_mini = (500 * mini.price_input + 4000 * mini.price_output) / 1e6
    terra = catalog.get("gpt-5.6-terra")
    worst_terra = (500 * terra.price_input + 4000 * terra.price_output) / 1e6
    assert round(worst_mini, 3) == 0.008 and round(worst_terra, 3) == 0.049


def test_referenced_files_exist():
    for path in (
        "src/neurocoach/llm_models.toml",
        "docs/MULTI_MODEL_DESIGN.md",
        "docs/DEMO_SCRIPT.md",
    ):
        assert (ROOT / path).is_file(), path
