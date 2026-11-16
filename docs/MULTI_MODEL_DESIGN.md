# Architecture multi-modèle : analyse et plan (non implémenté)

**Date :** 10 novembre 2026. **Statut :** principe approuvé ; **M1 à M5 réalisées** (D-62 à D-66). Procédure : `docs/MODEL_OPERATIONS.md`. Aucune modification de code, aucun appel payant, `.env` inchangé, `gpt-5-mini` reste le modèle actif.

**Décision du porteur du projet :** pas de migration immédiate vers Terra. On conserve `gpt-5-mini` et on prépare un changement de modèle par configuration, explicite, traçable et réversible, avant le retrait de `gpt-5-mini` le **11 décembre 2026**.

## 1. Existant à réutiliser

| Composant | Ce qu'il fait déjà | Réutilisation |
|---|---|---|
| `config.Settings` (`NEUROCOACH_LLM_PROVIDER`, `_MODEL`, `_EFFORT`, `_TIMEOUT_SECONDS`, `_MAX_OUTPUT_TOKENS`, `_MAX_RETRIES`) | Seul endroit où le modèle est choisi ; lu dans l'environnement puis dans `.env` ; validé par Pydantic | Il reste la valeur par défaut de tous les rôles : le `.env` actuel continue de fonctionner sans modification |
| `agent/llm.py` : protocole `LLMProvider`, `LangChainProvider`, `build_llm_provider`, `FakeLLM` | Un fournisseur par configuration ; erreurs ramenées à `LLM_UNAVAILABLE` et `LLM_OUTPUT_INVALID` ; interdiction du réel (`NEUROCOACH_FORBID_REAL_LLM`, D-60) | Construit un fournisseur **par rôle**. Le paramètre `task`, déjà passé à chaque appel (`classify_intent`, `clarify`, `draft_plan`, `draft_change`, `coach_reply`), sert à aiguiller vers un rôle sans toucher aux nœuds |
| `bootstrap.build_coach_runtime` | Point unique de construction du fournisseur | Assemble les fournisseurs par rôle |
| Nœuds LangGraph, garde-fous (D-56 à D-61), actions en attente | Indépendants du modèle : le code décide du routage, des confirmations et des écritures | **Inchangés** |
| `scripts/check_llm.py` | Contrôles locaux et `--ping` (1 appel), clé jamais affichée | Étendu à chaque rôle, avec les dates de retrait |
| `evaluate_llm.py`, `evaluate_strategy_r0.py`, `run_campaign.py`, `Ledger` | Scénarios, notation, registre partagé, faux fournisseur par défaut | Comparaison avant bascule ; tarifs lus dans le catalogue |
| Table `activity_events`, migrations SQL | Journal des actions par utilisateur | Modèle de la nouvelle table d'historique de configuration (niveau système) |

**Constats de l'inventaire :**
- **Code métier :** aucun nom de modèle ; seuls des commentaires datent les défauts observés.
- **Outils d'évaluation :** les seuls noms de modèles présents en dur sont des valeurs par défaut, par exemple `run_campaign.py --model gpt-5.6-terra`.
- **Point à corriger :** l'interface met en cache l'exécution selon `(data_dir, llm_provider)`. Si on change `NEUROCOACH_LLM_MODEL` sans redémarrer, le nouveau modèle n'est pas pris en compte, et rien ne le signale.

## 2. Architecture proposée (évolution minimale)

### 2.1 Catalogue de modèles : des données, pas du code
Fichier versionné `src/neurocoach/llm_models.toml`, validé par Pydantic au démarrage. Chaque entrée comprend :
- `id`, `provider` (`openai`, `anthropic`), `status` (`actif`, `candidat`, `déprécié`, `retiré`) ;
- `retirement_date` et `replacement` ;
- `efforts` acceptés, méthode de sortie structurée et API (Chat Completions ou Responses) ;
- tarifs (entrée, cache, sortie) ;
- `verified_on` et `source_url` (page officielle).

Entrées initiales, d'après la vérification du 10/11/2026 (`R0_MODEL_COMPARISON.md`) :

