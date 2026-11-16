"""Parcours Streamlit avec GPT-5 mini réel et recherche simulée."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import streamlit as st
from streamlit.testing.v1 import AppTest

from neurocoach.agent.coaching import revision_capacity_errors
from neurocoach.bootstrap import build_application
from neurocoach.config import Settings
from neurocoach.domain.models import TaskStatus

ROOT = Path(__file__).resolve().parents[1]


def run() -> None:
    if os.environ.get("NEUROCOACH_LLM_PROVIDER") != "openai" or not os.environ.get(
        "NEUROCOACH_SPENDING_CAP_USD"
    ):
        raise SystemExit("Configurer le fournisseur OpenAI et le plafond avant la recette.")
    with tempfile.TemporaryDirectory() as directory:
        os.environ["NEUROCOACH_DATA_DIR"] = directory
        os.environ["NEUROCOACH_RESEARCH_SIMULATION"] = "1"
        try:
            journey()
        finally:
            st.cache_resource.clear()


def journey() -> None:
    at = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=180).run()

    def click(prefix: str) -> None:
        button = next((b for b in at.button if (b.key or "").startswith(prefix)), None)
        assert button is not None, (prefix, [(b.key, b.label) for b in at.button])
        button.click().run()
        assert not at.exception, at.exception
        print(f"Clic : {button.label}", flush=True)

    def say(message: str) -> None:
        at.chat_input(key="chat").set_value(message).run()
        assert not at.exception, at.exception
        print(f"Utilisateur : {message}", flush=True)
        for bubble in at.chat_message[-1:]:
            print("\n".join(block.value for block in bubble.markdown), flush=True)

    for key, value in (
        ("profile_first", "Camille"),
        ("profile_last", "Test"),
        ("profile_username", "camille.recette"),
    ):
        at.text_input(key=key).input(value)
    click("create_space")
    click("go_create")
    app = build_application(Settings.from_env())
    user_id = at.query_params["u"]
    project_id = at.query_params["id"]

    def tasks():
        return app.coach.get_snapshot(user_id, project_id).ordered_tasks()

    say(
        "J'aide déjà mes amis à corriger leurs CV. J'avais vendu zéro planner sur Etsy, "
        "faute de visiteurs. Je vise 120 € par mois avec un service de CV à distance "
        "pour étudiants en Belgique. J'ai 4 heures par semaine et 50 € maximum."
    )
    if "--sans-recherche" not in sys.argv:
        say("Pas de recherche maintenant. Pourquoi privilégier un service personnalisé ?")
        assert not any((b.key or "").startswith("research_go_") for b in at.button)
        say("Vérifiez maintenant le marché belge, les concurrents et les prix de ce service de CV.")
        click("research_go_")
    say("Préparez-moi un plan détaillé pour tester ce service de CV. Sans dates limites.")
    assert not tasks()
    click("cancel_pac_")
    assert not tasks()
    say("Je préfère contacter des associations étudiantes, sans démarcher les étudiants.")
    click("confirm_pac_")
    assert tasks() and all(task.due_date is None for task in tasks())
    say("J'ai terminé la tâche T1.")
    done = tasks()[0]
    assert done.status == TaskStatus.DONE
    say("Deux associations refusent de partager une offre commerciale. Je suis bloquée.")
    say("Je veux mettre le projet en pause.")
    click("confirm_pac_")
    assert app.coach.get_project(user_id, project_id).paused_at is not None
    st.cache_resource.clear()
    at.run()
    say("Je veux reprendre le projet. Je n'ai plus que deux heures par semaine.")
    click("confirm_pac_")
    assert app.coach.get_project(user_id, project_id).paused_at is None
    before = app.coach.get_snapshot(user_id, project_id)
    say("Adaptez le plan à deux heures par semaine, sans échéances, avec mon réseau personnel.")
    click("confirm_pac_")
    at.run()
    assert next(task for task in tasks() if task.id == done.id) == done
    assert all(task.due_date is None for task in tasks())
    assert not revision_capacity_errors(before, app.coach.get_snapshot(user_id, project_id), 120)
    say("Où en suis-je ?")
    print("Contrôles SQLite et Streamlit terminés.", flush=True)


if __name__ == "__main__":
    run()
