"""D-76 : profils locaux (prenom, nom, nom d'utilisateur unique) et projets ouverts sans titre.

Le nom d'utilisateur identifie un espace local ; ce n'est pas une authentification.
"""

from __future__ import annotations

import pytest

from neurocoach.demo import DEMO_ALICE_ID, seed_demo
from neurocoach.domain.errors import DomainError, ErrorCode
from neurocoach.domain.models import EventType
from neurocoach.domain.profiles import PLACEHOLDER_TITLE, suggest_title, username_key


def test_a_profile_is_created_with_its_preferences_and_logged(app):
    user = app.coach.register_user("  Marie ", "Dupont", "marie.d")
    assert (user.first_name, user.last_name, user.username) == ("Marie", "Dupont", "marie.d")
    assert user.display_name == "Marie Dupont"
    assert app.coach.get_user(user.id) == user
    assert app.coach.get_preferences(user.id).display_timezone == "Europe/Paris"
    assert [e.type for e in app.coach.list_events(user.id)] == [EventType.PROFILE_CREATED]


@pytest.mark.parametrize(
    "variant", ["marie.d", "MARIE.D", "  Marie.D  ", "\uff4d\uff41\uff52\uff49\uff45.\uff44"]
)
def test_usernames_are_unique_ignoring_case_spaces_and_width(app, variant):
    app.coach.register_user("Marie", "Dupont", "Marie.D")
    with pytest.raises(DomainError) as error:
        app.coach.register_user("Autre", "Personne", variant)
    assert error.value.code is ErrorCode.VALIDATION_ERROR
    assert "déjà pris" in error.value.user_message
    assert len([u for u in app.coach.list_users() if u.username]) == 1


@pytest.mark.parametrize(
    ("first", "last", "username", "expected"),
    [
        ("", "Dupont", "marie", "Indiquez votre prénom."),
        ("Marie", "   ", "marie", "Indiquez votre nom."),
        ("Marie2", "Dupont", "marie", "ne peut contenir que des lettres"),
        ("Marie", "Dupont", "ma", "entre 3 et 30 caractères"),
        ("Marie", "Dupont", "marie dupont", "sans espace"),
        ("Marie", "Dupont", "marie@x", "sans espace"),
        ("M" * 41, "Dupont", "marie", "au plus 40 caractères"),
    ],
)
def test_invalid_profiles_get_an_understandable_message(app, first, last, username, expected):
    with pytest.raises(DomainError) as error:
        app.coach.register_user(first, last, username)
    assert expected in error.value.user_message
    assert app.coach.list_users() == []


def test_accented_and_composed_names_are_accepted(app):
    user = app.coach.register_user("Anne-Sophie", "D\u2019Arc de l'Isle", "anne_so.2")
    assert user.last_name == "D\u2019Arc de l'Isle"


def test_an_existing_space_is_found_by_username_whatever_the_case(app):
    user = app.coach.register_user("Marie", "Dupont", "Marie.D")
    assert app.coach.find_user(" marie.d ") == user
    assert app.coach.find_user("inconnu") is None
    assert app.coach.find_user("   ") is None


def test_profile_names_can_change_but_not_the_username(app):
    user = app.coach.register_user("Marie", "Dupont", "marie.d")
    changed = app.coach.update_profile(user.id, "Marie-Anne", "Durand")
    assert (changed.first_name, changed.last_name, changed.username) == (
        "Marie-Anne",
        "Durand",
        "marie.d",
    )
    assert changed.display_name == "Marie-Anne Durand"


def test_demo_spaces_get_readable_usernames_without_being_imposed(app):
    assert app.coach.list_users() == []  # rien n'est cree tant que la demo n'est pas demandee
    seed_demo(app)
    assert app.coach.find_user("alice-demo").id == DEMO_ALICE_ID


def test_username_key_normalisation():
    assert username_key("  Marie.D ") == username_key("marie.d") == "marie.d"


# --- projets commences par la conversation -----------------------------------------------


