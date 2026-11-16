# Exploitation des modèles IA et procédure de migration

**Date :** 10 novembre 2026. **Statut :** procédure (M5). **Modèle actif :** `gpt-5-mini`, inchangé.
Elle s'appuie sur D-60 (aucun appel réel sans demande explicite) et D-62 à D-65 (catalogue, rôles, traçabilité, harnais). Conception : [MULTI_MODEL_DESIGN.md](MULTI_MODEL_DESIGN.md).

> **Règles permanentes**
> - Aucune bascule automatique : un modèle ne change que si une personne modifie `.env`, puis redémarre l'application.
> - Aucun repli silencieux vers un autre modèle ou fournisseur.
> - Toute commande marquée **PAYANT** appelle un vrai modèle : elle exige une approbation explicite, un budget strict et, pour les campagnes, un registre. Aucune ne doit être lancée sans accord.
> - Les commandes sont données pour Windows (PowerShell), depuis la racine du dépôt.

## 1. Consulter les modèles réellement chargés
- **Dans l'interface**, barre latérale, encadré **« Modèles IA chargés »** :
  - une ligne par rôle (coaching entrepreneurial, stratégie et recherche business, tâches simples), avec le fournisseur, le modèle, l'effort et la mention « (chargé) ». C'est ce que l'application utilise réellement ;
  - « Configuration demandée : identique à la configuration chargée. » quand `.env` correspond.
  - Sinon, un bandeau jaune s'affiche : **« Configuration des modèles modifiée, mais pas encore active : redémarrez l'application… »**, suivi de la liste des écarts. Tant que vous ne redémarrez pas, l'ancien modèle reste utilisé.
- **En ligne de commande**, hors ligne et sans appel :

```powershell
.\.venv\Scripts\python.exe scripts\check_llm.py
```

  La commande compare la configuration demandée à **la dernière configuration chargée par l'application**, d'après l'historique :
  - « Dernière configuration chargée par l'application : identique. » ;
  - ou l'avertissement « Configuration demandée différente de la dernière chargée… : elle ne sera active qu'au prochain démarrage. ».

## 2. Vérifier la configuration par rôle
`check_llm.py` affiche, sans appel :
- **par rôle :** `Rôle coaching entrepreneurial : openai (hérité) · gpt-5-mini (hérité) · effort par défaut (hérité)`. « (hérité) » signifie que la valeur vient de la configuration commune ;
- **le routage :** « configuration commune pour tous les rôles », ou « actif (variables de rôle définies) » ;
- **la fiche du catalogue** de chaque modèle utilisé : statut, date de retrait, tarifs, date de vérification et champs non vérifiés ;
- **les avertissements :** retrait proche, effort non confirmé, variable mal orthographiée ;
- **les erreurs bloquantes**, qui arrêtent aussi le démarrage de l'application.

**Variables** (dans `.env`, jamais versionné) :

| Variable | Rôle | Si absente |
|---|---|---|
| `NEUROCOACH_LLM_PROVIDER`, `NEUROCOACH_LLM_MODEL`, `NEUROCOACH_LLM_EFFORT` | Configuration commune (historique) | Faux fournisseur |
| `NEUROCOACH_LLM_PROVIDER_COACHING`, `_MODEL_COACHING`, `_EFFORT_COACHING` | Rôle coaching | Valeur commune |
| `…_STRATEGY` | Rôle stratégie (aucune tâche de l'application aujourd'hui) | Valeur commune |
| `…_SIMPLE` | Rôle tâches simples (aucune tâche de l'application aujourd'hui) | Valeur commune |

**Validation :**
- **Variables de rôle :** validées **strictement**. Un modèle absent du catalogue, un fournisseur incohérent, un effort refusé ou un modèle retiré est une erreur.
- **Variables communes :** une valeur hors catalogue ne produit qu'un **avertissement**, par compatibilité avec les configurations historiques. Lisez donc toujours la sortie de `check_llm.py` avant de redémarrer.
- **Catalogue :** `src/neurocoach/llm_models.toml`. Les informations non confirmées par la documentation officielle (`unverified`) ne bloquent jamais.

