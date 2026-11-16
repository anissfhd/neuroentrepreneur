# Décisions de réutilisation

**Version :** phase 0 — 9 novembre 2026
**Statut :** les décisions de principe ont été validées le 9 novembre 2026. Depuis la phase 1, quatre modules sont portés depuis Personal Progress Assistant AI (MIT) ; détail et notices dans `THIRD_PARTY_NOTICES.md`. Aucun autre code tiers n'est intégré.
**Sources :** les cinq audits de `docs/research/` (documents de travail internes, non publiés).

## 1. Règles appliquées

1. **Bibliothèques officielles d'abord.** LangGraph, LangChain, Streamlit, Pydantic et `sqlite3` sont utilisés via leur API publique.
2. **Code MIT** : on ne le porte que s'il est utile et compatible. Chaque portion portée conserve le copyright et le texte MIT, et figure dans `THIRD_PARTY_NOTICES.md` avec son SHA, son chemin source et la nature des modifications.
3. **Code sans licence** (Todo Agent) : lecture seule. Aucune copie, traduction, paraphrase ou réorganisation. L'implémentation se fait exclusivement à partir de `DOMAIN_CONTRACTS.md` et de la documentation officielle.
4. **Licence d'un dépôt ≠ licence de ses dépendances.** Les dépendances sont recensées séparément (§ 5).
5. **Un test de contrat est écrit avant tout port** de logique externe.

## 2. Matrice de décision

