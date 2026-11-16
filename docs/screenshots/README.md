# Captures d'écran

## Interface actuelle

Captures du 16 novembre 2026, prises dans Chrome à 1 440 × 960 px avec la base fictive de démonstration et le fournisseur simulé.

- [Accueil](accueil.png)
- [Conversation](conversation.png)
- [Mes projets](projets.png)
- [Mes tâches](taches.png)

## Archives du parcours du 9 novembre

**Origine :** captures réelles produites le 9 novembre 2026 par `python scripts/capture_screenshots.py`. Le script lance l'interface sur une base neuve, la pilote avec Microsoft Edge sans fenêtre (protocole DevTools, fenêtre de 1400 × 960, thème clair) et enregistre ce que le navigateur affiche. **Aucune image n'est retouchée ni générée.**
**Données :** fictives (Alice et Bruno). **Fournisseur LLM :** faux fournisseur déterministe ; les réponses du coach ne proviennent donc pas d'un vrai modèle.
**Parcours :** celui de `docs/DEMO_SCRIPT.md`, avec les mêmes phrases, mais avec les préférences par défaut et sans l'étape de correction du plan : les trois tâches sont conservées, d'où 33,3 % au lieu de 50 %.

| Fichier | État montré | Utilisation proposée |
|---|---|---|
| `01_accueil_reprise.png` | Accueil d'Alice : résumé factuel, progression 33,3 % (1/3), prochaine action | Parcours historique |
| `02_conversation_clarification.png` | Projet de Bruno : idée vague, puis une seule question de clarification | Parcours historique |
| `03_plan_propose.png` | Plan proposé en attente : aperçu, Confirmer, Annuler, « Modifier la proposition » | Parcours historique |
| `04_plan_confirme.png` | Après le clic : « Le plan est enregistré. Première action : T1 » | Parcours historique |
| `05_taches_et_blocage.png` | Onglet « Plan et tâches » : T1 terminée, T2 bloquée avec sa raison, dépendances | Parcours historique |
| `06_progression.png` | Résumé recalculé : 1 tâche sur 3, 33,3 %, prochaine étape « lever le blocage » | Parcours historique |
| `07_replanification_proposee.png` | « Je n'ai pas avancé » : une étape plus petite, proposée sans jugement et non appliquée | Parcours historique |

## Recommandation
Conserver les sept captures (environ 720 Ko au total), qui couvrent l'accueil, le chat, le plan proposé, la confirmation, les tâches et la progression.

**Captures complémentaires possibles**, à prendre à la main si besoin :
- éditeur « Modifier la proposition avant de confirmer » ouvert ;
- panneau « Préférences » (réponses courtes, une action visible) ;
- « Mes données » : export et confirmation de suppression ;
- affichage étroit (mobile).

## Regénérer

```powershell
.\.venv\Scripts\python.exe scripts\capture_screenshots.py
```

Le script utilise une base séparée (`data/screenshots/`, ignorée par Git), force le faux fournisseur et retire les clés d'API de l'environnement du serveur lancé. Option `--browser` pour indiquer Chrome ou Chromium.
