# Third-Party Notices — NeuroEntrepreneur AI Coach

**Dernière mise à jour :** 9 novembre 2026 (phase 5)

Le code original de ce projet est publié sous licence MIT (fichier `LICENSE`). Les portions adaptées ci-dessous conservent leur copyright et leur licence d'origine.

## 1. Code tiers effectivement intégré

Toutes les entrées proviennent d'une seule source :
- **Dépôt :** https://github.com/LancelotGalahad/Personal-Progress-Assistant-AI
- **Commit :** `83d24df8f751aa7a311fa69ecfbb98df1d4df229`
- **Fichier source :** `core/engine.py`
- **Licence :** MIT — Copyright (c) 2026 Personal Progress Assistant contributors (texte complet : annexe A)
- **Date du port :** 9 novembre 2026

Chaque fichier de destination porte un en-tête d'attribution. Il s'agit d'adaptations de la logique, réécrites pour notre modèle. Aucun fichier n'a été copié tel quel.

### 1.1 Transitions de statut
- **Fonction source :** `update_task_status`
- **Destination :** `src/neurocoach/domain/transitions.py`
- **Modifications :**
  - statuts `todo/in_progress/blocked/done` et table de transitions explicite ;
  - `done → blocked` interdit ;
  - versionnement ;
  - entités immuables ;
  - fonction d'annulation ajoutée.

### 1.2 Disponibilité et dépendances
- **Fonction source :** `dependency_state`
- **Destination :** `src/neurocoach/domain/dependencies.py`
- **Modifications :**
  - arêtes explicites ;
  - détection de cycles (absente de la source) ;
  - validation des références ;
  - comptage des tâches dépendantes ouvertes.

### 1.3 Score de priorité et sélection des prochaines actions
- **Fonctions sources :** `priority_score`, `recommend_daily_focus`
- **Destination :** `src/neurocoach/domain/priority.py`
- **Modifications :**
  - 5 facteurs nommés en français, au lieu de 10 ;
  - urgence prise en compte seulement si les échéances sont activées ;
  - facteurs énergie, difficulté et report retirés ;
  - limite d'affichage issue des préférences ;
  - repli « lever le blocage » ou « découper » ;
  - tri stable.

### 1.4 Progression et alerte de charge
- **Fonctions sources :** `progress_summary`, `workload_warning`
- **Destination :** `src/neurocoach/domain/progress.py`
- **Modifications :**
  - arrondi à une décimale (Decimal, demi supérieur) ;
  - aucune progression affichée sans tâche ;
  - statut calculé par phase ;
  - retard calculé dans le fuseau d'affichage ;
  - capacité exprimée en minutes par jour ;
  - textes en français.

## 2. Ports prévus

Aucun autre port n'est prévu à ce jour.

## 3. Sources consultées sans réutilisation de code

| Source | Commit | Licence | Usage |
|---|---|---|---|
| Amankhan1009/todo-agent | `89328f533c3c8bc0a188de791640ce6e54787a84` | **Aucune licence** | Analyse fonctionnelle uniquement ; aucun code copié |
| Varsha-art126/EduAgent | `99ae1a3ea390acd202f8873a3608fab79ca0f6e3` | MIT | Inspiration de patterns généraux ; aucun code copié |
| langchain-ai/agents-from-scratch | `603fc7a4ac6119004f43894395e504a1fefcc6c0` | MIT | Référence pédagogique pour l'API officielle d'interruption ; aucun code copié |
| dkedar7/langstage | `f02f8fb69d514234c4a44f9b4b7e7a8928479eb1` | MIT | Évalué puis reporté ; aucun code copié |

## 4. Dépendances logicielles

Les dépendances installées via le gestionnaire de paquets restent régies par leurs propres licences (voir `docs/REUSE_DECISIONS.md` § 5). Elles ne sont pas relicenciées par ce projet.

Versions exactes dans `requirements.lock` (83 paquets avec les dépendances transitives) :
- **Exécution :** pydantic (MIT), python-dotenv (BSD-3-Clause), tzdata (Apache-2.0).
- **Extra `agent` (phase 2) :** langgraph, langgraph-checkpoint, langgraph-checkpoint-sqlite, langchain-core (MIT).
- **Extra `ui` (phase 2) :** streamlit (Apache-2.0).
- **Développement :** pytest, pytest-cov et ruff (MIT).
- **Extras `anthropic` et `openai` (phase 3, facultatifs) :** langchain-anthropic 1.7.10 et langchain-openai 1.7.4 (MIT), anthropic 2.6.0 et openai 3.48.0 (Apache-2.0). Installés pour vérifier le code de connexion ; aucun appel réel effectué.

L'API officielle de LangGraph (`interrupt`, `Command`, `context_schema`, `SqliteSaver`) est utilisée comme bibliothèque. Aucun code d'exemple n'a été copié depuis agents-from-scratch.

La liste complète, dépendances transitives comprises, figure dans `docs/DEPENDENCY_LICENSES.md` (générée par `python scripts/dev.py licenses`). Elle comprend notamment certifi (MPL-2.0) et orjson (MPL-2.0 et Apache-2.0 ou MIT), utilisés comme bibliothèques non modifiées.

## Annexe A — Licence MIT de Personal Progress Assistant AI

Texte reproduit depuis le fichier `LICENSE` du dépôt source au commit `83d24df8f751aa7a311fa69ecfbb98df1d4df229` :

```
MIT License

Copyright (c) 2026 Personal Progress Assistant contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```