| id | statut | retrait | tarifs ($/M : entrée / sortie) | efforts |
|---|---|---|---|---|
| `gpt-5-mini` | déprécié (actif pour le coaching) | 2026-12-11 → `gpt-5.6-terra` | 0,25 / 2,00 | `low` utilisé avec succès ; liste complète **à vérifier** sur la page officielle |
| `gpt-5.6-terra` | candidat | — | 2,00 / 12,00 | none, low, medium (défaut), high, xhigh, max |
| `gpt-5.6-luna` | candidat | — | 0,20 / 1,20 | mêmes niveaux que Terra |

`Settings.llm_effort` n'accepte aujourd'hui que `low`, `medium` et `high`. La validation prendra l'intersection avec les niveaux du catalogue, sans élargir cette liste sans décision.

**Ajouter un modèle d'un fournisseur déjà pris en charge = ajouter une entrée**, sans changer le code. Un nouveau fournisseur demande une petite fonction de construction, enregistrée dans une table `provider → fabrique` de `llm.py`, et un extra d'installation.

### 2.2 Rôles et affectation
Trois rôles fixes, chacun configurable par des variables facultatives :

| Rôle | Variable du modèle | Repli, explicite et documenté | Tâches actuelles |
|---|---|---|---|
| `coaching` | `NEUROCOACH_LLM_MODEL_COACHING` | `NEUROCOACH_LLM_MODEL` (le `.env` actuel) | `classify_intent`, `clarify`, `draft_plan`, `draft_change`, `coach_reply` |
| `strategy` (analyse et recherche business) | `NEUROCOACH_LLM_MODEL_STRATEGY` | modèle du coaching | aucune dans l'application ; `strategy` dans le harnais R0 ; futur Business Researcher |
| `simple` | `NEUROCOACH_LLM_MODEL_SIMPLE` | modèle du coaching | **aucune pour l'instant** (réservé : résumés de sources, extraction, titres) |

- **Options par rôle :** `NEUROCOACH_LLM_PROVIDER_<RÔLE>` et `NEUROCOACH_LLM_EFFORT_<RÔLE>` sont facultatives. Le délai, le plafond de sortie et les nouvelles tentatives restent communs.
- **Table des tâches :** la table `tâche → rôle` est **statique** et définie à un seul endroit, `agent/roles.py`. Un test vérifie que chaque tâche des prompts y figure, et une tâche inconnue est refusée. **Aucun routage automatique.**
- **`classify_intent` reste dans le rôle de coaching :** la qualité du routage en dépend (Terra classait une idée en « aide »). Le passer en `simple` serait une décision à part, à évaluer d'abord.
- **Valeur par défaut :** tous les rôles reprennent `gpt-5-mini`, d'où **aucun changement de comportement**.

### 2.3 Fournisseur par rôle
`RoleProvider` implémente le même protocole `LLMProvider`. Il reçoit `task`, choisit le rôle dans la table et appelle le fournisseur de ce rôle.
- Les nœuds et les garde-fous ne changent pas.
- `build_llm_provider(settings, role="coaching")` garde sa signature actuelle par défaut.
- Avec un seul modèle configuré, un seul client est construit.

### 2.4 Validation et messages d'erreur
La configuration est validée au démarrage de l'application, par `check-llm` et par les harnais. Toute erreur **bloque** et s'affiche en clair, sans clé :
- **Modèle absent du catalogue :** « Modèle inconnu pour le rôle coaching : gpt-5-minii. Modèles déclarés : gpt-5-mini, gpt-5.6-luna, gpt-5.6-terra (docs/MODEL_OPERATIONS.md). »
- **Fournisseur différent de celui du catalogue :** « gpt-5.6-terra est un modèle openai, mais le rôle coaching est configuré pour anthropic. »
- **Effort non accepté :** « L'effort « max » n'est pas accepté par gpt-5-mini (accepté : low, medium, high). »
- **Modèle `retiré` :** refus de démarrer. « gpt-5-mini est retiré depuis le 11/12/2026 : choisissez un autre modèle (remplacement indiqué : gpt-5.6-terra). »
- **Date de retrait proche (30 jours) ou dépassée, alors que le catalogue n'a pas encore été mis à jour :** avertissement visible dans `check-llm` et dans le journal de l'application, **sans bascule**.
- **Clé manquante pour le fournisseur d'un rôle :** message existant, précisé par le rôle.