## 3. Modifier un modèle de manière explicite
1. **Avant toute bascule réelle,** suivre la procédure de migration (section 8) et obtenir l'approbation du porteur du projet.
2. **Modifier une seule ligne de `.env`**, à la main. Exemple, pour tous les rôles :
   ```text
   NEUROCOACH_LLM_MODEL=gpt-5.6-terra
   NEUROCOACH_LLM_EFFORT=low
   ```
   Ou pour le seul coaching : `NEUROCOACH_LLM_MODEL_COACHING=gpt-5.6-terra`.
   - **Effort.** Fixez l'effort explicitement, à la valeur réellement évaluée. Aujourd'hui, l'application tourne avec `NEUROCOACH_LLM_EFFORT` vide, c'est-à-dire avec l'effort par défaut du modèle. Toutes les campagnes ont pourtant été mesurées en `low`, et l'effort par défaut de Terra et de Luna est `medium` d'après leur documentation.
   - **Choix de la variable.** Tant que seul le coaching sert dans l'application, modifier la variable commune garde tous les rôles alignés. Les variables de rôle servent à différencier les rôles plus tard ; elles sont validées plus strictement.
3. **Vérifier hors ligne :**
   ```powershell
   .\.venv\Scripts\python.exe scripts\check_llm.py
   ```
   Aucune ligne « Bloquant » ne doit apparaître, ni d'avertissement « Modèle inconnu ». L'écart avec la dernière configuration chargée est attendu à ce stade.
4. **Redémarrer** (section 4). Rien n'est appliqué avant.

## 4. Redémarrer l'application en sécurité
1. **Choisir un moment calme.** Un message en cours de traitement serait interrompu. Les propositions en attente sont conservées en base : elles ne dépendent pas du modèle et expirent après 15 minutes par défaut.
2. **Arrêter Streamlit** dans son terminal (`Ctrl+C`).
3. **Relancer :**
   ```powershell
   .\.venv\Scripts\python.exe scripts\dev.py demo
   ```
4. **Vérifier :**
   - l'encadré « Modèles IA chargés » montre le modèle voulu ;
   - aucun bandeau de redémarrage n'apparaît ;
   - `check_llm.py` indique « Dernière configuration chargée par l'application : identique » ;
   - `check_llm.py --history` contient une nouvelle ligne.

**Si le démarrage échoue** (erreur de configuration), rien n'est enregistré dans l'historique et aucun appel n'a lieu. Corrigez `.env` d'après le message, ou revenez à la valeur précédente (section 6).

## 5. Consulter l'historique des changements
```powershell
.\.venv\Scripts\python.exe scripts\check_llm.py --history
```
Exemple de ligne : `25/11/2026 10:00 · coaching entrepreneurial : openai · gpt-5-mini · effort par défaut → openai · gpt-5.6-terra · effort low`.
- **Contenu :**
  - une ligne par rôle modifié, écrite **au démarrage réussi** de l'application seulement ;
  - aucune ligne si la configuration n'a pas changé ;
  - heures stockées en UTC et affichées en `Europe/Paris`.
- **Garanties :**
  - ajout seul : la base refuse toute modification ou suppression ;
  - aucune clé, aucun utilisateur, aucun projet, aucun contenu de conversation ;
  - lecture seule : la commande ne crée pas la base si l'application n'a jamais démarré.
- **Avant le premier démarrage depuis M3 :** « Aucun historique : l'application n'a pas encore démarré avec cette base. ». La table est ajoutée par la migration 0002 au prochain lancement, sans toucher aux données existantes.

## 6. Revenir à la configuration précédente
1. `check_llm.py --history` : relever la valeur « avant » de la dernière ligne.
2. Remettre cette valeur dans `.env`, ligne par ligne, effort compris.
3. `check_llm.py` : aucune ligne « Bloquant ».
4. Redémarrer (section 4) et vérifier l'encadré, puis l'historique, qui contient la ligne de retour arrière.

**Le retour arrière n'est possible que vers un modèle encore disponible.** Après le **11 décembre 2026**, `gpt-5-mini` ne le sera plus. Il faudra alors revenir vers le **second candidat validé** (section 10).

