# Parcours de démonstration (3 à 5 minutes)

**Version :** phase 5 — 9 novembre 2026. Vérifié automatiquement par `tests/e2e/test_demo_script.py` ; captures du même parcours dans `docs/screenshots/` ; guide vidéo dans `docs/VIDEO_GUIDE.md`.

**Données :** entièrement fictives (Alice et Bruno). **LLM :** faux fournisseur déterministe ; les phrases ci-dessous produisent exactement les réponses indiquées.
**À dire en ouverture :** « Prototype indépendant, local, sans authentification. Aucun avis médical, juridique ou financier. Le modèle propose, le code vérifie, et rien n'est enregistré sans votre clic. »

## Préparation (hors chronomètre)

```powershell
.\.venv\Scripts\python.exe scripts\dev.py reset-data
.\.venv\Scripts\python.exe scripts\dev.py seed
.\.venv\Scripts\python.exe scripts\dev.py demo
```
Ouvrir http://localhost:8501. Dans **Préférences**, choisir « Réponses courtes » et 1 action visible, puis enregistrer.

## Déroulé

| Temps | Action | Ce que l'on montre |
|---|---|---|
| 0:00–0:30 | Utilisateur **Bruno (démo)**, projet « Atelier de réparation de vélos » | Résumé factuel : « pas encore de plan » ; préférences choisies par l'utilisateur |
| 0:30–1:15 | Écrire « Je veux ouvrir un atelier de réparation de vélos, par où commencer ? » puis « Trouver trois premiers clients. J'ai 45 minutes par jour. » | Une seule question, puis une proposition de plan ; **rien n'est enregistré** |
| 1:15–2:00 | « Modifier la proposition avant de confirmer » : renommer la tâche 1, retirer la tâche 3, « Mettre à jour la proposition », puis **Confirmer** | Correction sans écriture, puis plan enregistré : « Première action : T1 … » |
| 2:00–2:40 | Onglet **Plan et tâches** : « Commencer T1 », puis « Annuler ce changement (T1) », puis « Marquer terminée T1 » | Retour dans la carte, annulation possible, progression calculée (50 %) |
| 2:40–3:20 | Cocher « Signaler un blocage sur T2 », saisir « J'attends du matériel », enregistrer | Raison obligatoire, statut « bloquée », prochaine action : lever le blocage |
| 3:20–4:00 | Écrire « Je n'ai pas avancé cette semaine », puis « Oui » ; enfin **Annuler** | Proposition plus petite et sans jugement ; « Oui » écrit ne confirme pas ; annulation sans écriture |
| 4:00–4:30 | Arrêter le serveur (Ctrl+C), relancer `scripts\dev.py demo`, rouvrir Bruno | Reprise identique : historique, résumé et progression depuis la base |
| 4:30–5:00 | **Mes données** : « Préparer l'export », puis « Supprimer ce projet… » et **Confirmer la suppression** | Export disponible, suppression confirmée, données retirées |

## Points de vigilance
- Ne pas présenter le faux fournisseur comme un vrai LLM : la validation avec un modèle réel n'a pas encore eu lieu.
- Avec un vrai LLM, les formulations varieront : refaire une répétition complète avant toute présentation.

## Correspondance avec les six séquences du dossier initial

| Séquence attendue | Où elle apparaît |
|---|---|
| 1. Présenter le problème, choisir « réponses courtes, une tâche à la fois » | Ouverture et préparation (Préférences) |
| 2. Saisir une idée avec une contrainte de temps | 0:30–1:15 (vélos, 45 minutes par jour) ; le projet d'Alice montre la variante « bougies, 30 minutes par jour » |
| 3. Questions ciblées, plan court, prévisualisation | 0:30–1:15 |
| 4. Corriger une version, puis confirmer | 1:15–2:00 (correction dans « Modifier la proposition », puis Confirmer) |
| 5. Marquer une tâche terminée, pourcentage calculé | 2:00–2:40 |
| 6. Fermer et rouvrir, déclarer un blocage, replanification proposée mais non appliquée | 2:40–4:30 |

## Moments à capturer

| Moment | Capture |
|---|---|
| Ouverture (Alice) | `01_accueil_reprise.png` |
| Après la première phrase de Bruno | `02_conversation_clarification.png` |
| Plan proposé | `03_plan_propose.png` |
| Après Confirmer | `04_plan_confirme.png` |
| Après le blocage de T2 | `05_taches_et_blocage.png` et `06_progression.png` |
| Après « Je n'ai pas avancé cette semaine » | `07_replanification_proposee.png` |
