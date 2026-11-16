"""Taches de developpement multiplateformes, sans make (DECISIONS D-13).

Usage : python scripts/dev.py <commande>
  test           lance toute la suite pytest
  cov            tests + couverture (seuil 90 % sur domain/ et application/)
  lint           ruff check + verification du formatage
  format         ruff format + corrections automatiques sures
  seed           donnees de demonstration fictives
  demo           lance l'interface Streamlit (faux LLM par defaut)
  check-secrets  recherche de secrets dans les fichiers du depot
  check-research services de recherche web : cles, verrou, quota (aucun appel par defaut)
  check-llm      controle la configuration du fournisseur reel (cle jamais affichee)
  reset-data     supprime les bases locales (dossier NEUROCOACH_DATA_DIR)
  lock           regenere requirements.lock depuis l'environnement courant
  licenses       regenere docs/DEPENDENCY_LICENSES.md (licences des dependances)
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable


def run(*args: str) -> int:
    print("$", " ".join(args), flush=True)
    return subprocess.call(list(args), cwd=ROOT)


def cmd_test(extra: list[str]) -> int:
    return run(PY, "-m", "pytest", *extra)


def cmd_cov(extra: list[str]) -> int:
    return run(
        PY,
        "-m",
        "pytest",
        "--cov=neurocoach.domain",
        "--cov=neurocoach.application",
        "--cov=neurocoach.agent",
        "--cov-branch",
        "--cov-report=term-missing",
        "--cov-fail-under=90",
        *extra,
    )


SOURCES = ("src", "tests", "scripts", "ui")


def cmd_lint(extra: list[str]) -> int:
    code = run(PY, "-m", "ruff", "check", *SOURCES, *extra)
    return code or run(PY, "-m", "ruff", "format", "--check", *SOURCES)


def cmd_format(extra: list[str]) -> int:
    run(PY, "-m", "ruff", "check", "--fix", *SOURCES)
    return run(PY, "-m", "ruff", "format", *SOURCES, *extra)


def cmd_demo(extra: list[str]) -> int:
    return run(PY, "-m", "streamlit", "run", str(ROOT / "ui" / "app.py"), *extra)


def cmd_seed(extra: list[str]) -> int:
    return run(PY, str(ROOT / "scripts" / "seed_demo.py"), *extra)


def cmd_check_llm(extra: list[str]) -> int:
    return run(PY, str(ROOT / "scripts" / "check_llm.py"), *extra)


def cmd_check_research(extra: list[str]) -> int:
    return run(PY, str(ROOT / "scripts" / "check_research.py"), *extra)


def cmd_check_secrets(extra: list[str]) -> int:
    return run(PY, str(ROOT / "scripts" / "check_secrets.py"), *extra)


def cmd_reset_data(extra: list[str]) -> int:
    sys.path.insert(0, str(ROOT / "src"))
    from neurocoach.config import Settings

    data_dir = Settings.from_env().data_dir.resolve()
    if ROOT not in data_dir.parents:
        print(f"Refus : {data_dir} est hors du projet.")
        return 1
    if data_dir.exists():
        shutil.rmtree(data_dir)
        print(f"Supprimé : {data_dir}")
    else:
        print(f"Rien à supprimer : {data_dir}")
    return 0


def cmd_lock(extra: list[str]) -> int:
    output = subprocess.run(
        [PY, "-m", "pip", "freeze", "--exclude-editable"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    header = (
        "# Versions exactes de l'environnement de developpement (Python "
        f"{sys.version_info.major}.{sys.version_info.minor}).\n"
        "# Regenerer avec : python scripts/dev.py lock\n"
    )
    (ROOT / "requirements.lock").write_text(header + output, encoding="utf-8")
    print("requirements.lock mis à jour.")
    return 0


def _license_of(name: str) -> str:
    from importlib import metadata

    meta = metadata.metadata(name)
    expression = meta.get("License-Expression")
    if expression:
        return expression
    classifiers = [
        c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")
    ]
    text = (meta.get("License") or "").strip()
    if classifiers:
        return ", ".join(classifiers)
    # Certains paquets placent le texte complet de la licence dans ce champ : premiere ligne.
    return text.splitlines()[0][:60] if text else "non déclarée dans les métadonnées"


def cmd_licenses(extra: list[str]) -> int:
    """Licences declarees par les paquets de requirements.lock (environnement courant)."""
    rows = []
    for line in (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines():
        if "==" not in line or line.startswith("#"):
            continue
        name, version = line.split("==", 1)
        rows.append(f"| {name} | {version} | {_license_of(name)} |")
    header = [
        "# Licences des dépendances",
        "",
        "Généré par `python scripts/dev.py licenses` à partir des métadonnées des paquets "
        "installés et de `requirements.lock` (dépendances directes, transitives et extras "
        "facultatifs). Ces paquets restent régis par leurs propres licences ; ce projet ne les "
        "redistribue pas. Une métadonnée de paquet ne remplace pas la lecture de sa licence.",
        "",
        f"**Paquets :** {len(rows)}",
        "",
        "| Paquet | Version | Licence déclarée |",
        "|---|---|---|",
    ]
    output = ROOT / "docs" / "DEPENDENCY_LICENSES.md"
    output.write_text("\n".join([*header, *rows, ""]), encoding="utf-8")
    print(f"{output.relative_to(ROOT)} : {len(rows)} paquets.")
    return 0


COMMANDS = {
    "test": cmd_test,
    "cov": cmd_cov,
    "lint": cmd_lint,
    "format": cmd_format,
    "seed": cmd_seed,
    "demo": cmd_demo,
    "check-secrets": cmd_check_secrets,
    "check-llm": cmd_check_llm,
    "check-research": cmd_check_research,
    "reset-data": cmd_reset_data,
    "lock": cmd_lock,
    "licenses": cmd_licenses,
}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
