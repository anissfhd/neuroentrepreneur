# Démo entreprise sur Windows

L'instance de démonstration écoute sur `127.0.0.1:8540`. Son répertoire de données et
sa politique d'accès se trouvent dans `%LOCALAPPDATA%\NeuroEntrepreneur\entreprise-demo`,
hors du dépôt. Les identifiants de démo sont dans la politique locale. Transmettre le mot de passe séparément.

Dans une nouvelle fenêtre PowerShell, configurer l'agent avec l'authtoken du compte ngrok.
Utiliser `Read-Host -MaskInput` dans PowerShell 7 pour saisir le jeton localement.

```powershell
$token = Read-Host 'Authtoken ngrok' -MaskInput
ngrok config add-authtoken $token
Remove-Variable token
```

Puis ouvrir le tunnel avec la politique d'authentification et l'inspection désactivée.

```powershell
$policy = Join-Path $env:LOCALAPPDATA 'NeuroEntrepreneur\entreprise-demo\ngrok-policy.json'
ngrok http http://127.0.0.1:8540 --inspect=false --traffic-policy-file $policy
```

Avant de partager le lien affiché par ngrok, vérifier dans une fenêtre privée que le site
demande des identifiants, qu'un mot de passe incorrect est refusé et que les identifiants
de démo ouvrent le site. Tester ensuite un échange complet et une recherche web depuis ce lien.
Fermer le tunnel avec Ctrl+C après la démo.