**À l'exécution**, un modèle introuvable (HTTP 404) donne toujours le message utilisateur actuel, « Le service de langage ne répond pas. Vos données sont intactes ; réessayez. ». En plus, un journal destiné à l'exploitant indique « modèle introuvable » et le rôle concerné, sans le message d'erreur brut.

### 2.5 Aucune bascule silencieuse
- **Pas de repli automatique.** Aucun modèle de secours n'est appelé à la place d'un modèle en panne, retiré ou trop cher, et aucun fournisseur n'en remplace un autre.
- **Replis documentés :** le seul repli prévu est un repli de *configuration* (un rôle non configuré reprend le modèle du coaching). Il est documenté et affiché en toutes lettres par `check-llm`, par exemple « strategy : gpt-5-mini (hérité de coaching) ».
- **Changement pris en compte au redémarrage uniquement :** la clé de cache de l'interface comprend l'empreinte de la configuration des rôles. Un changement ne prend donc effet qu'au redémarrage, jamais au milieu d'une conversation.

### 2.6 Traçabilité
- **Historique de configuration :** une table `llm_config_events`, ajoutée par une migration et en ajout seul. Au démarrage, la configuration active (rôle, fournisseur, modèle, effort, version du catalogue) est comparée au dernier enregistrement. Si elle diffère, une ligne est ajoutée : avant, après, date en UTC, origine (`.env` ou environnement). `check-llm --history` affiche l'historique.
- **Provenance des propositions (option, à valider) :** le modèle et le rôle sont ajoutés aux métadonnées des actions en attente créées à partir d'une sortie du modèle. Cela permet de savoir quel modèle a rédigé un plan. Aucune règle métier n'est touchée.
- **Comptes rendus d'évaluation :** ils indiquent déjà le fournisseur et le modèle ; ils indiqueront aussi le rôle.

### 2.7 Changement de modèle et retour arrière
- **Changer de modèle :** modifier une ligne de `.env`, par exemple `NEUROCOACH_LLM_MODEL_COACHING=gpt-5.6-terra`, puis lancer `check-llm` (validation hors ligne) et redémarrer.
- **Revenir en arrière :** remettre la ligne précédente. L'historique indique la valeur à restaurer, et le retour est possible tant que le catalogue garde ce modèle avec un statut autre que `retiré`.
- **Prévisualiser :** un outil en lecture seule, `scripts/llm_config.py show|validate|diff`, affiche la configuration effective par rôle et ce qu'un changement modifierait. **Il ne modifie jamais `.env`.**

## 3. Préservation de la qualité et des corrections
- **Modèle et prompts :** `gpt-5-mini` reste actif ; **aucun prompt n'est modifié**.
- **Corrections D-56 à D-61 :** elles vivent dans `guards.py`, `nodes.py`, `proposals.py` et le service des actions, indépendamment du modèle. Elles restent actives quel que soit le rôle ou le modèle. Leurs tests existants ne sont pas modifiés.
- **Confirmations explicites, actions en attente, journal et interdiction du réel en test :** aucun changement.
- **Équivalence stricte pour `gpt-5-mini`.** Un test hors ligne capture les paramètres envoyés au client LangChain : modèle, délai, plafond de sortie, nouvelles tentatives, effort et méthode de sortie structurée. Il vérifie qu'ils sont **identiques** avant et après l'évolution, avec le `.env` actuel.

## 4. Point particulier : l'allègement à 10 minutes (D-61)

**Règle actuelle :** si la proposition du modèle n'allège pas le plan, le code ramène la prochaine tâche faisable, estimée à plus de 10 minutes, à 10 minutes.

