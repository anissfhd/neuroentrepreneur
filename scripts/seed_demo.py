"""Cree les deux utilisateurs fictifs et leurs donnees de demonstration (idempotent).

Usage : python scripts/seed_demo.py
"""

from __future__ import annotations

from neurocoach.bootstrap import build_application
from neurocoach.demo import seed_demo


def main() -> None:
    app = build_application()
    summary = seed_demo(app)
    print(f"Base : {app.settings.business_db_path}")
    print(f"Utilisateurs fictifs : {', '.join(summary['users'])}")
    for line in summary["created"] or ["Données déjà présentes : rien à créer."]:
        print(f"- {line}")


if __name__ == "__main__":
    main()
