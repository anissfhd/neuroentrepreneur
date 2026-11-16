"""Regles d'import entre couches (ARCHITECTURE section 3)."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "neurocoach"

FORBIDDEN = {
    "domain": (
        "neurocoach.infra",
        "neurocoach.application",
        "neurocoach.agent",
        "neurocoach.ui",
        "neurocoach.bootstrap",
        "sqlite3",
        "langgraph",
        "langchain",
        "streamlit",
    ),
    "application": ("neurocoach.agent", "neurocoach.ui", "langgraph", "langchain", "streamlit"),
    "infra": ("neurocoach.application", "neurocoach.agent", "neurocoach.ui", "streamlit"),
    # L'agent passe par les services : jamais de SQL ni d'acces direct aux repositories.
    "agent": (
        "neurocoach.infra.repositories",
        "neurocoach.infra.db",
        "sqlite3",
        "neurocoach.ui",
        "streamlit",
        # R3 (D-70) : l'agent passe par ``app.research`` ; jamais par les adaptateurs ni
        # par l'acces SQL de la recherche.
        "neurocoach.research",
        "neurocoach.infra.research_repository",
        "neurocoach.infra.search_providers",
    ),
    # R1 (D-68) : ports et simulations de recherche, sans base, sans graphe, sans reseau.
    "research": (
        "neurocoach.infra",
        "neurocoach.application",
        "neurocoach.agent",
        "neurocoach.ui",
        "sqlite3",
        "langgraph",
        "langchain",
        "streamlit",
        "socket",
        "http",
        "urllib",
        "httpx",
        "requests",
        "aiohttp",
        "tavily",
        "exa_py",
    ),
}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("layer", sorted(FORBIDDEN))
def test_layer_imports(layer):
    violations = []
    files = sorted((SRC / layer).rglob("*.py"))
    assert files, f"aucun fichier dans {layer}"
    for path in files:
        for name in _imports(path):
            if any(name == bad or name.startswith(bad + ".") for bad in FORBIDDEN[layer]):
                violations.append(f"{path.relative_to(SRC)} importe {name}")
    assert violations == []


def test_ui_never_touches_the_database_directly():
    app = SRC.parents[1] / "ui" / "app.py"
    names = _imports(app)
    assert not [name for name in names if name == "sqlite3" or name.startswith("neurocoach.infra")]


def test_domain_never_reads_system_time():
    for path in (SRC / "domain").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for call in ("datetime.now(", "date.today(", "time.time("):
            assert call not in text, f"{path.name} appelle {call}"


def test_only_the_search_adapters_open_http_connections():
    """R2 (D-69) : un seul module parle aux services de recherche ; aucun autre client HTTP."""
    allowed = {SRC / "infra" / "search_providers.py"}
    offenders = []
    for path in SRC.rglob("*.py"):
        names = _imports(path)
        if path not in allowed and any(
            n == lib or n.startswith(lib + ".") for n in names for lib in ("httpx", "requests")
        ):
            offenders.append(str(path.relative_to(SRC)))
    assert offenders == []


def test_graph_nodes_never_approve_or_run_research():
    """R3 (D-70) : les noeuds preparent et proposent ; approuver et lancer n'existent que dans
    le lanceur, appele par un bouton de l'interface."""
    nodes = (SRC / "agent" / "nodes.py").read_text(encoding="utf-8")
    for call in ("approve_mission", "run_mission", "run_query", "extend_mission", "close_mission"):
        assert call not in nodes, call
