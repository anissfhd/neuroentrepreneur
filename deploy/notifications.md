# Rappels d’échéance

Le processus `python -m neurocoach.deadline_worker` partage le répertoire de données de
Streamlit. Docker Compose lance ce processus automatiquement avec le service coach.

Les notifications persistantes figurent dans le journal avec le type `task.deadline_notice`.
Chaque événement identifie le destinataire, le projet, la tâche, l’échéance, le type de rappel,
le texte et l’identifiant à utiliser pour éviter les renvois. Ce contrat servira aux futurs
adaptateurs email et WhatsApp. Les coordonnées, le consentement, les fournisseurs et les
accusés de livraison restent à configurer avant l’activation de ces deux canaux.

## Configuration des canaux externes à venir

Le routage prévu est `task.deadline_notice` vers les adaptateurs ci-dessous.
Les valeurs restent côté serveur et la configuration est un modèle pour la prochaine étape.
Le worker actuel lit uniquement la configuration de l'application et ne charge aucun adaptateur externe.

| Canal | Configuration à renseigner à l'activation |
| --- | --- |
| Email | Fournisseur SMTP ou API, identifiant du secret, adresse expéditrice et adresse vérifiée du destinataire |
| WhatsApp | Fournisseur, identifiant du numéro émetteur, identifiant du secret, modèle approuvé et numéro vérifié du destinataire |

Utiliser l'identifiant de l'événement avec le canal comme clé de déduplication.
L'adresse et le numéro doivent être associés à l'identité du destinataire et à son consentement.
