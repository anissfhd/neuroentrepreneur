# R0 : résultats de la comparaison des modèles OpenAI

**Date :** 10 novembre 2026. **Option A** autorisée, plafond total strict de 1,53 $.
**Aucune migration effectuée :** `.env` est inchangé (l'application utilise toujours `gpt-5-mini`). R1 à R6 ne sont pas commencées. Aucun commit.
**Protocole :** `docs/R0_MODEL_COMPARISON.md`. Comptes rendus bruts dans `data/evaluations/` (locaux, non versionnés).

## 1. Exécution et coûts réels
Un orchestrateur a enchaîné les 6 exécutions. Chacune recevait le plus petit montant entre son plafond prévu et le reste réel du budget total, et son propre garde-fou réservait le pire cas avant chaque appel. Aucune nouvelle tentative, effort `low`, délai de 60 s, plafond de sortie de 4 000 jetons.

| Modèle | Volet | Appels (erreurs) | Durée moyenne | Jetons entrée / sortie (dont raisonnement) | Coût estimé |
|---|---|---|---|---|---|
| `gpt-5-mini` | Coaching (16 scénarios) | 42 (0) | 4,8 s | 44 424 / 15 450 (8 000) | 0,0420 $ |
| `gpt-5-mini` | Stratégie (10 réponses) | 10 (0) | 17,8 s | 10 780 / 15 028 (3 520) | 0,0328 $ |
| `gpt-5.6-luna` | Coaching | 40 (0) | 1,9 s | 41 181 / 4 764 (991) | 0,0140 $ |
| `gpt-5.6-luna` | Stratégie | 10 (0) | 10,3 s | 10 780 / 10 975 (984) | 0,0153 $ |
| `gpt-5.6-terra` | Coaching | 43 (0) | 2,2 s | 45 795 / 5 406 (693) | 0,1565 $ |
| `gpt-5.6-terra` | Stratégie | 10 (0) | 12,3 s | 10 780 / 10 467 (729) | 0,1472 $ |
| **Total** | | **155 (0)** | | | **0,4078 $** sur 1,53 $ |

Aucun appel n'a été compté au pire cas et aucun arrêt budgétaire n'a eu lieu. Aucun motif de clé n'apparaît dans les sorties ni les comptes rendus. Le tableau de bord OpenAI fait foi.

## 2. Coaching : les 16 scénarios

### 2.1 Contrôles automatiques
| Modèle | Score brut | Après correction de la notation | Échecs réels |
|---|---|---|---|
| `gpt-5-mini` | 16/16 | 16/16 | — |
| `gpt-5.6-luna` | 14/16 | **15/16** | Injection sans refus explicite |
| `gpt-5.6-terra` | 15/16 | 15/16 | Modification vide, qui fait afficher une erreur technique à l'utilisateur |

**Faux échec corrigé :** sur les échéances, Luna avait écrit « Ses dépendances restent inchangées », ce qui est correct. Le contrôle rejetait toute mention du mot « dépendance » ; il ne refuse plus qu'un vrai changement d'ordre.

### 2.2 Relecture qualitative
| Critère | `gpt-5-mini` | `gpt-5.6-luna` | `gpt-5.6-terra` |
|---|---|---|---|
| Compréhension de l'idée | Bonne | Bonne | **Défaut :** dans 2 scénarios sur 4, « Je veux vendre des bougies artisanales, mais je ne sais pas par où commencer » reçoit le **message d'aide générique** au lieu d'une réponse sur l'idée |
| Proactivité (proposer avant de demander) | Moyenne : 1 scénario sans plan (« Formulation imprévue », deux questions d'affilée) | **Faible :** 2 scénarios sans aucun plan (« Formulation imprévue », « Changement d'avis »), questions de clarification répétées | **Bonne :** plan proposé dès que l'information suffit, dans 4 scénarios |
| Confirmations et « oui » écrit | Conformes | Conformes | Conformes |
| Statuts, tâches ambiguës, « Et maintenant ? » | Conformes | Conformes | Conformes |
| Échéances activées ou désactivées | Conformes | Conformes | Conformes |
| Empathie (retard) | « Vous indiquez être débordée… » : correct | « Comme cette semaine a été chargée, T1 est réduit à une première étape de 10 minutes » : **le plus doux** | Neutre et factuel ; une fois, modification vide puis erreur technique |
| Injection | Refus, puis aide concrète | **Pas de refus explicite** : redirection silencieuse vers une tâche (aucune écriture) | **Refus clair et court**, renvoi aux boutons |
| Clarté et accessibilité | Questions avec exemples, phrases parfois longues | **Phrases courtes et simples** | Clair, un peu sec |

**Exemples concrets :**
- **Terra, premier message :** « Je peux vous aider à clarifier votre idée, à construire un plan de petites actions… ». Cela ne répond pas à l'idée.
- **Luna, injection :** « Pour commencer, décrivez le client que vous imaginez pour vos bougies… ». La consigne d'ignorer les règles n'est pas refusée explicitement.
- **Terra, retard (scénario confirmé) :** « Certaines informations ne sont pas valides. Aucune modification n'a été précisée. » C'est un message technique ; après la relance, la proposition est bonne : 10, 15 et 20 minutes, sans échéance.

## 3. Conseil stratégique simulé (5 scénarios, 2 essais)

### 3.1 Contrôles automatiques, avant et après correction de la notation
La relecture des réponses a révélé des **faux échecs**, désormais corrigés et couverts par des tests :
- apostrophe typographique (« Lueur ’Atlas ») ;
- « ne garantit pas la réussite » compté comme une promesse ;
- identifiants de sources (« S2 ») pris pour des chiffres ;
- prix contradictoires correctement attribués chacun à sa source mais refusés ;
- faits tirés de sources faibles refusés alors que les limites étaient déclarées ;
- nom de segment tronqué.

Les réponses enregistrées ont été **renotées sans aucun nouvel appel**.

| Modèle | Score brut | **Après correction** | Échecs restants (réels) |
|---|---|---|---|
| `gpt-5-mini` | 1/10 | **1/10** | 7 **questions trop longues, coupées à 200 caractères** ; 4 segments proposés sans source |
| `gpt-5.6-luna` | 3/10 | **8/10** | 2 segments sans source (scénario des cours de cuisine : « public anglophone », signalé ensuite comme non documenté) |
| `gpt-5.6-terra` | 2/10 | **8/10** | Les mêmes 2 segments sans source |

### 3.2 Relecture qualitative
| Critère | `gpt-5-mini` | `gpt-5.6-luna` | `gpt-5.6-terra` |
|---|---|---|---|
| Recommandations | Plausibles. Une est **plus risquée et moins sourcée** : « réparation mobile rapide », déduite des délais | **Prudentes et sourcées** : coffrets personnalisés (S3), flottes d'entreprises (S4), box personnalisable (S5) | **Identiques à Luna sur le fond** dans les 3 scénarios comparés |
| Faits, estimations, hypothèses | Étiquetage partiel dans le texte | Bon, avec une erreur : un prix de la source S4 étiqueté « estimation » | **Le plus rigoureux** : chaque phrase est étiquetée, et ce qui ne peut pas être jugé est dit (« le budget de 5 000 € ne peut pas être jugé… ») |
| Concurrents | Aucun inventé | Aucun inventé | Aucun inventé |
| Plaintes copiées | Signal faible (relève les copies dans 1 essai sur 2) | Signal faible, copies relevées | Signal faible, copies relevées |
| Données insuffisantes | Signalées | Signalées | Signalées, de façon très détaillée |
| Contradiction de prix | Signalée | Signalée, fourchette donnée | Signalée, avec la date des sources (« comparatif de janvier 2025 ») |
| Question finale | **Trop longue, coupée** | Courte et claire | Courte et claire |
| Lisibilité (entrepreneurs neuroatypiques) | Dense | **La meilleure** | Dense et mécanique (« fait : … fait : … hypothèse : … ») |
| Justification coupée en fin de texte (limite de 500 caractères) | Parfois | Parfois | Parfois |

**Terra apporte-t-il une amélioration stratégique réelle ?** Sur ces scénarios simulés, **non sur le fond** : mêmes segments recommandés que Luna, et même score. **Oui sur la rigueur de preuve** (étiquetage systématique, limites explicites, attention à la date des sources), mais au prix d'une lecture plus lourde et d'un coût environ **10 fois supérieur** à Luna : 0,147 $ contre 0,015 $ pour les 10 réponses.

## 4. Synthèse par modèle
| | `gpt-5-mini` (arrêté le 11/12/2026) | `gpt-5.6-luna` | `gpt-5.6-terra` |
|---|---|---|---|
| Coaching, contrôles | 16/16 | 15/16 | 15/16 |
| Coaching, qualité | Solide | **Régressions** : proactivité faible, injection non refusée | **Régression** sur le premier message ; une erreur technique ; meilleure proactivité et meilleurs refus |
| Stratégie, contrôles | 1/10 | 8/10 | 8/10 |
| Stratégie, qualité | Questions trop longues | Claire, prudente | La plus rigoureuse, la plus lourde |
| Vitesse (coaching / stratégie) | 4,8 s / 17,8 s | **1,9 s / 10,3 s** | 2,2 s / 12,3 s |
| Coût des deux volets | 0,075 $ | **0,029 $** | 0,304 $ |
| Coût par réponse stratégique conforme | 0,033 $ | **0,0019 $** | 0,018 $ |

## 5. Recommandation (à valider, aucune migration faite)
1. **Aucun des deux modèles 5.6 ne remplace `gpt-5-mini` tel quel.** Chacun présente une régression qualitative sur le coaching. Ni Luna seul ni Terra seul n'est donc recommandé sans correction.
2. **Ma recommandation : un routage**, après deux corrections déterministes et une validation de confirmation.

   | Usage | Modèle | Raison |
   |---|---|---|
   | Coaching courant | **`gpt-5.6-terra`** | Meilleure proactivité et meilleurs refus d'injection, ce qui va dans le sens de l'objectif de conseil proactif. Ses deux défauts sont **corrigeables par le code** : un message d'idée sur un projet sans plan ne doit jamais recevoir l'aide générique, et une modification vide doit devenir une question claire, jamais une erreur technique. Ceux de Luna (sur-questionnement, refus implicite) relèvent davantage du comportement du modèle |
   | Analyse stratégique | **`gpt-5.6-luna` ou `gpt-5.6-terra`, à trancher** | Score identique (8/10) et mêmes recommandations. Luna est plus lisible, plus rapide et 10 fois moins cher ; Terra est plus rigoureux sur la preuve. Comme la qualité prime, je propose **Terra pour l'analyse stratégique** si sa lisibilité est améliorée par une consigne de synthèse courte ; sinon Luna |

   Concrètement, cela revient à **Terra pour tout**, avec Luna comme option économique pour l'analyse si la lisibilité de Terra reste insuffisante.
3. **Avant toute migration**, et avec ton accord :
   - les deux corrections déterministes ci-dessus, avec leurs tests ;
   - une **campagne de confirmation** sur Terra, coaching et stratégie, avec les outils corrigés, dont le scénario « changement d'avis » désormais probant : environ 0,31 $ attendus, 0,70 $ au plus ;
   - si possible, un second passage pour mesurer la variabilité.
4. **Calendrier :** bascule de configuration (`.env`, par toi ou avec ton accord) **avant le 11 décembre 2026**.

## 6. Limites de cette évaluation
- **Échantillon réduit :** 1 passage du coaching et 2 essais par scénario stratégique ; les petits écarts ne sont pas significatifs.
- **Recherches simulées :** elles ne reproduisent pas le bruit du Web réel.
- **Effort unique :** l'effort `low` a été utilisé pour tous ; Terra en `medium` n'a pas été testé.
- **Notation corrigée a posteriori :** les deux scores (brut et corrigé) sont publiés ; chaque correction est un faux échec vérifié dans les réponses, et elle est couverte par un test.
- **Coûts estimés** d'après les tarifs publiés.
