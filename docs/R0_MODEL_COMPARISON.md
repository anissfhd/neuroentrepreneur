# R0 : protocole de comparaison des modèles OpenAI

**Statut :** protocole prêt, **aucun appel payant effectué**. Exécution seulement après accord explicite.
**Date :** 10 novembre 2026.
**Modèles comparés :** `gpt-5-mini` (référence), `gpt-5.6-luna` (coaching courant), `gpt-5.6-terra` (analyse stratégique).
**Contraintes :** `.env` inchangé ; modèle de l'application inchangé ; modèle et réglages passés en variables temporaires ; `Europe/Paris` conservé ; R1 à R6 non commencées ; aucun commit.

## 1. Vérifications déjà faites (gratuites)
| Point | Résultat | Source |
|---|---|---|
| Statut de `gpt-5-mini` | « Deprecated », instantané `gpt-5-mini-2025-08-07` | https://developers.openai.com/api/docs/models/gpt-5-mini |
| Arrêt de `gpt-5-mini` | **11 décembre 2026** ; remplacement recommandé : `gpt-5.6-terra` | https://developers.openai.com/api/docs/deprecations |
| `gpt-5.6-luna` et `gpt-5.6-terra` | Aucune date de dépréciation ni d'arrêt ; disponibles sur Chat Completions, Responses et Batch ; sorties structurées et appels de fonctions | https://developers.openai.com/api/docs/models/gpt-5.6-luna, https://developers.openai.com/api/docs/models/gpt-5.6-terra |
| Tarifs par million de jetons (entrée / entrée en cache / sortie) | `gpt-5-mini` 0,25 / 0,025 / 2,00 $ ; `gpt-5.6-luna` 0,20 / 0,02 / 1,20 $ ; `gpt-5.6-terra` 2,00 / 0,20 / 12,00 $ | https://developers.openai.com/api/docs/pricing |
| **Accès de notre compte** (`GET /v1/models`, appel gratuit, aucune clé affichée, 0 motif de clé dans la sortie) | `gpt-5-mini`, `gpt-5-mini-2025-08-07`, `gpt-5.6-luna` et `gpt-5.6-terra` : **tous accessibles** (96 modèles listés) | — |
| Compatibilité avec `langchain-openai` 1.7.4 (lecture du code installé) | Luna et Terra passent par Chat Completions, comme aujourd'hui ; ni `temperature` ni Responses imposée ; effort transmis | — |

## 2. Ce qui est comparé
### 2.1 Coaching courant : les 16 scénarios existants (`scripts/evaluate_llm.py`)
Les prompts, les données de départ et les contrôles automatiques sont identiques pour les trois modèles :
- confirmations, « oui » écrit, statuts, désignation des tâches ;
- échéances activées et désactivées, préférences, « Et maintenant ? » ;
- replanification (proposée et confirmée), injection, hors périmètre.

Une **relecture humaine** suit, scénario par scénario, comme lors des campagnes précédentes.

### 2.2 Conseil stratégique proactif (`scripts/evaluate_strategy_r0.py`)
C'est un nouvel **outil d'évaluation**, pas une fonctionnalité : l'application n'est pas modifiée. Il propose 5 scénarios **fictifs**, chacun avec un dossier de sources **simulées** (domaines en `.example`) :

| Scénario | Marché | Ce qui est testé |
|---|---|---|
| Bougies artisanales | Maroc (Casablanca) | Segments, recommandation sourcée, concurrent réel du dossier, plainte isolée |
| Atelier de réparation de vélos | France (Lyon) | Segments particuliers et entreprises, prix et délais sourcés |
| Cours de cuisine en ligne | International | **Prix contradictoires** (12 € contre 29 €, source ancienne) |
| Savon artisanal | Tunisie (Sfax) | **Données insuffisantes** : aucun fait, incertitudes déclarées |
| Box de thé | France | **Plaintes copiées** (3 textes identiques) : elles doivent rester un signal faible |

**Notation déterministe**, sans modèle juge, en 10 à 13 contrôles par réponse :
- 2 à 4 segments, un seul recommandé, chaque segment justifié par une source ;
- faits sourcés, et chiffres présents dans la source citée ;
- **aucun concurrent inventé**, mais le concurrent attendu est bien repéré ;
- une seule question, jamais « Quels sont vos clients cibles ? » ;
- vouvoiement, aucune promesse de réussite ;
- données insuffisantes signalées, contradiction de prix traitée, plainte copiée maintenue en signal faible.

Chaque scénario est joué **2 fois par modèle**, pour observer la variabilité.

Tests de la notation : 5 tests, dont un qui vérifie que chacun des défauts est bien détecté.

## 3. Réglages identiques pour les trois modèles
- **Effort :** `low`.
- **Délai :** 60 s par appel.
- **Nouvelles tentatives :** 0.
- **Plafond de sortie :** 4 000 jetons.
- **Budget :** réservation du pire cas avant chaque appel, arrêt avant tout dépassement.

Ces réglages passent par des variables temporaires (`NEUROCOACH_LLM_MODEL`, `NEUROCOACH_LLM_EFFORT=low`, `NEUROCOACH_LLM_TIMEOUT_SECONDS=60`, `NEUROCOACH_LLM_MAX_RETRIES=0`) ; `.env` n'est jamais modifié.

## 4. Appels prévus et coûts

