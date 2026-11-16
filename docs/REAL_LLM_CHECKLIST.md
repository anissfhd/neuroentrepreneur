# Checklist : configurer et tester un vrai fournisseur LLM

**But :** exécuter les 12 dialogues d'évaluation avec un vrai modèle et en consigner les résultats réels. Les appels sont **payants**, et ne sont jamais lancés par la CI.
**Règle :** la clé ne s'écrit que dans `.env`, avec un éditeur de texte. Elle ne se colle ni dans le chat, ni dans une commande, ni dans un autre fichier. Les outils du projet ne l'affichent jamais : ni sa valeur, ni sa longueur, ni un extrait.

## 1. Configurer (une fois, par le porteur du projet)
- [ ] Créer une clé dans la console du fournisseur (Anthropic ou OpenAI), avec un **plafond de dépense**.
- [ ] Installer l'extra : `.\.venv\Scripts\python.exe -m pip install -e ".[anthropic]"` (ou `".[openai]"`).
- [ ] `Copy-Item .env.example .env`, puis, dans `.env` :
  - `NEUROCOACH_LLM_PROVIDER=anthropic` (ou `openai`) ;
  - `NEUROCOACH_LLM_MODEL=claude-opus-5-5` (modèle Claude actuel par défaut ; `claude-sonnet-5-5` coûte deux fois moins cher) ;
  - `NEUROCOACH_LLM_MAX_OUTPUT_TOKENS=4000` (valeur par défaut) : la réflexion des modèles Claude récents compte dans ce plafond ;
  - `NEUROCOACH_LLM_EFFORT=low` est conseillé pour un premier passage moins cher et plus rapide. Laisser vide pour la valeur par défaut du modèle ;
  - la clé dans `ANTHROPIC_API_KEY` (ou `OPENAI_API_KEY`).
- [ ] Ne pas activer `LANGSMITH_TRACING` ni `ANTHROPIC_LOG` : les conversations partiraient vers un service tiers ou dans un journal.

## 2. Vérifier la configuration
- [ ] `.\.venv\Scripts\python.exe scripts\dev.py check-llm`. Résultat attendu : `.env ignoré par Git : oui`, `ANTHROPIC_API_KEY : définie (valeur masquée)`, `Construction du client : réussie`, aucune ligne « Bloquant ». Aucun appel réseau n'a lieu.
- [ ] `.\.venv\Scripts\python.exe scripts\dev.py check-llm --ping` : **un** appel réel minimal, avec sortie structurée comme dans l'application, pour quelques jetons. En cas d'échec, seuls le type d'erreur et le statut HTTP sont affichés : 401 = clé refusée, 404 = modèle inconnu, 400 = paramètre refusé, 429 = quota.
- [ ] `.\.venv\Scripts\python.exe scripts\dev.py check-secrets` : aucun secret destiné à Git.

## 3. Tester
> Changement de modèle, comparaisons, retour arrière et retrait de `gpt-5-mini` : voir [MODEL_OPERATIONS.md](MODEL_OPERATIONS.md).

- [ ] Essai à blanc d'abord : `.\.venv\Scripts\python.exe scripts\evaluate_llm.py` (faux fournisseur **imposé**, même si `.env` configure un vrai modèle).
- [ ] Les dialogues réels, **payants** : `scripts\evaluate_llm.py --real-api --budget-usd <plafond> --price-input <$/M> --price-output <$/M> --ledger data\evaluations\<campagne>.jsonl`. Sans l'une de ces options, rien n'est lancé. Le registre est partagé par toutes les exécutions d'une campagne (`scripts\run_campaign.py`) et relu avant chaque appel. Le compte rendu est écrit dans `data/evaluations/`, non versionné. Il comprend la section « Appels au fournisseur » (nombre, durée moyenne, erreurs par type).
- [ ] Les mêmes scénarios avec assertions : `$env:NEUROCOACH_RUN_REAL_LLM = "1"; .\.venv\Scripts\python.exe -m pytest tests/real_llm`, puis `Remove-Item Env:NEUROCOACH_RUN_REAL_LLM`.
- [ ] Remplir la grille d'évaluation humaine : utilité du plan, clarté, fidélité, ton sans jugement, respect des préférences, résistance aux injections.
- [ ] Rejouer la démonstration (`DEMO_SCRIPT.md`) dans l'interface avec le vrai modèle.

## 4. Après
- [ ] Consigner les résultats réels, réussites **et** échecs, dans `IMPLEMENTATION_LOG.md` et `VALIDATION_PLAN.md`, sans clé ni donnée personnelle.
- [ ] Corriger les consignes au modèle si besoin, relancer les dialogues, puis la suite de non-régression (`scripts\dev.py cov`).
- [ ] Revenir au faux fournisseur pour la démonstration hors ligne : `NEUROCOACH_LLM_PROVIDER=fake`.
- [ ] En cas de doute sur une fuite, révoquer la clé dans la console du fournisseur.
