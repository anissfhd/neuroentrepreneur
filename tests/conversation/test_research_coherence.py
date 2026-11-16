"""D-80 : de la conversation a la recherche, puis a l'analyse et au plan, sans contradiction.

Faux modele et fournisseur simule : aucun appel reseau ni payant. Ces tests verifient le
passage du contexte (sujet, zone, cible), la verification des preuves (pertinence, prix
chiffres, niveau de preuve) et la coherence des decisions. Ils ne prouvent pas la qualite
des requetes ni des analyses du vrai modele, qui se juge en recette reelle.
"""

from __future__ import annotations

import json
import socket

import pytest

from neurocoach.agent.schemas import CoachBrief, CoachTurn, ResearchSpec, SpecQuery
from neurocoach.application.formatting import format_resume_message
from neurocoach.application.research_format import format_analysis
from neurocoach.domain.analysis import ClaimDraft, IdeaAnalysisDraft
from neurocoach.domain.research import detect_markets
from neurocoach.infra.search_providers import build_research_registry
from neurocoach.research.fake import FakeResearchProvider

SUBJECT = "Micro-prestations de rédaction assistée par IA pour les TPE"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("connexion reseau tentee")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


@pytest.fixture
def provider(coach):
    fake = FakeResearchProvider()
    coach.app.research.registry = build_research_registry(simulation=True, extra={"fake": fake})
    return fake


@pytest.fixture
def project(coach, provider):
    user = coach.app.coach.register_user("Camille", "Martin", "camille.m")
    started = coach.app.coach.start_project(user.id)  # titre provisoire « Nouveau projet »
    coach.agent.greet(user.id, started.id)
    return coach, user.id, started.id


def say(coach, user, project, text, **kwargs):
    return coach.agent.send_message(user, project, text, **kwargs)


def turn(next_step="conseiller", **values):
    flags = {k: values.pop(k) for k in ("plan_requested", "plan_declined", "real_change")
             if k in values}  # fmt: skip
    values.setdefault("idea_summary", SUBJECT)
    return CoachTurn(intent="information_projet", reply="Réponse du modèle.",
                     fiche=CoachBrief(**values), next_step=next_step, **flags)  # fmt: skip


def facts_of(llm, task, index=-1):
    content = [m for t, m in llm.calls if t == task][index][-1]["content"]
    return json.loads(content.split("<donnees_projet>\n", 1)[1].split("\n</donnees_projet>")[0])


# --- 1. contexte de la conversation -> mission de recherche ----------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Je cible principalement le marché français.", ["France"]),
        ("Des clients belges et une clientèle suisse.", ["Belgique", "Suisse"]),
        ("Pour des PME québécoises.", ["Canada"]),
        ("Je rédige en français.", []),  # une langue n'est pas un marche
    ],
)
def test_a_market_said_with_an_adjective_is_kept(text, expected):
    assert sorted(detect_markets([text])) == sorted(expected)


def test_the_mission_uses_the_understood_subject_zone_and_queries(project, fake_llm):
    coach, user, project_id = project
    fake_llm.script(
        "research_spec",
        ResearchSpec(
            subject=SUBJECT, segment="TPE francophones", market="France",
            queries=[
                SpecQuery(category="marche", text="demande rédaction IA TPE France"),
                SpecQuery(category="prix", text="tarif rédaction article IA freelance"),
                SpecQuery(category="prix", text="prix prestation rédaction IA € contact@x.fr"),
            ],
            exclude_senses=["microservices (architecture logicielle)"],
        ),
    )  # fmt: skip
    fake_llm.script("coach_turn", turn("preparer_recherche"))
    say(coach, user, project_id, "D'accord pour cette recherche sur le marché français.")
    mission = coach.agent.research_pending(user, project_id)
    assert mission.scope.markets == ["France"]
    assert mission.scope.subject == SUBJECT and "Nouveau projet" not in mission.scope.objective
    preview = "\n".join(mission.preview)
    assert "Sujet : " + SUBJECT in preview and "Projet(s) : Nouveau projet" not in preview
    assert "Sens écartés : microservices (architecture logicielle)" in preview
    texts = {(q.category.value, q.text) for q in mission.planned}
    assert ("marche", "demande rédaction IA TPE France") in texts
    prices = [t for c, t in texts if c == "prix"]
    # Requetes du modele, completees du marche et minimisees (aucune adresse transmise).
    assert all("France" in t and "@" not in t for t in prices) and len(prices) == 2
    # Les categories sans requete du modele gardent une requete deterministe.
    assert {q.category.value for q in mission.planned} == {"marche", "concurrence", "prix", "avis"}
    assert not mission.queries_used  # rien n'est lance avant le clic


def test_an_answer_to_the_market_question_is_never_lost(project, fake_llm):
    coach, user, project_id = project
    fake_llm.script("research_spec", ResearchSpec(subject=SUBJECT))  # zone inconnue
    fake_llm.script("coach_turn", turn("preparer_recherche"))
    asked = say(coach, user, project_id, "Oui, proposez-moi cette recherche.")
    assert "Dans quel pays ou quelle zone" in asked.reply
    fake_llm.script("research_spec", ResearchSpec(subject=SUBJECT))
    say(coach, user, project_id, "Surtout le marché français, avec des clients francophones.")
    assert coach.agent.research_pending(user, project_id).scope.markets == ["France"]