**Risques identifiés :**
1. **Tâches incompressibles.** Un rendez-vous, un atelier, une cuisson ou un séchage, un tournage, un marché, un appel planifié : ramener « Interroger trois personnes » ou « Tenir un stand » à 10 minutes est irréaliste.
2. **Seul le chiffre change, pas la tâche.** Le titre et le critère de fin restent les mêmes : après 10 minutes, la tâche n'est pas terminée. Le message (« une première étape de 10 minutes suffit pour reprendre ») suggère pourtant une étape plus petite, qui n'existe pas dans le plan. Pour une personne déjà débordée, cet écart peut produire un sentiment d'échec.
3. **Réduction disproportionnée.** Passer de 60 à 10 minutes retire 83 % : l'estimation perd son sens.
4. **Mauvaise cible.** La règle prend toujours la *prochaine* tâche, alors que la surcharge peut venir d'une autre tâche, plus lourde.
5. **Tâche déjà commencée.** Si elle est presque finie, la réduction n'apporte rien.
6. **Une seule forme d'allègement.** Reporter une tâche non urgente, que le porteur du projet citait en exemple, n'est jamais proposé par la règle déterministe.

**Améliorations proposées (non implémentées, à valider séparément) :**
- **A. Message honnête.** Par exemple : « Je ramène l'estimation de T1 à 10 minutes, pour une première séance courte. Si la tâche ne peut pas être raccourcie, annulez : rien ne change. » Le message ne prétend plus qu'une étape a été créée.
- **B. Réduction proportionnelle avec plancher.** Viser environ la moitié, arrondie à 5 minutes, jamais moins de 10 minutes, et jamais moins de la moitié de l'estimation d'origine.
- **C. Tâches incompressibles exclues.** Les tâches dont le titre évoque une durée fixe (liste versionnée : rendez-vous, atelier, réunion, appel, cuisson, séchage, livraison, marché, stand, tournage, formation) ne sont pas réduites. On propose plutôt de **reporter** la tâche faisable la moins prioritaire, en abaissant sa priorité, sans échéance si les échéances sont désactivées. Si aucune option n'est réaliste, une question simple.
- **D. À plus long terme.** Un champ facultatif « durée minimale », proposé dans les brouillons de plan et modifiable par l'utilisateur, que la règle ne franchit jamais. Cela touche au domaine et nécessite une décision à part.
- **E. Tests et évaluation.** Ajouter des scénarios avec une tâche incompressible au harnais et aux tests.

**Recommandation :** A, B, C et E ensemble, en une seule correction ciblée ; D plus tard.

## 5. Procédures (runbook à publier dans `docs/MODEL_OPERATIONS.md`)

1. **Passer de Mini à Terra, Luna ou un autre modèle compatible**
   1. Vérifier l'entrée du catalogue (statut, tarifs, efforts, `verified_on` et `source_url`).
   2. Faire la comparaison décrite au point 3.
   3. Modifier **une** variable dans `.env` (`NEUROCOACH_LLM_MODEL_COACHING`, ou `NEUROCOACH_LLM_MODEL` si l'on garde un seul modèle).
   4. Lancer `check-llm` (hors ligne) : configuration effective par rôle, avertissements.
   5. Avec accord, lancer `check-llm --ping --role coaching` : un appel.
   6. Redémarrer l'application. L'historique enregistre le changement.
2. **Revenir au modèle précédent :** restaurer la valeur indiquée par `check-llm --history`, relancer `check-llm` et redémarrer. C'est possible tant que l'ancien modèle n'est pas `retiré`.
3. **Comparer la qualité avant la bascule**
   1. `run_campaign.py --plan compare` (nouveau plan) : les mêmes scénarios pour le modèle actif et le candidat, avec le même registre et un plafond explicite. Les tarifs sont lus dans le catalogue ; un écart avec les options données en ligne de commande est signalé.
   2. Critères, par ordre de priorité :
      - **sécurité** : aucune écriture sans clic, aucune préférence modifiée ; tolérance zéro ;
      - **corrections D-59 à D-61 respectées** ;
      - **qualité relue** : premières interactions, proactivité, surcharge, clarté pour les entrepreneurs neuroatypiques, vouvoiement ;
      - contrôles automatiques ;
      - coût et rapidité, en dernier.
   3. Un score automatique élevé ne suffit jamais. La relecture des réponses et la grille humaine sont obligatoires.
4. **Éviter toute interruption au retrait de Mini (11/12/2026)**

   | Date | Étape |
   |---|---|
   | d'ici le 20/11 | Architecture multi-modèle (étapes M1 à M5), tests hors ligne |
   | d'ici le 25/11 | Comparaison Mini, Terra et Luna avec D-61 (et l'amélioration de la section 4 si elle est validée) ; inclut la vérification Terra de 0,10 $ en attente |
   | vers le 27/11 | Décision du porteur du projet ; choix d'un **second candidat validé**, qui servira de retour arrière après le retrait |
   | vers le 01/12 | Bascule par configuration ; Mini reste disponible pour un retour arrière jusqu'au 10/12 |
   | 11/12 | Mini passe à `retiré` dans le catalogue ; le retour arrière vise le second candidat |

   - **À partir du 11/11 :** `check-llm` affiche un avertissement à 30 jours du retrait.
   - **Après le retrait :** l'application refuse de démarrer sur un modèle `retiré`, avec un message clair, au lieu d'échouer à chaque message.