| Module NeuroEntrepreneur | Source analysée | Type de réutilisation | Licence / autorisation | Preuve de compatibilité attendue | Décision |
|---|---|---|---|---|---|
| Orchestration (graphe, routage, contexte d'identité) | Todo Agent (concepts) + documentation LangGraph | API officielle + conception originale | Aucune copie de Todo Agent | Tests de routage avec faux LLM (phase 2) | **Réimplémentation originale** |
| Routage déterministe après classification | EduAgent (pattern) | Pattern général | MIT, aucune copie | Tests de routage (phase 2) | **Inspiration** |
| Sortie LLM validée, erreurs typées | EduAgent (pattern) + `with_structured_output` LangChain | API officielle | MIT, aucune copie | T11, sortie invalide (phase 2) | **Inspiration** |
| Faux fournisseur LLM | EduAgent (concept du fournisseur de démo) | Pattern | MIT, aucune copie | Suite de tests entièrement hors ligne | **Réimplémentation** |
| Dépendances, priorité, sélection du focus, transitions, progression, alerte de charge | Personal Progress Assistant `core/engine.py` | **Port MIT ciblé et adapté** | MIT + notice obligatoire | Tests de contrat avant port (phase 1) | **Port prévu en phase 1** |
| Confirmation humaine et reprise | Agents From Scratch + documentation LangGraph | API officielle (`interrupt`, `Command`) | MIT, aucune copie | Tests d'interruption et de reprise (phase 3) | **API officielle** |
| Mémoire longue | Agents From Scratch (concept de portée par utilisateur) | Concept | MIT, aucune copie | Tests de reprise de session (T06) | **Base métier SQLite** ; pas de LangGraph Store en P0 |
| Interface avancée | LangStage | Aucune | MIT | — | **Reporté** |

## 3. Détail par source

### 3.1 Todo Agent — commit `89328f533c3c8bc0a188de791640ce6e54787a84`
- **Repris :** aucun code.
- **Concepts généraux** (documentés publiquement par LangGraph) : identité injectée par le contexte d'exécution, filtrage par utilisateur dans la persistance, base métier séparée des checkpoints.
- **Écarté :** outils d'écriture appelables librement par le LLM, absence de confirmation, statut libre, fuseau codé en dur, identité par nom d'utilisateur présentée comme isolation.
- **Obligation :** aucune notice. Revue de similarité avant publication (`VALIDATION_PLAN.md`, phase 5).

### 3.2 EduAgent — commit `99ae1a3ea390acd202f8873a3608fab79ca0f6e3`
- **Repris :** aucun code. Patterns : routage déterministe, validation de sortie structurée, erreurs typées, fournisseur hors ligne, fixtures isolées.
- **Écarté :** multi-agent, quiz, RAG et ChromaDB, FastAPI, mémoire écrite par le LLM. Les dépendances `<1.0` sont incompatibles.
- **Obligation :** aucune notice. Attribution de courtoisie dans le README.

### 3.3 Personal Progress Assistant — commit `83d24df8f751aa7a311fa69ecfbb98df1d4df229`

| Élément source (`core/engine.py`) | Destination prévue | Adaptations obligatoires |
|---|---|---|
| `dependency_state` | `src/neurocoach/domain/dependencies.py` | Identifiants typés ; dépendances dans le même projet uniquement ; ajout de la détection de cycles (absente de la source) |
| `priority_score` | `src/neurocoach/domain/priority.py` | Facteurs réduits et renommés en français ; retrait de l'énergie, de la difficulté et de l'historique de report ; urgence seulement si les échéances sont activées ; horloge et fuseau injectés |
| `recommend_daily_focus` | `src/neurocoach/domain/priority.py` | Limite = préférence `max_visible_tasks` (1 à 3) ; repli « débloquer » ou « replanifier » ; tri stable et documenté |
| `update_task_status` | `src/neurocoach/domain/transitions.py` | Statuts `todo/in_progress/blocked/done` ; table de transitions explicite ; événement et annulation |
| `workload_warning` | `src/neurocoach/domain/progress.py` | Capacité en minutes par jour × jours d'horizon ; message en français |
| `progress_summary` | `src/neurocoach/domain/progress.py` | Arrondi à 1 décimale ; `None` quand il n'y a aucune tâche (« pas encore de plan ») ; progression par phase |

- **Écarté :** gabarit fixe de tâches, remplacement silencieux du plan, gamification, preuves, analytics, stockage JSON, fournisseurs IA.
- **Obligations :**
  - en-tête d'attribution dans chaque fichier de destination ;
  - entrée dans `THIRD_PARTY_NOTICES.md` (SHA, chemins, modifications) ;
  - texte MIT complet reproduit (déjà préparé dans `THIRD_PARTY_NOTICES.md`, annexe A).

### 3.4 Agents From Scratch — commit `603fc7a4ac6119004f43894395e504a1fefcc6c0`
- **Repris :** aucun code. API officielle `interrupt()` / `Command(resume=…)` / checkpointer ; taxonomie de décisions ; motif de test de reprise.
- **Écarté :** préférences réécrites par le LLM, outils Gmail, tests dépendant d'OpenAI et de LangSmith.
- **Obligation :** aucune notice. Citation comme référence dans le README.

### 3.5 LangStage — commit `f02f8fb69d514234c4a44f9b4b7e7a8928479eb1`
- **Repris :** rien. Reporté après le MVP.

## 4. Correspondance besoin → idée observée → implémentation

| Besoin produit | Idée observée | Module retenu | Implémentation choisie |
|---|---|---|---|
| Le LLM ne choisit jamais l'utilisateur | Contexte d'exécution de confiance (LangGraph) | `agent/graph.py` | `context_schema` officiel ; identité fournie par la session applicative |
| Aucune écriture sans accord | Interruption et reprise (LangGraph) | `agent/` + `application/pending_actions.py` | Action en attente en base + `interrupt()` ; écriture faite par le service au moment de la confirmation |
| Le LLM ne décide pas du chemin | Routage déterministe (EduAgent) | `agent/routing.py` | Table intention → nœud écrite en Python |
| Sortie LLM fiable | Validation Pydantic (EduAgent, LangChain) | `agent/llm.py` | `with_structured_output` + erreur typée |
| Progression exacte | Moteur déterministe (PPA) | `domain/progress.py` | Port MIT adapté |
| Prochaine action pertinente | Score explicable (PPA) | `domain/priority.py` | Port MIT adapté |
| Tests sans clé | Fournisseur de démo (EduAgent) | `agent/llm.py` | Faux LLM scripté |
| Reprise de session | Checkpointer SQLite (LangGraph) | `infra/checkpoint.py` | `SqliteSaver` officiel, fichier séparé |

## 5. Dépendances prévues et licences (vérifiées sur PyPI le 9 novembre 2026)

| Paquet | Version disponible | Licence | Rôle |
|---|---|---|---|
| langgraph | 1.2.20 | MIT | Graphe, interruptions |
| langgraph-checkpoint-sqlite | 3.1.3 | MIT | Checkpoints SQLite |
| langchain-core | 1.7.6 | MIT | Messages, sortie structurée |
| streamlit | 1.67.0 | Apache-2.0 | Interface |
| pydantic | 2.14.3 | MIT | Schémas |
| python-dotenv | 1.2.4 | BSD-3-Clause | Chargement de `.env` |
| tzdata | 2026.6 | Apache-2.0 | Base des fuseaux pour `zoneinfo` sous Windows |
| pytest / pytest-cov | 9.2.0 / 7.1.0 | MIT / MIT | Tests (dev) |
| ruff | 0.17.4 | MIT | Lint (dev) |
| langchain-anthropic / langchain-openai | 1.7.10 / 1.7.4 | MIT / MIT | Fournisseur réel (**facultatif**, selon configuration) |

Les versions exactes sont figées dans `requirements.lock` depuis la phase 1. Les licences des dépendances transitives restent celles de leurs paquets ; elles sont listées dans `docs/DEPENDENCY_LICENSES.md` (phase 5).

## 6. Revue de similarité avec Todo Agent (phase 5, 9 novembre 2026)

**Méthode.** Les fichiers Python lus pendant l'audit (application, graphe, prompts, base, outils) ont été relus en lecture seule au commit audité, dans un dossier temporaire hors du projet, supprimé ensuite. Ils ont été comparés automatiquement à `src/neurocoach/` et `ui/app.py` (identifiants, chaînes littérales d'au moins 20 caractères, lignes de plus de 25 caractères), puis la structure a été comparée à la main.

