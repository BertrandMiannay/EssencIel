# 🚗 Prix des Carburants — Data Pipeline & Dashboard

Projet portfolio Data Engineering — Pipeline de données en temps quasi-réel sur les prix des carburants en France, avec stockage historique sur BigQuery et restitution via une API Django.

---

## 📋 Objectif

Construire un pipeline de données end-to-end permettant de :

- **Ingérer** automatiquement les prix des carburants depuis l'API officielle du Ministère de l'Économie
- **Stocker** un historique des snapshots dans BigQuery (partitionné par date)
- **Exposer** des endpoints Django pour alimenter un front-end

---

## 🎯 Cas d'usage front

- Afficher le **prix moyen par zone géographique** (France, région, code postal) et le **taux de rupture** par carburant
- Afficher le **top / worst prix** par carburant et par zone
- **Rechercher des stations** par service associé (lavage, gonflage, boutique, etc.)

---

## 🗂️ Source de données

| Propriété | Valeur |
|---|---|
| **Source** | Ministère de l'Économie — DGCCRF |
| **Dataset** | Prix des carburants en France — Flux instantané v2 |
| **URL** | `data.economie.gouv.fr` (Opendatasoft) |
| **Fréquence source** | Toutes les 10 minutes |
| **Fréquence ingestion** | 1x / jour (snapshot quotidien) |
| **Volume** | ~12 000 stations × 6 carburants ≈ 4 MB / snapshot |
| **Licence** | Licence Ouverte 2.0 (Etalab) |
| **Clé API** | Non requise pour les exports open data |

**Endpoint d'export :**
```
https://data.economie.gouv.fr/api/explore/v2.1/catalog/datasets/prix-des-carburants-en-france-flux-instantane-v2/exports/csv
```

### Données disponibles par station
- Informations générales : adresse, coordonnées GPS, code postal, département, région
- Prix par carburant : Gazole, SP95, SP98, E10, E85, GPLc
- Dates de mise à jour des prix
- Ruptures de stock (type, date de début)
- Services proposés (boutique, lavage, gonflage, restauration, etc.)
- Horaires d'ouverture

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    SOURCE                               │
│   API data.economie.gouv.fr (export CSV, sans clé)     │
└────────────────────┬────────────────────────────────────┘
                     │ HTTP GET (1x/jour)
┌────────────────────▼────────────────────────────────────┐
│                 ORCHESTRATION (GCP)                     │
│   Cloud Scheduler → Cloud Functions (Python)            │
└────────────────────┬────────────────────────────────────┘
                     │
          ┌──────────┴──────────┐
          │                     │
┌─────────▼──────┐   ┌──────────▼──────────────────────┐
│  GCS (raw)     │   │  BigQuery                        │
│  CSV bruts     │   │  Table partitionnée par date     │
│  (data lake)   │   │  Clustering : région, cp         │
└────────────────┘   └──────────────────────────────────┘
                                 │
                     ┌───────────▼──────────────────────┐
                     │  Django (serveur OVH)             │
                     │  API REST — google-cloud-bigquery │
                     └───────────┬──────────────────────┘
                                 │
                     ┌───────────▼──────────────────────┐
                     │  Front-end                        │
                     │  Carte + Dashboard + Recherche    │
                     └──────────────────────────────────┘
```

---

## 🗄️ Schéma BigQuery

**Table** : `carburants.snapshots`  
**Partitionnement** : `DATE(ingested_at)`  
**Clustering** : `region`, `code_postal`

| Colonne | Type | Description |
|---|---|---|
| `ingested_at` | TIMESTAMP | Date/heure d'ingestion (clé de partition) |
| `station_id` | STRING | Identifiant unique de la station |
| `adresse` | STRING | Adresse complète |
| `code_postal` | STRING | Code postal |
| `ville` | STRING | Commune |
| `departement` | STRING | Département |
| `region` | STRING | Région |
| `latitude` | FLOAT64 | Coordonnée GPS |
| `longitude` | FLOAT64 | Coordonnée GPS |
| `autoroute` | BOOL | Station sur autoroute |
| `gazole_prix` | FLOAT64 | Prix en € |
| `gazole_maj` | TIMESTAMP | Dernière mise à jour du prix |
| `gazole_rupture` | BOOL | En rupture |
| `sp95_prix` | FLOAT64 | Prix en € |
| `sp95_maj` | TIMESTAMP | Dernière mise à jour du prix |
| `sp95_rupture` | BOOL | En rupture |
| `sp98_prix` | FLOAT64 | Prix en € |
| `sp98_maj` | TIMESTAMP | Dernière mise à jour du prix |
| `sp98_rupture` | BOOL | En rupture |
| `e10_prix` | FLOAT64 | Prix en € |
| `e10_maj` | TIMESTAMP | Dernière mise à jour du prix |
| `e10_rupture` | BOOL | En rupture |
| `e85_prix` | FLOAT64 | Prix en € |
| `e85_maj` | TIMESTAMP | Dernière mise à jour du prix |
| `e85_rupture` | BOOL | En rupture |
| `gplc_prix` | FLOAT64 | Prix en € |
| `gplc_maj` | TIMESTAMP | Dernière mise à jour du prix |
| `gplc_rupture` | BOOL | En rupture |
| `services` | STRING | Liste des services (JSON ou CSV) |
| `horaires` | STRING | Horaires d'ouverture (JSON) |

---

## 💻 Stack technique

| Composant | Technologie |
|---|---|
| Orchestration | Google Cloud Scheduler |
| Ingestion | Google Cloud Functions (Python) |
| Data Lake | Google Cloud Storage (GCS) |
| Data Warehouse | Google BigQuery |
| Backend API | Django + Django REST Framework |
| Client BQ | `google-cloud-bigquery` (Python) |
| Hébergement backend | Serveur OVH |

---

## 💰 Coûts estimés

Le projet est conçu pour rester **entièrement dans les free tiers GCP** :

| Service | Free tier | Usage estimé |
|---|---|---|
| BigQuery stockage | 10 GB / mois | ~1,5 GB / an |
| BigQuery requêtes | 1 TB / mois | Quelques MB / requête |
| Cloud Functions | 2M invocations / mois | ~30 / mois |
| Cloud Scheduler | 3 jobs gratuits | 1 job |
| Cloud Storage | 5 GB / mois | ~150 MB / mois |

> ⚠️ Un compte de facturation GCP avec carte bancaire est requis pour activer les services, même dans le free tier. Poser une **budget alert à 0 €** pour éviter toute surprise.

---

## 📁 Structure du repo

```
.
├── ingestion/
│   └── main.py              # Cloud Function — fetch + chargement BQ
├── django_api/
│   ├── views.py             # Endpoints REST
│   ├── queries.py           # Requêtes SQL BigQuery
│   └── serializers.py
├── bigquery/
│   └── schema.json          # Schéma de la table BQ
├── infra/
│   └── scheduler.yaml       # Config Cloud Scheduler
├── .env.example
├── requirements.txt
└── project.md
```

---

## 🚀 Roadmap

- [ ] Cloud Function d'ingestion quotidienne
- [ ] Création de la table BigQuery partitionnée
- [ ] Endpoints Django : prix moyen par zone
- [ ] Endpoints Django : top / worst prix
- [ ] Endpoints Django : recherche par service
- [ ] Front-end : carte interactive
- [ ] Front-end : dashboard agrégats