def test_a_project_can_start_without_a_title_and_is_reused_while_empty(app):
    user = app.coach.register_user("Marie", "Dupont", "marie.d")
    first = app.coach.start_project(user.id)
    assert (first.title, first.title_pending, first.status.value) == (
        PLACEHOLDER_TITLE,
        True,
        "draft",
    )
    assert app.coach.start_project(user.id).id == first.id  # pas de doublon vide
    app.coach.record_idea(user.id, first.id, "Je veux vendre des bougies parfumées.")
    second = app.coach.start_project(user.id)
    assert second.id != first.id


def test_the_first_idea_is_kept_and_never_overwritten(app):
    user = app.coach.register_user("Marie", "Dupont", "marie.d")
    project = app.coach.start_project(user.id)
    app.coach.record_idea(user.id, project.id, "Je veux vendre des bougies parfumées.")
    app.coach.record_idea(user.id, project.id, "Autre chose")
    assert app.coach.get_project(user.id, project.id).idea == (
        "Je veux vendre des bougies parfumées."
    )


def test_renaming_confirms_the_title_without_changing_the_version(app):
    user = app.coach.register_user("Marie", "Dupont", "marie.d")
    project = app.coach.start_project(user.id)
    renamed = app.coach.rename_project(user.id, project.id, "  Bougies   parfumées ")
    assert (renamed.title, renamed.title_pending, renamed.version) == (
        "Bougies parfumées",
        False,
        project.version,
    )
    event = app.coach.list_events(user.id, project.id)[-1]
    assert event.type is EventType.PROJECT_RENAMED
    assert event.payload == {"before": PLACEHOLDER_TITLE, "after": "Bougies parfumées"}
    with pytest.raises(DomainError):
        app.coach.rename_project(user.id, project.id, "ab")


def test_renaming_while_a_plan_waits_keeps_the_plan_confirmable(app):
    from factories import sample_plan

    user = app.coach.register_user("Marie", "Dupont", "marie.d")
    project = app.coach.start_project(user.id)
    action = app.actions.request_plan(user.id, project.id, sample_plan())
    app.coach.rename_project(user.id, project.id, "Bougies parfumées")
    app.actions.confirm(user.id, action.id)
    saved = app.coach.get_project(user.id, project.id)
    assert (saved.title, saved.status.value) == ("Bougies parfumées", "active")
    assert app.coach.get_progress(user.id, project.id).total > 0


def test_profiles_and_projects_stay_isolated(app):
    marie = app.coach.register_user("Marie", "Dupont", "marie.d")
    paul = app.coach.register_user("Paul", "Martin", "paul.m")
    project = app.coach.start_project(marie.id)
    assert app.coach.list_projects(paul.id) == []
    for attempt in (
        lambda: app.coach.rename_project(paul.id, project.id, "Volé"),
        lambda: app.coach.record_idea(paul.id, project.id, "Je veux vendre des bougies."),
        lambda: app.coach.get_project(paul.id, project.id),
    ):
        with pytest.raises(DomainError) as error:
            attempt()
        assert error.value.code is ErrorCode.NOT_FOUND
    assert app.coach.get_project(marie.id, project.id).title == PLACEHOLDER_TITLE


def test_last_activity_comes_from_the_event_journal(app):
    user = app.coach.register_user("Marie", "Dupont", "marie.d")
    project = app.coach.start_project(user.id)
    assert set(app.coach.last_activity(user.id)) == {project.id}


@pytest.mark.parametrize(
    ("idea", "title"),
    [
        (
            "Je veux vendre des bougies parfumées artisanales à Lyon, mais je ne sais pas.",
            "Bougies parfumées artisanales",
        ),
        ("Bonjour ! J'aimerais ouvrir un food truck de galettes", "Food truck de galettes"),
        (
            "J'ai une idée : une application de covoiturage scolaire pour les parents",
            "Application de covoiturage scolaire",
        ),
        ("Mon idée est de créer des cours de yoga en entreprise", "Cours de yoga en entreprise"),
        ("je sais pas trop", "Mon projet"),
        ("", "Mon projet"),
    ],
)
def test_suggested_titles_summarise_the_idea(idea, title):
    assert suggest_title(idea) == title