def test_a_zone_understood_only_by_the_model_is_used(project, fake_llm):
    coach, user, project_id = project
    fake_llm.script("research_spec", ResearchSpec(subject=SUBJECT))
    fake_llm.script("coach_turn", turn("preparer_recherche"))
    say(coach, user, project_id, "Oui, proposez-moi cette recherche.")
    fake_llm.script("research_spec", ResearchSpec(subject=SUBJECT, market="Bretagne"))
    say(coach, user, project_id, "Là où j'habite, dans ma région, autour de chez moi.")
    assert coach.agent.research_pending(user, project_id).scope.markets == ["Bretagne"]


# --- 2. sources reellement accessibles ------------------------------------------------------


def test_the_coach_only_knows_the_sources_really_available(project, fake_llm):
    coach, user, project_id = project
    say(coach, user, project_id, "Je veux proposer de la rédaction assistée par IA.")
    offer = facts_of(fake_llm, "coach_turn")["recherche_disponible"]
    assert offer["active"] is True and offer["fournisseurs"]
    assert {"Reddit", "LinkedIn"} <= set(offer["non_consultes"])
    system = [m for t, m in fake_llm.calls if t == "coach_turn"][-1][0]["content"]
    assert "ne promets jamais de consulter un site de recherche_disponible.non_consultes" in system


# --- 3. preuves : pertinence, prix chiffres, niveau de preuve -------------------------------


def _researched(coach, user, project_id, fake_llm, draft=None):
    fake_llm.script("research_spec", ResearchSpec(
        subject=SUBJECT, market="France", exclude_senses=["architecture"]))  # fmt: skip
    fake_llm.script("coach_turn", turn("preparer_recherche"))
    say(coach, user, project_id, "D'accord pour la recherche, marché français.")
    mission = coach.agent.research_pending(user, project_id)
    if draft is not None:
        fake_llm.script("research_analysis", draft)
    approval = coach.agent.approve_research(user, project_id, mission.id, mission.scope_hash)
    return mission, approval


def test_the_analysis_follows_the_approval_without_any_keyword(project, fake_llm):
    coach, user, project_id = project
    _, approval = _researched(coach, user, project_id, fake_llm)
    text = approval.reply.replace("\\", "")
    conclusion, details = text.split("<!-- détails -->")
    # D-82 : une conclusion courte d'abord (texte du modele), le detail replie ensuite.
    assert conclusion.startswith("[Conclusion simulée]") and len(conclusion) < 600
    # D-84 : une simulation reste signalee ; aucun journal d'execution dans la conversation.
    assert details.strip().startswith("Résultats simulés, fictifs")
    assert "Voici mon analyse critique" not in text and "Niveau de preuve" in text
    assert "Dites « analyse »" not in text and "source(s) retenue(s)" not in text
    assert [t for t, _ in fake_llm.calls].count("research_analysis") == 1
    assert coach.app.actions.get_pending(user, project_id) is None  # aucun plan propose


def test_off_topic_sources_and_unpriced_prices_never_count_as_evidence(project, fake_llm):
    coach, user, project_id = project
    draft = IdeaAnalysisDraft(
        summary="Analyse prudente.",
        off_topic=["S1", "S2"],
        evidence="suffisant",  # surestime : le code plafonne
        strengths=[ClaimDraft(text="Une demande existe.", kind="fait", sources=["S1"])],
        prices=[
            ClaimDraft(
                text="La plupart des freelances ne savent pas fixer leurs tarifs.",
                kind="fait",
                sources=["S3"],
            )
        ],
    )
    mission, approval = _researched(coach, user, project_id, fake_llm, draft)
    analysis = coach.app.research.latest_analysis(user, mission.id)
    idea = analysis.ideas[0]
    assert idea.off_topic_count == 2
    assert idea.sections["strengths"] == []  # appuyee sur une source hors sujet : retiree
    assert idea.sections["prices"] == []  # aucun montant chiffre : ce n'est pas un prix
    assert idea.evidence == "insuffisant"
    assert any("Prix observés : insuffisant" in u for u in idea.unknowns)
    text = approval.reply.replace("\\", "")
    tab = format_analysis(analysis, coach.app.research.mission_report(user, mission.id).sources)
    assert "dont 2 écarté(s) comme hors sujet" in tab  # D-84 : onglet Recherche
    assert "insuffisant pour recommander" in text
    # Le coach recoit le niveau de preuve pour sa reponse et sa decision.
    say(coach, user, project_id, "Ces données suffisent-elles ?")
    facts = facts_of(fake_llm, "coach_turn")
    assert facts["analyse"]["idees"][0]["niveau_de_preuve"] == "insuffisant"
    assert facts["preparation_du_plan"]["niveau_de_preuve_recherche"] == "insuffisant"


