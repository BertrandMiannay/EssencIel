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
sudo chmod 600 /etc/essenciel/env
```

## 3. Credentials GCP

Télécharger la clé JSON du compte de service depuis la console GCP, puis :

```bash
sudo cp gcp-sa.json /etc/essenciel/gcp-sa.json
sudo chmod 600 /etc/essenciel/gcp-sa.json
```

Le chemin doit correspondre à `GOOGLE_APPLICATION_CREDENTIALS` dans `/etc/essenciel/env`.

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

Remplacer `<domaine>` et `<your-user>` dans `deploy/nginx.conf`, puis :

```bash
sudo cp deploy/nginx.conf /etc/nginx/sites-available/essenciel
sudo ln -s /etc/nginx/sites-available/essenciel /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx
```

### Activer HTTPS avec Certbot

```bash
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d <domaine>
sudo systemctl restart essenciel
```

## 7. Ingestion quotidienne (cron systemd)

Remplacer `<your-user>` dans `deploy/essenciel-ingestion.service`, puis :

```bash
sudo cp deploy/essenciel-ingestion.service /etc/systemd/system/
sudo cp deploy/essenciel-ingestion.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now essenciel-ingestion.timer
sudo systemctl list-timers essenciel-ingestion.timer  # vérifier la prochaine exécution
```

Le timer déclenche l'ingestion chaque jour à 8h00 (±5 min aléatoires).

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