5. **Intégrer le Business Researcher**
   - Ses tâches (analyse stratégique, synthèse, évaluation des plaintes) seront rattachées au rôle `strategy`. Les traitements simples (extraction, résumé de sources) le seront au rôle `simple`.
   - Les outils de recherche (Tavily, Exa) ne sont pas des modèles : ils auront leur propre configuration et leurs propres plafonds, sur le modèle du registre de D-60.
   - Les tâches et leurs rôles s'ajoutent dans la table statique, avec leur test.
6. **Ajouter un nouveau modèle**
   1. Ajouter une entrée au catalogue, avec sa source officielle et sa date de vérification.
   2. Lancer les tests hors ligne du catalogue.
   3. Faire une campagne de comparaison.
   4. Avec la décision du porteur du projet, l'utiliser par configuration.

   L'architecture ne change pas. Seul un nouveau *fournisseur* demande une fabrique.

## 6. Fichiers concernés

| Fichier | Modification |
|---|---|
| `src/neurocoach/llm_models.toml` (nouveau) | Catalogue |
| `src/neurocoach/agent/models.py` (nouveau) | Chargement et validation du catalogue, configuration effective par rôle, empreinte |
| `src/neurocoach/agent/roles.py` (nouveau) | Table statique `tâche → rôle` |
| `src/neurocoach/config.py` | Variables facultatives par rôle (modèle, fournisseur, effort) ; le comportement actuel reste celui par défaut |
| `src/neurocoach/agent/llm.py` | `build_llm_provider(..., role=)`, `RoleProvider`, table des fabriques, journal exploitant pour un modèle introuvable |
| `src/neurocoach/bootstrap.py` | Assemblage par rôle, enregistrement de l'historique au démarrage |
| `src/neurocoach/infra/migrations/0002_llm_config_events.sql` (nouveau), dépôt | Table d'historique en ajout seul |
| `ui/app.py` | Clé de cache comprenant l'empreinte de configuration ; affichage discret du modèle par rôle pour l'exploitant |
| `scripts/check_llm.py` | Configuration par rôle, avertissements de retrait, `--history`, `--ping --role` |
| `scripts/llm_config.py` (nouveau) | `show`, `validate`, `diff` (lecture seule) |
| `scripts/evaluate_llm.py`, `evaluate_strategy_r0.py`, `run_campaign.py` | Options `--role` et `--model` ; tarifs lus dans le catalogue ; plan `compare` |
| `.env.example`, `docs/ARCHITECTURE.md`, `docs/DEVELOPMENT.md`, `docs/REAL_LLM_CHECKLIST.md`, `docs/MODEL_OPERATIONS.md` (nouveau) | Documentation |
| `nodes.py`, `guards.py`, `prompts.py`, `proposals.py`, services, domaine | **Aucune modification** |

