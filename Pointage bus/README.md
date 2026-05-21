# Pointage Bus

Web app mobile pour pointer les services de bus dans un Google Sheet.

Deux modes :
- **Service régulier** (Sheet1) : saisie d'un nombre de passagers, date + service (Aller le matin / Retour le soir) auto-détectés.
- **Service occasionnel** (Sheet2) : trajet ponctuel saisi en 2 temps (montée puis descente) avec date, heures de départ/arrivée, kilométrage, adultes et enfants. Compteurs +/- avec appui long pour compter les passagers à la montée. La saisie partielle survit à la fermeture de l'app (stockée comme ligne brouillon dans Sheet2).

Conçu pour tourner dans un conteneur Docker sur un serveur Unraid.

---

## 1. Prérequis Google

### a. Créer un compte de service Google
1. Aller sur <https://console.cloud.google.com/> et créer (ou choisir) un projet.
2. Menu → **APIs & Services → Library** → activer **Google Sheets API**
   (et **Google Drive API** si vous voulez aussi pouvoir lister les feuilles).
3. Menu → **APIs & Services → Credentials** → **Create credentials** →
   **Service account**. Donnez-lui un nom, ignorez les rôles facultatifs, créez.
4. Cliquez sur le compte créé → onglet **Keys** → **Add key → JSON**.
   Le fichier `xxxx.json` est téléchargé.
5. Renommez-le en `service-account.json`.

### b. Partager votre Google Sheet avec le compte de service
1. Ouvrir le fichier JSON, copier la valeur du champ `client_email`
   (de la forme `xxxx@yyyy.iam.gserviceaccount.com`).
2. Dans votre Google Sheet : **Partager** → coller cet email → rôle **Éditeur**.

### c. Préparer la structure des Sheets

**Sheet1 — Service régulier**
- Première ligne = en-têtes. Par défaut, l'app cherche `Date`, `Aller`, `Retour`
  (insensible aux majuscules et aux accents). Configurable via variables d'env.
- Une ligne par jour. L'app crée la ligne du jour si elle n'existe pas, sinon
  écrase la cellule Aller ou Retour correspondante.

**Sheet2 — Service occasionnel**
- Première ligne = en-têtes. Par défaut :
  `Date`, `Heure départ`, `Heure arrivée`, `Km départ`, `Km arrivée`, `Km total`, `Adultes`, `Enfants`.
- Une ligne par trajet, ajoutée à la fin. La ligne est créée à la montée
  (heure arrivée et km arrivée vides) puis complétée à la descente.
- L'app détecte automatiquement le trajet en cours (heure départ remplie,
  heure arrivée vide) au prochain accès à `/occasionnel`.

---

## 2. Variables d'environnement

| Nom | Défaut | Description |
|---|---|---|
| `GOOGLE_SHEET_ID` | — | ID extrait de l'URL `…/spreadsheets/d/<ID>/edit` |
| `GOOGLE_SHEET_TAB` | `Sheet1` | Onglet du service régulier |
| `GOOGLE_SHEET_TAB_OCCASIONNEL` | `Sheet2` | Onglet du service occasionnel |
| `GOOGLE_SERVICE_ACCOUNT_FILE` | `/secrets/service-account.json` | Chemin (dans le conteneur) vers la clé JSON |
| `COL_DATE` / `COL_ALLER` / `COL_RETOUR` | `Date` / `Aller` / `Retour` | Colonnes Sheet1 |
| `COL_OCC_DATE`, `COL_OCC_HEURE_DEPART`, `COL_OCC_HEURE_ARRIVEE`, `COL_OCC_KM_DEPART`, `COL_OCC_KM_ARRIVEE`, `COL_OCC_KM_TOTAL`, `COL_OCC_ADULTES`, `COL_OCC_ENFANTS` | voir `.env.example` | Colonnes Sheet2 |
| `DATE_FORMAT` / `TIME_FORMAT` | `%Y-%m-%d` / `%H:%M` | Formats `strftime` |
| `TZ` | `Europe/Paris` | Fuseau horaire pour la détection matin/soir |
| `MORNING_CUTOFF_HOUR` | `12` | Heure locale en dessous de laquelle = Aller |
| `MAX_KM` | `9999999` | Plafond de validation du kilométrage |
| `MAX_PASSENGERS_OCC` | `99` | Plafond adultes/enfants par catégorie (service occasionnel) |
| `APP_PASSWORD` | — | Mot de passe d'accès à l'app |
| `SESSION_SECRET` | — | Clé pour signer les cookies (16+ caractères, random) |
| `SESSION_LIFETIME_DAYS` | `30` | Durée du cookie de session |

