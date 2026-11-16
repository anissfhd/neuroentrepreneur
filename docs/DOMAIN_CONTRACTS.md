# Contrats du domaine — spécification neutre

**Version :** phase 0 — 9 novembre 2026
**Rôle :** c'est la **seule source d'implémentation** du domaine, des services et des contrats LLM. Elle a été rédigée à partir des exigences du produit (`docs/01` à `docs/06`) et des décisions de `docs/DECISIONS.md`, sans fragment de code tiers.
**Convention :** chaque règle porte un identifiant (`I-xx`, `R-xx`…) réutilisé dans les tests.

---

## 0. Conventions générales

- **Langue :** messages et contenus en français ; identifiants techniques en anglais.
- **Identifiants :** chaînes opaques préfixées : `usr_`, `prj_`, `pha_`, `tsk_`, `pac_` (action en attente), `evt_`, `thr_` (fil de conversation), suivies d'un UUID v4 hexadécimal. Le LLM ne voit et ne produit **jamais** ces identifiants.
- **Références d'affichage :** chaque tâche reçoit un numéro `number` (entier ≥ 1, unique dans son projet, jamais réutilisé) affiché sous la forme « T3 ». C'est le seul moyen pour le LLM de désigner une tâche.
- **Horodatages :** stockés en **UTC**, au format ISO 8601 avec suffixe `Z`, à la seconde.
- **Échéances :** une échéance est une **date calendaire** (`AAAA-MM-JJ`, sans heure ni fuseau) interprétée dans le fuseau d'affichage de l'utilisateur. « Aujourd'hui » se calcule avec l'horloge injectée et ce fuseau.
- **Horloge :** toute règle temporelle reçoit une horloge injectée (`Clock.now() -> datetime UTC`). Aucun appel direct à l'heure système dans `domain/`.
- **Versions :** `Project.version` et `Task.version` sont des entiers qui commencent à 1 et augmentent à chaque modification de l'entité.

---

## 1. Entités

### 1.1 User
| Champ | Type | Contraintes |
|---|---|---|
| id | str | `usr_…` |
| display_name | str | 1 à 40 caractères |
| created_at | datetime UTC | |

Le P0 ne contient que deux utilisateurs fictifs créés par le script de démonstration : `Alice (démo)` et `Bruno (démo)`. **Ce n'est pas une authentification** (voir R-SEC-01).

### 1.2 Preferences (une par utilisateur)
| Champ | Type | Valeurs | Défaut |
|---|---|---|---|
| user_id | str | | |
| response_length | enum | `court`, `standard`, `detaille` | `standard` |
| max_visible_tasks | int | 1, 2, 3 | 3 |
| one_question_at_a_time | bool | | `true` |
| deadlines_enabled | bool | échéances affichées et proposées | `false` |
| cadence | enum | `flexible`, `quotidienne`, `hebdomadaire` | `flexible` |
| display_timezone | str | nom IANA valide (`zoneinfo`) | valeur de configuration, par défaut `Europe/Paris` |
| updated_at | datetime UTC | | |

Il n'y a pas de champ « rappels » en P0 : aucune notification (voir DECISIONS D-12). La cadence ne sert qu'à formuler les suggestions de revue.

