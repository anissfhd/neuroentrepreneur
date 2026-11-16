# Recette réelle R1 à R6 — 10 et 11 novembre 2026

Projet fictif (bougies artisanales à Lyon, 500 €, 6 h par semaine). Recherches Tavily et Exa réelles, modèle `gpt-5-mini` (réglages de l'application). Comptes rendus complets, non versionnés : `data/evaluations/`.

## Résultats
| Test | Résultat |
|---|---|
| 1. Tavily, un appel | Réussi : 3 résultats, 1 crédit annoncé (0,008 $), paramètres acceptés |
| 1. Exa, un appel (pays, sites exclus, sans contenu) | Réussi : 3 résultats, 0,004 $ annoncés |
| 2. Évaluation R4, 9 appels | 2 scénarios conformes sur 3 ; 3 appels expirés à 30 s dans le scénario des quatre idées ; cause corrigée, scénario non rejoué (budget) |
| 3. Parcours complet, premier passage | 8 vérifications sur 10 : analyse tronquée à 4 000 jetons, donc aucune solution |
| 3. Parcours complet, après corrections | **15 sur 15** : 14 appels au modèle, aucune erreur |

## Consommation
- **OpenAI :** 0,149 $ engagés au registre sur un plafond de 0,16 $ (évaluation R4 0,063 $, parcours 0,019 $ puis 0,067 $). Quatre appels échoués y sont comptés au pire cas (0,037 $) : la dépense réelle se situe entre 0,113 $ et 0,149 $. 29 appels, environ 52 000 jetons d'entrée et 50 000 de sortie, dont plus de la moitié de raisonnement.
- **Tavily :** 16 crédits sur 1 000 gratuits. **Exa :** 9 requêtes (0,036 $ sur 10 $ gratuits). Reportés au compteur mensuel de l'application.

## Qualité constatée
- **Analyse :** précise et prudente. Elle relève les obligations d'étiquetage et d'assurance, compare les 800 € cités par une artisane au budget de 500 € (« défavorable »), refuse de trancher sans prix de revient ni objectifs, et propose quatre vérifications concrètes. 2 affirmations retirées par le contrôle des sources.
- **Avis clients :** la « tendance corroborée » trouvée (odeur appréciée, 3 sites) repose en partie sur des témoignages publiés par des vendeurs et sur un texte de marque : à lire avec réserve.
- **Solutions :** très bonnes pour l'expédition (emballage renforcé, retrait local, colis test ; le sur mesure écarté) ; faibles pour la réglementation (résultats de recherche hors sujet) ; vides pour l'étude de concurrence (outils retirés à tort par le contrôle, corrigé depuis).
- **Conversation :** consentement respecté (« oui » écrit sans effet), suivi cohérent avec l'analyse puis avec les solutions, 7 tâches créées seulement après confirmation, état du projet exact.

## Corrections effectuées
Voir D-74 dans `DECISIONS.md` (dix corrections, toutes couvertes par des tests hors ligne).

## À faire avant publication
1. Rejouer le parcours réel et le scénario des quatre idées avec les dernières corrections (environ 0,11 $).
2. Distinguer les avis publiés par un vendeur des avis indépendants.
3. Réduire l'attente : appels d'analyse en parallèle ou progression affichée.
4. Mieux cibler les requêtes de solutions selon la nature du problème.
5. Décider la migration du modèle avant le 30/11/2026 (`gpt-5-mini` retiré le 11/12/2026).
6. Points déjà ouverts : identité Git et premier commit, intégration continue jamais exécutée, confirmation des conditions des plateformes d'avis.

## Finalisation (11/11/2026, plafond OpenAI distinct de 0,12 $)

Mêmes conditions que le parcours de 09:28 (projet fictif « bougies artisanales », `gpt-5-mini`, Tavily et Exa réels), après l'optimisation D-75. Temps mesurés par le script, de bout en bout ; un appel au modèle varie de plusieurs secondes d'un essai à l'autre.

| Étape | Avant (09:28) | Après (13:53) | Ce qui explique l'écart |
|---|---|---|---|
| Message de recherche | 11 s | 6 s | Variation du modèle (même appel) |
| Approbation, 4 recherches | 7 s | 6 s | Recherches en parallèle (gain faible : 4 requêtes) |
| « analyse » (1 idée) | 92 s, 3 appels | **66 s**, 2 appels | Classification évitée (13 s) ; le reste est la variation de l'appel d'analyse (59 s puis 42 s). Une seule idée : pas de parallélisme |
| Question de suivi | 30 s | 19 s | Variation du modèle (mêmes 2 appels) |
| « Cherche des solutions » | 7 s | **0 s** | Classification évitée |
| Approbation, 15 recherches et 3 problèmes | 212 s | **69 s** | Recherches 28 s puis 12 s ; 3 appels de solutions l'un après l'autre (186 s) puis en même temps (58 s) |
| « Transforme ces actions en tâches » | 6 s | **0 s** | Classification évitée |
| « Laquelle de ces solutions… avec mon budget ? » | 26 s | 5 s | **Non comparable** : refus à tort, corrigé depuis (voir plus bas) |
| « Où en suis-je ? » | 6 s | 7 s | — |
| **Total du parcours** | 397 s | 178 s | Hors la question refusée : 371 s puis 173 s |

Appels au modèle : 14 puis 10. Coût estimé : 0,067 $ puis 0,057 $.

**Quatre idées** (sources fictives fixes, aucune recherche web) : 77 s avec 2 appels simultanés (4 analyses en 58 s, synthèse 19 s). Aucune mesure séquentielle comparable : le 10/11, trois appels avaient expiré. Pas d'essai à 4 appels simultanés : leur pire cas (0,07 $) dépassait le budget restant.

### Résultats
| Test | Résultat |
|---|---|
| Parcours R1–R6 | **15 sur 15** ; aucune erreur ; progression reçue à chaque étape longue |
| Quatre idées | 8 contrôles sur 10 : la contradiction de prix (9 € / 18 €) et le prix manquant de l'idée 4 ne sont pas signalés. Le compte rendu a été perdu (arrêt du script sur un caractère « ≈ » avant son écriture, corrigé). Causes probables, non confirmées : prix fusionnés en une seule affirmation ; inconnue du modèle évoquant le prix |

### Défauts trouvés en réel, corrigés hors ligne (non revérifiés en réel, faute de budget)
1. « Laquelle de ces solutions me conseillez-vous, avec mon budget ? » classée conseil financier et refusée (le matin, la même question avait reçu une réponse) : une question sur les résultats trouvés est désormais traitée par le suivi ; une vraie demande médicale, juridique, fiscale ou de placement reste refusée. Le contrôle du script, qui avait accepté ce refus, échoue désormais sur un refus.
2. Problème 1 des solutions : MyTDB, Geko et Etsy, présents dans les sources, avaient disparu des options (cités avec une mauvaise source) tout en restant dans les actions et la recommandation. L'outil est maintenant rattaché aux sources qui le nomment, et c'est signalé.
3. Deux prix de sources différentes fusionnés dans une même affirmation : l'écart est signalé « contradictoire ».
4. Prix absent : « Prix : aucune donnée sourcée » est toujours ajouté, même si le modèle évoque le prix ailleurs.

### Qualité constatée
- **Avis clients :** 6 sources d'avis publiées par des vendeurs (par exemple une note « 4,7/5 » sur le site d'une fabrique) et 12 textes commerciaux identifiés comme tels ; aucune « tendance » annoncée ; les limites sont dites. Reste perfectible : la « frustration principale » citée en suivi vient d'un site marchand (comme-avant.bio), présentée comme « non corroborée », mais sans préciser qu'il s'agit d'un vendeur.
- **Analyse :** prudente et personnalisée (500 €, 6 h par semaine, 800 € de conformité cités par une artisane) ; 2 affirmations retirées par le contrôle.
- **Solutions :** bonnes pour l'étiquetage CLP (générateurs, vérification, prestataires ; coûts non vérifiés dits comme tels) et pour le budget de conformité ; incomplètes pour la concurrence (défaut 2). Requêtes de solutions encore maladroites (« marché est très concurrentiel ce… »).
- **Conversation :** consentement respecté ; tâches créées seulement après confirmation ; état du projet exact.

### Consommation
- **OpenAI :** 0,092 $ sur le plafond de 0,12 $ (parcours 0,0566 $, quatre idées 0,0354 $) ; 15 appels ; 0,028 $ non utilisés. Aucun nouvel essai des quatre idées : son pire cas dépassait le reste.
- **Tavily :** 12 crédits (28 ce mois sur 1 000 gratuits). **Exa :** 7 requêtes (16 ce mois ; 0,064 $ sur 10 $ gratuits). Reportés au compteur mensuel de l'application.

### Reste non vérifié en réel
Les quatre corrections ci-dessus ; le scénario des quatre idées avec 4 appels simultanés ; une analyse réelle de plusieurs idées dans le parcours conversationnel.
