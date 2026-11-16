"""R2 (D-69) : script de controle des services de recherche, hors ligne."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from neurocoach.infra.search_providers import build_research_registry

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_research.py"
KEY = "tvly-TEST-script-ne-doit-pas-fuiter"


def load_script():
    spec = importlib.util.spec_from_file_location("check_research", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def script(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROCOACH_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.chdir(tmp_path)  # aucun .env lu
    return load_script()


def test_status_without_keys_makes_no_call(script, capsys):
    assert script.main([]) == 2
    out = capsys.readouterr().out
    assert "TAVILY_API_KEY absente" in out and "EXA_API_KEY absente" in out
    assert "NEUROCOACH_FORBID_REAL_RESEARCH" in out  # verrou des tests


def test_ping_requires_explicit_flags(script, capsys):
    assert script.main(["--ping", "--provider", "tavily"]) == 1
    assert "Aucun appel" in capsys.readouterr().out


def test_ping_refused_when_locked_or_without_key(script, capsys):
    assert script.main(["--ping", "--provider", "tavily", "--real-api", "--budget-usd", "1"]) == 1
    assert "non branché" in capsys.readouterr().out


def test_ping_makes_one_call_and_never_prints_the_key(script, capsys, monkeypatch, tmp_path):
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_RESEARCH", raising=False)
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={
            "results": [{"title": "t", "url": "https://site.example/x", "content": "c"}],
            "usage": {"credits": 1},
        })  # fmt: skip

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        script,
        "build_research_registry",
        lambda settings: build_research_registry(settings, client=client),
    )
    # Budget insuffisant : refus avant tout appel.
    assert script.main(["--ping", "--provider", "tavily", "--real-api",
                        "--budget-usd", "0.001"]) == 1  # fmt: skip
    assert requests == []
    assert script.main(["--ping", "--provider", "tavily", "--real-api",
                        "--budget-usd", "0.01"]) == 0  # fmt: skip
    assert len(requests) == 1
    assert json.loads(requests[0].content)["query"] == script.PING_QUERY
    out = capsys.readouterr().out
    assert KEY not in out and "TAVILY_API_KEY définie" in out
    assert "1 requête(s) et 0.008 $" in out or "OK : 1 résultat" in out


def test_ping_sends_the_application_parameters(script, capsys, monkeypatch):
    """Recette du 10/11/2026 : l'appel de test transmet pays et sites exclus, comme l'app."""
    monkeypatch.delenv("NEUROCOACH_FORBID_REAL_RESEARCH", raising=False)
    monkeypatch.setenv("EXA_API_KEY", "exa-TEST-script")
    bodies = []

    def handler(request):
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"results": [], "costDollars": {"total": 0.004}})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(
        script, "build_research_registry",
        lambda settings: build_research_registry(settings, client=client),
    )  # fmt: skip
    assert script.main(["--ping", "--provider", "exa", "--real-api", "--budget-usd", "0.01",
                        "--market", "France"]) == 0  # fmt: skip
    assert bodies[0]["userLocation"] == "FR" and "reddit.com" in bodies[0]["excludeDomains"]
