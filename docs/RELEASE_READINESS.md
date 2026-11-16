# État de préparation à la publication (fin de phase 5)

**Date :** 9 novembre 2026
**Recommandation :** le dépôt est **prêt à être publié comme prototype de portfolio**, avec le faux fournisseur et les avertissements du README, **dès que le porteur du projet aura** : (1) fourni son identité Git, (2) validé le contenu du premier commit et (3) décidé du sort des documents internes. Le projet **ne doit pas être présenté comme un agent IA validé** tant que les 12 dialogues avec un vrai modèle n'ont pas été exécutés et relus.

## 1. Fonctionnalités prêtes (testées et vérifiées dans le navigateur)
- Projet, clarification une question à la fois, plan proposé, correction avant confirmation, confirmation et annulation.
- Statuts, blocages avec raison, annulation du dernier changement, progression déterministe, prochaines actions.
- Replanification sans jugement et sans écriture silencieuse ; un « oui » écrit ne vaut pas confirmation.
- Reprise après redémarrage, préférences respectées et jamais modifiées par le LLM.
- Export limité à l'utilisateur, suppression d'un projet, effacement complet (checkpoints compris).
- Isolation entre utilisateurs et entre projets ; injections sans effet sur les écritures.

## 2. Livrables de publication (phase 5)

| Livrable | État |
|---|---|
| `README.md` public (problème, solution, fonctionnalités, architecture, technologies, installation Windows et Linux, limites, attributions, mention de non-affiliation) | Fait |
| `docs/LIMITATIONS.md`, `docs/SECURITY.md` | Faits |
| CI GitHub Actions (`.github/workflows/ci.yml`) | Écrite ; étapes simulées localement sous Windows ; **jamais exécutée sur GitHub ni sous Linux** |
| Captures réelles (`docs/screenshots/`, 7 images) | Faites, avec le faux fournisseur |
| Scénario de démonstration et guide vidéo | Faits ; **vidéo non enregistrée** (à faire par le porteur du projet) |
| Licences : `THIRD_PARTY_NOTICES.md` et `docs/DEPENDENCY_LICENSES.md` (83 paquets) | Faites |
| Revue de similarité avec Todo Agent | Faite, aucune reprise détectée (`REUSE_DECISIONS.md` § 6), sans valeur de clean-room stricte |
| Exclusion des documents internes (D-46) | Faite et testée |

## 3. Risques restants

| Risque | Gravité | Commentaire |
|---|---|---|
| Validation réelle limitée à un modèle | Moyenne | Quatre campagnes `gpt-5-mini` (effort `low`), dont la finale à 15/15 ; sécurité tenue ; aucun autre modèle évalué |
| Reformulations du modèle variables | Faible | Vouvoiement, faits et dates désormais encadrés par le code (D-58) ; à surveiller avec d'autres modèles |
| Aucune authentification | Élevée si exposé | Usage local uniquement (`SECURITY.md`) ; ne pas déployer de démo en ligne |
| CI jamais exécutée sur GitHub | Moyenne | Premier passage à surveiller après la publication, en particulier sous Linux |
| Accessibilité non testée avec un lecteur d'écran | Moyenne | Checklist prête (`ACCESSIBILITY_CHECKLIST.md`) |
| Échéance impossible à effacer ; correction limitée aux plans | Faible | Écarts documentés |

## 4. Checklist avant publication

**À fournir ou décider par le porteur du projet**
- [ ] Nom et adresse e-mail Git (configuration locale au dépôt, pas globale).
- [ ] Décision sur les documents internes (D-46) : `CLAUDE.md`, `DOSSIER_COMPLET.pdf`, `docs/00` à `docs/07`, `docs/research/`. Par défaut, ils restent hors du dépôt.
- [ ] Relecture du `README.md`, en particulier la mention de non-affiliation à Fantas.IA.
- [ ] Choix du nom et de la visibilité du dépôt GitHub. Le dépôt n'est pas créé.
- [ ] Hébergement de la vidéo, une fois enregistrée (`VIDEO_GUIDE.md`) ; à ne pas versionner dans Git.
- [ ] Facultatif : exclure aussi `docs/IMPLEMENTATION_LOG.md`, qui résume les autorisations données à chaque phase.

**Vérifications au moment du commit**
- [ ] `git status` : 126 fichiers attendus, aucun `.env`, `data/`, `.venv/`, `.claude/`, base SQLite, cache ni document interne.
- [ ] `python scripts/dev.py check-secrets`, `lint` et `cov` sans erreur.
- [ ] Premier commit avec le message préparé, sans `push` avant accord.

**Après la création du dépôt distant (sur autorisation explicite)**
- [ ] Premier passage de la CI (Linux et Windows) ; corriger tout écart propre à Linux.
- [ ] Ajouter le badge de CI au README une fois l'URL connue.
- [ ] Vérifier le rendu des diagrammes Mermaid et des captures sur GitHub.

**Avant de présenter le projet comme un agent IA**
- [ ] Clé configurée dans `.env`, puis `scripts/evaluate_llm.py` et `tests/real_llm/` exécutés ; résultats réels consignés et relus avec la grille humaine.
- [ ] Ajustement éventuel des consignes au modèle, puis nouvelle répétition de la démonstration avec le vrai modèle.