**Résultats.**
- **Lignes identiques :** 10, toutes des imports de bibliothèques standard ou de LangGraph/LangChain (par exemple l'import de `StateGraph`) et un test de type de message. Aucune ligne de logique commune.
- **Chaînes littérales :** la plus longue séquence commune fait 34 caractères, un fragment de requête SQL `UPDATE … SET description = ?`. **Aucun prompt n'est commun** : nos prompts sont en français et servent à classer une intention, sans outils.
- **Identifiants communs :** 22 sur 779, tous génériques (`task_id`, `user_id`, `thread_id`, `title`, `status`, `graph`, `checkpointer`…). `add_task`, `update_task` et `delete_task` existent des deux côtés, mais avec un rôle différent. Chez Todo Agent, ce sont des outils appelés par le LLM. Ici, ce sont les applicateurs des opérations `task.add`, `task.update` et `task.delete`, définies par `DOMAIN_CONTRACTS.md`, dans le moteur de validation des plans (`domain/plans.py`), sans aucun accès au LLM.
- **Structure :** des noms de modules courants dans les projets LangGraph sont partagés (`context.py`, `nodes.py`, `routing.py`, `state.py`, `db.py`). La conception est différente : Todo Agent boucle sur 2 nœuds et 5 outils CRUD ; ce projet compte une dizaine de nœuds, un routage décidé par le code, aucun outil d'écriture, des actions en attente et un modèle projet, phase et tâche avec événements.

**Conclusion.** Aucune reprise de code, de prompt ou de structure distinctive de Todo Agent n'a été détectée. Cette revue a été faite par le même agent que l'implémentation : elle **ne remplace pas une clean-room stricte**, puisque le code non licencié a été lu avant l'implémentation. Si une garantie juridique renforcée est nécessaire, il faut faire relire le code par une personne n'ayant pas eu accès au dépôt non licencié.