## 7. Réagir à une erreur ou à un modèle indisponible
| Symptôme | Cause probable | Action |
|---|---|---|
| Démarrage refusé : « Modèle inconnu pour le rôle… Modèles déclarés : … » | Faute de frappe, ou modèle absent du catalogue | Corriger `.env` ; un nouveau modèle s'ajoute d'abord au catalogue, avec ses sources officielles |
| « … est un modèle openai, mais le rôle … est configuré pour anthropic » | Fournisseur incohérent | Aligner `NEUROCOACH_LLM_PROVIDER[_RÔLE]` |
| « L'effort « … » n'est pas accepté par … » | Effort refusé par le modèle | Choisir un effort de la liste affichée |
| « … est retiré depuis le … » | Modèle retiré (catalogue) | Revenir au second candidat validé (section 6) |
| « Appels réels interdits dans ce processus (NEUROCOACH_FORBID_REAL_LLM=1) » | Variable de test présente dans le terminal | Ouvrir un terminal sans cette variable. Elle est posée volontairement par les tests et les essais à blanc |
| « Fournisseur … non configuré : vérifiez la clé API dans .env » | Clé absente ou invalide à la construction | Vérifier la clé dans `.env` (jamais affichée) |
| Bandeau « … pas encore active : redémarrez… » | `.env` modifié sans redémarrage | Redémarrer, ou annuler la modification |
| En conversation : « Le service de langage ne répond pas. Vos données sont intactes ; réessayez. » | Réseau, quota (429), clé refusée (401), modèle supprimé (404) | Consulter la page d'état et le tableau de bord du fournisseur. Avec accord, un test minimal **PAYANT** affiche le type d'erreur et le statut HTTP, sans la clé ni le message (voir ci-dessous). Aucun autre modèle n'est essayé automatiquement : si le modèle est retiré, revenir au second candidat |

Test minimal d'un rôle, **PAYANT** et seulement avec accord. Le pire cas est d'environ 0,008 $ pour `gpt-5-mini` et 0,049 $ pour Terra, avec un plafond de sortie de 4 000 jetons. La commande est refusée si ce pire cas dépasse le budget indiqué :
```powershell
.\.venv\Scripts\python.exe scripts\check_llm.py --ping --role coaching --budget-usd 0.01  # PAYANT
```
Sans variable de rôle, `check_llm.py --ping` (PAYANT) teste le modèle commun.

**Limite connue :** pendant une conversation, l'application ne conserve pas le statut HTTP d'une panne ; l'utilisateur voit seulement le message générique. Le diagnostic passe par le test minimal ci-dessus ou par le tableau de bord du fournisseur.

## 8. Procédure de migration : de `gpt-5-mini` vers un candidat
Chaque étape **PAYANTE** exige une approbation séparée, avec son budget. Aucune n'est réalisée par cette procédure.

1. **Vérifier la documentation officielle (gratuit).**
   - Sur la page du modèle, la page des dépréciations et la page des tarifs (`developers.openai.com/api/docs/...`) : identifiant exact, statut, date de retrait, API, sorties structurées, niveaux d'effort, tarifs.
   - Mettre à jour `src/neurocoach/llm_models.toml` : `verified_on`, `sources`, et `unverified` pour tout ce qui n'est pas confirmé.
2. **Exécuter les tests hors ligne (gratuit) :**
   ```powershell
   .\.venv\Scripts\python.exe scripts\dev.py cov
   .\.venv\Scripts\python.exe scripts\dev.py lint
   .\.venv\Scripts\python.exe scripts\dev.py check-secrets
   ```
3. **Préparer la campagne à blanc (gratuit).** Vérifier les commandes et les comptes rendus :
   ```powershell
   .\.venv\Scripts\python.exe scripts\run_campaign.py --plan compare-coaching --models gpt-5-mini,gpt-5.6-terra,gpt-5.6-luna
   ```
4. **Faire approuver la campagne réelle :** modèles, scénarios, effort, plafond total, registre neuf (section 9).
5. **Lancer la campagne réelle (PAYANT, après accord seulement).** Exemple avec un registre unique et un plafond global, un modèle par invocation, `--resume` à partir de la deuxième :
   ```powershell
   .\.venv\Scripts\python.exe scripts\run_campaign.py --real-api --plan compare-coaching --models gpt-5.6-terra --total-usd 0.60 --max-output-tokens 2000 --ledger data\evaluations\comparaison-2026-11.jsonl --campaign comparaison-2026-11  # PAYANT
   .\.venv\Scripts\python.exe scripts\run_campaign.py --real-api --plan compare-coaching --models gpt-5-mini --total-usd 0.60 --max-output-tokens 2000 --ledger data\evaluations\comparaison-2026-11.jsonl --campaign comparaison-2026-11 --resume  # PAYANT
   ```
   - Utiliser la **même valeur de `--total-usd`** à chaque invocation : c'est le plafond de tout le registre.
   - Suivre les coûts sans appel : `run_campaign.py --summary --ledger data\evaluations\comparaison-2026-11.jsonl`.
