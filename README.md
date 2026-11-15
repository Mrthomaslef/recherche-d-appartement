<img src="assets/icon.svg" width="64" height="64" alt="">

# Appart côté Bois

Recherche de location pour Thomas & Marie : **Paris 12e côté bois, Saint-Mandé, Vincennes côté château, Charenton-le-Pont**.

- App : https://mrthomaslef.github.io/recherche-d-appartement/
- Sources : SeLoger / Logic-Immo (même catalogue), Bien'ici, PAP (particuliers)
- Collecte automatique 2×/jour (GitHub Actions `scrape.yml`) → `data/listings.json` + `data/embedded_data.js`
- Carte avec date de publication, filtres, favoris, bouton « Candidater » (SMS prérempli ou message copié + annonce ouverte), profils Thomas / Marie stockés uniquement sur l'appareil.

Lancer à la main :

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python scripts/scrape.py
```
