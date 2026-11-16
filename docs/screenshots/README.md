# Captures d'écran

**Origine :** captures réelles produites le 9 novembre 2026 par `python scripts/capture_screenshots.py`. Le script lance l'interface sur une base neuve, la pilote avec Microsoft Edge sans fenêtre (protocole DevTools, fenêtre de 1400 × 960, thème clair) et enregistre ce que le navigateur affiche. **Aucune image n'est retouchée ni générée.**
**Données :** fictives (Alice et Bruno). **Fournisseur LLM :** faux fournisseur déterministe ; les réponses du coach ne proviennent donc pas d'un vrai modèle.
**Parcours :** celui de `docs/DEMO_SCRIPT.md`, avec les mêmes phrases, mais avec les préférences par défaut et sans l'étape de correction du plan : les trois tâches sont conservées, d'où 33,3 % au lieu de 50 %.

| Fichier | État montré | Utilisation proposée |
|---|---|---|
| `01_accueil_reprise.png` | Accueil d'Alice : résumé factuel, progression 33,3 % (1/3), prochaine action | README (grille) |
| `02_conversation_clarification.png` | Projet de Bruno : idée vague, puis une seule question de clarification | README (grille) |
| `03_plan_propose.png` | Plan proposé en attente : aperçu, Confirmer, Annuler, « Modifier la proposition » | **Image principale du README** |
| `04_plan_confirme.png` | Après le clic : « Le plan est enregistré. Première action : T1 » | README (grille) |
| `05_taches_et_blocage.png` | Onglet « Plan et tâches » : T1 terminée, T2 bloquée avec sa raison, dépendances | README (grille) |
| `06_progression.png` | Résumé recalculé : 1 tâche sur 3, 33,3 %, prochaine étape « lever le blocage » | README (grille) |
| `07_replanification_proposee.png` | « Je n'ai pas avancé » : une étape plus petite, proposée sans jugement et non appliquée | README (grille) |

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
