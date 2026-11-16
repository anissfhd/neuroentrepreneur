"""Donnees de demonstration fictives (deux utilisateurs locaux, sans authentification).

R-SEC-01 : ce mecanisme sert uniquement aux tests et a la demonstration locale ; il ne
constitue pas une authentification et interdit tout deploiement public en l'etat.
"""

from __future__ import annotations

import uuid
from typing import Any

from neurocoach.bootstrap import Application
from neurocoach.domain.models import TaskStatus
from neurocoach.domain.plans import BriefUpdate, PlanDraft


def _demo_id(name: str) -> str:
    return "usr_" + uuid.uuid5(uuid.NAMESPACE_URL, f"https://neurocoach.local/demo/{name}").hex


DEMO_ALICE_ID = _demo_id("alice")
DEMO_BRUNO_ID = _demo_id("bruno")
DEMO_USERS = ((DEMO_ALICE_ID, "Alice (démo)"), (DEMO_BRUNO_ID, "Bruno (démo)"))
DEMO_USERNAMES = {DEMO_ALICE_ID: "alice-demo", DEMO_BRUNO_ID: "bruno-demo"}

CANDLE_PLAN = PlanDraft(
    objective="Tester en deux semaines si des personnes seraient intéressées par mes bougies",
    assumptions=["30 minutes disponibles par jour"],
    phases=[
        {
            "title": "Valider l'intérêt",
            "exit_criterion": "Trois retours de clients potentiels recueillis",
            "tasks": [
                {
                    "key": "client",
                    "title": "Décrire le client visé",
                    "acceptance_criteria": "Une phrase décrit le client idéal",
                    "estimate_minutes": 20,
                    "priority": 4,
                },
                {
                    "key": "questions",
                    "title": "Préparer cinq questions",
                    "acceptance_criteria": "Cinq questions ouvertes sont rédigées",
                    "estimate_minutes": 30,
                    "depends_on": ["client"],
                },
                {
                    "key": "entretiens",
                    "title": "Interroger trois personnes",
                    "acceptance_criteria": "Trois échanges sont notés",
                    "estimate_minutes": 30,
                    "depends_on": ["questions"],
                },
            ],
        }
    ],
)


def seed_demo(app: Application) -> dict[str, Any]:
    """Idempotent : cree les deux utilisateurs et, s'ils n'existent pas, leurs projets."""
    for user_id, name in DEMO_USERS:
        # D-76 : espaces de demonstration rouvrables par leur nom d'utilisateur (jamais imposes
        # a l'ouverture de l'interface ; ``dev.py seed`` seulement).
        app.coach.ensure_user(user_id, name, username=DEMO_USERNAMES[user_id])

    summary: dict[str, Any] = {"users": [name for _, name in DEMO_USERS], "created": []}
    if not app.coach.list_projects(DEMO_ALICE_ID):
        project = app.coach.create_project(
            DEMO_ALICE_ID,
            "Bougies artisanales",
            "Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer.",
        )
        action = app.actions.request_plan(
            DEMO_ALICE_ID,
            project.id,
            CANDLE_PLAN,
            BriefUpdate(available_minutes_per_day=30, constraints=["30 minutes par jour"]),
        )
        app.actions.confirm(DEMO_ALICE_ID, action.id)
        first = app.coach.list_tasks(DEMO_ALICE_ID, project.id)[0]
        app.coach.set_task_status(DEMO_ALICE_ID, first.id, TaskStatus.DONE)
        summary["created"].append("Alice : projet « Bougies artisanales », 1 tâche sur 3 terminée")
    if not app.coach.list_projects(DEMO_BRUNO_ID):
        app.coach.create_project(DEMO_BRUNO_ID, "Atelier de réparation de vélos")
        summary["created"].append("Bruno : projet « Atelier de réparation de vélos » (brouillon)")
    return summary