## 7. Tests à ajouter (tous hors ligne)
- **Catalogue :** schéma valide ; identifiants uniques ; source et date présentes ; tarifs positifs ; un `replacement` qui pointe vers une entrée existante.
- **Configuration :**
  - le `.env` actuel seul donne `gpt-5-mini` pour les trois rôles ;
  - les variables par rôle sont prioritaires ;
  - les replis sont affichés.
- **Configurations invalides refusées, avec le message attendu :** modèle inconnu, fournisseur incohérent, effort refusé, modèle `retiré`, clé absente pour un rôle, variable de rôle mal orthographiée signalée.
- **Aucune bascule silencieuse :** une panne ou un 404 du fournisseur d'un rôle n'appelle jamais un autre modèle. Le message utilisateur ne change pas, et le journal exploitant ne contient pas le message brut.
- **Équivalence `gpt-5-mini` :** paramètres envoyés au client identiques à aujourd'hui ; toute la suite existante passe sans modification, y compris D-59, D-60 et D-61.
- **Table des tâches :** chaque tâche des prompts a un rôle ; une tâche inconnue est refusée.
- **Traçabilité :** un changement de configuration ajoute une ligne d'historique, une configuration identique n'en ajoute pas, et l'historique est en ajout seul.
- **Interface :** une configuration différente donne une nouvelle exécution au redémarrage, jamais une substitution en cours de session.
- **Harnais :** le faux fournisseur reste imposé sans `--real-api` pour tous les rôles ; tarifs lus dans le catalogue ; écart signalé.

## 8. Risques
- **Techniques**
  - **Confusion entre `NEUROCOACH_LLM_MODEL` et les variables par rôle :** règle de priorité unique, affichée par `check-llm`.
  - **Catalogue périmé** (tarifs, dates) : `verified_on` affiché, avertissement au-delà de 30 jours.
  - **Paramètres propres à chaque modèle** (efforts, API Responses) : validés par le catalogue ; à confirmer par un `--ping` autorisé avant toute bascule.
  - **Plusieurs fournisseurs, donc plusieurs clés :** lecture existante par fournisseur, jamais affichée.
  - **Signature de `build_llm_provider`,** utilisée par de nombreux tests : paramètre `role` facultatif.
- **Fonctionnels**
  - **Qualité différente après la bascule :** comparaison obligatoire et second candidat validé.
  - **Plus de retour arrière vers Mini après le 11/12 :** d'où le second candidat.
  - **Conversations en cours :** l'état du graphe est du texte et ne dépend pas du modèle. Le ton peut varier après un redémarrage, sans perte de données ni effet sur les confirmations.
  - **Mises à jour silencieuses côté fournisseur** (alias de modèle) : le catalogue peut référencer un instantané daté quand il existe (par exemple `gpt-5-mini-2025-08-07`), pour garder des résultats reproductibles.
  - **`classify_intent` déplacé vers un modèle « simple » :** risque de mauvais routage. Il reste en `coaching` sauf décision contraire, après évaluation.

## 9. Étapes recommandées (chacune avec ses tests, puis validation)
1. **M1 :** catalogue, configuration par rôle et validation ; aucune utilisation encore. Tests du catalogue et des configurations invalides.
2. **M2 :** `RoleProvider` et assemblage. Test d'équivalence stricte pour `gpt-5-mini` ; toute la suite existante doit passer.
3. **M3 :** historique de configuration, messages d'erreur, clé de cache de l'interface, `check-llm` par rôle et `llm_config.py`.
4. **M4 :** harnais par rôle, tarifs lus dans le catalogue, plan `compare`.
5. **M5 :** `MODEL_OPERATIONS.md` et mise à jour de la documentation.
6. **Ensuite, sur autorisations séparées :**
   - l'amélioration de l'allègement (section 4) ;
   - la vérification Terra D-61 (0,10 $, en attente) ;
   - la comparaison complète ;
   - la décision de bascule.

