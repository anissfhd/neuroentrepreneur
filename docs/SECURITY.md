# Sécurité et limites du mode local

**Version :** phase 5 — 9 novembre 2026
**Statut :** prototype local de démonstration. **Il ne doit pas être déployé publiquement en l'état.**

## 1. Ce qui est garanti et testé

| Garantie | Mécanisme | Tests |
|---|---|---|
| Aucune écriture sensible sans clic explicite | Actions en attente ; le LLM n'a aucun outil d'écriture ; seule l'interface appelle `confirm` | `test_pending_actions.py`, `test_agent_security.py`, `test_phase4_security.py` |
| Un message écrit ne confirme jamais | « oui » ou « 👍 » → rappel du bouton ; autre message → annulation (D-32, D-40, D-44) | `test_dialogue.py`, `test_unexpected_messages.py` |
| Confirmation à usage unique, avec expiration | Réservation conditionnelle, délai de 15 min, versions attendues | T05, expiration, conflit de version, redémarrage |
| Isolation entre utilisateurs | Filtrage par `user_id` à chaque requête ; une ressource d'autrui répond « introuvable » | `test_isolation.py` (21 appels), `test_phase4_security.py` |
| Isolation entre projets d'un même utilisateur | Un fil par projet ; une décision ne vaut que pour une action du projet courant (D-44) | `test_phase4_security.py` |
| Identité jamais choisie par le LLM ni lue dans le chat | Contexte d'exécution fourni par le serveur, jamais checkpointé | S-04, `test_agent_security.py` |
| Données transmises au LLM sans identifiant interne | Références « T<n> », données délimitées, chevrons neutralisés | `test_agent_security.py` |
| Effacement complet | Projets, tâches, événements, actions, fils et checkpoints ; seule reste la trace de l'action d'effacement, sans contenu | `test_full_journey.py` (contrôle SQL de toutes les tables) |
| Aucun secret versionné | `.env` et `data/` ignorés ; analyse des fichiers destinés à Git, aussi en CI | `test_no_secrets.py`, `test_phase4_security.py` (`git check-ignore`) |
| Documents internes non publiés | Dossier initial, consignes de Claude Code et audits ignorés par Git (D-46) | `test_internal_working_documents_are_not_published` |

## 2. Limites connues (non couvertes par le prototype)

1. **Aucune authentification.** Les deux utilisateurs sont fictifs et se choisissent dans une liste. N'importe qui ayant accès à l'interface peut se faire passer pour l'un ou l'autre. Le filtrage par utilisateur protège contre les erreurs de logique, **pas contre un utilisateur malveillant**.
2. **Interface sans TLS.** Streamlit écoute en HTTP sur le port 8501. Le serveur ne doit être exposé ni sur un réseau partagé ni sur Internet. Au démarrage, Streamlit affiche aussi une adresse réseau : seul l'usage de `localhost` est prévu.
3. **Données en clair sur le disque.** `data/neurocoach.sqlite` et `data/checkpoints.sqlite` ne sont pas chiffrés. Les conversations y sont conservées jusqu'à leur suppression.
4. **Contenu envoyé au fournisseur LLM** lorsqu'un fournisseur réel est configuré : le message, l'idée, les titres et les critères de fin du projet. Aucun identifiant interne n'est transmis. Il ne faut saisir aucune donnée personnelle sensible ni aucune donnée de santé.
5. **Pas de limitation de débit ni de plafond de coût global.** Seuls un délai et un nombre maximal de jetons s'appliquent par appel.
6. **Clés d'API dans `.env`** (fichier local ignoré par Git). Elles sont lues à part, jamais stockées dans la configuration, transmises masquées (`SecretStr`) au client du fournisseur et jamais affichées (`check-llm`, compte rendu d'évaluation : tests `test_llm_config_secrecy.py`). Le traçage LangSmith (`LANGSMITH_TRACING`) enverrait les conversations à un service tiers : `check-llm` le signale et il doit rester désactivé.
7. **Injection de prompt :** les données sont délimitées et ne peuvent déclencher aucune écriture. La qualité des réponses face à une injection n'est cependant **pas validée avec un vrai modèle**.
8. **Aucun journal technique :** le code n'écrit aucun journal. Il n'y a donc ni fuite de contenu par ce biais, ni trace exploitable pour diagnostiquer un incident.
9. **Dépendances :** les versions sont figées dans `requirements.lock` et leurs licences listées dans `DEPENDENCY_LICENSES.md`, sans audit de vulnérabilités automatisé (à ajouter à la CI, par exemple avec `pip-audit`).

## 3. Prérequis avant toute exposition publique
Une authentification réelle, le TLS, une base gérée et chiffrée, une politique de conservation, un plafond de coût, la surveillance, un audit des dépendances, et une analyse d'impact sur la protection des données si des données personnelles réelles sont traitées.
