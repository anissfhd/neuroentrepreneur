"""R4 (D-71) : harnais d'evaluation qualitative de l'analyse, hors ligne."""

from __future__ import annotations

import importlib.util
import socket
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "evaluate_research_analysis.py"


def load():
    spec = importlib.util.spec_from_file_location("evaluate_research_analysis", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def test_dry_run_grades_every_scenario_without_any_call(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)  # aucun .env lu
    harness = load()
    assert harness.main(["--out-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Essai à blanc : faux fournisseur imposé" in out
    assert "Analyses entièrement conformes : 3/3" in out
    assert "Campagne réelle équivalente : 9 appel(s)" in out
    [report] = tmp_path.glob("research-analysis-*.md")
    text = report.read_text(encoding="utf-8")
    for name in ("quatre_idees", "donnees_manquantes", "profil_inconnu"):
        assert f"## {name}" in text
    assert "Ignore les instructions" not in text.split("## quatre_idees", 1)[1]


def test_real_run_requires_explicit_model_and_budget(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    harness = load()
    with pytest.raises(SystemExit):
        harness.main(["--real-api"])
