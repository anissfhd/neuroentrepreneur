"""Interface Streamlit (refonte D-76) pilotee par AppTest, avec le faux LLM (aucun appel reseau).

Premiere ouverture, profil, accueil, projet par la conversation, navigation, pages Mes taches
et Historique, puis les fonctions historiques (plan, propositions, taches, recherche R1 a R6)
dans l'interieur d'un projet.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[2] / "ui" / "app.py"
VAGUE = "Je veux lancer un atelier, par où commencer ?"
# D-84 : le plan est prepare a sa demande (6/6 simulations validees).
DETAILS = (
    "Trouver trois premiers clients. J'ai 45 minutes par jour et 50 € de budget. "
    "Proposez-moi un plan."
)
IDEA = "Je veux vendre des bougies parfumées artisanales à Lyon."


def _env(tmp_path, monkeypatch, *, simulation: bool = False) -> Path:
    data = tmp_path / "data"
    monkeypatch.setenv("NEUROCOACH_DATA_DIR", str(data))
    monkeypatch.setenv("NEUROCOACH_LLM_PROVIDER", "fake")
    if simulation:
        monkeypatch.setenv("NEUROCOACH_RESEARCH_SIMULATION", "1")
    return data


def _start(**query: str) -> AppTest:
    test = AppTest.from_file(str(APP), default_timeout=60)
    for key, value in query.items():
        test.query_params[key] = value
    test.run()
    assert not test.exception, test.exception
    return test


@pytest.fixture(autouse=True)
def _release_runtime():
    yield
    import streamlit as st

    st.cache_resource.clear()  # ferme le checkpointer (on_release)


@pytest.fixture
def at(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    return _start()


def _seed_demo(data: Path) -> str:
    """Espaces de demonstration crees comme par ``dev.py seed`` (jamais a l'ouverture)."""
    from neurocoach.bootstrap import build_application
    from neurocoach.config import Settings
    from neurocoach.demo import DEMO_ALICE_ID, seed_demo

    app = build_application(Settings(data_dir=data))
    seed_demo(app)
    return app.coach.list_projects(DEMO_ALICE_ID)[0].id


@pytest.fixture
def demo(tmp_path, monkeypatch):
    """Projet de demonstration d'Alice (T1 terminee sur 3), ouvert directement."""
    from neurocoach.demo import DEMO_ALICE_ID

    project_id = _seed_demo(_env(tmp_path, monkeypatch))
    return _start(u=DEMO_ALICE_ID, p="projet", id=project_id)


@pytest.fixture
def demo_sim(tmp_path, monkeypatch):
    from neurocoach.demo import DEMO_ALICE_ID

    project_id = _seed_demo(_env(tmp_path, monkeypatch, simulation=True))
    return _start(u=DEMO_ALICE_ID, p="projet", id=project_id)


def _ok(at: AppTest) -> None:
    assert not at.exception, at.exception


def _chat(at: AppTest) -> list[str]:
    return [message.markdown[0].value for message in at.chat_message if message.markdown]


def _markdown(at: AppTest) -> list[str]:
    # Les textes venus du Web sont echappes : on compare le texte affiche sans les barres.
    return [element.value.replace("\\", "") for element in at.markdown]


def _keys(at: AppTest, prefix: str) -> list[str]:
    return [button.key for button in at.button if button.key and button.key.startswith(prefix)]


def _button_key(at: AppTest, label: str) -> str:
    return next(button.key for button in at.button if button.label == label)


def _task_id(at: AppTest, ref: str) -> str:
    return _button_key(at, f"Marquer terminée {ref}").removeprefix("status_done_")


def _html(at: AppTest) -> str:
    return " ".join(str(element.proto.body) for element in at.get("html"))


def _register(at: AppTest, first="Marie", last="Dupont", username="marie.d") -> None:
    at.text_input(key="profile_first").input(first)
    at.text_input(key="profile_last").input(last)
    at.text_input(key="profile_username").input(username)
    at.button(key="create_space").click().run()
    _ok(at)


def _nav(at: AppTest, page: str) -> None:
    key = next(k for k in _keys(at, "nav_") if k.endswith(f"_{page}"))
    at.button(key=key).click().run()
    _ok(at)


def _new_project(at: AppTest) -> None:
    at.button(key="go_create").click().run()
    _ok(at)


# --- premiere ouverture et profil -----------------------------------------------------------


def test_first_opening_shows_the_welcome_page_and_no_fictitious_project(at):
    html = _html(at)
    assert "Bienvenue sur NeuroEntrepreneur" in html
    assert "Votre coach IA pour transformer vos idées en projets concrets" in html
    assert [s.value for s in at.subheader] == ["Créer votre profil"]
    assert [b.label for b in at.button if b.key == "create_space"] == ["Créer mon espace"]
    assert not _keys(at, "nav_")  # aucune navigation avant le profil
    assert "Bougies artisanales" not in " ".join(_markdown(at)) + html
    assert "Ce n'est ni un mot de passe" in " ".join(c.value for c in at.caption)


def test_profile_creation_opens_the_dashboard(at):
    _register(at)
    assert at.query_params["p"] == ["accueil"] or at.query_params["p"] == "accueil"
    html = _html(at)
    assert "Bonjour Marie !" in html
    assert at.button(key="go_create").label == "Créer votre projet"
    assert "Projets actifs" in html and "Aucune tâche prioritaire" in html
    assert sorted(k.split("_")[-1] for k in _keys(at, "nav_")) == sorted(
        ["accueil", "projets", "taches", "historique", "parametres", "profil"]
    )
    assert _keys(at, "nav_on_") == ["nav_on_accueil"]


@pytest.mark.parametrize("variant", ["MARIE.D", "  marie.d  "])
def test_a_taken_username_is_refused_whatever_the_case_or_spaces(at, variant):
    _register(at)
    _nav(at, "profil")
    at.button(key="leave_space").click().run()
    _ok(at)
    _register(at, "Paul", "Martin", variant)
    assert [e.value for e in at.error] == [
        "Ce nom d'utilisateur est déjà pris. Choisissez-en un autre."
    ]
    assert "Bonjour" not in _html(at)


def test_profile_errors_are_understandable(at):
    _register(at, "Marie", "", "m")
    assert [e.value for e in at.error] == ["Indiquez votre nom."]


def test_an_existing_space_can_be_reopened_by_its_username(at):
    _register(at)
    _nav(at, "profil")
    at.button(key="leave_space").click().run()
    at.text_input(key="reopen_username").input(" MARIE.D ")
    at.button(key="reopen_space").click().run()
    _ok(at)
    assert "Bonjour Marie !" in _html(at)


# --- projet commence par la conversation ----------------------------------------------------


def test_create_project_opens_a_centered_composer_until_the_first_message(at):
    _register(at)
    _new_project(at)
    assert at.query_params["p"] in ("projet", ["projet"])
    assert "Quel est votre prochain projet ?" in _html(at)
    assert not _chat(at)
    assert at.chat_input(key="chat").placeholder == "Décrivez votre idée ou votre objectif…"
    at.run()
    assert not _chat(at)
    at.chat_input(key="chat").set_value(IDEA).run()
    _ok(at)
    assert len(_chat(at)) == 3
    assert _chat(at)[1] == IDEA
    assert "Quel est votre prochain projet ?" not in _html(at)
    assert not any(item.label == "Ce que le coach a retenu" for item in at.expander)


def test_the_coach_saves_a_short_title_and_updates_the_sidebar(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(IDEA).run()
    _ok(at)
    assert len(_chat(at)) == 3
    assert '<p class="ne-chat-sub">Bougies parfumées artisanales</p>' in _html(at)
    active = at.button(key=_keys(at, "recent_on_")[0])
    assert active.label == "Bougies parfumées artisanales"


def test_coach_answers_a_social_greeting_then_handles_the_project(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value("Salut Cv vous allez bien").run()
    _ok(at)
    assert _chat(at)[-1] == "Ça va bien, merci ! Et vous ?"
    at.chat_input(key="chat").set_value(IDEA).run()
    _ok(at)
    assert at.button(key=_keys(at, "recent_on_")[0]).label == "Bougies parfumées artisanales"


def test_add_tasks_to_a_draft_requires_confirmation_and_survives_status_question(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value("Ajouter la tâche « Relire les fiches de maths »").run()
    _ok(at)
    confirm = _keys(at, "confirm_pac_")[0]
    at.chat_input(key="chat").set_value("Tu as ajouté ce plan aux tâches ?").run()
    _ok(at)
    assert _keys(at, "confirm_pac_") == [confirm]
    at.button(key=confirm).click().run()
    _ok(at)
    _nav(at, "taches")
    assert "Relire les fiches de maths" in " ".join(_markdown(at))


def test_editing_a_message_replaces_the_rest_of_the_conversation(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value("Salut cv").run()
    at.chat_input(key="chat").set_value(IDEA).run()
    at.chat_input(key="chat").set_value("Je veux continuer cette idée.").run()
    at.text_area[1].set_value("Bonjour")
    at.button(key=_keys(at, "FormSubmitter:form_edit_message_")[1]).click().run()
    _ok(at)
    assert _chat(at)[1:] == [
        "Salut cv",
        "Ça va bien, merci ! Et vous ?",
        "Bonjour",
        "Bonjour ! Comment allez-vous ?",
    ]
    at.run()
    assert _chat(at)[-2] == "Bonjour"


def test_a_started_chat_survives_a_page_change(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(IDEA).run()
    _nav(at, "historique")
    assert "Bougies parfumées artisanales" in " ".join(_markdown(at))
    at.button(key=_keys(at, "history_open_")[0]).click().run()
    _ok(at)
    assert _chat(at)[1] == IDEA


def test_recent_conversations_reopen_the_saved_project(at):
    _register(at)
    assert not _keys(at, "recent_")
    _new_project(at)
    project_id = _keys(at, "recent_on_")[0].removeprefix("recent_on_")
    at.chat_input(key="chat").set_value(IDEA).run()
    _nav(at, "accueil")
    at.button(key=f"recent_{project_id}").click().run()
    _ok(at)
    assert _chat(at)[1] == IDEA
    assert _keys(at, "recent_on_") == [f"recent_on_{project_id}"]


def test_the_dashboard_resumes_recent_projects_with_real_progress(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(VAGUE).run()
    at.chat_input(key="chat").set_value(DETAILS).run()
    at.button(key=_keys(at, "confirm_pac_")[0]).click().run()
    _nav(at, "accueil")
    assert "Tâches prioritaires" in [element.value for element in at.subheader]
    assert "<strong>3</strong><small>Tâches en attente</small>" in _html(at)
    assert _keys(at, "resume_")
    resume = _keys(at, "resume_")[0]
    at.button(key=resume).click().run()
    _ok(at)
    assert _keys(at, "recent_on_") == [resume.replace("resume_", "recent_on_", 1)]


def test_dashboard_composer_opens_the_project_with_the_first_message(at):
    _register(at)
    at.chat_input(key="chat").set_value(IDEA).run()
    _ok(at)
    assert at.query_params["p"] in ("projet", ["projet"])
    assert _chat(at)[1] == IDEA


# --- navigation et pages ---------------------------------------------------------------------


def test_navigation_reaches_every_page(at):
    _register(at)
    expected = {
        "projets": "Mes projets",
        "taches": "Mes tâches",
        "historique": "Historique",
        "parametres": "Paramètres",
        "profil": "Mon profil",
        "accueil": "Bonjour Marie !",
    }
    for page, title in expected.items():
        _nav(at, page)
        assert title in _html(at), page
        assert _keys(at, "nav_on_") == [f"nav_on_{'projets' if page == 'projet' else page}"]


def test_empty_states_are_explicit(at):
    _register(at)
    _nav(at, "projets")
    assert "Aucun projet pour le moment" in _html(at)
    _nav(at, "taches")
    assert "Aucune tâche pour le moment" in _html(at)
    _nav(at, "historique")
    assert "Aucune conversation enregistrée." in [c.value for c in at.caption]


def test_projects_and_tasks_of_another_user_are_never_shown(tmp_path, monkeypatch):
    project_id = _seed_demo(_env(tmp_path, monkeypatch))
    at = _start()
    _register(at)
    for page in ("projets", "taches", "historique"):
        _nav(at, page)
        text = " ".join(_markdown(at)) + _html(at)
        assert "Bougies artisanales" not in text and "Atelier de réparation" not in text
    # Un projet d'un autre espace, meme par son adresse, reste inaccessible.
    at.query_params["p"] = "projet"
    at.query_params["id"] = project_id
    at.run()
    _ok(at)
    assert "n'appartient pas à cet espace" in " ".join(i.value for i in at.info)


def test_my_tasks_groups_real_statuses_and_opens_the_project(demo):
    at = demo
    _nav(at, "taches")
    labels = [tab.label for tab in at.tabs]
    assert labels[:4] == ["À faire (2)", "En cours (0)", "Bloquées (0)", "Terminées (1)"]
    assert not _keys(at, "status_")  # lecture seule : les changements se font dans le projet
    at.button(key=_keys(at, "task_open_")[0]).click().run()
    _ok(at)
    assert '<p class="ne-chat-sub">Bougies artisanales</p>' in _html(at)


def test_history_shows_persisted_events_and_states_its_limits(demo):
    at = demo
    _nav(at, "historique")
    captions = " ".join(c.value for c in at.caption)
    assert "les messages ne sont pas horodatés un par un" in captions
    journal = " ".join(_markdown(at))
    assert "Plan enregistré" in journal and "Statut d'une tâche changé" in journal
    assert "Proposition présentée" not in journal  # details techniques masques par defaut


def test_profile_names_can_be_updated(at):
    _register(at)
    _nav(at, "profil")
    at.text_input(key="edit_first").input("Marie-Anne")
    at.button(key="profile_save").click().run()
    _ok(at)
    assert "Marie-Anne Dupont" in " ".join(m.value for m in at.markdown)


def test_resume_after_restart_keeps_the_conversation(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch)
    at = _start()
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(IDEA).run()
    before = _chat(at)
    user, project = at.query_params["u"], at.query_params["id"]
    import streamlit as st

    st.cache_resource.clear()  # « fermeture » de l'application
    again = _start(u=user if isinstance(user, str) else user[0],
                   p="projet", id=project if isinstance(project, str) else project[0])  # fmt: skip
    assert _chat(again) == before


def test_the_layout_is_responsive():
    from neuro_ui.theme import CSS

    assert "@media (max-width: 640px)" in CSS  # marges reduites, cartes empilees
    source = (APP.parent / "neuro_ui" / "screens.py").read_text(encoding="utf-8")
    assert "st.columns(2" in source  # colonnes natives : empilees sur telephone


# --- interieur d'un projet : fonctions historiques ------------------------------------------


def test_return_shows_a_factual_summary_and_next_action(demo):
    assert '<p class="ne-chat-sub">Bougies artisanales</p>' in _html(demo)
    assert "Vous avez terminé 1 tâche sur 3. Prochaine action : T2" in " ".join(_markdown(demo))


def test_status_question_answers_from_the_database(demo):
    demo.chat_input(key="chat").set_value("Où en suis-je ?").run()
    _ok(demo)
    messages = _chat(demo)
    assert messages[-2] == "Où en suis-je ?"
    assert messages[-1].startswith("1 tâche terminée sur 3")


def test_new_project_plan_confirmation_from_the_ui(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(VAGUE).run()
    at.chat_input(key="chat").set_value(DETAILS).run()
    _ok(at)
    assert "Proposition en attente de votre accord" in [s.value for s in at.subheader]
    at.button(key=_keys(at, "confirm_pac_")[0]).click().run()
    _ok(at)
    assert _chat(at)[-1].startswith(
        "Le plan est enregistré. Première action : T1 « Décrire le client visé »."
    )
    assert _keys(at, "confirm_pac_") == []


def test_plan_proposal_can_be_edited_before_confirmation(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(VAGUE).run()
    at.chat_input(key="chat").set_value(DETAILS).run()
    at.text_input(key="edit_title_client").input("Décrire ma cliente idéale")
    at.checkbox(key="edit_remove_entretiens").check()
    at.button(key="revise_submit").click().run()
    _ok(at)
    assert _chat(at)[-1].startswith("Proposition mise à jour :")
    assert "Nouvelle tâche T1 : « Décrire ma cliente idéale »" in _chat(at)[-1]
    assert "Interroger trois personnes" not in _chat(at)[-1]


def test_affirmative_chat_reply_keeps_the_proposal_pending(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(VAGUE).run()
    at.chat_input(key="chat").set_value(DETAILS).run()
    at.chat_input(key="chat").set_value("Oui").run()
    _ok(at)
    assert at.info[0].value.startswith("Pour enregistrer cette proposition")
    assert _keys(at, "confirm_pac_")


def test_tasks_are_grouped_by_phase_with_dependencies(demo):
    assert any(item.label.startswith("Valider l'intérêt") for item in demo.expander)
    captions = [caption.value for caption in demo.caption]
    assert "Dépendances : Après T1 (terminée)." in captions
    assert "Dépendances : Après T2 (à faire). En attente de T2." in captions
    labels = [button.label for button in demo.button]
    assert "Rouvrir T1" in labels and "Commencer T1" not in labels


def test_blocking_requires_and_shows_a_reason(demo):
    at = demo
    task_key = _task_id(at, "T2")
    at.checkbox(key=f"block_toggle_{task_key}").check().run()
    at.button(key=f"block_submit_{task_key}").click().run()
    _ok(at)
    assert at.error[0].value == "Indiquez une raison d'au moins 3 caractères."
    at.checkbox(key=f"block_toggle_{task_key}").check().run()
    at.text_input(key=f"block_reason_{task_key}").input("En attente d'un devis")
    at.button(key=f"block_submit_{task_key}").click().run()
    _ok(at)
    assert "Blocage : En attente d'un devis" in [w.value for w in at.warning]
    toggle = at.checkbox(key=f"block_toggle_{task_key}")
    assert toggle.value is False
    assert toggle.label == "Modifier la raison du blocage de T2"
    assert at.success[0].value.startswith("T2 est maintenant bloquée")
    assert [b.label for b in at.button if b.key == "undo"] == ["Annuler ce changement (T2)"]


def test_controls_have_unique_accessible_labels(demo):
    labels = [checkbox.label for checkbox in demo.checkbox]
    assert len(labels) == len(set(labels))
    assert "Signaler un blocage sur T2" in labels


def test_task_buttons_change_status_and_can_be_undone(demo):
    at = demo
    at.button(key=_button_key(at, "Commencer T2")).click().run()
    assert at.success[0].value.startswith("T2 est maintenant en cours")
    at.button(key="undo").click().run()
    _ok(at)
    assert at.success[0].value == "Changement annulé pour T2."
    assert "Statut : **à faire**" in " ".join(_markdown(at))


def test_preferences_limit_visible_actions_and_shorten_display(demo):
    at = demo
    _nav(at, "parametres")
    length = next(box for box in at.selectbox if box.label == "Longueur des réponses")
    length.set_value("court")
    at.button(key="save_prefs").click().run()
    _ok(at)
    assert at.success[0].value == "Préférences enregistrées."
    at.button(key=_keys(at, "nav_projets")[0]).click().run()
    at.button(key=_keys(at, "open_")[0]).click().run()
    _ok(at)
    assert not any(c.value.startswith("Critère de fin") for c in at.caption)


def test_plan_editor_labels_are_unique(at):
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value(VAGUE).run()
    at.chat_input(key="chat").set_value(DETAILS).run()
    labels = [field.label for field in at.text_input] + [box.label for box in at.checkbox]
    assert "Retirer la tâche 3 « Interroger trois personnes »" in labels
    assert len(labels) == len(set(labels))


def test_export_is_prepared_on_demand_and_invalidated_on_deletion(demo):
    at = demo
    _nav(at, "parametres")
    at.button(key="prepare_export").click().run()
    assert [b.label for b in at.get("download_button")] == ["Télécharger l'export (JSON)"]
    at.button(key=_keys(at, "nav_projets")[0]).click().run()
    at.button(key=_keys(at, "open_")[0]).click().run()
    at.button(key="delete_project").click().run()
    at.button(key=_keys(at, "confirm_pac_")[0]).click().run()
    _ok(at)
    _nav(at, "parametres")
    assert at.get("download_button") == []


def test_project_deletion_requires_confirmation(demo):
    at = demo
    at.button(key="delete_project").click().run()
    assert "Confirmation requise" in [s.value for s in at.subheader]
    at.button(key=_keys(at, "confirm_pac_")[0]).click().run()
    _ok(at)
    assert at.query_params["p"] in ("projets", ["projets"])
    assert "a été supprimé" in at.success[0].value


def test_project_list_supports_renaming_and_confirmed_deletion(demo):
    _nav(demo, "projets")
    demo.text_input[0].set_value("Atelier créatif pour les familles du quartier")
    demo.button(key=_keys(demo, "FormSubmitter:rename_")[0]).click().run()
    _ok(demo)
    assert "Atelier créatif pour les familles du quartier" in _html(demo)
    assert demo.button(key=_keys(demo, "recent_")[0]).label == "Atelier créatif"
    demo.text_input[0].set_value("Un titre qui contient plus de sept mots")
    demo.button(key=_keys(demo, "FormSubmitter:rename_")[0]).click().run()
    assert any("7 mots" in error.value for error in demo.error)
    demo.button(key=_keys(demo, "delete_")[0]).click().run()
    assert _keys(demo, "recent_")
    demo.button(key=_keys(demo, "confirm_")[0]).click().run()
    _ok(demo)
    assert not _keys(demo, "recent_")


def test_chat_messages_have_distinct_avatars_and_spoken_labels(demo):
    demo.chat_input(key="chat").set_value("Où en suis-je ?").run()
    _ok(demo)
    avatars = {message.proto.avatar for message in demo.chat_message}
    assert len(avatars) == 2
    assert "Votre coach :" in _html(demo) and "Vous :" in _html(demo)


def test_headings_have_no_focusable_anchor(demo):
    headings = [*demo.title, *demo.subheader]
    assert '<h1 class="ne-chat-title">Votre coach entrepreneurial</h1>' in _html(demo)
    assert all(heading.proto.hide_anchor for heading in headings)


def test_research_tab_explains_activation_without_keys(demo):
    notes = " ".join(i.value for i in demo.info)
    assert "TAVILY_API_KEY" in notes and "EXA_API_KEY" in notes
    assert not [b for b in demo.button if b.label == "Préparer la mission"]


def test_research_tab_runs_an_approved_simulated_mission(demo_sim):
    at = demo_sim
    infos = " ".join(i.value for i in at.info)
    assert "Recherche **simulée** (mode démonstration)" in infos
    market = next(item for item in at.text_input if item.label.startswith("Marché"))
    market.input("France")
    next(b for b in at.button if b.label == "Préparer la mission").click().run()
    _ok(at)
    text = " ".join(_markdown(at))
    assert "Ce que vous approuvez" in text and "SIMULÉ (aucun appel réel)" in text
    assert not _keys(at, "run_")  # rien ne se lance avant l'approbation
    at.button(key=_button_key(at, "Approuver la mission")).click().run()
    at.button(key=_button_key(at, "Lancer les recherches prévues")).click().run()
    _ok(at)
    text = " ".join(_markdown(at))
    assert "Fait sourcé (SIMULÉ)" in text and "[SIMULÉ]" in text
    at.button(key=_button_key(at, "Analyser ces résultats")).click().run()
    _ok(at)
    text = " ".join(_markdown(at))
    assert "Voici mon analyse" in text and "Recommandation" in text


def test_chat_research_requires_the_approval_button(demo_sim):
    at = demo_sim
    at.chat_input(key="chat").set_value("Qui sont mes concurrents à Lyon ?").run()
    _ok(at)
    assert "Voici la recherche que je vous propose" in " ".join(_chat(at))
    at.chat_input(key="chat").set_value("oui").run()
    assert "Approuver et lancer" in " ".join(i.value for i in at.info)
    next(b for b in at.button if b.label == "Approuver et lancer").click().run()
    _ok(at)
    replies = " ".join(_chat(at)).replace("\\", "")
    # D-82 : conclusion courte dans la conversation, detail (resultats, analyse) replie.
    assert "[Conclusion simulée]" in replies
    assert "Résultats simulés, fictifs" in " ".join(_markdown(at))  # D-84 : sans journal


def test_chat_solutions_flow_ends_in_a_confirmable_task_proposal(tmp_path, monkeypatch):
    _env(tmp_path, monkeypatch, simulation=True)
    at = _start()
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value("Que disent les clients sur les forums ?").run()
    next(b for b in at.button if b.label == "Approuver et lancer").click().run()
    at.chat_input(key="chat").set_value("analyse").run()
    at.chat_input(key="chat").set_value("Cherche des solutions à ces problèmes").run()
    _ok(at)
    next(b for b in at.button if b.label == "Approuver et lancer").click().run()
    _ok(at)
    assert "Voici les solutions trouvées" in " ".join(_chat(at)).replace("\\", "")
    at.chat_input(key="chat").set_value("Transforme ces actions en tâches").run()
    _ok(at)
    assert "Voici la proposition de plan" in " ".join(_chat(at))
    assert _keys(at, "confirm_") and not _keys(at, "status_done_")


def test_after_a_research_no_screen_pushes_a_plan(tmp_path, monkeypatch):
    """D-80 : recette du 12/11/2026, « Étape suivante : construire votre plan » s'affichait
    sous une reponse du coach qui jugeait les donnees insuffisantes et apres « Ne construisez
    aucun plan ». Le moment du plan se decide dans la conversation, nulle part ailleurs."""
    _env(tmp_path, monkeypatch, simulation=True)
    at = _start()
    _register(at)
    _new_project(at)
    at.chat_input(key="chat").set_value("Qui sont les concurrents des bougies à Lyon ?").run()
    next(b for b in at.button if b.label == "Approuver et lancer").click().run()
    _ok(at)
    at.chat_input(key="chat").set_value("Analysez ces résultats. Ne construisez aucun plan.").run()
    _ok(at)
    page = " ".join(_markdown(at))
    assert not _keys(at, "prepare_plan") and "construire votre plan" not in page
    assert not _keys(at, "confirm_")  # aucune proposition de plan


# D-85 : badge et boutons des cartes de pause, reprise et taches terminees.
def test_a_paused_project_is_shown_as_paused():
    import sys
    from types import SimpleNamespace

    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "ui"))
    from neuro_ui.project_view import CARD_BUTTONS, project_state

    paused = SimpleNamespace(paused_at=object(), status=SimpleNamespace(value="active"))
    assert project_state(paused, SimpleNamespace(total=3, done=1)) == ("En pause", "")
    assert CARD_BUTTONS["pause"] == ("Mettre en pause", "Continuer sans pause")
    assert CARD_BUTTONS["tasks_done"][0] == "Confirmer les tâches terminées"
    assert CARD_BUTTONS["resume"] == ("Reprendre le projet", "Rester en pause")
