"""D-77 : faits connus lus dans ce que l'utilisateur a ecrit, sans rien inventer."""

from __future__ import annotations

import pytest

from neurocoach.domain.project_profile import extract_known, recap, second_person

RECETTE = (
    "Mon idée est de créer une petite marque de bougies artisanales parfumées à Lyon. Je débute "
    "complètement, j'ai un budget maximum de 500 € et je peux consacrer environ 8 heures par "
    "semaine à ce projet. Mon objectif est de réaliser mes premières ventes dans trois mois. Je "
    "ne veux pas de dates limites imposées pour mes tâches. Pouvez-vous m'aider à structurer ce "
    "projet progressivement ?"
)


def test_the_manual_test_message_is_fully_understood():
    known = extract_known([RECETTE])
    assert (known.budget_eur, known.weekly_hours, known.city) == (500, 8.0, "Lyon")
    assert known.objective == "Réaliser mes premières ventes dans trois mois"
    assert (known.horizon_text, known.horizon_days) == ("dans trois mois", 90)
    assert known.beginner and known.no_deadlines and known.progressive
    assert known.schedule is None and known.daily_minutes is None


@pytest.mark.parametrize(
    ("answer", "schedule", "session"),
    [
        ("Plutôt le week-end.", "le week-end", 240),
        ("Le soir après le travail", "en soirée", 95),
        ("Le mardi et le jeudi", "le mardi, le jeudi", 240),
        ("Un peu tous les jours", "chaque jour", 70),
    ],
)
def test_the_weekly_time_is_split_as_the_user_says(answer, schedule, session):
    known = extract_known([RECETTE, answer])
    assert known.schedule == schedule
    assert known.session_minutes() == session


def test_a_skipped_schedule_is_remembered_once_asked():
    assert extract_known([RECETTE, "Je ne sais pas"], asked_schedule=True).schedule == (
        "non précisée"
    )
    assert extract_known([RECETTE, "Je ne sais pas"]).schedule is None


def test_words_that_only_contain_a_schedule_are_not_one():
    """« provisoire » contient « soir » : ce n'est pas une repartition (constate en test)."""
    assert extract_known(["plan provisoire"]).schedule is None


def test_information_spread_over_messages_and_another_domain():
    known = extract_known(
        [
            "Je veux ouvrir un food truck de galettes à Nantes.",
            "J'ai 3000 euros de budget.",
            "Je peux y passer 45 minutes par jour.",
            "Mon objectif : trouver 10 clients d'ici deux mois.",
        ]
    )
    assert (known.city, known.budget_eur, known.daily_minutes) == ("Nantes", 3000, 45)
    assert known.objective == "Trouver 10 clients d'ici deux mois"
    assert known.horizon_days == 60 and known.session_minutes() == 45


def test_the_latest_value_wins():
    known = extract_known(["J'ai un budget de 500 €.", "Finalement, mon budget est de 800 €."])
    assert known.budget_eur == 800


def test_nothing_is_invented():
    known = extract_known(["Je veux vendre des bougies."])
    assert known.as_facts() == {}
    assert recap(known, None) == ""


def test_the_recap_rephrases_in_the_second_person():
    text = recap(extract_known([RECETTE]), "bougies artisanales parfumées")
    assert text == (
        "Vous souhaitez lancer : bougies artisanales parfumées à Lyon, avec un budget de 500 € "
        "et environ 8 heures par semaine. Vous débutez dans ce domaine. Votre objectif : "
        "réaliser vos premières ventes dans trois mois."
    )
    assert second_person("mes clients et mon atelier") == "vos clients et votre atelier"
