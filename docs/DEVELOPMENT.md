# Développement local (Windows, sans `make`)

**État :** phase 5. Prototype complet avec le faux fournisseur LLM ; CI GitHub Actions, captures et documents de publication prêts ; harnais de validation avec un vrai LLM prêt mais non exécuté.

## Prérequis
- Python **3.13** (`py -3.13 --version`).
- Git 2.56 (installé dans `C:\Program Files\Git\cmd`). Si `git` n'est pas reconnu, ouvrir un nouveau terminal ou utiliser le chemin complet.

## Installation

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev,agent,ui]"
```

Pour reproduire exactement l'environnement : `pip install -r requirements.lock`, puis `pip install -e . --no-deps`.
Fournisseur réel (facultatif) : `pip install -e ".[anthropic]"` ou `".[openai]"`.
Sous Windows, placer le projet et l'environnement virtuel dans un chemin court : sans la prise en charge des chemins longs, l'installation du paquet `anthropic` échoue (constaté en phase 5 depuis un dossier temporaire profond).

## Commandes

Toutes les commandes passent par `.\.venv\Scripts\python.exe scripts\dev.py <commande>` :

| Commande | Effet |
|---|---|
| `test` | Lance toute la suite pytest (aucun appel réseau) |
| `cov` | Tests + couverture de `domain`, `application` et `agent` ; échoue sous 90 % |
| `lint` | `ruff check` + vérification du formatage (`src`, `tests`, `scripts`, `ui`) |
| `format` | Formatage et corrections automatiques sûres |
| `demo` | Lance l'interface Streamlit (`ui/app.py`), avec le faux LLM par défaut |
| `seed` | Crée Alice et Bruno (fictifs) et leurs données de démonstration ; peut être relancé sans effet |
| `check-secrets` | Recherche de secrets dans les fichiers suivis ou non ignorés |
| `check-llm` | Contrôle la configuration du fournisseur réel sans afficher la clé ; `--ping` : un appel réel minimal (payant) |
| `reset-data` | Supprime les bases locales (`NEUROCOACH_DATA_DIR`, à l'intérieur du projet uniquement) |
| `lock` | Regénère `requirements.lock` |
| `licenses` | Regénère `docs/DEPENDENCY_LICENSES.md` à partir des paquets installés |

## Configuration
Copier `.env.example` en `.env` si nécessaire. Avec le fournisseur par défaut `fake`, aucune clé n'est requise et aucun appel réseau n'a lieu. Pour un fournisseur réel, définir `NEUROCOACH_LLM_PROVIDER`, `NEUROCOACH_LLM_MODEL` et la clé correspondante, **uniquement dans `.env`**.

## Phrases utiles avec le faux fournisseur
- « Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer. »
- « Tester si des personnes seraient intéressées. J'ai 30 minutes par jour. »
- « J'ai terminé T1 », « Je commence T2 », « T2 est bloquée car … », « Rouvre T1 »
- « Où en suis-je ? », « Je n'ai pas avancé », « Supprime T3 », « Renomme T2 en « … » »

## Valider avec un vrai LLM (dès qu'une clé est disponible)

```powershell
# 1. Dans .env (jamais versionné) :
#    NEUROCOACH_LLM_PROVIDER=anthropic
#    NEUROCOACH_LLM_MODEL=claude-opus-5-5   (ou claude-sonnet-5-5, moins cher)
#    ANTHROPIC_API_KEY=<votre clé>
# 2. Essai à blanc (faux fournisseur IMPOSÉ, quel que soit .env ; aucun coût)
.\.venv\Scripts\python.exe scripts\evaluate_llm.py
#    Appels réels PAYANTS : option explicite, plafond, tarifs et registre partagé obligatoires
.\.venv\Scripts\python.exe scripts\evaluate_llm.py --real-api --budget-usd 0.20 `
    --price-input 2 --price-output 12 --ledger data\evaluations\registre.jsonl
#    Campagne en plusieurs exécutions sous un plafond total (reprise : --resume)
.\.venv\Scripts\python.exe scripts\run_campaign.py            # essai à blanc
# 3. Mêmes scénarios avec assertions (payant, jamais en CI)
$env:NEUROCOACH_RUN_REAL_LLM = "1"; .\.venv\Scripts\python.exe -m pytest tests/real_llm
```

Exploitation des modèles (configuration par rôle, historique, migration) : `docs/MODEL_OPERATIONS.md`.

## Configuration de l'interface
`.streamlit/config.toml` (versionné) masque le bouton « Deploy », limite les erreurs inattendues à leur type et désactive les statistiques d'usage. Démonstration pas à pas : `docs/DEMO_SCRIPT.md`. Limites de sécurité : `docs/SECURITY.md`.

## Vérification visuelle
Captures réelles : `.\.venv\Scripts\python.exe scripts\capture_screenshots.py` (Edge ou Chrome sans fenêtre, base séparée, faux fournisseur ; voir `docs/screenshots/README.md`).
`.claude/launch.json` (ignoré par Git) permet de lancer l'interface dans la prévisualisation de l'application de bureau. Sinon : `scripts\dev.py demo`, puis ouvrir http://localhost:8501.

## Limites connues
- Les deux utilisateurs fictifs **ne constituent pas une authentification** : usage local uniquement.
- Aucun dialogue avec un fournisseur LLM réel n'a encore été exécuté.
- CI (`.github/workflows/ci.yml`) jamais exécutée sur GitHub ; la suite n'a pas encore tourné sous Linux.
