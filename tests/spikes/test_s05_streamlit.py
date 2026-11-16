"""S-05 : confirmation et reprise du graphe depuis Streamlit (AppTest, sans navigateur)."""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).with_name("streamlit_spike_app.py")


@pytest.fixture
def at(tmp_path, monkeypatch):
    monkeypatch.setenv("NEUROCOACH_DATA_DIR", str(tmp_path / "data"))
    test = AppTest.from_file(str(APP), default_timeout=60)
    test.run()
    assert not test.exception
    yield test
    test.session_state["runtime"]["graph"].checkpointer.conn.close()


def _texts(at: AppTest) -> list[str]:
    return [element.value for element in at.text]


def _runtime(at: AppTest):
    runtime = at.session_state["runtime"]
    return runtime["app"], runtime["graph"], runtime["context"], runtime["config"]


def test_confirm_applies_and_resumes_the_graph(at):
    at.button(key="ask").click().run()
    assert at.subheader[0].value == "Proposition en attente"
    at.button(key="confirm").click().run()
    assert not at.exception
    assert _texts(at) == ["resultat=applied", "taches=3"]
    _, graph, _, config = _runtime(at)
    assert graph.get_state(config).next == ()
    # Les boutons disparaissent apres la decision.
    assert [button.key for button in at.button] == ["ask"]


def test_cancel_writes_nothing(at):
    at.button(key="ask").click().run()
    at.button(key="cancel").click().run()
    assert _texts(at) == ["resultat=cancelled", "taches=0"]


def test_stale_double_click_is_harmless(at):
    at.button(key="ask").click().run()
    pending = at.session_state["pending"]
    at.button(key="confirm").click().run()
    # Clic tardif sur un apercu perime : l'identifiant est remis de force dans la session.
    at.session_state["pending"] = pending
    at.run()
    at.button(key="confirm").click().run()
    assert not at.exception
    assert _texts(at) == ["resultat=applied", "taches=3"]
    assert at.info[0].value == "Cette proposition a déjà été traitée."
    counters = at.session_state["runtime"]["counters"]
    assert counters.calls["propose"] == 1
    assert counters.calls["await_after"] == 1


def test_plain_rerun_does_not_reapply(at):
    at.button(key="ask").click().run()
    at.button(key="confirm").click().run()
    for _ in range(2):
        at.run()
    assert _texts(at) == ["resultat=applied", "taches=3"]
    app, _, context, _ = _runtime(at)
    assert len(app.coach.list_events(context.user_id, context.project_id)) == 4