6. **Comparer les mêmes scénarios** (section 9) : seulement ceux que tous les modèles ont terminés.
7. **Faire relire les comptes rendus par une personne** (`data/evaluations/`), grille remplie. Les contrôles automatiques ne suffisent jamais.
8. **Obtenir l'approbation explicite du porteur du projet,** avec le modèle principal, l'effort et le second candidat de retour arrière.
9. **Basculer** (section 3, par la personne qui gère `.env`) et **redémarrer** (section 4).
10. **Vérifier le modèle effectivement chargé et le comportement** (section 11).
11. **Garder un retour arrière prêt :** `gpt-5-mini` jusqu'au 10/12/2026, puis le second candidat.

## 9. Qualité des comparaisons
### 9.1 Limites actuelles des harnais
- **Même effort, pas même raisonnement.** Un effort `low` identique ne garantit pas une quantité de raisonnement équivalente d'un modèle à l'autre : chaque fournisseur l'interprète à sa manière. C'est un paramètre aligné, pas une équivalence.
- **Les essais à blanc ne prouvent rien sur la qualité.** Leurs scores (20/20, 10/10, 11/11) valident les harnais, pas les modèles. Chaque compte rendu le rappelle en tête.
- **Stratégie : recherches simulées.** Les 5 scénarios reposent sur des sources fictives et ne reproduisent pas le bruit du Web réel.
- **Petits échantillons.** 20 scénarios de coaching, 5 de stratégie (2 essais) et 11 cas simples ne suffisent pas, à eux seuls, à choisir un modèle. Les écarts d'un ou deux scénarios ne sont pas significatifs.
- **Parts égales du budget.** Une part égale ne garantit pas que chaque modèle termine ses scénarios : Terra coûte environ 4 fois plus que Mini par scénario de coaching. Il faut comparer les **mêmes scénarios effectivement terminés**.
- **La relecture humaine reste obligatoire.** Les contrôles automatiques ne mesurent ni la justesse d'un conseil, ni la clarté pour des entrepreneurs neuroatypiques.
- **Aucune mesure de la variabilité,** sans plusieurs passages.
- **Effort non mesuré pour Mini.** Les niveaux d'effort de `gpt-5-mini` ne sont pas listés par sa documentation officielle. Seul `low` a été utilisé avec succès.