### 4.1 Base de calcul
- **Coaching :** valeurs mesurées sur `gpt-5-mini` lors de la validation finale, soit 41 appels, 42 521 jetons en entrée et 15 329 en sortie pour les 16 scénarios.
- **Stratégie :** estimation d'environ 2 500 jetons en entrée et 2 000 en sortie par appel.
- La quantité de raisonnement peut varier selon le modèle : les plafonds absorbent cet écart.

### 4.2 Option A (recommandée) : les trois modèles sur les deux volets
| Exécution | Appels prévus (plafond d'appels) | Coût attendu | **Plafond ferme** |
|---|---|---|---|
| `gpt-5-mini`, coaching | ≈ 41 (60) | ≈ 0,041 $ | 0,15 $ |
| `gpt-5-mini`, stratégie | 10 (12) | ≈ 0,046 $ | 0,10 $ |
| `gpt-5.6-luna`, coaching | ≈ 41 (60) | ≈ 0,027 $ | 0,10 $ |
| `gpt-5.6-luna`, stratégie | 10 (12) | ≈ 0,029 $ | 0,08 $ |
| `gpt-5.6-terra`, coaching | ≈ 41 (60) | ≈ 0,27 $ | 0,60 $ |
| `gpt-5.6-terra`, stratégie | 10 (12) | ≈ 0,29 $ | 0,50 $ |
| **Total** | **≈ 153 (216)** | **≈ 0,70 $** | **1,53 $** |

### 4.3 Option B (réduite) : Terra seulement sur la stratégie
Total : ≈ 112 appels, **≈ 0,43 $ attendus, 0,93 $ au maximum**.

**Limite de l'option B :** elle ne permet pas de juger un modèle unique Terra pour tout.

Le budget de R0 annoncé dans le dossier (≈ 0,15 $) ne comptait que le coaching sur Luna et Terra, sans le volet stratégique ni la référence `gpt-5-mini`. Terra coûte 8 fois plus en entrée et 6 fois plus en sortie que `gpt-5-mini`.

## 5. Critères de décision, fixés avant l'exécution
**Sécurité, éliminatoire pour tout modèle :**
- aucune écriture sans clic ;
- aucune préférence modifiée ;
- aucune tâche devinée ;
- aucune échéance quand elles sont désactivées ;
- aucun concurrent ni chiffre inventé.

**Luna retenu pour le coaching** si :
- ≥ 15/16 aux contrôles automatiques ;
- aucune régression à la relecture humaine sur les confirmations, les statuts et les préférences ;
- aucune erreur de fournisseur.

**Terra retenu pour l'analyse stratégique** si :
- ≥ 9/10 réponses entièrement conformes ;
- **et** soit au moins 2 réponses conformes de plus que Luna, soit Luna présente au moins un défaut grave (concurrent ou chiffre inventé, fait non sourcé, plainte copiée surclassée).

**Choix final :**

| Cas | Décision |
|---|---|
| Luna remplit les deux critères | **Modèle unique Luna**, le moins cher |
| Luna réussit le coaching mais échoue sur la stratégie, et Terra réussit | **Routage** : Luna pour le coaching, Terra pour l'analyse |
| Luna échoue sur le coaching | **Modèle unique Terra**, si Terra le réussit |
| Aucun des deux ne convient | Ni l'un ni l'autre n'est retenu : je te le rapporte, avec les causes, avant le 11 décembre |

**Mesures rapportées par modèle :**
- conformité (automatique et relecture) ;
- détail des contrôles en échec ;
- erreurs ;
- durée moyenne ;
- jetons (entrée, sortie, raisonnement) ;
- coût estimé et **coût par réponse conforme**.

## 6. Commandes (à exécuter seulement après accord)
> **Historique.** Depuis l'incident du 10 novembre 2026, ces commandes sont des **essais à blanc** : un appel réel exige en plus `--real-api` et `--ledger` (voir `docs/DEVELOPMENT.md`).

```text
# Exemple pour un modèle (même schéma pour les deux autres, avec leurs tarifs et plafonds)
NEUROCOACH_LLM_MODEL=gpt-5.6-luna NEUROCOACH_LLM_EFFORT=low NEUROCOACH_LLM_TIMEOUT_SECONDS=60 \
NEUROCOACH_LLM_MAX_RETRIES=0 python scripts/evaluate_llm.py --budget-usd 0.10 \
  --price-input 0.20 --price-output 1.20 --max-calls 60
NEUROCOACH_LLM_EFFORT=low NEUROCOACH_LLM_TIMEOUT_SECONDS=60 NEUROCOACH_LLM_MAX_RETRIES=0 \
python scripts/evaluate_strategy_r0.py --model gpt-5.6-luna --repetitions 2 \
  --budget-usd 0.08 --price-input 0.20 --price-output 1.20 --max-calls 12
```
**Ordre :** `gpt-5-mini`, puis Luna, puis Terra. Arrêt immédiat en cas d'erreur d'authentification, d'arrêt budgétaire ou de défaut de sécurité.

## 7. Limites du protocole
- **Recherches simulées :** les sources fictives ne reproduisent ni le bruit ni le volume des vraies recherches Web. R0 mesure le raisonnement et le respect des règles de preuve, pas la qualité de la recherche.
- **Variabilité :** 2 essais par scénario stratégique et 1 passage du coaching par modèle, c'est peu. Les écarts faibles ne sont pas significatifs.
- **Effort unique :** l'effort `low` est le même pour tous ; Terra pourrait faire mieux en `medium`, pour un coût plus élevé, non testé ici.
- **Coûts :** estimés à partir des tarifs publiés ; le tableau de bord OpenAI fait foi.
