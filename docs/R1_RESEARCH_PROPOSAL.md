# R1 du Business Researcher : proposition technique

> **Mise à jour du 10/11/2026 : R1 implémenté avec deux ajustements demandés** (D-68) : consentement **par mission** délimitée au lieu d'une approbation par recherche, et missions stockées dans leurs propres tables au lieu du type d'action `research.launch` (qui aurait remplacé une proposition de plan en attente). Résultats simulés uniquement ; aucun fournisseur réel branché.

**Date :** 10 novembre 2026. **Statut :** proposition à approuver. Aucun code modifié, aucun appel payant, `.env` et `gpt-5-mini` inchangés.
**Objectif de R1 :** permettre au coach de **préparer** une recherche réelle sur une idée : rassembler l'essentiel du projet, proposer explicitement la recherche, puis conserver sources et constats en distinguant faits et hypothèses. Tout est testé **hors ligne**, avec des résultats simulés. Les vrais fournisseurs (R2), la synthèse par le modèle et l'intégration conversationnelle (R3, R4) viennent ensuite.
**Base :** [BUSINESS_RESEARCHER_DESIGN.md](BUSINESS_RESEARCHER_DESIGN.md) (v3), architecture actuelle et M1 à M5 (catalogue des modèles, rôle `strategy`, registre de budget).

## 1. Solutions existantes comparées
Vérifié le 10/11/2026. « Officiel » signifie page du fournisseur lue ; « secondaire » signifie sources tierces concordantes, **à confirmer** à l'ouverture des comptes.

