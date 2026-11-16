# Business Researcher : feuille de route R3 à R6

**Date :** 10 novembre 2026. **État :** R1 (missions, preuves, stockage), R2 (Tavily et Exa réels, quotas gratuits protégés) R3 (proposition depuis la conversation, D-70) R4 (analyse par le modèle de stratégie, D-71) R5 (avis, forums et retours d'expérience, sans Reddit, D-72) et **R6 (solutions concrètes, puis tâches sur confirmation, D-73)** implémentés ; aucun appel réel effectué. Reste la recette réelle. Historique : l'analyse expose déjà les inconvénients, besoins et risques à traiter (`solution_targets`), et les catégories « avis » et « problèmes » accueilleront les sources de forums autorisés.

## Principes conservés à chaque étape
- **Le code décide** : routage, permissions, périmètre, budget et écriture. Le modèle propose ; les règles de preuve valident.
- **Aucune modification de données sans confirmation** : une recherche n'écrit jamais dans le plan. Transformer une recommandation en tâches passe par les propositions existantes (aperçu, Confirmer).
- **Aucune source inventée**, simulation jamais présentée comme réelle ; offres gratuites seulement ; aucun appel facturable sans accord.

## Étapes

| Étape | Livrable | Dépend de | Blocages ou décisions |
|---|---|---|---|
| **R3. Proposition depuis la conversation** | Le coach repère une idée ou une question de marché, de prix ou de concurrence et **propose** une mission ; l'aperçu s'affiche dans la conversation avec les boutons Approuver ou Annuler. Un « oui » écrit ne lance rien. Résumé des résultats dans la conversation, avec liens. | R2. Développable et testable avec la simulation | Modifie le graphe (un nœud et une route) et ajoute un prompt : **accord requis**, puisque les nœuds et les prompts sont protégés jusqu'ici. Évaluation réelle des nouveaux dialogues avec `gpt-5-mini` : payante, accord requis |
| **R4. Analyse de marché, concurrents et avis** | Synthèse par le rôle `strategy` : le modèle reçoit les sources comme des **données délimitées** et rend des constats candidats (identifiants de sources, citations), validés par `validate_finding`. Fiche « marché » (taille, tendances, prix observés en fourchette avec sources), tableau des concurrents (nom, offre, prix, source), avis récurrents. Incertitudes affichées | R2 avec clés réelles. R3 facultatif : l'onglet suffit pour commencer | Coût du modèle (faible, mais payant) : budget à autoriser. **Décision de migration du modèle avant le 30/11/2026** (`gpt-5-mini` retiré le 11/12/2026). Option Tavily `advanced` (2 crédits) pour des extraits plus riches |
| **R5. Avis clients, forums et Reddit** | Avis et problèmes tirés de sources publiques **autorisées** : d'abord par les résultats de Tavily restreints à des domaines choisis (`include_domains`, extraits seulement, aucune extraction de pages) ; ensuite, Reddit par son **API officielle** si l'accès est accordé | R2 ; R4 pour la synthèse | **Reddit** : création d'une application OAuth et acceptation de ses conditions par vous ; l'usage commercial ou à grande échelle peut exiger une approbation de Reddit (à vérifier au moment de la demande). **Forums** : liste de sites et vérification de leurs conditions, site par site. Aucun contournement d'accès |
| **R6. Solutions aux inconvénients** | Pour chaque problème sourcé : recherche de solutions (catégorie « solutions »), recommandations **actionnables**, adaptées au temps et aux contraintes du projet, avec sources et incertitudes ; bouton « transformer en tâches » qui crée une **proposition de plan** à confirmer | R4 (problèmes identifiés) ; R3 pour le déclenchement dans la conversation | Aucun blocage externe. Garde-fou : aucune recommandation médicale, juridique ou financière personnalisée |
| **Recette finale** | Parcours complet testé : idée → mission → recherches réelles → recommandations → tâches proposées → confirmation → suivi → reprise. Tests hors ligne de bout en bout, plus une campagne réelle courte | R3 à R6 | Campagne réelle : budget à autoriser (recherches dans les offres gratuites ; modèle payant) |

## Ordre proposé
1. **Votre activation des clés**, puis un appel de test par service (`check_research.py --ping`), sur votre accord.
2. **R4, puis R3** : la synthèse donne de la valeur dès l'onglet Recherche ; R3 l'amène ensuite dans la conversation.
3. **R6**, qui s'appuie sur les problèmes de R4.
4. **R5** dès que les accès sont décidés. Il ne bloque pas les autres étapes.
5. **Recette finale**.

## Coûts attendus, par analyse d'idée
- **Recherche :** 9 requêtes (6 Tavily, 3 Exa), environ 0,06 $ **pris sur les offres gratuites**. Cela laisse une centaine d'analyses par mois sous les plafonds locaux.
- **Synthèse (R4, R6) :** quelques milliers de jetons avec le modèle `strategy`. Estimation à présenter avant toute campagne.