### 9.2 Protocole de comparaison équitable (proposé, non lancé)
1. **Mêmes conditions.** Même jour, même version du code et du catalogue, mêmes scénarios, même effort (`low`, ou l'effort retenu pour la production, à tester alors pour tous), même délai, aucune nouvelle tentative, même plafond de sortie. La référence `gpt-5-mini` est jouée dans la même campagne.
2. **Budget dimensionné pour terminer.** Plafond global unique, et un modèle par invocation (section 8, étape 5), pour qu'aucun modèle ne soit arrêté faute de part. Estimation à partir des coûts réels observés le 10/11/2026, effort `low` :

   | Harnais | `gpt-5-mini` | `gpt-5.6-terra` | `gpt-5.6-luna` |
   |---|---|---|---|
   | Coaching, un passage (16 à 19 scénarios observés) | ≈ 0,04 $ | ≈ 0,20 $ | ≈ 0,02 $ |
   | Stratégie (10 réponses) | ≈ 0,03 $ | ≈ 0,15 $ | ≈ 0,02 $ |
   | Tâches simples (11 cas) | non mesuré | non mesuré | non mesuré |

   Prévoir une marge pour la réservation au pire cas, avec `--max-output-tokens 2000`. Pour les tâches simples, commencer par un petit plafond.
3. **Au moins deux passages** du coaching par modèle, pour estimer la variabilité.
4. **Analyse limitée à l'intersection.** Ne comparer que les scénarios terminés par tous les modèles. Un modèle arrêté par le budget est relancé avec `--resume`, sans être jugé sur moins de scénarios.
5. **Relecture humaine, si possible à l'aveugle.** Une personne lit les réponses sans connaître le modèle (noms masqués dans une copie des comptes rendus) et remplit la grille.
6. **Règle de décision, par ordre de priorité :**
   - **sécurité :** tolérance zéro (écriture sans clic, préférence modifiée, injection acceptée, tutoiement) ;
   - **comportements corrigés D-59 à D-61 :** premières interactions, modification imprécise, surcharge, objectif incertain ;
   - **qualité relue :** utilité du conseil, proactivité, clarté et accessibilité, fidélité ;
   - **contrôles automatiques ;**
   - **coût et rapidité,** en dernier.
7. **Décision documentée :** modèle principal, effort, second candidat de retour arrière, limites.

## 10. Préparer le retrait de `gpt-5-mini`
**Source officielle,** vérifiée le 10/11/2026 : <https://developers.openai.com/api/docs/deprecations>.
- `gpt-5-mini` et `gpt-5-mini-2025-08-07` : dépréciés (notification du 11/06/2026), **retrait de l'API le 11/12/2026**, remplacement recommandé : `gpt-5.6-terra`.
- `gpt-5.6-terra` et `gpt-5.6-luna` : aucune dépréciation listée à cette date.
- **Revérifier cette page avant chaque étape du calendrier.**

**Calendrier prudent proposé** (chaque étape payante est soumise à approbation) :

| Au plus tard | Étape | Coût |
|---|---|---|
| 14/11/2026 | Valider cette procédure ; décider des améliorations préalables éventuelles (allègement de D-61, voir [MULTI_MODEL_DESIGN.md](MULTI_MODEL_DESIGN.md) §4) | Gratuit |
| 18/11/2026 | Comparaison du coaching : Mini en référence, Terra et Luna, deux passages | PAYANT, à approuver |
| 20/11/2026 | Comparaisons de la stratégie et des tâches simples | PAYANT, à approuver |
| 24/11/2026 | Relecture humaine et décision : **modèle principal** et **second candidat validé** | Gratuit |
| 26/11/2026 | Corrections déterministes éventuelles, avec leurs tests, puis courte confirmation réelle | PAYANT, à approuver |
| 30/11/2026 | **Bascule** (au moins 11 jours avant le retrait), puis vérifications (section 11) | Usage normal |
| 01/12 → 09/12/2026 | Période d'observation ; retour arrière possible vers Mini ; second candidat prêt (configuration et vérification hors ligne) | — |
| 04/12/2026 | Gel : plus de changement de modèle, sauf retour arrière | — |
| 11/12/2026 | Retrait de Mini : passer `gpt-5-mini` à `retired` dans le catalogue après confirmation officielle ; le retour arrière vise désormais le second candidat | Gratuit |

**Ne pas attendre le dernier jour :** si la décision n'est pas prise le 30/11, basculer quand même vers le meilleur candidat validé. Mini serait sinon indisponible le 11/12, et chaque message échouerait.

## 11. Vérifications après migration
1. **Modèle chargé :**
   - l'encadré « Modèles IA chargés » montre le modèle voulu, et aucun bandeau n'est affiché ;
   - `check_llm.py` affiche « Dernière configuration chargée par l'application : identique » ;
   - `check_llm.py --history` contient la nouvelle ligne.
2. **Fonctionnement, par une personne et sur un projet de démonstration** (`docs/DEMO_SCRIPT.md`) :
   - première idée : une orientation puis une seule question ;
   - un plan est proposé, et rien n'est enregistré avant Confirmer ;
   - un « oui » écrit ne confirme pas ;
   - la surcharge donne un allègement proposé et non appliqué ;
   - une modification vague donne la question « Quelle tâche… ? » ;
   - les préférences ne sont pas modifiées par la conversation ;
   - aucune échéance n'apparaît si elles sont désactivées ;
   - une injection est refusée ;
   - le vouvoiement est respecté.
3. **Sécurité :**
   - la suite hors ligne complète passe (`dev.py cov`), et `dev.py check-secrets` aussi ;
   - aucune clé n'apparaît dans les journaux ni dans les comptes rendus.
4. **Coûts :** comparer la consommation réelle au tableau de bord du fournisseur pendant la période d'observation.
5. **En cas de doute :** retour arrière (section 6), puis analyse.

## 12. Décisions qui exigent l'approbation du porteur du projet
- Toute campagne réelle : modèles, scénarios, effort, plafond, registre.
- Le choix du modèle principal, de l'effort et du second candidat de retour arrière.
- La bascule elle-même (modification de `.env`) et sa date.
- Les améliorations préalables éventuelles : allègement de D-61, catalogage des modèles Anthropic.
- Le passage de `gpt-5-mini` à `retired` dans le catalogue, après confirmation officielle.