### 1.3 Project
| Champ | Type | Contraintes |
|---|---|---|
| id, user_id | str | |
| title | str | 3 à 120 caractères |
| idea | str | 0 à 1 000 caractères (texte initial de l'utilisateur) |
| target_outcome | str ou null | ≤ 300 |
| constraints | list[str] | ≤ 10 éléments de ≤ 200 caractères |
| facts | list[str] | ≤ 10 × ≤ 200 |
| assumptions | list[str] | ≤ 10 × ≤ 200 |
| available_minutes_per_day | int ou null | 5 à 720 |
| horizon_date | date ou null | ≥ date du jour au moment de la demande (fuseau d'affichage) |
| status | enum | `draft`, `active` |
| next_task_number | int | ≥ 1 |
| version | int | ≥ 1 |
| created_at, updated_at | datetime UTC | |

### 1.4 Phase
| Champ | Type | Contraintes |
|---|---|---|
| id, project_id | str | |
| title | str | 3 à 80 caractères |
| exit_criterion | str ou null | ≤ 300 (remplace la notion de jalon) |
| position | int | ≥ 0, unique dans le projet |

Le statut d'une phase n'est **pas stocké**, il se **calcule** (§ 7.3).

### 1.5 Task
| Champ | Type | Contraintes |
|---|---|---|
| id, project_id, phase_id | str | la phase appartient au même projet |
| number | int | ≥ 1, unique dans le projet, jamais réutilisé |
| title | str | 3 à 120 caractères |
| description | str ou null | ≤ 1 000 |
| acceptance_criteria | str | **obligatoire**, 3 à 300 caractères (critère de fin) |
| status | enum | `todo`, `in_progress`, `blocked`, `done` |
| blocked_reason | str ou null | obligatoire (3 à 300) si et seulement si `status = blocked` |
| priority | int | 1 à 5, défaut 3 |
| estimate_minutes | int ou null | 5 à 480 |
| due_date | date ou null | |
| position | int | ≥ 0, unique dans la phase |
| completed_at | datetime UTC ou null | non nul si et seulement si `status = done` |
| version | int | ≥ 1 |
| created_at, updated_at | datetime UTC | |

### 1.6 TaskDependency
| Champ | Contraintes |
|---|---|
| task_id, depends_on_task_id | les deux tâches appartiennent au **même projet** ; pas d'auto-dépendance ; pas de doublon ; **pas de cycle** |

### 1.7 PendingAction
| Champ | Type | Contraintes |
|---|---|---|
| id, user_id | str | |
| project_id | str ou null | null uniquement pour `user.delete_data` |
| action_type | enum | voir § 4.2 |
| payload | JSON | commande canonique validée |
| preview | JSON | liste de changements avant/après (§ 5.2) |
| expected_versions | JSON | `{"project": v, "tasks": {"tsk_…": v}}` |
| status | enum | `pending`, `applied`, `cancelled`, `expired`, `superseded`, `failed` |
| idempotency_key | str | unique, générée à la création |
| created_at, expires_at, decided_at | datetime UTC | `expires_at = created_at + TTL` (15 min par défaut, configurable) |
| result | JSON ou null | résultat de l'application, ou code d'erreur |

### 1.8 ActivityEvent
| Champ | Type | Contraintes |
|---|---|---|
| id, user_id | str | |
| project_id, task_id, pending_action_id | str ou null | |
| type | enum | voir § 6.1 |
| payload | JSON | identifiants, champs modifiés, valeurs avant/après ; jamais le contenu des messages de conversation |
| reverts_event_id | str ou null | pour une annulation |
| created_at | datetime UTC | |

Le journal est en **ajout seul** : aucune mise à jour ni suppression, sauf lors de la suppression complète des données de l'utilisateur (§ 10).

### 1.9 ConversationThread
| Champ | Contraintes |
|---|---|
| id (`thr_…`), user_id, project_id, created_at | un fil par couple (utilisateur, projet) ; l'identifiant sert de `thread_id` pour le checkpointer |

---

## 2. Statuts et transitions

### 2.1 Tâche

| Depuis \ Vers | `todo` | `in_progress` | `blocked` | `done` |
|---|---|---|---|---|
| `todo` | sans effet | commencer | bloquer (raison) | terminer |
| `in_progress` | remettre à faire | sans effet | bloquer (raison) | terminer |
| `blocked` | débloquer → à faire | reprendre | sans effet, ou nouvelle raison | terminer |
| `done` | **rouvrir** | rouvrir et commencer | interdit | sans effet |

- **T-01** Une transition vers le même statut ne fait rien : aucun événement, version inchangée. Exception : `blocked → blocked` avec une nouvelle raison met la raison à jour.
- **T-02** Passer en `blocked` exige une raison. Quitter `blocked` efface la raison.
- **T-03** Entrer en `done` renseigne `completed_at` (s'il est vide). Quitter `done` le remet à vide.
- **T-04** `done → blocked` est interdit (erreur `INVALID_TRANSITION`) : il faut d'abord rouvrir la tâche.
- **T-05** Commencer ou terminer une tâche dont les dépendances ne sont pas terminées est **autorisé**. Le résultat contient alors l'avertissement `UNMET_DEPENDENCIES`, avec les références des tâches concernées.
- **T-06** Chaque transition effective incrémente `Task.version`, met à jour `updated_at` et crée un événement `task.status_changed` avec `{from, to, reason?}`.
- **T-07** Changer un statut ne demande **pas de confirmation** (§ 4), mais doit pouvoir être **annulé** (§ 6.2).

### 2.2 Projet
- `draft` : créé, sans plan confirmé.
- `active` : au moins un plan a été appliqué.
- **P-01** `draft → active` se produit uniquement lors de l'application confirmée de `plan.create`. Il n'existe pas de transition inverse en P0.

### 2.3 Action en attente
```
pending ──confirmation valide──▶ applied
pending ──annulation──────────▶ cancelled
pending ──confirmation après expiration──▶ expired
pending ──nouvelle action sur le même projet──▶ superseded
pending ──conflit de version ou erreur d'écriture──▶ failed
```
- **A-01** Seule une action `pending` peut changer d'état. Les autres états sont définitifs.

---

## 3. Invariants

| ID | Invariant |
|---|---|
| I-01 | Un projet appartient à exactement un utilisateur ; phases, tâches, dépendances, actions et événements héritent de cette propriété. |
| I-02 | Toute lecture et toute écriture sont filtrées par l'utilisateur courant, fourni par la session applicative et jamais par le LLM. |
| I-03 | Une ressource appartenant à un autre utilisateur est traitée exactement comme une ressource inexistante (`NOT_FOUND`), sans fuite d'information. |
| I-04 | Le graphe de dépendances d'un projet est acyclique en permanence. |
| I-05 | `completed_at` est non nul si et seulement si le statut est `done` ; `blocked_reason` est non nul si et seulement si le statut est `blocked`. |
| I-06 | Les numéros de tâche sont uniques dans un projet et jamais réutilisés, même après suppression. |
| I-07 | Une écriture soumise à confirmation (§ 4) ne peut avoir lieu que par l'application d'une action en attente `pending`, non expirée, appartenant à l'utilisateur. |
| I-08 | Une action en attente est appliquée **au plus une fois** (usage unique). |
| I-09 | Une application est atomique : tout est écrit (entités, statut de l'action, événements), ou rien. |
| I-10 | La progression, les statuts et les dates affichés proviennent de la base, jamais d'une sortie LLM. |
| I-11 | Une replanification ne modifie ni ne supprime une tâche `done` (les réalisations sont préservées). |
| I-12 | Il existe au plus une action `pending` par couple (utilisateur, projet). Cette règle est aussi garantie par un index unique partiel en base. |
| I-13 | Chaque écriture effective produit au moins un événement du journal. Seule exception : `user.delete_data` efface le journal de l'utilisateur ; l'action appliquée en reste la seule trace (E-02). |

---

## 4. Règles de confirmation

### 4.1 Principe (validé le 9 novembre 2026)
- **R-CONF-01** Sont appliqués **directement**, avec journalisation : (a) les changements de statut simples (§ 2.1) ; (b) la modification des préférences dans l'écran dédié ; (c) la création d'un projet vide via le formulaire « Nouveau projet », dont le titre est saisi par l'utilisateur.
- **R-CONF-02** **Toute autre écriture** exige une action en attente confirmée. C'est notamment le cas des créations groupées, suppressions, replanifications et modifications de dates, de titres ou de critères de fin.

### 4.2 Types d'action soumis à confirmation

| action_type | Effet | Exemple de déclencheur |
|---|---|---|
| `plan.create` | Met à jour le brief du projet, crée les phases, les tâches et les dépendances ; `draft → active` | « Oui, enregistre ce plan » |
| `plan.replan` | Ajoute, modifie, déplace ou supprime des tâches non terminées ; ajoute ou supprime des phases vides | « Je n'ai pas avancé, simplifie » |
| `task.create` | Ajoute une tâche à une phase existante | « Ajoute une tâche : … » |
| `task.update` | Modifie titre, critère de fin, description, priorité, estimation ou échéance | « Repousse T2 à vendredi » |
| `task.delete` | Supprime une tâche non terminée et ses dépendances (dans les deux sens) | « Supprime T4 » |
| `project.delete` | Supprime un projet et tout son contenu, fil de conversation compris | Bouton « Supprimer le projet » |
| `user.delete_data` | Supprime toutes les données de l'utilisateur (§ 10) | Bouton « Effacer mes données » |

- **R-CONF-03** Une tâche `done` ne peut être ni modifiée par `task.update` (sauf la description) ni supprimée par `task.delete` ou `plan.replan`. Il faut d'abord la rouvrir.

---

## 5. Cycle de vie d'une action en attente

### 5.1 Création — `request_change(user_id, project_id, action_type, command)`
1. Valider la commande : schéma Pydantic, puis règles du domaine (I-04, R-CONF-03, longueurs, appartenance).
2. Calculer l'aperçu (§ 5.2) et les versions attendues.
3. Dans une transaction : passer l'éventuelle action `pending` existante du même projet en `superseded`, insérer la nouvelle action, journaliser `pending_action.created`.
4. Renvoyer l'identifiant de l'action, l'aperçu et l'expiration.

Aucune entité métier n'est modifiée à cette étape.

### 5.2 Aperçu
Un aperçu est une liste ordonnée d'éléments de la forme `{op: "add"|"update"|"delete", entity: "project"|"phase"|"task"|"dependency", ref, before, after}`. Exemple :
```json
[{"op": "update", "entity": "task", "ref": "T2",
  "before": {"due_date": "2026-11-12"}, "after": {"due_date": "2026-11-14"}}]
```
L'interface l'affiche en français : « T2 — échéance : 12/11/2026 → 14/11/2026 ».

### 5.3 Confirmation — `confirm(user_id, action_id)`
Dans **une seule transaction** :
1. Charger l'action en filtrant par `user_id` (sinon `NOT_FOUND`).
2. Si le statut n'est pas `pending` : renvoyer `ACTION_ALREADY_DECIDED` avec le statut et le résultat existants. **Rien n'est écrit** (double clic, T05).
3. Si l'heure courante dépasse `expires_at` : passer à `expired`, journaliser, renvoyer `ACTION_EXPIRED`.
4. Vérifier que les versions courantes correspondent à `expected_versions`. Sinon : passer à `failed` avec `VERSION_CONFLICT` et demander un nouvel aperçu.
5. Réserver l'action par une mise à jour conditionnelle (`status` passe de `pending` à `applied`, seulement si le statut est encore `pending`). Si aucune ligne n'est modifiée, c'est un appel concurrent : revenir à l'étape 2.
6. Appliquer les écritures, incrémenter les versions, journaliser les événements métier et `pending_action.applied`, enregistrer `result`.
7. En cas d'erreur, annuler toute la transaction. Puis, dans une transaction séparée, passer l'action à `failed` avec le code d'erreur, et renvoyer l'erreur. Aucune écriture partielle (I-09, US-08).

### 5.4 Annulation — `cancel(user_id, action_id)`
`pending → cancelled`, journalisé. **Aucune écriture métier** (T03, T09). Annuler une action déjà décidée ne fait rien et renvoie son statut.

### 5.5 Modification d'un aperçu
L'utilisateur peut modifier le contenu proposé (par exemple corriger le titre d'une tâche dans l'aperçu d'un plan). L'interface envoie alors la commande modifiée à `request_change`. L'ancienne action passe en `superseded`, une nouvelle action est créée et doit être confirmée à son tour.

**Implémenté en phase 3 (D-42)** pour `plan.create` : `PlanEdits` (titres de phase ; titre, critère de fin, estimation ou retrait d'une tâche), appliqué par `revise_plan_command`. Une action expirée, déjà décidée, d'un autre type ou appartenant à un autre utilisateur ne peut pas être modifiée.

### 5.6 Réponse écrite à une proposition (D-40)
Pendant qu'une proposition attend : un « oui » court ne confirme rien et n'annule rien (rappel du bouton) ; un « non » court annule ; tout autre message annule la proposition, puis est traité (D-32).

---

## 6. Journal et annulation

### 6.1 Types d'événements
`project.created`, `plan.applied`, `plan.replanned`, `task.created`, `task.updated`, `task.deleted`, `task.status_changed`, `task.status_reverted`, `preferences.updated`, `project.deleted`, `pending_action.created`, `pending_action.applied`, `pending_action.cancelled`, `pending_action.expired`, `pending_action.superseded`, `pending_action.failed`, `user.data_exported`.

### 6.2 Annulation d'un changement de statut — `undo_status_change(user_id, event_id)`
- **U-01** On ne peut annuler qu'un événement `task.status_changed` de l'utilisateur, non encore annulé, **qui est le dernier changement de statut de la tâche**, et seulement si le statut actuel de la tâche est égal à `to` de l'événement.
- **U-02** L'annulation restaure `from` et la `blocked_reason` d'avant (conservée dans le payload). Elle applique T-03 à `completed_at`, incrémente la version et crée `task.status_reverted` avec `reverts_event_id`.
- **U-03** Un événement `task.status_reverted` ne peut pas lui-même être annulé. L'utilisateur peut toujours changer le statut à nouveau.
- **U-04** Il n'y a pas de limite de temps en P0.

---

## 7. Progression

- **PR-01** `percent = arrondi_demi_supérieur(done × 100 / total, 1 décimale)`, calculé en `Decimal`. `total` compte toutes les tâches du projet, quel que soit leur statut.
- **PR-02** Si `total = 0` : `percent = null`, et l'interface affiche « Pas encore de plan », jamais 0 % ni 100 %.
- **PR-03 Phase :** le même calcul s'applique sur les tâches de la phase ; null si la phase est vide. Statut calculé : `vide` (aucune tâche), `terminee` (toutes `done`), `a_faire` (aucune en `in_progress`, `blocked` ou `done`), sinon `en_cours`.
- **PR-04 Synthèse :** `{total, done, in_progress, blocked, todo, overdue, percent, phases[]}`. `overdue` compte les tâches non `done` dont la `due_date` est antérieure à aujourd'hui (fuseau d'affichage). Le calcul est toujours fait, mais l'affichage n'apparaît que si `deadlines_enabled`.
- **PR-05 Format d'affichage :** virgule décimale française et espace insécable avant « % ». Exemples : `33,3 %`, `100 %` (`.0` supprimé).
- **PR-06 Alerte de charge :** si `available_minutes_per_day` et `horizon_date` sont renseignés, la capacité vaut minutes par jour × jours restants (au moins 1). L'effort est la somme des estimations des tâches non `done` (les tâches sans estimation comptent pour 0 et sont signalées). Au-delà de 100 % de la capacité : alerte « dépassement » ; au-delà de 85 % : alerte « marge faible ».

Exemples de référence : 1 tâche terminée sur 3 donne `33,3 %` (T07) ; 2 sur 3 donnent `66,7 %` ; 1 sur 8 donne `12,5 %` ; 0 tâche donne `null`.

---

## 8. Prochaines actions

Le calcul est adapté du moteur de Personal Progress Assistant (MIT, voir `THIRD_PARTY_NOTICES.md`).

- **N-01 Tâche prête :** son statut est `todo` ou `in_progress`, et toutes ses dépendances sont `done`.
- **N-02 Score** (somme de facteurs nommés, détail renvoyé à l'interface) :

| Facteur | Valeur |
|---|---|
| `priorite` | 2 × priority (2 à 10) |
| `urgence` (seulement si `deadlines_enabled` et une échéance existe) | jours restants ≤ 0 : 10 ; ≤ 3 : 8 ; ≤ 7 : 6 ; ≤ 14 : 4 ; au-delà : 2 |
| `deja_commencee` | +3 si `in_progress` |
| `impact` | 2 × min(3, nombre de tâches non terminées qui dépendent directement d'elle) |
| `temps_disponible` (si l'estimation et `available_minutes_per_day` sont connues) | +2 si l'estimation tient dans la journée, −3 sinon |

- **N-03 Tri :** score décroissant, puis position de la phase, position de la tâche, numéro.
- **N-04 Sélection :** parmi les tâches prêtes qui tiennent dans le temps disponible (ou dont l'estimation ou la disponibilité est inconnue), retenir les `max_visible_tasks` premières. Une tâche prête mais trop longue n'est jamais proposée en premier choix : elle va dans le repli.
- **N-05 Repli** (si aucune tâche n'est sélectionnée) : d'abord la tâche bloquée la mieux classée (« lever le blocage »), sinon la tâche prête trop longue la mieux classée (« la découper »). Si toutes les tâches sont `done` : « plan terminé ». S'il n'y a aucune tâche : « pas encore de plan ».
- **N-06** Une tâche `blocked` ou dont des dépendances ne sont pas terminées n'est **jamais** présentée comme immédiatement faisable.

---

## 9. Préférences et adaptation

- **PF-01** Les préférences ne sont modifiées que par l'utilisateur, dans l'écran dédié. Le LLM ne les modifie jamais et n'en déduit aucune.
- **PF-02** `response_length` agit sur la consigne de longueur donnée au LLM et sur les gabarits : court ≤ 2 phrases, standard ≤ 5, détaillé sans limite stricte.
- **PF-03** `one_question_at_a_time = true` : la clarification pose **une seule question** par tour (le champ `next_question` est unique, § 11.2).
- **PF-04** `max_visible_tasks` limite les prochaines actions affichées dans le chat et en tête de liste. La liste complète reste accessible à la demande.
- **PF-05** `deadlines_enabled = false` : aucune échéance n'est proposée par le LLM (les `due_in_days` sont ignorés), ni affichée, ni prise en compte dans le score.
- **PF-06** Aucune étiquette médicale, aucun diagnostic, aucune inférence sur la santé ou la neurodivergence.

---

## 10. Export et suppression

- **E-01** `export_user_data(user_id)` renvoie un JSON contenant les préférences, les projets, phases, tâches et dépendances, les événements, et les messages des fils de l'utilisateur (dernier état du checkpoint). Journalise `user.data_exported`. Aucune confirmation (lecture seule).
- **E-02** `user.delete_data` (avec confirmation) supprime toutes les lignes métier de l'utilisateur, ses autres actions, ses événements, ses correspondances de fils et **ses fils dans le checkpointer**. L'utilisateur fictif est conservé et ses préférences sont remises aux valeurs par défaut. Seule trace conservée : l'action appliquée, avec les nombres d'éléments supprimés et sans aucun contenu. Aucune donnée d'un autre utilisateur n'est touchée. Les fils du checkpointer sont supprimés avant la validation de la transaction : si cette suppression échoue, tout est annulé et l'action passe en `failed`.
- **E-03** `project.delete` (avec confirmation) supprime le projet, son contenu et son fil dans le checkpointer.

---

## 11. Contrats LLM

Toutes les sorties LLM sont validées par Pydantic. Une sortie invalide lève `LLM_OUTPUT_INVALID` et **n'entraîne aucune écriture**. Le LLM ne manipule jamais d'identifiant interne.

### 11.1 `IntentResult`
| Champ | Contraintes |
|---|---|
| intent | `aide`, `information_projet`, `demande_plan`, `etat_projet`, `changer_statut`, `modifier_tache`, `ajouter_tache`, `supprimer_tache`, `replanifier`, `hors_perimetre`, `autre` |
| task_ref | `T<n>`, ou null |
| target_status | `todo`, `in_progress`, `blocked`, `done`, ou null |
| blocked_reason | ≤ 300, ou null |
| user_text_summary | ≤ 300 |

Le routage (`agent/routing.py`) est une **table écrite en code**. Une référence `task_ref` inexistante dans le projet courant conduit à une question de clarification, jamais à une écriture.

### 11.2 `ProjectBrief` (clarification)
`facts[]`, `assumptions[]`, `open_questions[]` (≤ 5 chacune), `target_outcome?`, `constraints[]`, `available_minutes_per_day?`, `horizon_days?`, `missing[]`, `skipped[]`, `next_question` (**une seule** question, ≤ 200 caractères, ou null si rien ne manque). Ce brouillon reste dans l'état du graphe et n'est enregistré qu'avec `plan.create`.

**Complétude (D-34) :** elle est calculée par le code, jamais reprise du champ `missing` du LLM. Le brief est complet quand le résultat attendu et le temps disponible sont fournis ou explicitement passés (`skipped`) ; les contraintes sont facultatives. Si la même question revient deux fois de suite, l'assistant rappelle qu'on peut répondre « je passe ».

### 11.3 `PlanDraft`
- `objective` (≤ 200) ; `assumptions[]` (≤ 5).
- `phases` : **1 à 5** éléments (2 à 5 recommandés pour un plan complet ; une seule phase est admise pour un « premier lot »). Chaque phase a un `title` et un `exit_criterion?`.
- `tasks` par phase : 1 à 7, **20 au total au maximum**. Chaque tâche a :
  - `key` : identifiant local au brouillon, `[a-z0-9_]{1,20}` ;
  - `title`, `acceptance_criteria` (obligatoire), `description?` ;
  - `estimate_minutes?`, `priority?` (1 à 5), `due_in_days?` (0 à 365, ignoré si les échéances sont désactivées) ;
  - `depends_on[]` : clés du même brouillon.
- **Validation par le domaine :** clés uniques, dépendances existantes et acyclicité, pas de titres en double dans une même phase, respect des longueurs. Le domaine convertit `due_in_days` en date avec l'horloge et le fuseau.

### 11.4 `ChangeProposal` (modification ou replanification)
`changes[]` : `{op: "add"|"update"|"delete"|"move", task_ref?, phase_title?, fields}` et `rationale` (≤ 300, sans jugement). Depuis D-41, `fields` est un objet **fermé** : `title?`, `acceptance_criteria?`, `description?`, `priority?`, `estimate_minutes?`, `due_date?`, `depends_on[]` (ajout uniquement). `null` signifie « inchangé ». Le domaine le transforme en commande `task.*` ou `plan.replan`, puis en action en attente. Un changement qui touche une tâche `done` est rejeté (R-CONF-03, I-11).

### 11.5 Réponses
- **Les faits** (progression, statuts, prochaines actions, résultat d'une action, erreurs) sont formulés par des **gabarits déterministes en français**. Les chiffres viennent du domaine (I-10).
- **Le LLM** formule les questions de clarification et le texte d'accompagnement. Il reçoit les faits en lecture seule.
- **Hors périmètre** (médical, juridique, financier personnalisé) : message fixe qui rappelle les limites de l'assistant et oriente vers un professionnel.

---

## 12. Erreurs

| Code | Message utilisateur (français) | Écriture |
|---|---|---|
| `NOT_FOUND` | « Élément introuvable. » | aucune |
| `VALIDATION_ERROR` | précise le champ en cause | aucune |
| `INVALID_TRANSITION` | « Ce changement de statut n'est pas possible : … » | aucune |
| `CYCLE_DETECTED` | « Ces dépendances formeraient une boucle. » | aucune |
| `DONE_TASK_PROTECTED` | « Cette tâche est terminée ; rouvrez-la d'abord. » | aucune |
| `ACTION_EXPIRED` | « Cette proposition a expiré ; je peux la regénérer. » | statut de l'action seulement |
| `ACTION_ALREADY_DECIDED` | « Cette proposition a déjà été traitée. » | aucune |
| `VERSION_CONFLICT` | « Le projet a changé depuis la proposition ; voici un nouvel aperçu. » | statut de l'action seulement |
| `LLM_UNAVAILABLE` | « Le service de langage ne répond pas. Vos données sont intactes ; réessayez. » | aucune |
| `LLM_OUTPUT_INVALID` | « Je n'ai pas pu produire une proposition valide. Réessayez ou reformulez. » | aucune |
| `STORAGE_ERROR` | « Enregistrement impossible pour le moment ; rien n'a été modifié. » | aucune (annulation de la transaction) |

Le journal technique contient le code, l'identifiant de corrélation et le type d'exception, **jamais** le contenu des messages ou des tâches.

---

## 13. Sécurité et isolation

- **R-SEC-01** En P0, l'utilisateur est choisi dans un sélecteur de deux utilisateurs fictifs. **Ce mécanisme n'est pas une authentification sécurisée.** Il interdit tout déploiement public en l'état (voir `ARCHITECTURE.md` § 9).
- **R-SEC-02** Le graphe reçoit `user_id`, `project_id` et `thread_id` par le **contexte d'exécution**, depuis la session applicative. Ces valeurs ne sont jamais lues dans l'état modifiable par le modèle ni dans le texte.
- **R-SEC-03** Le LLM n'a accès à **aucun outil d'écriture**. Les lectures sont déclenchées par le code selon le routage.
- **R-SEC-04** Les confirmations ne sont possibles que par l'interface (boutons), qui appelle `confirm` / `cancel`. Une phrase comme « je confirme » dans le chat **ne confirme rien** (T12).
- **R-SEC-05** Le texte de l'utilisateur et les données des tâches sont transmis au LLM comme des données, délimitées, et jamais comme des instructions.
- **R-SEC-06** Aucun secret dans le code ni dans Git. Les clés sont lues uniquement depuis l'environnement ou le fichier `.env` local, ignoré par Git.

---

## 14. Contrats des services applicatifs

| Service | Entrées | Sortie | Erreurs | Confirmation |
|---|---|---|---|---|
| `create_project` | user_id, title, idea? | Project (`draft`) + fil | VALIDATION_ERROR | directe (R-CONF-01c) |
| `list_projects` / `get_project_summary` | user_id, project_id? | projets / synthèse PR-04 | NOT_FOUND | — |
| `list_tasks` | user_id, project_id, filtres (statut, phase), pagination (limit ≤ 50, offset) | tâches | NOT_FOUND | — |
| `get_progress` | user_id, project_id | synthèse PR-04 | NOT_FOUND | — |
| `get_next_actions` | user_id, project_id | sélection N-04 / N-05 avec détail des scores | NOT_FOUND | — |
| `set_task_status` | user_id, task_id, status, reason? | tâche, événement, avertissements | NOT_FOUND, INVALID_TRANSITION, VALIDATION_ERROR | directe + annulable |
| `undo_status_change` | user_id, event_id | tâche | NOT_FOUND, INVALID_TRANSITION | directe |
| `get_preferences` / `update_preferences` | user_id, champs | Preferences | VALIDATION_ERROR | directe (R-CONF-01b) |
| `request_change` | user_id, project_id?, action_type, command | PendingAction (aperçu) | VALIDATION_ERROR, CYCLE_DETECTED, DONE_TASK_PROTECTED, NOT_FOUND | crée l'action |
| `confirm` | user_id, action_id | résultat | ACTION_*, VERSION_CONFLICT, STORAGE_ERROR, NOT_FOUND | applique |
| `cancel` | user_id, action_id | statut | NOT_FOUND | — |
| `export_user_data` | user_id | JSON | — | lecture |
