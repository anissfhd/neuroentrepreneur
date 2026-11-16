# Démo entreprise

Déployer le code sur une VM avec stockage persistant. Dans `deploy/demo.env`, définir
`NEUROCOACH_LLM_MODEL` avec le modèle actuellement utilisé, `OPENAI_API_KEY`, les clés
`TAVILY_API_KEY` et/ou `EXA_API_KEY` correspondant aux fournisseurs actifs et, si souhaité,
`NEUROCOACH_SPENDING_CAP_USD`. Garder ce fichier sur le serveur avec des droits restreints.
Pour une configuration locale par rôle, recopier aussi les variables de routage correspondantes.

Depuis la racine, lancer `docker compose -f deploy/compose.yaml up -d --build`.
L'application écoute sur `127.0.0.1:8501`. Publier ce port via un proxy HTTPS avec accès
sur invitation, compatible WebSocket. Pour cette démo, consacrer une instance à l'entreprise
car l'application utilise des profils locaux et ne fournit pas d'isolation par connexion.
Le volume `coach_data` démarre vide et conserve SQLite et les checkpoints après redémarrage.

Sur le lien HTTPS, vérifier l'accès invité, une réponse réelle du coach, une recherche web
approuvée, la confirmation d'un plan et la réouverture de la conversation après redémarrage.