# --- 4. plan : jamais contre la demande ni sur des preuves insuffisantes ----------------------


def test_insufficient_evidence_blocks_a_plan_the_user_did_not_ask_for(project, fake_llm):
    coach, user, project_id = project
    draft = IdeaAnalysisDraft(summary="Peu de preuves.", evidence="insuffisant")
    _researched(coach, user, project_id, fake_llm, draft)
    known = {"available_minutes_per_day": 60, "budget": "150 €"}
    fake_llm.script("coach_turn", turn("preparer_plan", **known))
    refused = say(coach, user, project_id, "Merci, c'est clair.")
    assert refused.pending is None and "preuves suffisantes" in refused.notice
    # Demande explicite : plan provisoire, sans s'appuyer sur la recherche.
    fake_llm.script("coach_turn", turn("preparer_plan", plan_requested=True, **known))
    asked = say(coach, user, project_id, "Faites-moi quand même un plan provisoire.")
    assert asked.pending is not None
    plan_facts = facts_of(fake_llm, "draft_plan")
    assert plan_facts["niveau_de_preuve_recherche"] == "insuffisant"
    assert plan_facts["plan_provisoire"] is True
    assert coach.app.coach.list_tasks(user, project_id) == []


def test_no_plan_is_built_after_the_user_refused_one(project, fake_llm):
    coach, user, project_id = project
    known = {"available_minutes_per_day": 60, "budget": "150 €"}
    say(coach, user, project_id, "Analysez d'abord. Ne construisez aucun plan.")
    fake_llm.script("coach_turn", turn("preparer_plan", **known))  # le modele se contredit
    refused = say(coach, user, project_id, "J'ai 1 h par jour et 150 €.")
    assert refused.pending is None and "ne pas en construire" in refused.notice
    assert "draft_plan" not in [t for t, _ in fake_llm.calls]
    # La personne le demande ensuite : le refus est leve.
    fake_llm.script("coach_turn", turn("preparer_plan", plan_requested=True, **known))
    assert say(coach, user, project_id, "Maintenant, proposez-moi un plan.").pending is not None


def test_the_resume_banner_never_pushes_a_plan(project):
    coach, user, project_id = project
    snapshot = coach.app.coach.get_snapshot(user, project_id)
    text = format_resume_message(
        snapshot.project,
        coach.app.coach.get_progress(user, project_id),
        coach.app.coach.get_next_actions(user, project_id),
    )
    assert text == "Bon retour sur votre projet. Ce projet n'a pas encore de plan."


# --- 5. memoire : la fiche du modele remplace les hypotheses perimees -------------------------


def test_stale_assumptions_are_replaced_by_the_cumulative_brief(project, fake_llm):
    coach, user, project_id = project
    fake_llm.script("coach_turn", turn(assumptions=["Temps disponible non précisé"]))
    say(coach, user, project_id, "Je veux proposer de la rédaction assistée par IA.")
    fake_llm.script("coach_turn", turn(available_minutes_per_day=60,
                                       assumptions=["Les TPE paient à la mission"]))  # fmt: skip
    say(coach, user, project_id, "J'ai une heure par jour.")
    say(coach, user, project_id, "Et ensuite ?")
    brief = facts_of(fake_llm, "coach_turn")["brief"]
    assert brief["assumptions"] == ["Les TPE paient à la mission"]


# --- 6. accompagnement progressif (consigne transmise au modele) ----------------------------


def test_the_coach_is_told_to_help_discover_an_idea_before_asking_for_an_offer(project, fake_llm):
    coach, user, project_id = project
    say(coach, user, project_id, "Je ne sais pas du tout quel business créer.")
    system = [m for t, m in fake_llm.calls if t == "coach_turn"][-1][0]["content"]
    # D-81 : diagnostic d'abord, une seule question a part, aucune piste ni tache.
    assert "d'abord comprendre la personne, ensuite recommander" in system
    assert "aucune piste, aucun conseil, aucune liste, aucune tâche" in system
    assert "ta seule question du tour" in system and "est une hypothèse" in system


def test_a_refusal_said_in_a_research_follow_up_is_kept(project, fake_llm):
    """Recette du 12/11/2026 : « Ne construisez aucun plan », dit en commentant les resultats
    d'une recherche, puis une invitation a construire le plan. Le refus est retenu."""
    coach, user, project_id = project
    _researched(coach, user, project_id, fake_llm)
    follow = say(coach, user, project_id, "Analysez ces résultats de manière critique, "
                 "sources pertinentes et hors sujet. Ne construisez aucun plan.")  # fmt: skip
    assert follow.pending is None
    assert "coach_turn" in [t for t, _ in fake_llm.calls][-2:]  # fiche et decision tenues
    known = {"available_minutes_per_day": 60, "budget": "150 €"}
    fake_llm.script("coach_turn", turn("preparer_plan", **known))
    refused = say(coach, user, project_id, "J'ai une heure par jour et 150 €.")
    assert refused.pending is None and "ne pas en construire" in refused.notice
