# Déploiement sur VPS

## Prérequis

- VPS Ubuntu/Debian avec Python 3.11+, Nginx, Git installés
- Accès SSH avec droits sudo
- Compte de service GCP avec rôles `BigQuery Data Viewer`, `BigQuery Job User` et `Storage Object Creator`

## 1. Cloner et installer

```bash
git clone https://github.com/BertrandMiannay/EssencIel.git ~/EssencIel
cd ~/EssencIel
python3 -m venv .venv
.venv/bin/pip install poetry
.venv/bin/poetry install --only main
```

## 2. Variables d'environnement

```bash
sudo mkdir /etc/essenciel
sudo cp deploy/env.example /etc/essenciel/env
sudo nano /etc/essenciel/env  # remplir SECRET_KEY, ALLOWED_HOSTS, GCP_PROJECT, GCS_BUCKET
sudo chmod 666 /etc/essenciel/env
```

## 3. Credentials GCP

Installer le SDK Google Cloud puis générer les credentials Application Default :

```bash
sudo apt install apt-transport-https ca-certificates gnupg -y
echo "deb [signed-by=/usr/share/keyrings/cloud.google.gpg] https://packages.cloud.google.com/apt cloud-sdk main" \
  | sudo tee /etc/apt/sources.list.d/google-cloud-sdk.list
curl https://packages.cloud.google.com/apt/doc/apt-key.gpg \
  | sudo apt-key --keyring /usr/share/keyrings/cloud.google.gpg add -
sudo apt update && sudo apt install google-cloud-cli -y
```

Se connecter et générer le profil ADC sous l'utilisateur qui exécutera le service :

```bash
gcloud auth login
gcloud config set project <GCP_PROJECT>
gcloud auth application-default login
```

Les credentials sont écrits dans `~/.config/gcloud/application_default_credentials.json` et utilisés automatiquement par les SDK Google Cloud (BigQuery, Storage).

## 4. Préparer l'app

```bash
set -a && source /etc/essenciel/env && set +a
cd ~/EssencIel/web
../.venv/bin/python manage.py collectstatic --no-input
```

Pas de `migrate` — l'app n'utilise pas de base de données Django (lecture BigQuery uniquement).

## 5. Lancer gunicorn via systemd

Avant de copier le service, remplacer `<your-user>` par ton nom d'utilisateur dans `deploy/essenciel.service`.

```bash
sudo cp deploy/essenciel.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now essenciel
sudo systemctl status essenciel
```

## 6. Nginx + HTTPS (Let's Encrypt)

Remplacer `<domaine>` et `<your-user>` dans `deploy/nginx.conf`, puis déployer la config HTTP d'abord :

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/essenciel
sudo ln -sf /etc/nginx/sites-available/essenciel /etc/nginx/sites-enabled/essenciel
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

### Activer HTTPS avec Certbot

Certbot génère les certificats **et** met à jour la config nginx automatiquement (redirection 80→443 incluse) :

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d <domaine>
sudo systemctl restart essenciel
```

L'app est ensuite accessible sur `https://<domaine>`.

## 7. Ingestion quotidienne (cron systemd)

Remplacer `<your-user>` dans `deploy/essenciel-ingestion.service`, puis :

```bash
sudo cp deploy/essenciel-ingestion.service /etc/systemd/system/
sudo cp deploy/essenciel-ingestion.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now essenciel-ingestion.timer
sudo systemctl list-timers essenciel-ingestion.timer  # vérifier la prochaine exécution
```


### Lancer l'ingestion manuellement

```bash
sudo systemctl start essenciel-ingestion.service
sudo journalctl -u essenciel-ingestion -f
```

## Mise à jour

```bash
cd ~/EssencIel
git pull
.venv/bin/poetry install --only main
cd web && ../.venv/bin/python manage.py collectstatic --no-input
sudo systemctl restart essenciel
```

## Commandes utiles

```bash
sudo journalctl -u essenciel -f   # logs en temps réel
sudo systemctl status essenciel   # état du service
sudo systemctl restart essenciel  # redémarrer
sudo nginx -t                     # vérifier la config Nginx
sudo journalctl -u essenciel-ingestion -f          # logs ingestion
sudo systemctl list-timers essenciel-ingestion.timer  # prochaine exécution
```
