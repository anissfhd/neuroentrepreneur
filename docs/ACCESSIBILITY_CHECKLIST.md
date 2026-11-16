# Accessibilité : vérifications réalisées et checklist manuelle

**Version :** phase 4 — 9 novembre 2026
**Avertissement :** aucun test avec un lecteur d'écran réel (NVDA, JAWS, VoiceOver) n'a été effectué. Seuls la navigation au clavier dans un navigateur et l'arbre d'accessibilité ont été examinés.

## 1. Vérifié réellement (navigateur intégré, données fictives)

| Point | Résultat |
|---|---|
| Ordre de tabulation (page d'accueil) | 11 arrêts utiles : zone principale, onglet « Conversation », zone de message, lien d'évitement, utilisateur, projet, titre du nouveau projet, « Créer le projet », « Préférences », « Mes données » |
| Changement d'onglet | Flèches gauche et droite (modèle ARIA des onglets) |
| Focus visible | Soulignement de l'onglet, halo autour des boutons et des sections dépliables |
| Boutons des tâches | Atteignables au clavier, libellés explicites (« Commencer T2 », « Marquer terminée T2 ») |
| Libellés uniques | Cases et champs nommés par tâche (« Signaler un blocage sur T2 », « Retirer la tâche 3 « … » ») ; vérifié aussi par test |
| **Corrigé en phase 4** | Ancres « Link to heading » focalisables retirées ; boutons « Deploy » et « Main menu » retirés (`toolbarMode = "minimal"`) |
| **Corrigé en phase 3** | Avatars lus « face » / « smart_toy » ; retour d'action hors de vue |

## 2. Limites connues (composants Streamlit)
- Les sections dépliables exposent le nom d'icône « keyboard_arrow_right » ou « keyboard_arrow_down » dans leur texte : un lecteur d'écran pourrait le lire.
- Le lien d'évitement (« Skip to main content ») et l'indication « Press Enter to submit form » sont en anglais.
- Les messages de succès et d'erreur ne sont pas annoncés explicitement (`aria-live`) : comportement à vérifier avec un lecteur d'écran.
- Le contraste du thème par défaut n'a pas été mesuré avec un outil dédié.

## 3. Checklist manuelle (à exécuter avec un lecteur d'écran)

**Clavier seul**
- [ ] Choisir un utilisateur et un projet sans souris.
- [ ] Envoyer un message (Entrée), puis confirmer une proposition au clavier.
- [ ] Ouvrir « Modifier la proposition », corriger un titre, retirer une tâche, valider.
- [ ] Passer à l'onglet « Plan et tâches » (flèches), ouvrir une phase, changer un statut, annuler le changement.
- [ ] Signaler un blocage avec une raison ; vérifier le message d'erreur si la raison est vide.
- [ ] Préférences : modifier puis enregistrer ; Mes données : préparer l'export, demander puis annuler une suppression.
- [ ] À chaque étape : le focus reste visible et ne se perd pas après une relance de la page.

**Lecteur d'écran** (NVDA + Firefox, ou VoiceOver + Safari)
- [ ] Les titres (« Où en est le projet », « Proposition en attente de votre accord ») sont annoncés comme titres.
- [ ] Les messages du chat sont lus dans l'ordre, avec un auteur identifiable.
- [ ] Les statuts sont lus en toutes lettres (« Statut : bloquée »).
- [ ] Après une action, le message de confirmation ou d'erreur est perçu sans chercher.
- [ ] La barre de progression annonce sa valeur (« Progression : 33,3 % (1/3) »).
- [ ] Noter tout libellé en anglais ou tout nom d'icône lu à voix haute.

**Lisibilité**
- [ ] Zoom à 200 % : rien n'est coupé et aucun défilement horizontal n'apparaît.
- [ ] Contraste du texte secondaire (légendes grises) mesuré à au moins 4,5:1.
