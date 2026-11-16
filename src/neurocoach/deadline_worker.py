"""Surveillance des échéances, indépendante du serveur Streamlit."""

import logging
import time

from neurocoach.bootstrap import build_application
from neurocoach.config import Settings

logger = logging.getLogger(__name__)


def main() -> None:
    app = build_application(Settings.from_env())
    while True:
        try:
            for user in app.coach.list_users():
                try:
                    app.coach.check_deadlines(user.id)
                except Exception:
                    logger.exception("Échec du contrôle pour un espace")
        except Exception:
            logger.exception("Échec de la lecture des espaces")
        time.sleep(30)


if __name__ == "__main__":
    main()
