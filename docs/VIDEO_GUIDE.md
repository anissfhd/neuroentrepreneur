# Guide d'enregistrement de la vidéo de démonstration

**Durée visée :** 3 à 5 minutes. **Contenu :** le parcours de `DEMO_SCRIPT.md`, sur des données fictives, avec le faux fournisseur LLM.
**À dire clairement dans la vidéo :** prototype indépendant, non affilié à Fantas.IA ; réponses produites par un faux fournisseur déterministe ; aucune validation avec un vrai modèle à ce jour.

## 1. Outils (au choix, gratuits sous Windows)
- **OBS Studio** : enregistrement d'une fenêtre ou d'une zone, micro séparé. Recommandé.
- **Barre de jeux Xbox** (`Win + Alt + R`) : simple, mais limitée à la fenêtre active.
- **Outil Capture d'écran** de Windows 11 (mode vidéo), si disponible.

Réglages conseillés : 1920 × 1080 ou 1280 × 720, 30 images par seconde, MP4 (H.264). Micro testé, notifications coupées (Assistant de concentration ou « Ne pas déranger »).

## 2. Préparation (5 minutes, hors enregistrement)
1. Vérifier qu'aucun fichier `.env` ne contient de clé, ou ne jamais l'afficher à l'écran.
2. Repartir de données propres :
   ```powershell
   .\.venv\Scripts\python.exe scripts\dev.py reset-data
   .\.venv\Scripts\python.exe scripts\dev.py seed
   .\.venv\Scripts\python.exe scripts\dev.py demo
   ```
3. Ouvrir http://localhost:8501 dans une fenêtre de navigateur dédiée : profil sans favoris ni extensions visibles, zoom à 110 ou 125 % pour la lisibilité.
4. Masquer ou fermer le terminal pendant l'enregistrement : il affiche des chemins locaux.
5. Garder `DEMO_SCRIPT.md` ouvert sur un second écran ou imprimé. Copier les phrases à saisir dans un bloc-notes pour éviter les fautes de frappe.
6. Faire **une répétition complète** chronométrée.

## 3. Déroulé et narration

| Temps | À l'écran | Narration suggérée |
|---|---|---|
| 0:00–0:20 | Page d'accueil (Alice) | « NeuroEntrepreneur est un prototype indépendant de coach conversationnel. Le modèle propose, le code vérifie, et rien n'est enregistré sans votre clic. Ici, les réponses viennent d'un faux fournisseur, pour une démonstration reproductible. » |
| 0:20–1:15 | Bruno : idée, question, plan proposé | « Une seule question à la fois. Le plan proposé n'est qu'un aperçu : rien n'est encore enregistré. » |
| 1:15–2:00 | Correction de la proposition, puis Confirmer | « Je peux corriger avant d'accepter. L'écriture n'a lieu qu'au clic sur Confirmer. » |
| 2:00–3:20 | Tâches : commencer, annuler, terminer, bloquer | « Les statuts et le pourcentage sont calculés par le code. Un blocage exige une raison. » |
| 3:20–4:00 | « Je n'ai pas avancé », puis « Oui », puis Annuler | « Aucune culpabilisation : une étape plus petite est proposée. Un “oui” écrit ne vaut pas confirmation. » |
| 4:00–4:30 | Redémarrage du serveur, reprise | « Après un redémarrage, tout est relu depuis la base : historique, résumé, progression. » |
| 4:30–5:00 | Mes données : export, suppression | « Chaque utilisateur peut exporter ou effacer ses données. Limites : usage local, pas d'authentification, validation avec un vrai modèle à venir. » |

Pour le redémarrage (4:00), couper l'enregistrement de la fenêtre du terminal ou insérer un carton « Redémarrage du serveur ».

## 4. Montage et publication
- Couper les temps morts ; ne pas accélérer les réponses du coach (la démonstration doit rester fidèle).
- Ajouter des **sous-titres en français** (accessibilité) et un carton final avec les limites.
- Vérifier image par image qu'aucune clé, adresse e-mail, ni chemin personnel n'apparaît.
- **Ne pas versionner la vidéo dans Git** (fichier lourd). Options : pièce jointe d'une *release* GitHub, ou plateforme vidéo en accès « non répertorié », avec un lien depuis le README. Le choix et la publication reviennent au porteur du projet.
