"""Etat de la base de recette, en LECTURE SEULE (recette manuelle reelle).

Usage (PowerShell, depuis le dossier du projet) :
  .\\.venv\\Scripts\\python.exe scripts\\recette_etat.py            # resume de tous les projets
  .\\.venv\\Scripts\\python.exe scripts\\recette_etat.py --events 15 # + 15 derniers evenements

La base est ouverte en mode lecture seule (``mode=ro``) : ce script n'ecrit rien, n'appelle
aucun service externe et n'affiche aucune cle. Dossier lu : NEUROCOACH_DATA_DIR si la variable
est posee, sinon ``data-recette-reelle``.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATUS = {"todo": "à faire", "in_progress": "en cours", "blocked": "bloquée", "done": "terminée"}


def connect(data_dir: Path) -> sqlite3.Connection:
    db = data_dir / "neurocoach.sqlite"
    if not db.exists():
        sys.exit(f"Base introuvable : {db} (lancez d'abord l'application avec ce dossier).")
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def main(argv: list[str]) -> int:
    with __import__("contextlib").suppress(AttributeError, ValueError):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--events", type=int, default=8, help="derniers evenements affiches")
    args = parser.parse_args(argv)
    data_dir = Path(os.environ.get("NEUROCOACH_DATA_DIR") or ROOT / "data-recette-reelle")
    if not data_dir.is_absolute():
        data_dir = ROOT / data_dir
    conn = connect(data_dir)
    print(f"Base : {data_dir / 'neurocoach.sqlite'} (lecture seule ; heures en UTC)\n")
    users = {r["id"]: r["display_name"] for r in conn.execute("SELECT id, display_name FROM users")}
    for prefs in conn.execute("SELECT * FROM preferences"):
        print(
            f"Préférences de {users.get(prefs['user_id'], '?')} : réponses "
            f"{prefs['response_length']}, {prefs['max_visible_tasks']} action(s) visibles, "
            f"une question à la fois={bool(prefs['one_question_at_a_time'])}, "
            f"échéances={bool(prefs['deadlines_enabled'])}, rythme {prefs['cadence']}, "
            f"fuseau {prefs['display_timezone']}"
        )
    for project in conn.execute("SELECT * FROM projects ORDER BY created_at"):
        print(
            f"\n=== Projet « {project['title']} » ({users.get(project['user_id'], '?')}) : "
            f"statut {project['status']}, version {project['version']}"
        )
        print(f"  Objectif : {project['target_outcome'] or '(non défini)'}")
        print(
            f"  Temps par jour : {project['available_minutes_per_day'] or '?'} min ; "
            f"horizon : {project['horizon_date'] or '?'}"
        )
        constraints = json.loads(project["constraints_json"] or "[]")
        if constraints:
            print(f"  Contraintes : {' ; '.join(constraints)}")
        tasks = list(
            conn.execute(
                "SELECT t.*, p.title AS phase FROM tasks t JOIN phases p ON p.id = t.phase_id "
                "WHERE t.project_id = ? ORDER BY p.position, t.position",
                (project["id"],),
            )
        )
        numbers = {t["id"]: t["number"] for t in tasks}
        deps: dict[str, list[str]] = {}
        for edge in conn.execute(
            "SELECT d.task_id, d.depends_on_task_id FROM task_dependencies d "
            "JOIN tasks t ON t.id = d.task_id WHERE t.project_id = ?",
            (project["id"],),
        ):
            deps.setdefault(edge["task_id"], []).append(f"T{numbers.get(edge[1], '?')}")
        done = sum(1 for t in tasks if t["status"] == "done")
        if tasks:
            print(f"  Avancement : {done}/{len(tasks)} ({done * 100 / len(tasks):.1f} %)")
        phase = None
        for t in tasks:
            if t["phase"] != phase:
                phase = t["phase"]
                print(f"  Phase « {phase} »")
            extra = []
            if deps.get(t["id"]):
                extra.append("dépend de " + ", ".join(deps[t["id"]]))
            if t["estimate_minutes"]:
                extra.append(f"{t['estimate_minutes']} min")
            if t["due_date"]:
                extra.append(f"échéance {t['due_date']}")
            if t["blocked_reason"]:
                extra.append(f"blocage : {t['blocked_reason']}")
            if t["completed_at"]:
                extra.append(f"terminée le {t['completed_at'][:16]}")
            suffix = f" ({' ; '.join(extra)})" if extra else ""
            status = STATUS.get(t["status"], t["status"])
            print(f"    T{t['number']} [{status}] {t['title']}{suffix}")
        for action in conn.execute(
            "SELECT action_type, status, created_at, expires_at, decided_at FROM pending_actions "
            "WHERE project_id = ? ORDER BY created_at DESC LIMIT 5",
            (project["id"],),
        ):
            print(
                f"  Proposition {action['action_type']} : {action['status']} "
                f"(créée {action['created_at'][:16]}, expire {action['expires_at'][:16]}, "
                f"décidée {(action['decided_at'] or '-')[:16]})"
            )
        for mission in conn.execute(
            "SELECT m.id, m.status, m.simulated, m.queries_used, m.spent_usd, m.scope_json "
            "FROM research_missions m JOIN research_mission_projects mp ON mp.mission_id = m.id "
            "WHERE mp.project_id = ? ORDER BY m.created_at",
            (project["id"],),
        ):
            purpose = json.loads(mission["scope_json"] or "{}").get("purpose", "research")
            analyses = conn.execute(
                "SELECT COUNT(*) FROM research_analyses WHERE mission_id = ?", (mission["id"],)
            ).fetchone()[0]
            solutions = conn.execute(
                "SELECT COUNT(*) FROM research_solutions WHERE mission_id = ?", (mission["id"],)
            ).fetchone()[0]
            mode = "SIMULÉE" if mission["simulated"] else "réelle"
            print(
                f"  Mission {purpose} ({mode}) : {mission['status']} ; "
                f"{mission['queries_used']} recherche(s), {mission['spent_usd']:.3f} $ de quota ; "
                f"analyses {analyses}, solutions {solutions}"
            )
        events = list(
            conn.execute(
                "SELECT type, created_at, task_id, reverts_event_id FROM activity_events "
                "WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project["id"], args.events),
            )
        )
        if events:
            print(f"  Derniers événements ({len(events)}) :")
            for event in events:
                ref = f" T{numbers[event['task_id']]}" if event["task_id"] in numbers else ""
                undo = " (annulation)" if event["reverts_event_id"] else ""
                print(f"    {event['created_at'][:19]} {event['type']}{ref}{undo}")
    print("\nCompteur mensuel des recherches (quotas gratuits) :")
    for usage in conn.execute("SELECT * FROM research_provider_usage ORDER BY period, provider"):
        state = "épuisé" if usage["exhausted"] else "disponible"
        print(
            f"  {usage['period']} {usage['provider']} : {usage['queries']} requête(s), "
            f"{usage['reserved_usd']:.3f} $ ; {state}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
