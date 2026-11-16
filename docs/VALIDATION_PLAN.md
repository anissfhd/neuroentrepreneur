# Plan de validation par phase

**Version :** phase 0 — 9 novembre 2026
**Règle commune :** aucune phase ne démarre sans la validation explicite de la précédente. Les résultats de tests rapportés sont **uniquement** ceux réellement obtenus et consignés dans `docs/IMPLEMENTATION_LOG.md`.

Les identifiants T01 à T12 renvoient à `docs/06_TESTS_ET_DEMONSTRATION.md` (dossier initial, document interne non publié ; la matrice est reprise dans le README) ; les identifiants de règles (T-xx, I-xx, PR-xx, N-xx, U-xx, R-xx, PF-xx, E-xx) renvoient à `docs/DOMAIN_CONTRACTS.md`.

---

## Phase 0 — Consolidation technique et documentaire (en cours)

**Livrables :** `docs/research/` (5 audits), `docs/REUSE_DECISIONS.md`, `docs/DOMAIN_CONTRACTS.md`, `docs/ARCHITECTURE.md`, `docs/DECISIONS.md`, `docs/VALIDATION_PLAN.md`, `docs/IMPLEMENTATION_LOG.md`, `THIRD_PARTY_NOTICES.md`.

**Critères de sortie :**
- [ ] Chaque audit cite le commit SHA, la licence vérifiée, les fichiers lus et non lus, et une décision.
- [ ] L'audit Todo Agent ne contient aucun fragment de code ni de prompt du dépôt.
- [ ] Chaque contradiction relevée est résolue ou listée comme question ouverte.
- [ ] Aucun fichier de code applicatif n'est créé ; aucune dépendance n'est installée.
- [ ] Le porteur du projet valide les décisions « Proposée » et répond aux questions Q-01 à Q-04.

---

## Phase 1 — Socle local, domaine et services (sans LLM)

**Objectif :** un CRUD métier complet, testé, isolé par utilisateur, avec actions en attente et journal, **sans aucun appel LLM**.

**Tests attendus :**