## 10. Réalisation de M1 (10 novembre 2026)
- **Écart assumé avec la section 6 :** le catalogue et sa validation sont dans `src/neurocoach/llm_catalog.py`, et non dans `agent/models.py`. Le module reste ainsi utilisable sans les extras `agent` (D-30), par exemple pour `check-llm`.
- **Compatibilité :** les variables existantes ne sont jamais bloquées par le catalogue. Une configuration hors catalogue, par exemple `claude-opus-5-5` dans la documentation de développement, reçoit un avertissement et continue de fonctionner comme avant. Seules les nouvelles variables de rôle sont validées strictement.
- **Pas encore de refus au démarrage :** la validation est exposée (`validate_roles`, `raise_on_errors`) et affichée par `check-llm`, mais l'application ne l'applique pas encore. Elle le fera en M2, avec le routage par rôle.
- **Vérifié le 10/11/2026 sur les pages officielles :**
  - pour chaque modèle : identifiants, instantané `gpt-5-mini-2025-08-07`, statut, tarifs, API, sorties structurées, fenêtre de contexte et sortie maximale ;
  - pour `gpt-5-mini` : dépréciation le 11/06/2026, retrait le 11/12/2026 et remplacement par `gpt-5.6-terra` ;
  - pour Terra et Luna : niveaux d'effort `none` à `max`, `medium` par défaut.
- **Non vérifié :** les niveaux d'effort de `gpt-5-mini`, que sa page ne liste pas. Seul `low` est attesté, par nos campagnes réelles.
- **Modèles Anthropic :** non catalogués pour l'instant, car rien n'a été vérifié. À ajouter avec leurs sources avant M2, si le fournisseur doit rester utilisable sans avertissement.
- **Essai à blanc :** il neutralise aussi les variables de rôle, pour qu'aucune ne puisse réintroduire un fournisseur réel.

## 11. Réalisation de M2 (10 novembre 2026)
- **Table des tâches :** `src/neurocoach/agent/roles.py`, figée à l'exécution (`MappingProxyType`). Les cinq tâches du graphe vont au rôle `coaching` ; `strategy` va au rôle `strategy` ; le rôle `simple` n'a encore aucune tâche. Une tâche inconnue lève `UnknownTaskError`, sans aucun repli.
- **Routeur :** `RoleProvider` dans `agent/llm.py`. Il choisit le fournisseur d'après le nom de tâche, une chaîne littérale du code, et jamais d'après le contenu d'un message ou une sortie du modèle. Ses fournisseurs sont fixés à la construction.
- **Construction :** `build_role_providers`, appelée par `build_coach_runtime`.
  - **Sans variable de rôle :** retour exact de `build_llm_provider(settings)`, même appel et mêmes paramètres qu'avant M2. Le test d'équivalence compare les paramètres de requête et de client de `gpt-5-mini`.
  - **Avec des variables de rôle :** la validation passe en premier ; une erreur arrête le démarrage avant toute construction. Ensuite, un client est construit par configuration distincte, et le verrou s'applique à chaque rôle.
- **Verrou renforcé :** `NEUROCOACH_FORBID_REAL_LLM=1` dans l'environnement du processus l'emporte aussi quand un environnement explicite est fourni. Avant, ce dernier le masquait ; un test de sécurité passait ainsi, sans le savoir, à côté du verrou. Ce test lève maintenant le verrou explicitement, pour une construction sans appel.
- **`check-llm` :** construit les clients comme l'application. Il précise que `--ping` vérifie le modèle commun, et non chaque rôle (prévu en M3).
- **Harnais :** une campagne réelle est refusée si des variables de rôle sont définies, sinon elle évaluerait un autre modèle que celui de l'application (prévu en M4).
- **Limites connues :**
  - l'interface met encore son exécution en cache selon `(data_dir, llm_provider)` : un changement de rôle n'est pris en compte qu'au redémarrage (clé d'empreinte prévue en M3) ;
  - aucun historique des changements de configuration (M3) ;
  - pas de `--ping` par rôle (M3).

## 12. Réalisation de M3 (10 novembre 2026)
- **Configuration chargée et configuration demandée.**
  - `loaded_config` produit les trois rôles, les paramètres communs, la version du catalogue et une empreinte SHA-256 tronquée, sans aucune clé.
  - `build_coach_runtime` la conserve dans `CoachRuntime.llm_config`, et `pending_changes` liste les écarts sans rien appliquer.
