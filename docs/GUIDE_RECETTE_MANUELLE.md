# Guide de recette manuelle

**But :** tester vous-même le parcours complet dans l'interface, avant toute publication. **Durée :** 20 à 30 minutes. **Prérequis :** l'environnement virtuel du projet (`.venv`) est installé ; aucune modification de `.env` n'est nécessaire.

## 1. Choisir le mode

| Mode | Coût | Ce qu'il vérifie |
|---|---|---|
| **A. Gratuit** (conseillé d'abord) | 0 $ | L'enchaînement, les boutons, les confirmations, la progression. Réponses du faux modèle et résultats **fictifs** (marqués « SIMULÉ ») |
| **B. Réel** | ≈ 0,06 $ OpenAI pour le parcours court (mesuré le 11/11/2026), davantage avec quatre idées ; recherches sur les quotas gratuits Tavily et Exa | La qualité réelle des recherches, de l'analyse et des solutions |

> **Attention, mode B :** l'application n'a pas de plafond global de dépense OpenAI. Chaque message consomme quelques millièmes de dollar ; une analyse ou une recherche de solutions, environ 0,01 à 0,03 $. Vérifiez si vous le souhaitez la limite de dépense de votre compte OpenAI (vous seul pouvez la modifier).

Les commandes ci-dessous sont pour **PowerShell**, depuis le dossier du projet. Les variables posées par `$env:` ne valent que pour cette fenêtre et ne modifient pas `.env`.

## 2. Lancer l'application

Utilisez un dossier de données à part, pour garder vos données habituelles intactes :

**Mode A (gratuit) :**
```powershell
$env:NEUROCOACH_DATA_DIR = ".\data-recette"
$env:NEUROCOACH_LLM_PROVIDER = "fake"
$env:NEUROCOACH_RESEARCH_SIMULATION = "1"
$env:NEUROCOACH_FORBID_REAL_RESEARCH = "1"
.\.venv\Scripts\python.exe scripts\dev.py demo
```

**Mode B (réel), dans une nouvelle fenêtre PowerShell :**
```powershell
$env:NEUROCOACH_DATA_DIR = ".\data-recette-reelle"
.\.venv\Scripts\python.exe scripts\dev.py check-research
.\.venv\Scripts\python.exe scripts\dev.py demo
```
`check-research` doit indiquer les deux clés « définie » et le quota restant, sans aucun appel.

L'interface s'ouvre sur **http://localhost:8501**. Pour arrêter : `Ctrl+C` dans la fenêtre PowerShell. Pour recommencer à zéro : supprimer le dossier `data-recette` (ou `data-recette-reelle`).

## 3. Parcours à tester

Dans la barre latérale, choisissez « Alice (démo) », puis créez un projet, par exemple « Bougies artisanales ».

| # | Vous écrivez ou cliquez | Ce que vous devez constater |
|---|---|---|
| 1 | « J'ai quatre idées de business, mais je ne sais pas laquelle choisir. » | Le coach demande les quatre idées, une par ligne. Une seule question |
| 2 | Les quatre idées, une par ligne (par exemple : bougies parfumées, food truck de galettes, cours de yoga en entreprise, application de covoiturage scolaire) | Une question sur vos critères (démarrer vite, investir peu…) |
| 3 | « J'ai 500 € de budget et 6 heures par semaine, je veux un revenu complémentaire. » | Une question sur le marché, puis rien de redemandé ensuite |
| 4 | « France » | La **proposition de recherche** : idées, recherches prévues, fournisseurs, données envoyées, budget, sites exclus (Reddit…), requêtes exactes |
| 5 | « oui » (écrit) | Le coach rappelle qu'il faut cliquer : **rien n'est lancé** |
| 6 | Bouton **« Approuver et lancer »** | Un encart « Recherches en cours… » affiche l'avancement (« Recherches web : 12/24 »). Puis un résumé sourcé par idée |
| 7 | « analyse » | Encart de progression (« Analyses d'idées terminées : 2/4 », « Synthèse… »). Puis l'analyse : faits sourcés, avis du coach, concurrents, avis clients, adéquation à votre budget et à votre temps, recommandation avec son niveau de confiance |
| 8 | « Laquelle est la plus risquée pour moi ? » | Une réponse appuyée sur l'analyse, avec ses sources ; aucune nouvelle recherche |
| 9 | « Cherche des solutions » | La proposition de recherche de solutions pour les problèmes les mieux étayés |
| 10 | Bouton **« Approuver et lancer »** | Progression (« Problèmes traités : 1/3 »), puis des solutions : outils existants d'abord, coût vérifié ou « non vérifié », recommandation, prochaines actions |
| 11 | « Transforme ces actions en tâches » | Une **proposition** de tâches avec les boutons Confirmer / Annuler ; aucune tâche créée avant le clic |
| 12 | **« Confirmer »**, puis « Où en suis-je ? » | Les tâches apparaissent dans l'onglet « Plan et tâches » ; l'état du projet est exact |
| 13 | « Laquelle de ces solutions me conseillez-vous, avec mon budget ? » | Une réponse appuyée sur les solutions trouvées, **pas** un refus « conseil financier » |

Pour une recherche plus courte (et moins chère en mode B), commencez plutôt par : « Que disent les clients des bougies artisanales dans les avis et sur les forums ? »

## 4. Points à vérifier

**Confiance et sécurité**
- [ ] Aucun appel externe avant un clic « Approuver et lancer » ; un « oui » écrit ne lance rien.
- [ ] Aucune tâche ni aucun plan créé sans « Confirmer ».
- [ ] Aucune clé API visible, ni dans l'interface ni dans la fenêtre PowerShell.

**Avis clients**
- [ ] « Tendance corroborée » n'apparaît que pour un thème présent sur plusieurs sites non commerciaux, dont un forum, un comparatif ou un média.
- [ ] Un avis affiché par une boutique est signalé « publié par un vendeur » et ne fait jamais une tendance.
- [ ] Les limites sont dites : avis promotionnels écartés, textes de vendeurs ignorés, Reddit non consulté.

**Qualité du coaching**
- [ ] Les questions sont courtes, une à la fois, jamais répétées.
- [ ] L'analyse tient compte de votre budget, de votre temps et de vos objectifs, et dit ce qu'elle ignore.
- [ ] Aucun concurrent, prix ou chiffre sans source ; les coûts non vérifiés sont dits comme tels.
- [ ] Les solutions privilégient les outils existants quand ils conviennent.
- [ ] Le coach garde le contexte jusqu'à la fin (idées, critères, résultats).

**Confort**
- [ ] L'encart de progression indique toujours ce qui se passe pendant les attentes.
- [ ] Durées mode B : notez-les. Repères mesurés le 11/11/2026 : « analyse » d'une idée ≈ 1 min ; recherche de solutions (15 recherches, 3 problèmes) ≈ 70 s ; les autres messages, quelques secondes (`docs/RECETTE_REELLE_R1_R6.md`, section « Finalisation »).

## 5. Si quelque chose ne va pas

Notez le numéro de l'étape, ce que vous avez écrit et ce que le coach a répondu (une capture d'écran suffit). L'onglet **Recherche** montre le détail des sources, des avis classés et de ce que le contrôle a retiré.