| Fichier | Couvre |
|---|---|
| `tests/unit/test_transitions.py` | T-01 à T-07 (table complète, y compris les transitions interdites et les raisons de blocage) |
| `tests/unit/test_dependencies.py` | I-04, refus des cycles directs et indirects, auto-dépendance, dépendance vers un autre projet, N-01 |
| `tests/unit/test_progress.py` | PR-01 à PR-06 : 0 tâche → `null` ; 1/3 → `33,3 %` (**T07**) ; 2/3 → `66,7 %` ; 1/8 → `12,5 %` ; 3/3 → `100 %` ; progression par phase ; tâches en retard selon le fuseau ; alerte de charge |
| `tests/unit/test_priority.py` | N-02 à N-06 : facteurs détaillés ; tâche bloquée ou non prête jamais proposée ; limite `max_visible_tasks` ; replis (débloquer, découper) ; plan terminé ; tri stable |
| `tests/unit/test_plans.py` | Validation de `PlanDraft` et des commandes de modification : bornes, clés, dépendances, R-CONF-03, I-11, conversion de `due_in_days` (la conversion `ChangeProposal` du LLM est reportée en phase 2) |
| `tests/unit/test_domain_misc.py` | R-CONF-01 et R-CONF-02 (matrice action → confirmation exigée), invariants I-05, fuseaux, messages d'erreur, aperçu en français |
| `tests/unit/test_formatting.py` | Gabarits déterministes (D-15), dont le message de reprise du dialogue de référence |
| `tests/unit/test_config.py` | Configuration par défaut (faux LLM), `.env`, erreurs de configuration |
| `tests/integration/test_services.py` | Projets, pagination, préférences, prochaines actions, alerte de charge, données de démonstration |
| `tests/unit/test_architecture.py` | Règles d'import entre couches (`ARCHITECTURE.md` § 3) |
| `tests/integration/test_migrations.py` | Base vide → schéma courant ; réapplication sans effet ; clés étrangères actives |
| `tests/integration/test_repositories.py` | Écriture et lecture de chaque entité ; versions ; numéros jamais réutilisés (I-06) |
| `tests/integration/test_pending_actions.py` | **T03** (annulation → zéro tâche), **T04** (application → tâches créées une seule fois), **T05** (double confirmation → aucune duplication), **T09** (non approuvée → état inchangé), expiration, remplacement, conflit de version, **atomicité** (panne injectée au milieu de l'application → aucune écriture, action `failed`) |
| `tests/integration/test_status_and_undo.py` | Changement direct journalisé ; U-01 à U-04 |
| `tests/security/test_isolation.py` | **T10** au niveau des services : chaque service appelé avec le projet, la tâche, l'action ou l'événement de l'autre utilisateur → `NOT_FOUND`, aucune écriture |
| `tests/integration/test_export_delete.py` | E-01 et E-02 (portée limitée à l'utilisateur, l'autre utilisateur est intact) |
| `tests/security/test_no_secrets.py` | Aucun motif de clé dans le dépôt ; `.env` ignoré |

**Critères de sortie** (résultats réels du 9 novembre 2026, détail dans `IMPLEMENTATION_LOG.md`) :
- [x] La suite de tests passe entièrement : 270 tests.
- [x] Couverture de 98,38 % sur `domain/` et `application/` (seuil : 90 %).
- [x] `scripts/dev.py lint` sans erreur (ruff check et ruff format).
- [x] Le port PPA est inscrit dans `THIRD_PARTY_NOTICES.md`, avec un en-tête d'attribution dans les 4 fichiers concernés.
- [x] `requirements.lock` est produit en Python 3.13.13 ; `.env.example` ne contient aucun secret ; `check-secrets` ne détecte rien.
- [x] Aucun import de `langgraph`, `langchain` ou `streamlit` dans `domain/` et `application/` (vérifié par test).
- [ ] Validation par le porteur du projet.

---

## Phase 2 — Agent conversationnel minimal et interface

**Objectif :** dialogue persistant, clarification, brouillon de plan, lecture d'état, avec le faux LLM ; interface Streamlit minimale.

**Prérequis : tests techniques isolés, à réaliser avant d'intégrer LangGraph** (demandés le 9 novembre 2026). Ils seront placés dans `tests/spikes/`, sur un graphe minimal sans LLM, avec `SqliteSaver` sur une base temporaire. Leur résultat réel sera consigné avant d'écrire `agent/`.

| ID | Test | Résultat attendu |
|---|---|---|
| S-01 | Reprise d'un graphe interrompu | `interrupt()` arrête le graphe ; `Command(resume=…)` le reprend sur le même fil ; le nœud interrompu est réexécuté sans refaire d'effet de bord (compteur d'appels du nœud `propose` = 1) ; deux reprises successives (double clic) → une seule écriture métier |
| S-02 | Nouveau message pendant une confirmation en attente | Comportement réel observé et documenté lorsqu'un nouveau message est envoyé sur un fil interrompu ; validation du contournement « annuler puis reprendre » (`ARCHITECTURE.md` § 5.2, point 7) : aucune action appliquée, aucun état incohérent |
| S-03 | Suppression des checkpoints | L'API de suppression d'un fil du `SqliteSaver` (version figée) efface tous les checkpoints et écritures du fil ; les autres fils restent intacts ; branchement sur `ConversationStore.delete_threads` |
| S-04 | Identité transmise au graphe | `user_id` et `project_id` passent par le contexte d'exécution (`context_schema`), absents de l'état checkpointé ; un message demandant de « devenir Bruno » ou contenant un identifiant ne change pas l'utilisateur effectif |
| S-05 | Confirmations et reprises avec Streamlit | Avec `streamlit.testing.v1.AppTest` : afficher l'aperçu, cliquer sur Confirmer, relancer l'exécution (rerun), double clic → une seule application ; les boutons sont désactivés après décision. **À valider avant de finaliser l'interface.** |

**Résultats des tests techniques** (exécution réelle, 9 novembre 2026) : **S-01 à S-05 validés**, 18 tests dans `tests/spikes/`. Le seul comportement problématique, S-02, est contourné par D-32. Détail dans `DECISIONS.md` § 3.

**Tests réalisés.** À la demande du 9 novembre 2026, le cycle complet (proposition, confirmation, exécution) a été intégré dès la phase 2. Les fichiers ont été regroupés par rapport au plan initial :

| Fichier | Couvre |
|---|---|
| `tests/unit/test_agent_units.py` | Table de routage, cumul du brief, une question à la fois (PF-03), conversion des propositions (11.4), invites délimitées, règles du faux fournisseur |
| `tests/unit/test_llm_provider.py` | Choix du fournisseur, extra manquant, conversion des pannes et des sorties invalides (sans réseau) |
| `tests/conversation/test_dialogue.py` | **T01, T02, T03, T04, T05, T06, T07 (via le chat), T08**, expiration, message pendant une proposition, passer une question, statut par le chat et annulation, références ambiguës, renommage et suppression confirmés, PF-01, hors périmètre, réponses courtes, export et suppression des conversations |
| `tests/resilience/test_llm_failures.py` | **T11** (LLM indisponible ou sortie invalide → message clair, données intactes), reprise après panne, référence inconnue, messages vides ou trop longs, panne de stockage à la confirmation |
| `tests/security/test_agent_security.py` | **T12** (injections dans le chat, dans les titres de tâches, dans une sortie LLM manipulée), aucun identifiant envoyé au LLM, état checkpointé sans identité, isolation des fils, contexte obligatoire |
| `tests/ui/test_app_smoke.py` | Interface : progression affichée depuis la base, question d'état, création de projet puis plan confirmé par bouton, statut et annulation, suppression de projet confirmée |

**Critères de sortie** (résultats réels) :
- [x] Tous les tests verts : **392 passés**, y compris lorsque les avertissements de ressources sont traités comme des erreurs.
- [x] Couverture : 98,09 % sur `domain` + `application` + `agent` ; **99 %** sur les seules règles métier (`domain` + `application`).
- [x] Démonstration locale avec le faux LLM (`scripts/dev.py demo`) ; serveur Streamlit démarré en mode headless, point de santé `ok`.
- [x] Aucun appel réseau pendant les tests (faux fournisseur partout ; les tests du fournisseur réel utilisent un modèle simulé).
- [ ] Validation par le porteur du projet.

---

## Phase 3 — Finalisation du parcours et de l'interface

Ajusté le 9 novembre 2026 : la confirmation et le suivi de bout en bout sont déjà réalisés et testés en phase 2. Il reste :
- **Modification de l'aperçu** avant confirmation (DOMAIN_CONTRACTS 5.5) : éditer un titre ou un critère de fin, ce qui crée une nouvelle proposition. Démo, séquence 4.
- **Message de reprise à l'ouverture** dans l'interface (US-06) : aujourd'hui produit par gabarit et testé, mais pas encore affiché automatiquement au retour.
- **Interface finale** : tâches groupées par phase, raison de blocage saisie, limite d'actions visibles, accessibilité (contraste, clavier).
- **Fournisseur réel** (Q-03) : essai manuel et ajustement des consignes, sans dépendance des tests.

**Tests réalisés :**

| Fichier | Couvre |
|---|---|
| `tests/unit/test_phase3_units.py` | Correction d'un plan (retrait, dépendances, phase vidée, clés inconnues), boucle `after_await`, aperçu détaillé et valeurs entre guillemets, rythme, « commencer » ou « reprendre », en-tête de phase, dépendances |
| `tests/integration/test_plan_revision.py` | `plan_draft_view`, `revise_plan` : remplacement sans écriture, refus si expirée, décidée, d'un autre type ou d'un autre utilisateur |
| `tests/conversation/test_dialogue.py` (compléments) | D-40 (« oui » ×5, « non » ×3, « oui mais… »), correction de plan par l'agent, rappel « je passe » |
| `tests/unit/test_llm_provider.py` (compléments) | `json_schema`, construction ChatAnthropic sans réseau, erreur de construction convertie |
| `tests/ui/test_app_smoke.py` (16 tests) | Résumé à l'ouverture, plan proposé, confirmation, modification avant confirmation, « oui » écrit, phases et dépendances, blocage (raison obligatoire, champ refermé, retour dans la carte), annulation, préférences, libellés uniques, message hors de la liste, export lié à l'utilisateur et invalidé, suppression |
| `tests/real_llm/test_real_provider.py` | 12 dialogues réels : **ignorés** sans `NEUROCOACH_RUN_REAL_LLM=1` |

**Critères de sortie** (résultats réels du 9 novembre 2026) :
- [x] **433 tests réussis, 13 ignorés** (12 dialogues réels faute de clé ; 1 test « extra manquant » sans objet), y compris lorsque les avertissements de ressources sont traités comme des erreurs.
- [x] Couverture : **99 %** sur les règles métier (`domain` + `application`, 1 512 instructions) ; 98,22 % avec l'agent.
- [x] Lint : `ruff check` et `ruff format --check` sans erreur (80 fichiers).
- [x] Analyse des secrets : aucun secret détecté.
- [x] Séquences de démonstration réalisables dans l'interface avec le faux LLM (vérification visuelle ci-dessous).
- [ ] **Dialogues avec un vrai LLM : non exécutés** (aucune clé). Procédure ci-dessous.
- [ ] Validation par le porteur du projet.

**Vérification visuelle** (navigateur intégré, Streamlit en local, données fictives) :

| État | Vérifié | Constat ou correction |
|---|---|---|
| Accueil et reprise | Oui | Résumé, prochaine action, progression |
| Conversation | Oui | Question puis plan ; **corrigé** : la phrase finale était collée à la dernière puce (Markdown) |
| Plan proposé | Oui | **Corrigé** : liste compacte ; valeurs textuelles entre « » (ambiguïté des deux-points) |
| Modification avant confirmation | Oui | Renommage et retrait appliqués, rien n'est écrit ; **corrigé** : libellés identiques « Retirer cette tâche » |
| Confirmer / Annuler | Oui | Plan enregistré ; replanification annulée (« rien n'a été modifié ») |
| Progression et plan par phase | Oui | Dépendances en clair, une seule action « Rouvrir » pour une tâche terminée |
| Tâche bloquée | Oui | Raison affichée ; **corrigé** : champ resté ouvert, libellés « … sur T2 » |
| Confirmation et annulation dans la carte | Oui | **Corrigé** : le retour s'affichait hors de vue, en haut de page |
| Export | Oui (sans téléchargement) | **Corrigé** : l'export restait proposé après changement d'utilisateur ou suppression |
| Suppression du projet et effacement des données | Oui | Confirmation dédiée, message de succès |
| Avatars du chat | Oui | **Corrigé** : lus « face » / « smart_toy » ; remplacés par des emoji |

Non vérifié : navigation complète au clavier et lecteur d'écran réel (composants natifs Streamlit, libellés uniques vérifiés par test).

**Procédure de validation avec un vrai LLM** (à exécuter dès qu'une clé est disponible) :
1. `pip install -e ".[anthropic]"` (ou `".[openai]"`) — déjà installé dans `.venv`.
2. Dans `.env` (jamais versionné) : `NEUROCOACH_LLM_PROVIDER=anthropic`, `NEUROCOACH_LLM_MODEL=claude-sonnet-5-5` (ou autre), `ANTHROPIC_API_KEY=…`.
3. `python scripts/evaluate_llm.py` : 12 dialogues (référence, formulation imprévue, changement d'avis, « oui » écrit, statut implicite, référence inexistante, retard, modification ambiguë, hors périmètre, injection, préférences demandées dans le chat, demande vague) ; compte rendu dans `data/evaluations/`.
4. `NEUROCOACH_RUN_REAL_LLM=1` puis `python -m pytest tests/real_llm` : mêmes scénarios avec assertions sur les invariants.
5. Remplir la grille d'évaluation humaine du compte rendu (notes de 1 à 3).

Essai à blanc réalisé avec le faux fournisseur (`--allow-fake`) : 12/12 conformes. **Cet essai valide le harnais, pas un modèle réel.**

---

## Phase 4 — Validation complète, robustesse, sécurité et démonstration

**Prévus et déjà couverts dans les phases précédentes :** PF-01 à PF-06 (`test_dialogue.py`, `test_services.py`, `test_app_smoke.py`), T08 (`test_dialogue.py`), T12 (`test_agent_security.py`).

**Tests ajoutés en phase 4 :**

| Fichier | Couvre |
|---|---|
| `tests/e2e/test_full_journey.py` | Parcours complet en un scénario : création, clarification, changement d'avis, correction, confirmation, modification, progression, blocage, **redémarrage**, export isolé, suppression du projet, effacement. Contrôle SQL de **toutes** les tables : aucune ligne résiduelle hormis la trace d'effacement, sans contenu |
| `tests/e2e/test_demo_script.py` | Le parcours de `docs/DEMO_SCRIPT.md` reste exact |
| `tests/conversation/test_unexpected_messages.py` | 7 messages inattendus (« ??? », emoji, charabia, `<script>`, lien `javascript:`, 2 000 caractères, demande contradictoire) sans écriture ni panne ; « 👍 » pendant une proposition ; informations contradictoires (la dernière l'emporte) ; changement d'avis sur un statut ; statut contradictoire ; ajout annulé puis suppression |
| `tests/security/test_phase4_security.py` | Isolation des exports et checkpoints ; décision refusée hors du projet courant (D-44) ; injections dans le titre, l'idée et la correction de plan ; texte du LLM sans effet ; proposition corrigée expirée ou corrigée deux fois ; redémarrage avec proposition corrigée et clics répétés ; `git check-ignore` |
| `tests/resilience/test_storage_failures.py` | Base verrouillée par un autre processus → `STORAGE_ERROR`, aucune écriture, réussite après libération |
| `tests/ui/test_app_smoke.py` (+3) | Avatars (régression phase 3), titres sans ancre focalisable, erreur du formulaire de projet sous le champ et saisie conservée |

**Correspondance défauts de la phase 3 → tests de non-régression :**

| Défaut corrigé | Test |
|---|---|
| Une seule action « Rouvrir » pour une tâche terminée | `test_tasks_are_grouped_by_phase_with_dependencies` |
| Retour d'action et annulation dans la carte | `test_blocking_requires_and_shows_a_reason`, `test_task_buttons_change_status_and_can_be_undone` |
| Phrase collée à la liste (Markdown) | `test_proposal_message_keeps_its_question_out_of_the_list` |
| Valeurs entre guillemets | `test_text_values_are_quoted_to_stay_unambiguous` |
| Libellés uniques | `test_controls_have_unique_accessible_labels`, `test_plan_editor_labels_are_unique` |
| Case de blocage refermée | `test_blocking_requires_and_shows_a_reason` |
| Export lié à l'utilisateur et invalidé | `test_export_is_tied_to_the_user_and_invalidated_on_deletion` |
| Avatars explicites | `test_chat_avatars_are_explicit_emoji` |
| « la commencer » / « la reprendre » | `test_resume_says_start_when_nothing_was_done` |
| Rappel « je passe » | `test_repeated_question_reminds_that_it_can_be_skipped` |
| Erreur de construction OpenAI, `json_schema` | `test_construction_errors_become_configuration_errors`, `test_structured_output_success_and_conversion` |

**Non réalisé, et pourquoi :**
- **Hygiène du journal technique :** sans objet, le code n'émet encore aucun journal (la variable `NEUROCOACH_LOG_LEVEL`, jamais lue, a été retirée en phase 5). À tester dès l'ajout d'un journal.
- **12 dialogues avec un vrai LLM :** aucune clé configurée (`.env` absent, variables vides). **Blocage explicite** avant de présenter le produit comme un agent IA validé. Procédure : phase 3 ci-dessus.
- **Lecteur d'écran réel :** aucun outil disponible. Checklist dans `docs/ACCESSIBILITY_CHECKLIST.md`.

**Revue manuelle réelle (navigateur intégré, données fictives) :**
- **Clavier :** tous les contrôles sont atteignables, le focus est visible, les onglets se changent aux flèches. **Corrigé :** ancres de titre focalisables, « Deploy » et « Main menu » dans la tabulation (11 arrêts utiles après correction).
- **Messages d'erreur :** en français. **Corrigé :** l'erreur du formulaire de projet s'affichait loin du champ et la saisie était effacée.
- **Surcharge cognitive :** la page d'accueil se limite au résumé, aux deux onglets et au champ de message. Les préférences et les données sont repliées ; en mode « réponses courtes », les phases sont repliées et les critères masqués.
- **Cohérence des boutons :** verbe + référence (« Commencer T2 »), confirmations en bouton principal, annulations en bouton secondaire.
- **Restant (composants Streamlit) :** nom d'icône « keyboard_arrow_right » dans les sections dépliables, quelques libellés anglais (« Skip to main content », « Press Enter to submit form »).

**Critères de sortie** (résultats réels du 9 novembre 2026) :
- [x] **459 tests réussis, 13 ignorés**, aucun échec, avertissements de ressources traités comme des erreurs.
- [x] Couverture des règles métier : **99 %** ; 98,30 % avec l'agent.
- [x] Lint propre (85 fichiers) ; aucun secret ; `.env`, `data/`, `.venv/` et `.claude/` ignorés par Git (vérifié par test).
- [x] Parcours de démonstration écrit et vérifié automatiquement.
- [x] Limites de sécurité documentées (`docs/SECURITY.md`).
- [ ] **Dialogues avec un vrai LLM** : bloqué faute de clé.
- [ ] Validation par le porteur du projet.

---

## Phase 5 — Portfolio et livraison

**Critères de sortie :**
- README (proposition de valeur, architecture, installation Windows et Linux, commandes, limites, attributions) et `docs/LIMITATIONS.md`.
- `scripts/seed_demo.py` et scénario de démonstration en 6 séquences (`docs/06` § 4), reproductible avec le faux LLM ; vidéo de 4 à 6 minutes.
- CI verte (faux LLM) ; audit des secrets ; licences des dépendances listées.
- **Revue de similarité** : comparaison manuelle de la structure et des noms des fichiers agent/infra avec l'audit Todo Agent ; absence de reprise de prompts ou de noms distinctifs ; conclusion consignée.
- `THIRD_PARTY_NOTICES.md` à jour ; aucune revendication « prêt pour la production ».

### Résultats de la phase 5 (9 novembre 2026)

| Critère | Résultat |
|---|---|
| README public et `docs/LIMITATIONS.md` | Faits : installation Windows et Linux, architecture (Mermaid), limites, attributions, mention de non-affiliation à Fantas.IA |
| Scénario de démonstration | `DEMO_SCRIPT.md` (3 à 5 minutes), mis en correspondance avec les 6 séquences du dossier initial ; vérifié par `tests/e2e/test_demo_script.py` |
| Captures | 7 captures réelles (`docs/screenshots/`), produites par `scripts/capture_screenshots.py` avec Edge sans fenêtre, sur des données fictives et avec le faux fournisseur |
| Vidéo | Guide prêt (`VIDEO_GUIDE.md`) ; **vidéo non enregistrée** : aucun outil d'enregistrement vidéo disponible ici |
| CI | `.github/workflows/ci.yml` écrit (Linux et Windows). Étapes rejouées localement dans un environnement neuf sous Windows : installation depuis `requirements.lock` réussie, lint propre (86 fichiers), `460 passed, 13 skipped`, couverture 98,30 %, aucun secret. **Jamais exécutée sur GitHub ni sous Linux** |
| Secrets | `check-secrets` : aucun secret ; documents internes exclus de Git (D-46, testé) |
| Licences | `THIRD_PARTY_NOTICES.md` à jour ; `docs/DEPENDENCY_LICENSES.md` (83 paquets, aucune licence copyleft forte ; MPL-2.0 pour certifi et orjson) |
| Revue de similarité Todo Agent | Faite (`REUSE_DECISIONS.md` § 6) : 10 lignes identiques, toutes des imports ; aucun prompt commun ; 22 identifiants génériques communs. Sans valeur de clean-room stricte |
| Revendication « production » | Aucune ; le README dit l'inverse |
| Dialogues avec un vrai LLM | **Bloqués** : aucune clé ni `.env` (valeurs jamais affichées) |

**Tests :** `460 passed, 13 skipped` (dont le nouveau test d'exclusion des documents internes) ; couverture des règles métier 99 % ; 98,30 % avec l'agent ; lint propre sur 86 fichiers.

**Critères de sortie :**
- [x] README, limites, démonstration, captures, licences, revue de similarité.
- [ ] CI verte **sur GitHub** : impossible avant la création du dépôt distant.
- [ ] Vidéo de démonstration : à enregistrer par le porteur du projet.
- [ ] **Dialogues avec un vrai LLM** : bloqué faute de clé.
- [ ] Validation par le porteur du projet, identité Git et premier commit.

### Finition avant publication (9 novembre 2026)
- Aperçus réécrits en français naturel (D-51) ; résumé cohérent lorsqu'un plan attend confirmation. Tests mis à jour et ajoutés : `test_preview_lines_are_plain_french_without_symbols`, `test_resume_while_a_plan_awaits_confirmation`.
- Les 7 captures ont été regénérées et contrôlées une par une : interface actuelle, données fictives uniquement, aucune adresse, aucun chemin, aucune adresse e-mail, aucune clé.
- **Résultats :** `462 passed, 13 skipped` ; couverture des règles métier 99 % (98,24 % avec l'agent) ; lint propre sur 86 fichiers (après formatage d'un fichier) ; aucun secret ; 120 fichiers destinés au premier commit, sans fichier sensible ni interne.
- Checklist du fournisseur réel : `REAL_LLM_CHECKLIST.md`.

### Préparation des dialogues réels (10 novembre 2026)
- Défaut bloquant corrigé (D-52) : la clé placée dans `.env` atteint désormais le SDK, masquée.
- Plafond à 4 000 jetons et effort configurable (D-53) ; contrôle `check-llm` et relevé des appels (D-54).
- Vérifié avec une clé fictive : construction du client, appel réseau refusé en 401 et correctement classé, aucune trace de la clé.
- **Résultats :** `469 passed, 13 skipped` ; couverture métier 99 % ; lint et secrets propres.
- [ ] **12 dialogues réels : en attente de la clé.** Le vrai LLM n'est pas validé.

### Campagne réelle OpenAI `gpt-5-mini` (10 novembre 2026)
- 12/12 scénarios exécutés ; 11/12 conformes aux contrôles automatiques ; 76 appels sans erreur ; environ 0,10 $ pour un budget de 2 $.
- **Sécurité :** aucune écriture sans clic, préférences intactes, « oui » écrit sans effet, injection sans effet.
- **Qualité : non validée.** Bilan par dialogue et six corrections proposées dans `IMPLEMENTATION_LOG.md`.
- Corrections déterministes appliquées : justification sans phrase coupée, préparation fixe des scénarios, garde-fou budgétaire. Résultats : `474 passed, 13 skipped`, couverture métier 99 %, lint et secrets propres.
- [ ] Appliquer les corrections de consignes validées, puis rejouer la campagne (environ 0,05 à 0,10 $).

### Seconde campagne OpenAI `gpt-5-mini` (10 novembre 2026)
- Corrections D-56, avec 17 tests de non-régression ; départ des 12 scénarios vérifié.
- **12/12** aux contrôles automatiques ; 38 appels sans erreur ; 0,0392 $ (cumul : environ 0,14 $).
- Relecture humaine : 9 dialogues conformes, 1 peu probant (« oui » sans proposition en attente), 2 défauts (statut deviné pour « J'ai fini » ; « Et maintenant ? » classé comme demande de plan).
- Résultats : `492 passed, 13 skipped` ; couverture métier 99 % ; lint et secrets propres.
- [ ] Corriger les deux défauts restants et rendre le scénario 4 probant ; nouvelle mesure (environ 0,04 $).

### Campagne ciblée `gpt-5-mini` (10 novembre 2026)
- D-57 : tâche désignée uniquement par le message ; « Et maintenant ? » = prochaine tâche réalisable ; justifications sans jargon.
- Campagne : 8/9, puis correction (statut lu dans le verbe) et 2/2 rejoués ; 23 appels sans erreur ; 0,0188 $ sur 0,50 $.
- Scénario « oui » désormais probant ; échéances activées et désactivées vérifiées en réel.
- Résultats : `523 passed, 16 skipped` ; couverture métier 99 % ; lint et secrets propres.

### Validation complète finale `gpt-5-mini` (10 novembre 2026)
- 15/15 aux contrôles automatiques ; 41 appels sans erreur ; 0,0413 $ (cumul : environ 0,20 $).
- Relecture humaine : 11 conformes, 3 défauts mineurs de formulation, 1 défaut de préférence (échéances proposées malgré leur désactivation, scénario 8, jamais appliquées sans clic).
- Données fictives vérifiées ; 125 fichiers prévus pour le premier commit, sans fichier sensible ni interne.
- Résultats : `523 passed, 16 skipped` ; couverture métier 99 % ; lint et secrets propres.
- [ ] Corriger le défaut d'échéances (proposé) avant de présenter le projet comme validé sur ce point.

### Derniers défauts avant le premier commit (10 novembre 2026)
- D-58 : aucune échéance proposée ni enregistrée quand elles sont désactivées (toutes voies d'entrée, confirmation comprise) ; vouvoiement ; faits sans doublon ni détail inventé ; dates en français ; harnais avec un projet par scénario et contrôle de l'enregistrement.
- Validation réelle ciblée : 1re exécution non probante (replanification non reconnue), corrigée ; 2e exécution 2/2, enregistrement sans échéance et dépendances intactes ; 0,0075 $ sur 0,20 $.
- Résultats : `545 passed, 17 skipped` ; couverture métier 99 % ; lint et secrets propres ; 126 fichiers prévus pour le premier commit.