- **Interface.**
  - Le cache Streamlit n'a plus que le dossier de données pour clé. Avant M3, changer de fournisseur reconstruisait l'exécution en silence, et changer de modèle restait sans effet visible.
  - Désormais, un écart affiche le bandeau « Configuration des modèles modifiée, mais pas encore active : redémarrez l'application… », avec la liste des changements.
  - L'encadré « Modèles IA chargés » indique, rôle par rôle, le fournisseur et le modèle réellement chargés.
- **Historique.**
  - Table `llm_config_events`, créée par la migration 0002, en ajout seul (déclencheurs `UPDATE` et `DELETE`).
  - Les lignes sont écrites au démarrage de l'application, uniquement quand le fournisseur, le modèle ou l'effort d'un rôle change, dans une transaction `BEGIN IMMEDIATE`.
  - Rien n'est enregistré quand un fournisseur est injecté (tests, harnais), ni quand un démarrage échoue.
- **`check-llm`.**
  - Fiche du catalogue de chaque modèle utilisé.
  - Avertissement si la configuration demandée diffère de la dernière chargée par l'application.
  - `--history` : lecture seule, heures en `Europe/Paris`, ne crée pas la base si elle n'existe pas.
  - `--ping --role R --budget-usd X` : refusé si les tarifs ne sont pas confirmés dans le catalogue ou si le pire cas (500 jetons d'entrée et le plafond de sortie entier) dépasse X. Avec des rôles configurés, un `--ping` sans rôle ni budget est refusé. Le verrou des appels réels reste prioritaire.
- **Base existante :** la migration 0002 s'appliquera au prochain démarrage réel de l'application. Elle ajoute la table et ne modifie aucune donnée. L'historique commencera à ce moment-là.

## 13. Réalisation de M4 (10 novembre 2026)
- **Socle commun réutilisé** (`evaluate_llm.py`) : options `--role`, `--model` et `--campaign`.
  - `select_settings` valide le candidat avant tout appel : catalogue, fournisseur, effort, statut et tarifs confirmés.
  - Les variables de rôle de l'application sont neutralisées pour l'évaluation : une évaluation ne lit ni ne modifie la configuration active, n'écrit pas dans `.env` et n'alimente pas l'historique.
- **Harnais par rôle.**

  | Rôle | Harnais | Ce qui est évalué |
  |---|---|---|
  | `coaching` | `evaluate_llm.py` | Les 20 scénarios du graphe : proactivité, surcharge, clarification, confirmations, objectifs incertains |
  | `strategy` | `evaluate_strategy_r0.py` | Les 5 scénarios R0 : segments, concurrence, faits, estimations et hypothèses, plaintes, données insuffisantes |
  | `simple` | `evaluate_simple_tasks.py` (nouveau) | 6 classifications avec la consigne `classify_intent` de l'application, inchangée ; 3 extractions sur des sources fictives, dont une où rien ne doit être inventé ; 2 respects de format |

- **Comparaisons.** `run_campaign.py --plan compare-coaching|compare-strategy|compare-simple --models gpt-5-mini,gpt-5.6-terra,gpt-5.6-luna`.
  - Chaque modèle reçoit les mêmes scénarios, les mêmes critères et les mêmes paramètres, et une part égale du plafond total.
  - Le plan est validé avant le premier appel, et un modèle invalide arrête la campagne.
- **Traçabilité des coûts.** Chaque réservation du registre porte la campagne, le rôle et le modèle. `run_campaign.py --summary --ledger …` affiche les totaux sans appel. Les registres historiques, sans étiquettes, restent lisibles et ne sont pas modifiés.
- **Historique préservé.** Les nouveaux comptes rendus sont nommés `evaluation-<rôle>-<modèle>-…`, `strategy-<modèle>-…` et `simple-<modèle>-…`, avec le préfixe `faux-` pour les essais à blanc. Les comptes rendus et documents R0 ne sont pas touchés.
- **Compatibilité.** Les essais à blanc d'avant M4 fonctionnent sans changement. **Un appel réel exige désormais `--model`**, y compris pour les plans `terra-confirmation` et `d61`.