| Solution | Type | Sources vérifiables | Gratuit | Payant | Conditions et licence | Verdict pour nous |
|---|---|---|---|---|---|---|
| **Tavily** (Search, Extract) | API de recherche conçue pour les agents | URL, titre, extrait, date (actualités), score ; extraction du contenu des pages | **1 000 crédits par mois, sans carte** (officiel) | 0,008 $ par crédit ; recherche basique 1 crédit, avancée 2 ; extraction 1 crédit pour 5 URL (officiel) | Conditions à relire à l'ouverture du compte | **Fournisseur principal** |
| **Exa** (Search, Contents) | Recherche sémantique ; catégories entreprise, actualité, rapport financier | URL, titre, date, contenu des pages | **10 $ à l'inscription, puis 10 $ chaque mois**, sans moyen de paiement (officiel) | Recherche `lite` 4 $ pour 1 000, `auto` 7 $ ; contenus 1 $ pour 1 000 pages (officiel) | Idem | **Complément** pour concurrents et entreprises |
| Brave Search API | Index indépendant | URL, titre, extrait | Environ 5 $ de crédit par mois (secondaire ; l'ancien forfait de 2 000 requêtes aurait disparu en février 2026) | ≈ 5 $ pour 1 000 (secondaire) | À vérifier | Repli possible plus tard, pas en R1 |
| Serper.dev | Résultats Google | URL, titre, extrait | 2 500 requêtes une seule fois (secondaire) | ≈ 1 $ pour 1 000 (secondaire) | Revente de résultats Google : zone grise | Non retenu |
| SerpApi | Résultats Google | Idem | 250 par mois (secondaire) | 25 $ pour 1 000 | Idem | Non retenu (cher) |
| Google Custom Search JSON API | Officiel Google | Oui | — | — | **Fermée aux nouveaux clients, arrêt le 01/01/2027** (secondaire concordant) | **Exclu** |
| SearXNG | Métamoteur à héberger soi-même | Oui | Logiciel libre (AGPL-3.0) | Hébergement | Interroge d'autres moteurs : leurs conditions s'appliquent ; maintenance | Exclu en R1 (risque de conditions) |
| Bibliothèques DuckDuckGo non officielles | Lecture de pages de résultats | Partiel | — | — | Aucune API officielle | **Exclu** (contournement) |
| Outil `web_search` d'OpenAI | Recherche intégrée au modèle | Citations | — | ≈ 10 $ pour 1 000 appels, plus les jetons (secondaire) | Exige l'API Responses ; sources moins contrôlables | Non retenu en V1 (D-R3) |
| trafilatura | Extraction de texte, en local | — | Apache-2.0 (depuis 1.8.0) | — | Il faut récupérer les pages soi-même (conditions des sites) | Pas en R1 ; Tavily Extract suffit |
| Jina Reader, Firecrawl | Lecture et exploration de pages | — | Offres gratuites aux montants contradictoires (secondaire) | — | À vérifier | Non retenu |
| **Données publiques** (API Sirene de l'INSEE, data.gouv.fr ; Eurostat, Banque mondiale à vérifier) | Statistiques officielles | Oui, et durables | Gratuit (Sirene : identifiants requis) | — | Licences ouvertes à confirmer par jeu de données | **Plus tard** : sources « officielles » pour la France |
| `langchain-tavily`, Exa pour LangChain | Intégrations | — | — | — | — | Non : nous gardons notre propre port, et le modèle n'a pas d'outil en libre accès (pas de boucle ReAct) |

**Combinaison recommandée (hybride) :**
1. **R1 :** notre domaine, notre port `ResearchProvider` et un **faux fournisseur** aux résultats fictifs. Aucun réseau.
2. **R2 :** des adaptateurs **Tavily** (principal) et **Exa** (entreprises, concurrents), derrière le même port, tous deux dans leur offre gratuite. Brave Search reste un repli à évaluer.
3. **Plus tard :** données publiques officielles ; synthèse par le modèle du rôle `strategy` (M2) ; aucune extraction de Reddit ni des sites d'avis.

## 2. Recueillir l'essentiel sans questions inutiles
- **D'abord ce qui est déjà connu.** On réutilise l'idée, le titre, l'objectif, les contraintes, les faits et les hypothèses du projet, ainsi que le brouillon de clarification et le temps disponible. Aucune question sur une information déjà fournie.
- **Fiche de recherche** (`ResearchBrief`) : offre, cible, marché géographique, canal envisagé, contraintes (budget, temps). Pour chaque champ, on garde sa valeur, son **origine** (dit par l'utilisateur ou supposé) et sa nécessité pour la recherche.
- **Règle de la question unique :**
  - une seule question au plus, et seulement si un champ **indispensable** au type de recherche manque. Par exemple, le marché est indispensable pour les prix et les concurrents locaux, pas pour les tendances générales ;
  - sinon, la recherche est proposée avec des **hypothèses affichées** (« cible supposée : particuliers ») que l'utilisateur peut corriger dans la proposition ;
  - aucun marché par défaut (D-R10) : si le marché manque et n'est pas indispensable, la recherche est marquée « internationale, non spécifique ».
- **En R1, sans modèle :** le marché est repéré de façon déterministe dans le texte (pays, villes, « en ligne »). L'extraction par le modèle viendra avec l'intégration au graphe.

## 3. Proposition explicite avant tout lancement
- **On réutilise le mécanisme des actions en attente**, déjà sûr : aperçu, confirmation à usage unique, expiration, versions et journal. Un nouveau type, `research.launch`, ne modifie jamais un projet ni une tâche : il écrit uniquement dans les tables de recherche.
- **L'aperçu montre :**
  - les questions étudiées et les requêtes exactes ;
  - les services interrogés et **ce qui leur est envoyé** : des mots-clés seulement, jamais les messages, le nom ou les coordonnées ;
  - le marché ;
  - les hypothèses ;
  - le **coût maximal** et le nombre d'appels ;
  - la mention « résultats simulés » en R1.
- **Les boutons :** Lancer, Modifier ou Annuler. Rien ne part sans un clic sur Lancer. Un « oui » écrit ne lance rien, comme aujourd'hui.
- **Recherche par recherche :** en R1, chaque recherche est approuvée séparément. C'est plus strict que le « consentement unique » de D-R5, qui reste une option à décider plus tard.
- **Minimisation contrôlée par le code :** au plus 25 mots par requête ; adresses e-mail, téléphones, URL et noms de personnes retirés ; aucun identifiant interne. Ce sont les garde-fous prévus au §6.2 du dossier de conception.

## 4. Sources, faits, hypothèses et absence d'invention
- **Chaque source conservée** comprend :
  - l'URL, le domaine, le titre et la date de publication si elle est connue ;
  - la date de collecte (UTC, affichée en `Europe/Paris`) ;
  - le service et la requête d'origine ;
  - un **extrait de 500 caractères au plus** (D-R8) et une empreinte du contenu.

  Jamais de page entière.
- **Chaque constat** a une nature (`fait`, `estimation` ou `hypothèse`), des sources, au plus 300 caractères cités, une confiance, et la mention de sources contradictoires s'il y a lieu.
- **Règles de preuve appliquées par le code,** dans la lignée de la notation R0 :
  - un « fait » sans source devient une **hypothèse** ;
  - un chiffre absent de l'extrait cité devient une **estimation**, ou le constat est refusé ;
  - un concurrent ou un nom absent des sources est retiré ou devient une hypothèse ;
  - des valeurs incompatibles entre sources sont marquées « contradictoires » et affichées en fourchette, avec leurs sources ;
  - une source d'un autre marché que celui du projet est signalée ;
  - une source sans date est marquée « date inconnue ».
- **Contenu du Web délimité,** traité comme des données et jamais comme une consigne (injection). Aucun outil d'écriture pour le modèle.
- **Aucun résultat :** le constat est « aucune donnée fiable trouvée », puis viennent les hypothèses à vérifier. Rien n'est inventé.

## 5. Confirmations obligatoires préservées
- **Les projets et les tâches ne sont modifiés qu'après Confirmer,** inchangé. Une recherche ne crée ni plan, ni tâche, ni objectif.
- **Plus tard (R4) :** transformer un constat en orientation ou en plan passera par les propositions existantes.
- **Les écritures directes autorisées restent les mêmes :** statut, préférences, projet vide.

## 6. Stockage (migration 0003)
- **Tables :**
  - `research_runs` : projet, utilisateur, statut (proposée, approuvée, terminée, partielle, échouée), marché, coût estimé et coût réel, simulée ou non ;
  - `research_queries` ;
  - `research_sources` ;
  - `research_findings` ;
  - `research_finding_sources`.
- **Confidentialité :** isolation par `user_id`, comme le reste de la base. L'export et l'effacement des données de l'utilisateur sont étendus à ces tables.
- **Ce que R1 n'inclut pas :** la mémoire complète à trois niveaux du dossier (cache technique, actualisation, mémoire du conseil). R1 pose la mémoire métier minimale ; le reste viendra avec les vrais fournisseurs et la réutilisation (R2, R3).

## 7. Coûts
| Étape | Coût |
|---|---|
| **R1** (cette proposition) | **0 $** : aucun réseau |
| R2, test réel minimal (une recherche par fournisseur), sur approbation | 0 $ dans les offres gratuites (1 crédit Tavily, quelques millièmes de dollar sur le crédit Exa) |
| Une analyse typique plus tard (6 recherches Tavily et 10 pages extraites, 3 recherches Exa et 10 pages) | ≈ 8 crédits Tavily (≈ 0,064 $ hors offre gratuite) et ≈ 0,03 $ d'Exa, **dans les offres gratuites** pour environ 100 analyses par mois. Le coût du modèle de synthèse s'y ajoute (rôle `strategy`) |

## 8. Fichiers concernés (si approuvé)
| Fichier | Nature |
|---|---|
| `src/neurocoach/domain/research.py` (nouveau) | Fiche, requêtes, sources, constats, règles de preuve, minimisation |
| `src/neurocoach/application/research_service.py` (nouveau) | Préparer la fiche, estimer, proposer, lancer après confirmation, enregistrer |
| `src/neurocoach/research/ports.py` (nouveau) et `fake.py` (nouveau) | Port `ResearchProvider` ; faux fournisseur aux résultats fictifs (`.example`) |
| `src/neurocoach/research_providers.toml` (nouveau) | Tarifs et conditions vérifiés, sur le modèle du catalogue des modèles |
| `src/neurocoach/infra/migrations/0003_research.sql`, `infra/repositories.py` | Tables et accès |
| `domain/models.py`, `application/pending_actions.py` | Nouveau type d'action `research.launch` (application limitée aux tables de recherche) |
| `application/services.py` (export et effacement), `bootstrap.py` | Branchement |
| `ui/app.py` | Encadré « Préparer une recherche » sur un projet : proposition, Lancer, Annuler, sources et constats. **Aucune modification du graphe, des prompts ni des règles existantes** |
| Documentation | Décisions, journal, limites |

**Hors R1 :** les nœuds LangGraph et les prompts ne sont pas modifiés. Le déclenchement conversationnel (« Voulez-vous que je prépare une recherche ? ») est prévu en R3, avec l'accord du porteur du projet.

## 9. Tests hors ligne prévus
- **Fiche de recherche :** réutilisation des informations connues, aucune question si rien d'indispensable ne manque, une seule question sinon, hypothèses étiquetées, marché repéré ou absent.
- **Proposition :** aperçu complet, Lancer, Annuler, expiration, double clic, « oui » écrit sans effet, aucune écriture dans les projets ou les tâches.
- **Résultats simulés :**
  - enregistrement des sources (extrait borné, dates, empreinte) ;
  - les règles de preuve, cas par cas : fait sans source, chiffre absent, concurrent inventé, contradiction, autre marché, date inconnue, aucun résultat ;
  - une source malveillante qui contient une consigne reste une donnée.
- **Minimisation :** aucune donnée personnelle ni identifiant dans les requêtes.
- **Isolation, export et effacement :** un utilisateur ne voit pas les recherches d'un autre.
- **Sans réseau :** faux fournisseur imposé, verrou `NEUROCOACH_FORBID_REAL_LLM` respecté, aucun client externe construit.
- **Non-régression :** toute la suite (839 tests) et l'interface.

## 10. Risques
| Risque | Atténuation |
|---|---|
| Règle de `CLAUDE.md` : aucune API externe non nécessaire (D-R1) | R1 reste sans réseau ; D-R1 est à décider avant R2 |
| Faits inventés | Règles de preuve dans le code ; libellés ; relecture humaine |
| Injection depuis une source | Contenu délimité, aucun outil d'écriture, sorties validées |
| Confidentialité (requêtes envoyées en R2) | Minimisation, aperçu de ce qui est envoyé, approbation à chaque recherche |
| Conditions d'utilisation et droits d'auteur | Extraits bornés, aucune page entière, pas d'extraction de Reddit ni des sites d'avis |
| Résultats simulés pris pour réels | Mention « simulé » dans l'aperçu, le stockage et l'affichage |
| Périmètre de R1 plus étroit que dans le dossier v3 | Choix assumé (mémoire complète en R2 et R3), à valider |
| Charge pour des utilisateurs neurodivergents | Aperçu court, une question au plus, détails repliés |
| Tarifs changeants | Catalogue des services avec date de vérification, revérifié avant R2 |

## 11. Décisions à prendre
1. Périmètre de R1 (préparation, proposition, preuves, stockage minimal), plus étroit que le R1 du dossier v3.
2. Approbation **à chaque recherche** (plutôt que le consentement unique de D-R5).
3. Point d'entrée de R1 : l'interface (encadré sur le projet), sans modifier le graphe.
4. Le nouveau type d'action en attente `research.launch`.
5. Fournisseurs de R2 : Tavily, plus Exa ; Brave comme repli à évaluer. D-R1 est à décider avant R2.

## Sources consultées (10 novembre 2026)
- Officiel : [Tavily, crédits](https://docs.tavily.com/documentation/api-credits) · [Exa, tarifs](https://exa.ai/pricing)
- Secondaire, à confirmer :
  - Brave : [CostBench, changement de prix](https://costbench.com/changelog/brave-search-api-price-decrease-2026-05/), [apiserpent](https://apiserpent.com/blog/free-brave-search-api) ;
  - Google CSE : [Brave, arrêt de l'API Google](https://brave.com/learn/google-api-shutdown/), [Firecrawl](https://www.firecrawl.dev/blog/google-search-json-api-alternative) ;
  - Serper et SerpApi : [CostBench](https://costbench.com/compare/serpapi-vs-serper/) ;
  - SearXNG : [Railway](https://railway.com/deploy/searxng-search-api) ;
  - OpenAI `web_search` : [forum OpenAI](https://community.openai.com/t/web-search-pricing-for-reasoning-models/1377274) ;
  - trafilatura : [PyPI](https://pypi.org/project/trafilatura/) ;
  - Jina : [Jina, tarifs](https://jina.ai/api-dashboard/pricing/) ;
  - INSEE Sirene : [INSEE](https://www.insee.fr/fr/information/3587074).