Générer un `SESSION_SECRET` :

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## 3. Déploiement Unraid

### Option A — Docker Compose (recommandé)

1. Sur le serveur, créer le dossier d'app :
   ```
   /mnt/user/appdata/pointage-bus/
   ├── secrets/
   │   └── service-account.json   ← votre clé Google
   ├── docker-compose.yml         ← copié depuis ce repo
   └── .env                       ← copié depuis .env.example, complété
   ```
2. Lancer :
   ```bash
   cd /mnt/user/appdata/pointage-bus
   docker compose up -d --build
   ```
3. Accéder à `http://<ip-unraid>:8088` depuis votre téléphone.

### Option B — Template Unraid "Add Container"

Réglages :
- **Repository** : `pointage-bus:latest` (après `docker build` sur Unraid),
  ou bien construisez l'image localement et chargez-la.
- **Network Type** : `Bridge`
- **Port** : Container `8088` → Host `8088`
- **Path** : Container `/secrets` → Host `/mnt/user/appdata/pointage-bus/secrets` (mode `RO`)
- **Variables** : remplir toutes celles du tableau ci-dessus.

---

## 4. Utilisation

Ouvrir l'app sur le téléphone, entrer le mot de passe (une fois, le cookie
reste 30 jours). La page d'accueil propose deux modes.

### 4.1 Service régulier (`/regulier`)
1. Taper le nombre de passagers, valider.
2. Le service est détecté selon l'heure :
   - avant `MORNING_CUTOFF_HOUR` → Aller
   - sinon → Retour
3. Pour forcer manuellement : ouvrir « Forcer le service (override) » et choisir
   Aller ou Retour avant de valider.
4. Pour corriger la dernière saisie : utiliser le second formulaire qui apparaît
   après chaque enregistrement.

### 4.2 Service occasionnel (`/occasionnel`)
**À la montée** :
1. Vérifier date et heure de départ (pré-remplies, modifiables).
2. Lire le compteur kilométrique au démarrage et entrer la valeur.
3. Compter les passagers avec les boutons +/- (appui long pour accélérer).
4. « Enregistrer la montée » → une ligne brouillon est créée dans Sheet2.

Vous pouvez fermer l'app. À la réouverture, l'app détecte le trajet en cours
et propose directement la phase 2.

**À la descente** :
1. Vérifier l'heure d'arrivée (pré-remplie).
2. Lire et entrer le kilométrage d'arrivée.
3. « Terminer le trajet » → l'app calcule `Km total = Km arrivée - Km départ`
   et complète la ligne.

**Modifier la montée** : si vous avez fait une erreur à la phase 1, déplier
« Modifier les infos de montée » dans la page de descente.

**Abandonner** : bouton dédié au bas de la page de descente. La ligne est
supprimée de Sheet2 après confirmation.

---

## 5. Vérification

- Healthcheck : `curl http://<ip-unraid>:8088/healthz` doit renvoyer un objet
  avec les clés `sheet_regulier` et `sheet_occasionnel`, chacune contenant
  `tab` et `columns`. HTTP 503 si l'un des deux est mal configuré.
- Logs : `docker logs -f pointage-bus`.
- Si en-têtes mal nommés : la page d'accueil affiche un bandeau rouge listant
  les colonnes manquantes.

---

## 6. Sécurité

- L'app utilise un mot de passe simple et un cookie signé (HMAC). Suffisant
  pour un usage perso sur LAN.
- **N'exposez pas le port directement à Internet.** Si vous voulez y accéder
  hors LAN, mettez-la derrière un reverse proxy avec HTTPS (SWAG, Nginx Proxy
  Manager, Tailscale, etc.).
- Le fichier `service-account.json` ne doit jamais être commit ; il est
  ignoré par `.gitignore` et `.dockerignore`.

---

## 7. Développement local

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e .
cp .env.example .env  # puis compléter
uvicorn app.main:app --reload --port 8088
```
