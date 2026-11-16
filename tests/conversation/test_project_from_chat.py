"""D-76 : « Créer votre projet » ouvre une conversation ; le coach accueille, l'utilisateur
decrit son idee, un titre est propose puis enregistre seulement apres son clic."""

from __future__ import annotations

from neurocoach.agent.runner import WELCOME_MESSAGE
from neurocoach.domain.profiles import PLACEHOLDER_TITLE

IDEA = "Je veux vendre des bougies parfumées artisanales à Lyon, mais je ne sais pas comment."


def _start(coach):
    user = coach.app.coach.register_user("Marie", "Dupont", "marie.d")
    project = coach.app.coach.start_project(user.id)
    return user.id, project.id


def test_the_coach_greets_first_once_and_without_any_model_call(coach, fake_llm):
    user, project = _start(coach)
    assert coach.agent.greet(user, project) is True
    assert coach.agent.greet(user, project) is False  # une seule fois par projet
    assert coach.agent.history(user, project) == [{"role": "assistant", "content": WELCOME_MESSAGE}]
    assert fake_llm.calls == []
    # D-84 : accueil court, sans longue introduction (vision V1).
    assert WELCOME_MESSAGE.startswith("Bonjour, je suis votre coach entrepreneurial.")
    assert len(WELCOME_MESSAGE) < 200 and WELCOME_MESSAGE.count("?") == 0


def test_the_first_idea_is_answered_by_the_model_and_kept_as_the_project_idea(coach, fake_llm):
    user, project = _start(coach)
    coach.agent.greet(user, project)
    turn = coach.agent.send_message(user, project, IDEA)
    assert turn.reply
    assert [t for t, _ in fake_llm.calls][:1] == ["coach_turn"]
    saved = coach.app.coach.get_project(user, project)
    assert (saved.idea, saved.title, saved.title_pending) == (IDEA, PLACEHOLDER_TITLE, True)
    history = coach.agent.history(user, project)
    assert [m["role"] for m in history] == ["assistant", "user", "assistant"]
    assert history[0]["content"] == WELCOME_MESSAGE


def test_a_title_is_proposed_but_never_saved_without_the_click(coach):
    user, project = _start(coach)
    coach.agent.greet(user, project)
    assert coach.agent.title_suggestion(user, project) is None  # rien a proposer avant l'idee
    coach.agent.send_message(user, project, IDEA)
    proposal = coach.agent.title_suggestion(user, project)
    assert proposal == "Bougies parfumées artisanales"
    assert coach.app.coach.get_project(user, project).title == PLACEHOLDER_TITLE
    coach.app.coach.rename_project(user, project, proposal)
    assert coach.agent.title_suggestion(user, project) is None
    assert coach.app.coach.get_project(user, project).title == proposal


def test_the_model_title_is_preferred_when_usable(coach):
    user, project = _start(coach)
    coach.agent.greet(user, project)
    coach.agent.send_message(user, project, IDEA)
    config, _ = coach.agent._session(user, project)
    idea = {"idea_summary": IDEA}
    coach.graph.update_state(
        config, {"brief_draft": {**idea, "project_title": "« Lumières de Lyon »"}}
    )
    assert coach.agent.title_suggestion(user, project) == "Lumières de Lyon"
    # D-80 : un titre inutilisable n'est pas remplace par une coupe d'une phrase
    # (recette du 12/11/2026 : « Son propre business (offre et cible »).
    for bad in ("ab", "Son propre business (offre et cible", "Offre à définir", "Mon business"):
        coach.graph.update_state(config, {"brief_draft": {**idea, "project_title": bad}})
        assert coach.agent.title_suggestion(user, project) is None, bad
    # Aucun titre tant qu'aucune idee n'est retenue.
    coach.graph.update_state(config, {"brief_draft": {"project_title": "Services IA"}})
    assert coach.agent.title_suggestion(user, project) is None


def test_the_title_hint_reaches_the_model_only_for_provisional_titles(coach, fake_llm):
    user, project = _start(coach)
    coach.agent.send_message(user, project, IDEA)
    clarify = [m for t, m in fake_llm.calls if t == "coach_turn"]
    assert clarify and '"title_pending": true' in clarify[-1][-1]["content"]
    assert "project_title" in clarify[-1][0]["content"]


def test_a_greeting_alone_is_not_taken_as_the_idea(coach):
    user, project = _start(coach)
    coach.agent.send_message(user, project, "Bonjour")
    assert coach.app.coach.get_project(user, project).idea == ""
    assert coach.agent.title_suggestion(user, project) is None


def test_the_conversation_survives_a_restart(settings, clock, fake_llm):
    from neurocoach.bootstrap import build_coach_runtime

    first = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    user, project = _start(first)
    first.agent.greet(user, project)
    first.agent.send_message(user, project, IDEA)
    before = first.agent.history(user, project)
    first.checkpointer.conn.close()
    second = build_coach_runtime(settings, clock=clock, llm=fake_llm)
    try:
        assert second.agent.history(user, project) == before
        assert second.agent.greet(user, project) is False  # pas de second accueil
        summary = second.agent.conversation_summary(user, project)
        assert summary["count"] == 3 and summary["user_count"] == 1
        assert summary["saved_at"]
    finally:
        second.checkpointer.conn.close()


def test_another_user_cannot_read_or_greet_the_conversation(coach):
    from neurocoach.domain.errors import DomainError

    user, project = _start(coach)
    other = coach.app.coach.register_user("Paul", "Martin", "paul.m")
    for call in (coach.agent.history, coach.agent.greet, coach.agent.title_suggestion):
        try:
            call(other.id, project)
        except DomainError:
            continue
        raise AssertionError(f"{call.__name__} accessible a un autre utilisateur")
    assert coach.agent.history(user, project) == []  # rien n'a ete ecrit dans le fil
