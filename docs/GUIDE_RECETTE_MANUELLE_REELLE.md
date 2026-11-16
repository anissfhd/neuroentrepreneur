# Guide de recette manuelle RÉELLE

**Mode :** modèle OpenAI réel (`gpt-5-mini`), recherches Tavily et Exa réelles, simulation désactivée. **Aucun résultat fictif.** Base SQLite de test séparée : `data-recette-reelle\`. Vos données habituelles (`data\`) ne sont ni lues ni modifiées par l'application pendant la recette.

> **Important, avant le premier message :** l'application **n'a pas de plafond global de dépense OpenAI** et n'enregistre pas sa consommation de jetons. Le plafond que vous autoriserez sera donc suivi **à la main** : chaque étape du scénario indique son coût estimé, et la colonne « Cumul » du tableau de contrôle vous permet de vous arrêter avant le plafond. Seules les recherches web ont des plafonds appliqués par le code (budget par mission, quota mensuel local).

Préparé le 11/11/2026, à partir du code réel. Les réponses du modèle varient d'un essai à l'autre : le guide décrit le **comportement attendu**, pas un texte mot pour mot.

> **Mise à jour du 11/11/2026 (D-76, D-77).** L'interface a changé : il n'y a plus de sélecteur d'utilisateurs fictifs. À la première ouverture, créez votre profil (ou rouvrez un espace existant par son nom d'utilisateur, par exemple `alice-demo`). Les projets se créent par **Accueil → Créer votre projet**, les préférences sont dans **Paramètres**. Les scénarios ci-dessous restent valables, mais les emplacements des boutons de la barre latérale ont changé. Section 8 : messages pour vérifier le coaching proactif.

---

## 1. Démarrer, arrêter, redémarrer

### État préparé (aucun appel payant)
| Vérification | Résultat constaté le 11/11/2026 |
|---|---|
| `.env` | présent, ignoré par Git, **non modifié** ; `NEUROCOACH_LLM_PROVIDER=openai`, `NEUROCOACH_LLM_MODEL=gpt-5-mini`, `NEUROCOACH_DEFAULT_TIMEZONE=Europe/Paris` |
| Clés | `OPENAI_API_KEY`, `TAVILY_API_KEY`, `EXA_API_KEY` « définies » (valeurs jamais affichées) |
| Dépendances | `pip check` : aucune dépendance cassée ; Streamlit 1.67.0, openai 3.48.0 |
| Construction du client OpenAI | réussie, **aucun appel réseau** (`scripts/check_llm.py`) |
| Recherche web | `check_research.py` : Tavily et Exa disponibles, **simulation désactivée** |
| Base de test | `data-recette-reelle\neurocoach.sqlite` créée, 8 migrations appliquées, 20 tables |
| Données présentes dans la base de test | les deux utilisateurs fictifs (Alice, Bruno) et leurs projets de démonstration (« Bougies artisanales » d'Alice, T1 terminée ; « Atelier de réparation de vélos » de Bruno). Ce sont des exemples, pas des résultats de recherche |
| Quotas gratuits | compteur de la base de test aligné sur la consommation réelle du mois : Tavily 28 requêtes (0,224 $ sur 6,40 $ autorisés localement), Exa 16 requêtes (0,064 $ sur 8,00 $) |
| Interface | http://localhost:8501, **accessible uniquement depuis cet ordinateur** (`--server.address localhost`) ; statistiques d'usage Streamlit désactivées |

### Ouvrir l'interface
Elle est déjà démarrée dans le panneau navigateur de l'application Claude. Vous pouvez aussi ouvrir **http://localhost:8501** dans votre propre navigateur.

Pour la démarrer vous-même dans une fenêtre PowerShell (après l'avoir arrêtée côté Claude, voir plus bas, sinon le port 8501 est occupé) :
```powershell
cd chemin\vers\NeuroEntrepreneur
$env:NEUROCOACH_DATA_DIR = ".\data-recette-reelle"
.\.venv\Scripts\python.exe -m streamlit run ui\app.py --server.address localhost --server.port 8501
```
`$env:` ne vaut que pour cette fenêtre et ne modifie pas `.env`. Ne posez **pas** `NEUROCOACH_LLM_PROVIDER=fake` ni `NEUROCOACH_RESEARCH_SIMULATION=1` (ce serait le mode simulé).

Vérifier la configuration à tout moment, sans appel payant :
```powershell
$env:NEUROCOACH_DATA_DIR = ".\data-recette-reelle"
.\.venv\Scripts\python.exe scripts\check_research.py
.\.venv\Scripts\python.exe scripts\check_llm.py
```

### Voir ce qui est enregistré dans SQLite (lecture seule)
```powershell
.\.venv\Scripts\python.exe scripts\recette_etat.py
.\.venv\Scripts\python.exe scripts\recette_etat.py --events 20
```
Affiche, sans rien écrire ni appeler : préférences, projets (objectif, temps, contraintes), phases et tâches (statut, dépendances, estimation, échéance, blocage, date de fin), avancement, propositions (en attente, appliquées, annulées, expirées), missions de recherche (réelle ou simulée, nombre de requêtes, analyses, solutions), derniers événements du journal, compteur des quotas. Heures en UTC (heure de Paris moins 1 h en novembre).

### Arrêter proprement
- **Lancée par Claude** : demandez « arrête l'application » ; ou fermez-la depuis le panneau navigateur.
- **Lancée par vous** : `Ctrl+C` dans la fenêtre PowerShell, puis fermez l'onglet.

L'arrêt ne perd rien : chaque action est enregistrée au moment où elle a lieu (base métier et fil de conversation dans `data-recette-reelle\`).

### Recommencer à zéro
Arrêtez l'application, puis supprimez le dossier `data-recette-reelle`. Attention : le compteur des quotas Tavily et Exa de ce dossier serait perdu ; demandez-moi de le recréer aligné sur le compteur réel.

---

## 2. Inventaire vérifié des fonctionnalités

Légende : **Oui** = implémentée et accessible ; **Partielle** = existe avec des limites dites ; **Absente** = non implémentée.

| # | Fonctionnalité | État | Où, dans l'interface | Remarques vérifiées dans le code |
|---|---|---|---|---|
| F1 | Création d'un utilisateur | **Partielle** | Barre latérale, « Utilisateur fictif » | Pas de création ni de connexion : deux utilisateurs fictifs fixes, Alice et Bruno. Aucune authentification (prototype local) |
| F2 | Création d'un projet | Oui | Barre latérale, « Titre du nouveau projet » puis **Créer le projet** | Titre d'au moins 3 caractères ; projet créé au statut « brouillon » (`draft`) |
| F3 | Conversation naturelle | Oui | Onglet **Conversation**, champ en bas « Votre message » | Message de 2 000 caractères au plus. Le modèle classe la demande, le code choisit le chemin |
| F4 | Compréhension d'une idée | Oui | Conversation | Le coach reformule, pose **une** question à la fois (préférence), offre une fois une recherche web |
| F5 | Mémoire des informations du projet | Oui | « Où en est le projet » ; conversation | Objectif, temps par jour, horizon, contraintes, faits et hypothèses enregistrés dans le projet ; questions déjà répondues jamais reposées |
| F6 | Préférences | **Partielle** | Barre latérale, **Préférences**, puis **Enregistrer les préférences** | Longueur des réponses, nombre d'actions visibles (1 à 3), une question à la fois, échéances, rythme, fuseau. **Le coach ne les modifie jamais** : une demande dans la conversation reçoit une explication |
| F7 | Structuration objectif / phases / tâches | Oui | Proposition dans la conversation ; onglet **Plan et tâches** | 3 à 6 micro-tâches dans 1 à 3 phases, critère de fin, estimation, dépendances. Il faut un objectif et un temps par jour (ou « je passe ») |
| F8 | Modification d'une proposition avant confirmation | Oui | Encadré « Proposition en attente », **Modifier la proposition avant de confirmer**, puis **Mettre à jour la proposition** | Titres des phases et des tâches, critères de fin, retrait d'une tâche ; sans appel au modèle |
| F9 | Création, modification, suppression de tâches avec confirmation | Oui | Conversation (« Ajoute une tâche… », « Supprime T4 », « Décale T2 à vendredi »), puis **Confirmer** / **Annuler** | Rien n'est écrit avant **Confirmer** ; un « oui » écrit ne confirme jamais ; une date n'est possible que si les échéances sont activées. **Pas d'édition directe** d'une tâche existante dans l'onglet Plan |
| F10 | Expiration des propositions | Oui | — | Une proposition non confirmée expire après **15 minutes** |
| F11 | Suivi de progression | Oui | « Où en est le projet » (barre et pourcentage) ; Plan et tâches (par phase) ; « Où en suis-je ? » | Voir section 3 |
| F12 | Exécution et validation d'une tâche | Oui | Plan et tâches : **Commencer T*n***, **Marquer terminée T*n***, **Rouvrir T*n*** ; ou conversation « J'ai terminé T2 » | Enregistré **immédiatement**, sans confirmation, avec bouton **Annuler ce changement**. Le critère de fin n'est pas vérifié par l'application : c'est votre déclaration |
| F13 | Réaction du coach après une tâche terminée | **Partielle** | Message de confirmation ; encadré « Où en est le projet » | Message factuel (« T2 est maintenant terminée… »), avertissement si une dépendance n'est pas terminée. Pas de félicitation ni de prochaine tâche dans ce message : la prochaine action s'affiche en haut de page et sur demande (« Et maintenant ? ») |
| F14 | Prochaine tâche recommandée | Oui | « Où en est le projet » ; Plan et tâches, « Prochaines actions » ; « Et maintenant ? » | Calcul déterministe (section 3), jamais par le modèle |
| F15 | Dépendances | Oui | Carte de chaque tâche, « Dépendances » | Une tâche n'est recommandée que si ses dépendances sont terminées. La terminer avant reste possible, avec un avertissement |
| F16 | Blocages | Oui | Carte de la tâche, **Signaler un blocage sur T*n*** + raison + **Enregistrer le blocage** ; ou conversation « T3 est bloquée car… » | Raison obligatoire (3 caractères au moins). Une tâche bloquée n'est plus recommandée ; si rien d'autre n'est faisable, le coach propose de lever le blocage |
| F17 | Retards | **Partielle** | « En retard : T… » en haut de page | Seulement si les échéances sont activées et qu'une tâche a une date passée. Aucune notification ni rappel automatique (choix du projet) |
| F18 | Replanification | Oui | Conversation (« Je n'ai pas eu le temps… », « C'est trop gros ») | **Proposition** plus légère à confirmer (par exemple une étape de 10 minutes), jamais appliquée seule |
| F19 | Changement d'avis | Oui | Conversation | Un nouveau message pendant une proposition l'annule puis est traité ; « non » annule ; avant le plan, un nouvel objectif remplace l'ancien |
| F20 | Modification de l'objectif d'un projet déjà planifié | **Absente** | — | Aucune opération ne change l'objectif d'un projet actif ; seules les tâches se modifient. Contournement : nouveau projet |
| F21 | Tâche « échouée » | **Absente** | — | Pas de statut « échouée » : utilisez « bloquée » (avec la raison) ou **Remettre à faire** |
| F22 | Recherche web réelle Tavily et Exa | Oui | Conversation (proposition + **Approuver et lancer**) ; onglet **Recherche** (formulaire **Préparer la mission**, **Approuver la mission**, **Lancer les recherches prévues**) | Une approbation par mission ; aperçu des requêtes exactes et des données envoyées ; aucun appel avant le clic ; budget par mission (0,40 $ par défaut, 15 recherches au plus) |
| F23 | Analyse marché, concurrents, prix, risques | Oui | Conversation (« analyse ») ; onglet Recherche, **Analyser ces résultats** / **Mettre à jour l'analyse** | Faits sourcés, estimations, hypothèses, avis du coach ; contrôle des sources par le code (affirmations retirées ou requalifiées) ; adéquation à votre budget et à votre temps |
| F24 | Comparaison de plusieurs idées | Oui | Conversation (« J'ai quatre idées… ») | Idées, critères, marché demandés un par un ; analyse par idée puis synthèse et recommandation avec niveau de confiance |
| F25 | Avis clients et forums | Oui | Résumé de recherche ; analyse, « Limites des avis » | Origine de chaque source (indépendante, vendeur, promotionnelle, incertaine) ; tendance seulement si corroborée. **Reddit non consulté** ; Trustpilot, Yelp, Tripadvisor, Amazon (avis), réseaux sociaux exclus |
| F26 | Recherche de solutions | Oui | Conversation (« Cherche des solutions ») ; onglet Recherche, **Proposer les solutions** | Nouvelle mission à approuver ; outils existants d'abord ; coût « non vérifié » si non sourcé |
| F27 | Conversion des solutions en tâches | Oui | Conversation (« Transforme ces actions en tâches »), puis **Confirmer** | Phase « Solutions aux problèmes repérés » ; rien d'écrit avant **Confirmer** |
| F28 | Questions de suivi et continuité | Oui | Conversation | Réponses appuyées sur l'analyse et les solutions enregistrées, sans nouvelle recherche |
| F29 | Historique, sauvegarde, reprise après redémarrage | Oui | Conversation (historique) ; « Où en est le projet » | SQLite (`neurocoach.sqlite`) et fil de conversation (`checkpoints.sqlite`) ; message de reprise calculé depuis la base |
| F30 | Annulation d'un changement de statut | Oui | Bouton **Annuler ce changement (T*n*)** | Journalisé comme annulation |
| F31 | Export et suppression des données | Oui | Barre latérale, **Mes données** | Export JSON ; suppression d'un projet ou de tout, avec confirmation |
| F32 | Isolation entre utilisateurs | Oui | Changer d'« Utilisateur fictif » | Bruno ne voit ni les projets ni les missions d'Alice |
| F33 | Alerte de charge | **Partielle** | « Où en est le projet » | Seulement si un temps par jour **et** un horizon sont connus |
| F34 | Gestion des erreurs | Oui | Messages en clair | Modèle indisponible ou lent, proposition expirée, raison de blocage trop courte, titre trop court, quota atteint : message compréhensible, données intactes |
| F35 | Limites de consommation | **Partielle** | Onglet Recherche (quotas) ; aperçu des missions | Recherche : plafonds appliqués (mission, mois). **OpenAI : aucun plafond dans l'application** |
| F36 | Notifications, rappels, envoi d'e-mails | **Absente** | — | Volontairement absents |

---

## 3. Le suivi après l'exécution des tâches (réponses précises)

| Question | Réponse vérifiée dans le code |
|---|---|
| Comment indiquer qu'une tâche est terminée ? | Bouton **Marquer terminée T*n*** (onglet Plan et tâches), ou message « J'ai terminé T2 » ou « J'ai terminé la tâche Préparer cinq questions ». Le message doit **désigner** la tâche : « J'ai fini » seul reçoit une question, jamais une tâche devinée |
| Enregistré immédiatement ou après confirmation ? | **Immédiatement**, sans confirmation (changement simple et réversible) ; journalisé (`task.status_changed`) ; bouton **Annuler ce changement** |
| Calcul du pourcentage | Tâches terminées ÷ toutes les tâches du projet × 100, arrondi à une décimale (1/3 = 33,3 %). Les tâches bloquées ou en cours comptent comme non terminées ; pas de pondération par la durée. Même calcul par phase |
| Le coach reconnaît-il les tâches terminées ? | Oui : « Où en suis-je ? » donne « X tâches terminées sur Y (Z %) » et la reprise « Vous avez terminé X tâches sur Y », calculés depuis la base |
| Recommande-t-il automatiquement la prochaine tâche ? | Oui en haut de page et dans « Prochaines actions », recalculé à chaque affichage ; **pas** dans le message qui confirme la fin d'une tâche (voir F13) |
| Règle de recommandation | Parmi les tâches **réalisables** (non terminées, non bloquées, toutes dépendances terminées) qui tiennent dans votre temps par jour : score = 2 × priorité + urgence de l'échéance (si activées) + 3 si déjà commencée + 2 par tâche qui en dépend (max 3) ± temps disponible ; à égalité, ordre des phases et des tâches. Nombre affiché selon la préférence (1 à 3) |
| Dépendances et blocages respectés ? | Oui : une tâche dont une dépendance n'est pas terminée, ou bloquée, n'est jamais recommandée. Si plus rien n'est réalisable : « lever le blocage de T*n* » ou « découper T*n* » (trop longue), sinon « aucune tâche réalisable » |
| Tâche échouée ou en retard | Pas de statut « échouée » (F21). Retard : visible seulement avec les échéances activées. « Je n'ai pas eu le temps » produit une **proposition** d'allègement à confirmer |
| Historique après fermeture et réouverture | Conservé : statuts, dates de fin, journal, conversation, missions, analyses et solutions restent dans `data-recette-reelle\` |

---

## 4. Coûts prévisionnels

**Tarifs `gpt-5-mini`** (catalogue vérifié le 10/11/2026) : 0,25 $ par million de jetons d'entrée, 2,00 $ par million de jetons de sortie. Coûts unitaires **mesurés** lors des recettes réelles des 10 et 11/11/2026 :

| Appel | Coût mesuré | Pire cas (plafond de sortie) |
|---|---|---|
| Classification d'un message | 0,001 à 0,002 $ | ≈ 0,008 $ |
| Réponse du coach, question de clarification | 0,002 à 0,005 $ | ≈ 0,009 $ |
| Proposition de plan ou de modification | ≈ 0,005 à 0,010 $ (estimation) | ≈ 0,009 $ |
| Analyse d'une idée | 0,007 à 0,011 $ | ≈ 0,018 $ |
| Synthèse et recommandation | ≈ 0,005 $ | ≈ 0,018 $ |
| Solutions pour un problème | 0,010 à 0,012 $ | ≈ 0,018 $ |

Sans appel OpenAI (0 $) : boutons de statut, blocage, annulation, préférences, création de projet, **Confirmer** / **Annuler**, modification d'une proposition, « oui » écrit, « Cherche des solutions », « Transforme ces actions en tâches », clics d'approbation (les recherches web consomment seulement le quota gratuit).

**Estimation du scénario complet (section 5) : ≈ 0,20 $**, pire cas ≈ 0,45 $.

**Recherches :** ≈ 30 à 45 requêtes au total (Tavily et Exa), dans les quotas gratuits : Tavily 1 000 crédits par mois (28 utilisés), Exa 10 $ par mois (0,064 $ utilisés). Le budget de chaque mission (0,40 $) et le plafond mensuel local bloquent tout dépassement.

**Registre local des tests automatisés** (`data/evaluations/`, informatif) : 0,149 $ engagés le 10/11 (plafond 0,16 $) et 0,092 $ le 11/11 (plafond 0,12 $), campagnes **closes**. Ce reliquat n'autorise **pas** la recette manuelle : un nouveau plafond doit être autorisé par vous.

---

## 5. Scénario de A à Z

Conventions : **« texte »** = à écrire exactement dans le champ « Votre message », puis Entrée ; **[Bouton]** = clic ; 🔎 = vérification SQLite avec `scripts\recette_etat.py` ; 💲 = coût estimé. Notez le résultat dans le tableau de contrôle (section 6).

### Partie A : préparation (0 $)
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| A1 | Barre latérale : « Utilisateur fictif » = **Alice (démo)** ; ouvrez **Modèles IA chargés** | Trois rôles en `openai · gpt-5-mini` ; « identique à la configuration chargée » ; aucune clé visible | — | 0 |
| A2 | Onglet **Recherche** (projet « Bougies artisanales » de démo) | « Recherche web **réelle** » ; Exa et Tavily « actif » avec les montants du mois. **Pas** de « simulée » | — | 0 |
| A3 | « Titre du nouveau projet » = `ab`, **[Créer le projet]** | Erreur « au moins 3 caractères » ; rien créé | aucun nouveau projet | 0 |
| A4 | Titre = `Bougies parfumées Lyon`, **[Créer le projet]** | Projet sélectionné ; « n'a pas encore de plan » | projet `draft`, version 1, objectif non défini | 0 |
| A5 | **Préférences** : longueur Standard, 3 actions, « Une seule question à la fois » cochée, « Utiliser des échéances » **cochée**, rythme « Un point par semaine », fuseau `Europe/Paris`, **[Enregistrer les préférences]** | « Préférences enregistrées. » | `échéances=True`, rythme `hebdomadaire` | 0 |

### Partie B : discussion et compréhension de l'idée
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| B1 | « Je veux vendre des bougies parfumées artisanales à Lyon, mais je ne sais pas par où commencer. » | Encart « Je réfléchis… ». Une orientation simple, l'offre (une seule fois) de préparer une recherche web, et **une seule** question (résultat visé) | projet toujours `draft` ; aucune tâche | ≈ 0,004 $ |
| B2 | « Quel placement en bourse me conseilles-tu pour financer le projet ? » | Refus : « pas d'avis médical, juridique ou financier personnalisé », proposition d'aider à structurer | rien | ≈ 0,002 $ |
| B3 | « Réponds-moi en une seule phrase à partir de maintenant. » | « Je ne peux pas modifier vos préférences depuis la conversation : rien n'a changé… » | préférences inchangées | ≈ 0,002 $ |
| B4 | Répondez à la question du coach : « Je veux vendre mes 20 premières bougies d'ici deux mois. » | Prise en compte de l'objectif ; question suivante sur le temps par jour (pas de nouvelle question sur l'objectif) | — (l'objectif est enregistré avec le plan) | ≈ 0,004 $ |
| B5 | **Ne répondez pas encore au temps** : passez à la partie C (le plan sera demandé après les recherches) | — | — | 0 |

### Partie C : recherche web réelle, avis et forums
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| C1 | « Que disent les clients des bougies artisanales dans les avis et sur les forums ? Et qui sont les concurrents ? » | **Proposition de recherche** : objectif, marché (France), recherches prévues, fournisseurs, données transmises, budget max 0,40 $, coût estimé, Reddit non consulté, sites exclus, **requêtes exactes** ; bouton **Approuver et lancer** | mission `proposed`, réelle, 0 requête | ≈ 0,002 $ |
| C2 | « oui » | « Pour lancer la recherche, cliquez sur « Approuver et lancer »… » : **rien n'est lancé** | mission toujours `proposed`, 0 requête | 0 |
| C3 | **[Annuler la recherche]** | Mission annulée, plus de bouton | mission `cancelled` | 0 |
| C4 | Reposez le message de C1 | Nouvelle proposition | nouvelle mission `proposed` | ≈ 0,002 $ |
| C5 | **[Approuver et lancer]** | Encart « Recherches en cours… » : « Recherches web : 1/4 … 4/4 » (≈ 6 s). Puis un résumé **sourcé** (« recherche web réelle »), avec « contenu publié par un vendeur, pas un avis indépendant » quand c'est le cas | mission terminée (`completed`) ; ≈ 4 requêtes réelles ; compteur Tavily et Exa augmenté | 0 $ OpenAI ; ≈ 0,03 $ de quota gratuit |
| C6 | Onglet **Recherche** : ouvrez **Sources (…)** | Chaque source : titre cliquable, site, date ou « date inconnue », date de collecte ; **aucun** « [SIMULÉ] » | — | 0 |

### Partie D : analyse et questions de suivi
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| D1 | « analyse » | Encart « Analyse de 1 idée(s) en cours », puis « Synthèse… » (≈ 1 min). Analyse : légende des natures, avantages, inconvénients, besoins des clients, prix observés, risques, concurrents (tous sourcés), « Limites des avis » (vendeurs non comptés, Reddit non consulté), inconnues, adéquation à votre situation, recommandation avec niveau de confiance, affirmations retirées par le contrôle | `analyses 1` sur la mission | ≈ 0,016 $ |
| D2 | « Quelle est la principale frustration des clients, et est-ce une tendance ou un témoignage isolé ? » | Réponse appuyée sur l'analyse, nature (tendance corroborée ou témoignage) et sources ; **aucune nouvelle recherche** | aucune nouvelle mission | ≈ 0,006 $ |
| D3 | Onglet Recherche : **Analyse du coach** (déplier) | Même analyse ; liste « Retiré ou requalifié par le contrôle des sources » | — | 0 |

### Partie E : solutions concrètes
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| E1 | « Cherche des solutions à ces problèmes » | Proposition de mission de solutions : problèmes traités (au plus 3), requêtes exactes, budget ; **réponse immédiate** (0 s, sans modèle) | mission `solutions` `proposed` | 0 |
| E2 | **[Approuver et lancer]** | « Recherches web : x/15 » puis « Problèmes traités : 1/3 … 3/3 » (≈ 70 s). Solutions par problème : outils existants d'abord, coût vérifié ou « non vérifié », recommandation, prochaines actions (durée, critère de fin), « À vérifier » | mission terminée ; ≈ 15 requêtes ; `solutions 1` | ≈ 0,033 $ ; ≈ 0,10 $ de quota gratuit |
| E3 | « Laquelle de ces solutions me conseillez-vous, avec mon budget ? » | Réponse appuyée sur les solutions trouvées, **pas** un refus « conseil financier » (correction du 11/11, jamais vérifiée en réel) | — | ≈ 0,006 $ |

### Partie F : plan, modification, confirmation
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| F1 | « Propose-moi un plan pour démarrer. » | Le coach demande ce qui manque : le **temps par jour** (l'objectif de B4 n'est pas redemandé) | projet `draft` | ≈ 0,004 $ |
| F2 | « J'ai 45 minutes par jour et un budget de 300 €. » | **Proposition de plan** : objectif, phases, 3 à 6 tâches avec critère de fin et durée ≤ 45 min, dépendances ; boutons **Confirmer** / **Annuler** ; « Rien n'est enregistré tant que… » | proposition `plan.create` `pending` ; **aucune tâche** | ≈ 0,012 $ |
| F3 | « oui » | « Pour enregistrer cette proposition, utilisez le bouton « Confirmer »… » | proposition toujours `pending`, aucune tâche | 0 |
| F4 | **[Annuler]** | « D'accord, rien n'a été modifié. » | proposition `cancelled` ; aucune tâche | 0 |
| F5 | « Finalement, je préfère viser 10 bougies vendues d'ici un mois. Propose-moi un plan. » | Nouvelle proposition, adaptée au **nouvel objectif** (changement d'avis) | nouvelle proposition `pending` | ≈ 0,012 $ |
| F6 | **Modifier la proposition avant de confirmer** : changez le titre de la tâche 1, cochez « Retirer la tâche » sur la dernière, **[Mettre à jour la proposition]** | « Proposition mise à jour » avec vos changements ; l'ancienne est remplacée | ancienne `superseded`, nouvelle `pending` | 0 |
| F7 | **[Confirmer]** | « Le plan est enregistré. Première action : T1… » ; barre « Progression : 0 % » ; onglet **Plan et tâches** rempli | projet `active` ; phases et tâches T1…Tn `à faire` ; dépendances ; proposition `applied` ; événement `plan.applied` | 0 |

### Partie G : solutions en tâches, modifications de tâches
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| G1 | « Transforme ces actions en tâches » | Proposition : nouvelle phase « Solutions aux problèmes repérés » et ses tâches ; **Confirmer** / **Annuler** | proposition `pending` ; tâches inchangées | 0 |
| G2 | **[Confirmer]** | Les nouvelles tâches apparaissent ; le pourcentage baisse (plus de tâches) | nouvelle phase et tâches ; proposition `applied` | 0 |
| G3 | « Ajoute une tâche : demander un devis d'assurance à deux assureurs. » | Proposition d'ajout (une tâche, critère de fin) à confirmer | proposition `pending` | ≈ 0,008 $ |
| G4 | **[Confirmer]** | Tâche ajoutée, numéro suivant | nouvelle tâche `à faire` | 0 |
| G5 | « Décale T2 à vendredi prochain. » | Proposition d'échéance (date affichée en français) à confirmer | proposition `pending` | ≈ 0,008 $ |
| G6 | **[Confirmer]** | « Échéance : … » sur la carte de T2 | `échéance` de T2 renseignée | 0 |
| G7 | « Supprime la dernière tâche ajoutée. » | Si la tâche n'est pas désignée clairement : une **question** (jamais une tâche devinée) ; sinon une proposition de suppression | rien supprimé avant **Confirmer** | ≈ 0,008 $ |
| G8 | Répondez avec le numéro, par exemple « Supprime T*n* », puis **[Annuler]** | « rien n'a été modifié » | tâche toujours présente | ≈ 0,008 $ |

### Partie H : exécution, suivi, prochaine tâche
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| H1 | « Où en suis-je ? » | « 0 tâche terminée sur N (0 %). Prochaines actions possibles : … » (au plus 3, sans dépendance en attente) | — | ≈ 0,002 $ |
| H2 | Plan et tâches : **[Commencer T1]** | « T1 est maintenant en cours » ; bouton **Annuler ce changement** | T1 `en cours` ; événement `task.status_changed` | 0 |
| H3 | **[Marquer terminée T1]** | « T1 est maintenant terminée » ; barre mise à jour (1/N) ; « Où en est le projet » annonce la prochaine action | T1 `terminée`, date de fin | 0 |
| H4 | « J'ai fini » | Une question : quelle tâche ? (aucune tâche devinée) | rien changé | ≈ 0,002 $ |
| H5 | « J'ai terminé T2 » | « T2 est maintenant terminée… » en haut de page, avec **Annuler ce changement** | T2 `terminée` | ≈ 0,002 $ |
| H6 | **[Annuler ce changement (conversation)]** | « Changement annulé pour conversation » ; T2 revient à son statut précédent | événement d'annulation ; T2 non terminée | 0 |
| H7 | Choisissez une tâche T*k* qui **dépend** d'une tâche non terminée et cliquez **[Marquer terminée T*k*]** | Enregistré, avec « À noter : T*j* n'est pas encore terminée » | T*k* `terminée` | 0 |
| H8 | **[Rouvrir T*k*]** | T*k* revient « à faire » | T*k* `à faire` | 0 |
| H9 | « Et maintenant ? » | **Une** prochaine tâche réalisable (dépendances terminées) | — | ≈ 0,002 $ |
| H10 | Terminez deux autres tâches réalisables (boutons), puis « Où en suis-je ? » | « 3 tâches terminées sur N (x %) » ; les tâches dont les dépendances sont maintenant terminées deviennent recommandées | 3 tâches `terminée` | ≈ 0,002 $ |

### Partie I : blocages, retards, replanification
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| I1 | Sur la prochaine tâche recommandée : cochez **Signaler un blocage sur T*n***, raison `ab`, **[Enregistrer le blocage de T*n*]** | « Indiquez une raison d'au moins 3 caractères. » | rien changé | 0 |
| I2 | Raison `en attente du devis du fournisseur de cire`, **[Enregistrer le blocage]** | « Blocage : … » sur la carte ; T*n* n'est plus dans les prochaines actions | T*n* `bloquée`, raison | 0 |
| I3 | « Je n'ai pas eu le temps cette semaine, c'est trop gros pour moi. » | **Proposition** d'allègement (par exemple une étape de 10 minutes) à confirmer | proposition `pending` | ≈ 0,010 $ |
| I4 | « non » | Proposition annulée | proposition `cancelled` | 0 |
| I5 | Si une tâche a une échéance passée (sinon, passez) : regardez le haut de page | « En retard : T… » | — | 0 |
| I6 | Débloquez : **[Remettre à faire T*n*]** sur la tâche bloquée | Elle redevient recommandable | T*n* `à faire`, raison effacée | 0 |

### Partie J : comparaison de plusieurs idées (nouveau projet)
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| J1 | Créez le projet `Choisir mon idée` | Projet vide | projet `draft` | 0 |
| J2 | « J'ai quatre idées de business, mais je ne sais pas laquelle choisir. » | Le coach demande les quatre idées, une par ligne | — | ≈ 0,002 $ |
| J3 | Les quatre idées, une par ligne (Maj+Entrée pour aller à la ligne) : `Bougies parfumées artisanales` / `Food truck de galettes` / `Cours de yoga en entreprise` / `Application de covoiturage scolaire` | Une question sur vos critères | — | ≈ 0,002 $ |
| J4 | « J'ai 500 € de budget et 6 heures par semaine, je veux un revenu complémentaire. » | Une question sur le marché ; rien redemandé ensuite | — | ≈ 0,002 $ |
| J5 | « France » | Proposition de recherche **comparative** (4 idées, requêtes exactes) | mission `proposed` | ≈ 0,002 $ |
| J6 | **[Approuver et lancer]** | Progression, puis un résumé sourcé par idée | ≈ 15 requêtes | 0 $ OpenAI ; quota |
| J7 | « analyse » | « Analyses d'idées terminées : 1/4 … 4/4 » (en parallèle), puis synthèse : tableau par idée, arbitrages, recommandation avec confiance, adaptée à 500 € et 6 h | `analyses 1` | ≈ 0,045 $ |
| J8 | « Laquelle est la plus risquée pour moi ? » | Réponse appuyée sur l'analyse, sans nouvelle recherche | — | ≈ 0,006 $ |

### Partie K : continuité, reprise après redémarrage, isolation
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| K1 | Arrêtez l'application (section 1), puis redémarrez-la (commande PowerShell ou demande à Claude) ; ouvrez http://localhost:8501 | L'interface revient | — | 0 |
| K2 | Alice, projet `Bougies parfumées Lyon` | Historique complet de la conversation ; « Vous avez terminé 3 tâches sur N… Prochaine action : … » ; statuts, blocages et échéances intacts ; onglet Recherche : missions, analyse et solutions | identique à avant l'arrêt | 0 |
| K3 | « Rappelle-moi mon objectif et ce que la recherche a montré sur les avis clients. » | Réponse cohérente avec le nouvel objectif (F5) et l'analyse (D1) | — | ≈ 0,005 $ |
| K4 | Utilisateur **Bruno (démo)** | Aucun projet d'Alice ; seul « Atelier de réparation de vélos » | — | 0 |
| K5 | Retour à Alice ; **Mes données** → **[Préparer l'export de mes données]** → **[Télécharger l'export (JSON)]** | Fichier JSON avec projets, tâches, événements ; aucune clé | — | 0 |

### Partie L : erreurs et limites (facultatif)
| ID | Action | Comportement attendu | 🔎 SQLite | 💲 |
|---|---|---|---|---|
| L1 | Provoquez une proposition (par exemple « Ajoute une tâche : appeler la mairie »), attendez **16 minutes**, puis **[Confirmer]** | Message « proposition expirée », rien d'écrit | proposition `expired` | ≈ 0,008 $ |
| L2 | Message de plus de 2 000 caractères | « Certaines informations ne sont pas valides. » ; aucun appel au modèle | rien | 0 |
| L3 | Onglet Recherche : **Budget maximal de la mission** = 0,01, **[Préparer la mission]** | Mission refusée ou réduite au budget (aucun appel avant approbation) | — | 0 |
| L4 | Projet de démonstration « Bougies artisanales » : **Mes données** → **[Supprimer ce projet…]** → **[Annuler]** | Rien supprimé | projet présent | 0 |

**Total estimé : ≈ 0,20 $ OpenAI** (pire cas ≈ 0,45 $) ; ≈ 35 à 45 requêtes Tavily et Exa sur les quotas gratuits.

---

## 6. Tableau de contrôle

Cochez une case par étape. « Cumul $ » : ajoutez le coût estimé de l'étape, pour vous arrêter avant le plafond autorisé.

| ID | Réussi | Échoué | À corriger | Cumul $ | Notes (ce que vous avez écrit, ce que le coach a répondu) |
|---|---|---|---|---|---|
| A1 | ☐ | ☐ | ☐ | 0 | |
| A2 | ☐ | ☐ | ☐ | 0 | |
| A3 | ☐ | ☐ | ☐ | 0 | |
| A4 | ☐ | ☐ | ☐ | 0 | |
| A5 | ☐ | ☐ | ☐ | 0 | |
| B1 | ☐ | ☐ | ☐ | | |
| B2 | ☐ | ☐ | ☐ | | |
| B3 | ☐ | ☐ | ☐ | | |
| B4 | ☐ | ☐ | ☐ | | |
| C1 | ☐ | ☐ | ☐ | | |
| C2 | ☐ | ☐ | ☐ | | |
| C3 | ☐ | ☐ | ☐ | | |
| C4 | ☐ | ☐ | ☐ | | |
| C5 | ☐ | ☐ | ☐ | | |
| C6 | ☐ | ☐ | ☐ | | |
| D1 | ☐ | ☐ | ☐ | | |
| D2 | ☐ | ☐ | ☐ | | |
| D3 | ☐ | ☐ | ☐ | | |
| E1 | ☐ | ☐ | ☐ | | |
| E2 | ☐ | ☐ | ☐ | | |
| E3 | ☐ | ☐ | ☐ | | |
| F1 | ☐ | ☐ | ☐ | | |
| F2 | ☐ | ☐ | ☐ | | |
| F3 | ☐ | ☐ | ☐ | | |
| F4 | ☐ | ☐ | ☐ | | |
| F5 | ☐ | ☐ | ☐ | | |
| F6 | ☐ | ☐ | ☐ | | |
| F7 | ☐ | ☐ | ☐ | | |
| G1 | ☐ | ☐ | ☐ | | |
| G2 | ☐ | ☐ | ☐ | | |
| G3 | ☐ | ☐ | ☐ | | |
| G4 | ☐ | ☐ | ☐ | | |
| G5 | ☐ | ☐ | ☐ | | |
| G6 | ☐ | ☐ | ☐ | | |
| G7 | ☐ | ☐ | ☐ | | |
| G8 | ☐ | ☐ | ☐ | | |
| H1 | ☐ | ☐ | ☐ | | |
| H2 | ☐ | ☐ | ☐ | | |
| H3 | ☐ | ☐ | ☐ | | |
| H4 | ☐ | ☐ | ☐ | | |
| H5 | ☐ | ☐ | ☐ | | |
| H6 | ☐ | ☐ | ☐ | | |
| H7 | ☐ | ☐ | ☐ | | |
| H8 | ☐ | ☐ | ☐ | | |
| H9 | ☐ | ☐ | ☐ | | |
| H10 | ☐ | ☐ | ☐ | | |
| I1 | ☐ | ☐ | ☐ | | |
| I2 | ☐ | ☐ | ☐ | | |
| I3 | ☐ | ☐ | ☐ | | |
| I4 | ☐ | ☐ | ☐ | | |
| I5 | ☐ | ☐ | ☐ | | |
| I6 | ☐ | ☐ | ☐ | | |
| J1 | ☐ | ☐ | ☐ | | |
| J2 | ☐ | ☐ | ☐ | | |
| J3 | ☐ | ☐ | ☐ | | |
| J4 | ☐ | ☐ | ☐ | | |
| J5 | ☐ | ☐ | ☐ | | |
| J6 | ☐ | ☐ | ☐ | | |
| J7 | ☐ | ☐ | ☐ | | |
| J8 | ☐ | ☐ | ☐ | | |
| K1 | ☐ | ☐ | ☐ | | |
| K2 | ☐ | ☐ | ☐ | | |
| K3 | ☐ | ☐ | ☐ | | |
| K4 | ☐ | ☐ | ☐ | | |
| K5 | ☐ | ☐ | ☐ | | |
| L1 | ☐ | ☐ | ☐ | | |
| L2 | ☐ | ☐ | ☐ | | |
| L3 | ☐ | ☐ | ☐ | | |
| L4 | ☐ | ☐ | ☐ | | |

## 7. Pendant et après la recette
- En cas d'écart : notez l'ID, votre message et la réponse (une capture suffit), et envoyez-les-moi ; je diagnostiquerai sans relancer d'appel payant sans votre accord.
- Après la recette, la consommation Tavily et Exa enregistrée dans `data-recette-reelle\` devra être reportée dans le compteur mensuel principal (`data\`), pour que les quotas gratuits restent protégés.
- L'application n'est **pas** déclarée prête à publier : cette recette sert à le décider.

## 8. Vérifier le coach (D-78)

Les réponses sont écrites par `gpt-5-mini` : leur texte varie. Ce qu'il faut juger, c'est le comportement. Nouveau profil, puis **Accueil → Créer votre projet**. Coût estimé : quelques millièmes de dollar par message.

| # | Message | Ce qui doit se passer |
|---|---|---|
| V1 | « Bonjour, j'aimerais créer mon propre business, mais je ne sais pas par où commencer. Pouvez-vous m'aider ? » | Les premiers mots de la réponse apparaissent rapidement puis le texte s'écrit au fil de l'eau. Une réponse naturelle, qui aide à faire émerger l'idée, sans phrase type (« Piste provisoire, à vérifier… », « objectif provisoire ») |
| V2 | « J'aimerais vendre des bougies artisanales parfumées, mais je n'ai aucune expérience. » | Le coach parle des bougies, tient compte de votre inexpérience et propose une première orientation concrète |
| V3 | « Mon projet est de fabriquer et vendre des bougies artisanales parfumées. Je connais donc déjà mon idée. Je suis débutant et j'ai besoin que vous me guidiez concrètement, étape par étape. Que me conseillez-vous de faire en premier ? » | Une réponse différente des précédentes, qui donne une première étape concrète. Si un titre générique avait été enregistré, une carte propose un titre précis (« Bougies… »), enregistré seulement par votre clic |
| V4 | Une autre idée dans un nouveau projet (par exemple une boulangerie à Rennes) | Aucune trace du projet de bougies |
| V5 | « Proposez-moi un plan. » | Une proposition de plan s'affiche (présentation écrite par le modèle, tâches, durées, priorités) ; rien n'est enregistré avant « Confirmer » ; un « oui » écrit ne confirme pas |
| V6 | « D'accord, vérifiez le marché à Lyon. » | Une mission de recherche est proposée avec **Approuver et lancer** ; rien n'est lancé avant le clic |
| V7 | Fermer, relancer, rouvrir le projet, puis « On en était où ? » | La conversation est là ; la réponse tient compte de ce qui a été dit |
| V8 | Couper le réseau puis envoyer un message | Un message d'erreur explicite et un bouton **Réessayer** ; aucune réponse inventée |

Mesurer soi-même les temps de réponse : `.\.venv\Scripts\python.exe scripts\measure_latency.py --real-api --budget-usd 0.05` (appels payants, plafond strict, pire cas réservé avant chaque appel).

## 9. Vérifier la décision du coach (D-79)

Nouveau projet. Après chaque message, notez si un plan est préparé (« Préparation de la proposition de plan… » sous la réponse, puis la carte **Proposition en attente de votre accord**).

| # | Message | Ce qui doit se passer |
|---|---|---|
| P1 | « Je veux vendre des bougies artisanales. » | Un premier conseil adapté et, au plus, une question (temps ou budget) ; **aucun plan préparé** |
| P2 | « J'ai une heure par jour. » | Le coach ne redemande pas votre temps ; il peut demander le budget ; **aucun plan** |
| P3 | « Mon budget est de 200 €. » | Le coach peut proposer un plan de lui-même : sa réponse l'annonce, puis la proposition s'affiche ; rien n'est enregistré |
| P4 | Nouveau projet : « Faites-moi tout de suite un plan provisoire pour un food truck. » | Un plan est proposé sans questionnaire ; les inconnues (temps, budget) apparaissent comme hypothèses |
| P5 | Nouveau projet, idée + temps, puis « Je préfère ne pas donner de budget. » | Le coach n'insiste pas ; un plan peut être proposé avec une hypothèse de budget signalée |
| P6 | Pendant une proposition : « Finalement je préfère vendre en ligne. » | La proposition précédente n'est pas enregistrée ; une proposition adaptée (vente en ligne) peut suivre |
| P7 | Après une proposition annulée : « En résumé, ce sont des bougies faites main. » | Pas de nouveau plan (simple reformulation) |
| P8 | Le coach propose une recherche ; répondre « Non, je préfère avancer sans. » | Aucune mission ; la recherche n'est pas reproposée d'elle-même |
| P9 | « Oui, vérifiez le marché à Lyon. » | Une mission est proposée avec **Approuver et lancer** ; rien n'est lancé avant le clic |
| P10 | Si un avis « Aucune proposition de plan n'a été préparée : il manque encore… » apparaît | Le modèle a voulu un plan sans les informations nécessaires ; le code l'a refusé et vous le dit |

## 10. Vérifier recherche, preuves et cohérence (D-80)

Nouveau projet. Coût : appels OpenAI, plus 6 à 8 recherches Tavily/Exa par mission approuvée (coût estimé affiché avant le clic).

| # | Message ou action | Ce qui doit se passer |
|---|---|---|
| R1 | « Je ne sais pas du tout quel business créer. Je suis débutant. » | Le coach vous aide à découvrir une idée (une question, ou quelques pistes) ; il ne vous demande pas de définir une offre ni de contacter des clients |
| R2 | Donnez votre profil (temps, budget, compétences) | Des pistes hiérarchisées et expliquées ; les chiffres non sourcés sont présentés comme hypothèses ; pas de questionnaire |
| R3 | Choisissez une piste et demandez une recherche « sur le marché français » | La proposition montre **Sujet** (la piste précise, jamais « Nouveau projet »), **Marché(s) : France**, des requêtes en français sans ambiguïté, les **Sens écartés** si besoin ; le coach ne promet ni Reddit ni LinkedIn |
| R4 | **Approuver et lancer** | Les résultats arrivent avec une **analyse critique** : nombre de résultats écartés comme hors sujet, **Niveau de preuve**, prix seulement s'ils sont chiffrés dans une source, sinon « Prix observés : insuffisant » ; aucun « Dites analyse » |
| R5 | « Analysez ces résultats de manière critique. Ne construisez aucun plan. » | Une réponse du coach fondée sur l'analyse ; **aucune** carte ni message ne vous invite ensuite à construire le plan |
| R6 | Donnez votre temps et votre budget | Toujours pas de plan de l'initiative du coach ; si le modèle en voulait un, un avis dit pourquoi il n'a pas été préparé |
| R7 | « Maintenant, proposez-moi un plan provisoire. » | Une proposition (provisoire si les preuves sont insuffisantes), rien d'enregistré avant **Confirmer** |
| R8 | Carte de titre | Un titre concret et complet (jamais « Son propre business (offre et cible ») ; enregistré seulement par votre clic |

## 11. Vérifier le diagnostic du coach (D-81)

Nouveau projet pour chaque profil. À chaque tour : une seule question, une réponse courte, aucune piste de business, aucune tâche, aucune durée imposée tant que le coach ne vous connaît pas ; il ne redemande jamais ce que vous avez dit.

| # | Messages | Ce qui doit se passer |
|---|---|---|
| D1 | « Bonjour, j'aimerais créer mon propre business, mais je ne sais pas par où commencer. Pouvez-vous m'aider ? » | Un accueil bref et UNE question sur vous (vos intérêts, ce que vous aimez faire) ; aucune piste, aucune tâche, aucun plan, aucun titre proposé |
| D2 | Répondez « je ne sais pas » | Le coach ne repose pas la même question : il aborde le sujet autrement ou passe à autre chose |
| D3 | Donnez vos intérêts, puis votre métier, puis votre objectif | Chaque question rebondit sur votre réponse précédente ; temps et budget viennent plus tard |
| D4 | Une fois assez connu(e) | Deux ou trois idées rattachées explicitement à ce que vous avez dit, comparées, avec les hypothèses signalées, puis une question pour choisir |
| D5 | Nouveau projet : « J'ai déjà essayé une boutique en ligne, ça n'a pas marché… » | Le coach s'intéresse à ce que vous en avez appris |
| D6 | Nouveau projet : une idée précise (« ouvrir un food truck de crêpes à Nantes… ») | Pas de diagnostic complet : une aide directe sur votre question |
| D7 | Nouveau projet : « Donnez-moi directement un conseil… » | Un conseil immédiat, hypothèses signalées |

Évaluation automatique sur ces profils (appels payants, plafond strict) : `.\.venv\Scripts\python.exe scripts\evaluate_discovery.py --real-api --budget-usd 0.15` ; la transcription est écrite dans `data\evaluations\`.

## 12. Parcours complet du consultant (D-82)

Nouveau projet. À vérifier à chaque étape, sans chercher une formulation précise.

| # | Étape | Ce qui doit se passer |
|---|---|---|
| C1 | Découverte (5 à 8 tours) | Réponses courtes : une phrase au plus puis une seule question ; jamais « je ne donne pas encore de conseils » ; aucune question déjà posée ni sur ce qui est déjà dit ; aucune piste avant de connaître vos essais passés, votre objectif, votre temps, votre budget et votre zone |
| C2 | « Ce que le coach a retenu » | Ce que vous avez dit, avec vos mots ; rien d'inventé |
| C3 | « Que me recommandez-vous ? » | UNE recommandation motivée par votre profil, risques et hypothèses dits |
| C4 | « Je peux investir 150 € » | Jamais de refus « avis financier » |
| C5 | Demande de recherche | Un message court ; la carte montre sujet, zone, clientèle, sources, données transmises et coût avant « Approuver et lancer » |
| C6 | Après l'approbation | Une conclusion courte (recommandation ou preuves insuffisantes, ce qu'on sait, ce qui reste à vérifier) ; le détail dans « Détail » et l'onglet Recherche |
| C7 | « Retenez que… » | Le point apparaît dans « Ce que le coach a retenu » ; aucune autre annonce « j'ai enregistré » |
| C8 | Demande de plan | Un plan détaillé par étapes ; boutons « Accepter et ajouter ce plan à mes tâches » et « Demander un changement » |
| C9 | « Demander un changement », puis décrire le changement | Rien n'est enregistré ; un plan modifié est présenté avec une nouvelle validation |
| C10 | Accepter, actualiser la page | Les tâches sont dans « Plan et tâches » ; « Marquer terminée » fait avancer la progression |
| C11 | « Créer votre projet » depuis l'accueil | Un nouveau projet vide, jamais le projet en cours |
