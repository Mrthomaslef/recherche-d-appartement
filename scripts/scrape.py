#!/usr/bin/env python3
"""Collecte des annonces de location (Paris 12e côté bois, Saint-Mandé,
Vincennes côté château, Charenton-le-Pont).

Sources : Logic-Immo (même catalogue que SeLoger), Bien'ici, PAP (particuliers).
Sortie : data/listings.json + data/embedded_data.js (window.APPART_DATA).

Usage : .venv/bin/python scripts/scrape.py
"""
from __future__ import annotations

import html
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from curl_cffi import requests

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT_JSON = DATA / "listings.json"
OUT_JS = DATA / "embedded_data.js"

# Critères larges : l'app affine ensuite (budget, pièces, surface).
MIN_ROOMS = 3
MIN_SURFACE = 55
MAX_PRICE = 3200

COMMUNES = {
    "75012": {"name": "Paris 12e", "li": "AD09FR37", "bi": "-9525", "pap": "paris-12e-g37779"},
    "94160": {"name": "Saint-Mandé", "li": "AD08FR36708", "bi": "-108318", "pap": "saint-mande-94160-g43350"},
    "94300": {"name": "Vincennes", "li": "AD08FR36720", "bi": "-108346", "pap": "vincennes-94300-g43370"},
    "94220": {"name": "Charenton-le-Pont", "li": "AD08FR36683", "bi": "-104868", "pap": "charenton-le-pont-94220-g43354"},
}

HEADERS = {"Accept-Language": "fr-FR,fr;q=0.9"}
SESSION = requests.Session(impersonate="safari")

MONTHS = {m: i + 1 for i, m in enumerate(
    ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
     "septembre", "octobre", "novembre", "décembre"])}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def get(url, **kw):
    for attempt in range(3):
        try:
            r = SESSION.get(url, headers=HEADERS, timeout=30, **kw)
            if r.status_code == 200:
                return r
            log(f"  HTTP {r.status_code} {url[:100]}")
        except Exception as e:  # réseau
            log(f"  ERR {e} {url[:100]}")
        time.sleep(2 + attempt * 3)
    return None


def ufrn(text, script_id):
    m = re.search(rf'<script id="{script_id}"[^>]*>(.*?)</script>', text, re.S)
    if not m:
        return None
    s = m.group(1)
    return json.loads(json.loads(s[s.find("JSON.parse(") + 11: s.rfind(")")]))


def num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    v = str(v).replace(" ", "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", v)
    return float(m.group()) if m else None


def clean_phone(p):
    if not p:
        return None
    first = re.split(r"[/;,]", p)[0]
    digits = re.sub(r"\D", "", first)
    if digits.startswith("33"):
        digits = "0" + digits[2:]
    return digits if len(digits) == 10 else None


# --------------------------------------------------------------- Logic-Immo
def scrape_logicimmo(prev):
    ids = ",".join(c["li"] for c in COMMUNES.values())
    base = (f"https://www.logic-immo.com/classified-search?distributionTypes=Rent&estateTypes=Apartment"
            f"&locations={ids}&priceMax={MAX_PRICE}&numberOfRoomsMin={MIN_ROOMS}&spaceMin={MIN_SURFACE}"
            f"&projectTypes=Stock&order=DateDesc")
    out = []
    for page in range(1, 15):
        r = get(base + (f"&page={page}" if page > 1 else ""))
        if not r:
            break
        d = (ufrn(r.text, "__UFRN_FETCHER__") or {}).get("data", {}).get("classified-serp-data")
        if not d:
            break
        ids_page = d.get("classifieds") or []
        if not ids_page:
            break
        enriched = d.get("enrichedClassifiedsData", {})
        for cid in ids_page:
            c = d["classifiedsData"].get(cid)
            if not c or enriched.get(cid, {}).get("isSuggestion"):
                continue
            raw = c.get("rawData", {})
            addr = c.get("location", {}).get("address", {})
            facts = {f["type"]: f for f in c.get("hardFacts", {}).get("facts", [])}
            floor = facts.get("numberOfFloors", {}).get("label")
            prov = c.get("provider", {})
            imgs = [i.get("url") for i in (c.get("gallery", {}).get("images") or []) if i.get("url")]
            price_info = c.get("hardFacts", {}).get("price", {})
            out.append({
                "id": f"li-{cid}",
                "source": "SeLoger / Logic-Immo",
                "url": f"https://www.seloger.com/annonce/location/ile-de-france/paris-75/paris-75000/{cid}",
                "altUrl": c.get("url"),
                "price": raw.get("price"),
                "chargesIncluded": "charges comprises" in (price_info.get("additionalInformation") or ""),
                "surface": (raw.get("surface") or {}).get("main"),
                "rooms": raw.get("nbroom"),
                "bedrooms": raw.get("nbbedroom"),
                "zip": addr.get("zipCode"),
                "city": addr.get("city"),
                "district": addr.get("district"),
                "floor": floor,
                "energy": c.get("energyClass"),
                "title": (c.get("mainDescription") or {}).get("headline") or c.get("hardFacts", {}).get("title"),
                "description": (c.get("mainDescription") or {}).get("description"),
                "photo": imgs[0] if imgs else None,
                "photos": imgs[:6],
                "published": (c.get("metadata") or {}).get("creationDate"),
                "updated": (c.get("metadata") or {}).get("updateDate"),
                "agency": (prov.get("intermediaryCard") or {}).get("title"),
                "privateOwner": bool(prov.get("isPrivateOwner")),
                "exclusive": bool((c.get("tags") or {}).get("isExclusive")),
                "_cid": cid,
            })
        total = d.get("totalCount") or 0
        if page * 25 >= total:
            break
        time.sleep(1.5)

    # Détail : coordonnées GPS + téléphone (seulement pour les nouvelles annonces)
    for it in out:
        old = prev.get(it["id"])
        if old and old.get("lat") is not None:
            for k in ("lat", "lng", "phone", "addressPublished"):
                it[k] = old.get(k)
            continue
        r = get(it["altUrl"])
        if r:
            d = ufrn(r.text, "__UFRN_LIFECYCLE_SERVERREQUEST__") or {}
            c = (d.get("app_cldp") or {}).get("data", {}).get("classified") or {}
            loc = (c.get("sections") or {}).get("location") or {}
            coords = (loc.get("geometry") or {}).get("coordinates")
            while isinstance(coords, list) and coords and isinstance(coords[0], list):
                coords = coords[0]  # polygone flouté -> premier point
            if isinstance(coords, list) and len(coords) >= 2:
                it["lng"], it["lat"] = coords[0], coords[1]
                it["approxPosition"] = (loc.get("geometry") or {}).get("type") != "Point"
            it["addressPublished"] = loc.get("isAddressPublished")
            phones = ((c.get("contactSections") or {}).get("contactCard") or {}).get("phoneNumbers") or []
            it["phone"] = clean_phone(phones[0]) if phones else None
        time.sleep(1.0)
    for it in out:
        it.pop("_cid", None)
    log(f"Logic-Immo : {len(out)} annonces")
    return out


# ------------------------------------------------------------------ Bien'ici
def scrape_bienici(prev):
    filters = {
        "size": 200, "from": 0, "filterType": "rent", "propertyType": ["flat"],
        "minRoomsQuantity": MIN_ROOMS, "maxPrice": MAX_PRICE, "minArea": MIN_SURFACE,
        "sortBy": "publicationDate", "sortOrder": "desc", "onTheMarket": [True],
        "zoneIdsByTypes": {"zoneIds": [c["bi"] for c in COMMUNES.values()]},
    }
    r = get("https://www.bienici.com/realEstateAds.json", params={"filters": json.dumps(filters)})
    out = []
    if not r:
        return out
    for a in r.json().get("realEstateAds", []):
        pos = (a.get("blurInfo") or {}).get("position") or {}
        pub = a.get("publicationDate")
        if not pub or pub.startswith("1970"):
            pub = a.get("modificationDate")
        district = a.get("district")
        photos = [p.get("url") for p in (a.get("photos") or []) if p.get("url")]
        out.append({
            "id": f"bi-{a['id']}",
            "source": "Bien'ici",
            "url": f"https://www.bienici.com/annonce/{a['id']}",
            "price": a.get("price"),
            "chargesIncluded": True,
            "charges": a.get("charges"),
            "surface": a.get("surfaceArea"),
            "rooms": a.get("roomsQuantity"),
            "bedrooms": a.get("bedroomsQuantity"),
            "zip": a.get("postalCode"),
            "city": a.get("city"),
            "district": district.get("libelle") if isinstance(district, dict) else None,
            "floor": (f"{a['floor']}/{a['floorQuantity']}" if a.get("floor") is not None and a.get("floorQuantity")
                      else (str(a["floor"]) if a.get("floor") is not None else None)),
            "elevator": a.get("hasElevator"),
            "furnished": a.get("isFurnished"),
            "energy": a.get("energyClassification"),
            "title": a.get("title"),
            "description": (a.get("description") or "")[:600],
            "photo": photos[0] if photos else None,
            "photos": photos[:6],
            "published": pub,
            "updated": a.get("modificationDate"),
            "agency": None,
            "privateOwner": a.get("accountType") == "particulier",
            "agencyFee": a.get("agencyRentalFee"),
            "lat": pos.get("lat"),
            "lng": pos.get("lon"),
            "approxPosition": (a.get("blurInfo") or {}).get("type") != "point",
        })
    log(f"Bien'ici : {len(out)} annonces")
    return out


# ----------------------------------------------------------------------- PAP
def parse_pap_date(s):
    m = re.search(r"(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", s or "")
    if not m or m.group(2) not in MONTHS:
        return None
    return f"{m.group(3)}-{MONTHS[m.group(2)]:02d}-{int(m.group(1)):02d}T08:00:00Z"


def strip(s):
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def scrape_pap(prev):
    urls = set()
    for zipc, c in COMMUNES.items():
        for page in range(1, 4):
            u = (f"https://www.pap.fr/annonce/locations-appartement-{c['pap']}"
                 f"-jusqu-a-{MAX_PRICE}-euros-a-partir-de-{MIN_SURFACE}-m2" + (f"-{page}" if page > 1 else ""))
            r = get(u)
            if not r:
                break
            found = [h for h in re.findall(r'href="(/annonces/appartement-[^"]+-r\d+)"', r.text) if zipc in h]
            new = set(found) - urls
            urls |= new
            if not new or "pagination" not in r.text:
                break
            time.sleep(1.2)
    out = []
    for path in sorted(urls):
        pid = "pap-" + path.rsplit("-r", 1)[1]
        old = prev.get(pid)
        if old:
            out.append(old)
            continue
        r = get("https://www.pap.fr" + path)
        time.sleep(1.0)
        if not r:
            continue
        t = r.text
        head = strip(t[t.find('class="item-title-container"'):][:1500])
        m_rooms = re.search(r"(\d+)\s*pièces?", head)
        m_surf = re.search(r"(\d+(?:[.,]\d+)?)\s*m²", head)
        m_price = re.search(r"([\d.\s]+)\s*€", head)
        m_city = re.search(r"m²\s+(.+?\(\d{5}\))", head)
        center = re.search(r'data-thunderforest="[^"]*center&quot;:\[&quot;([\d.]+)&quot;,&quot;([\d.]+)', t)
        tel = re.search(r'href="tel:([^"]+)"', t)
        desc_i = t.find('class="margin-bottom-30"><p>')
        desc = strip(t[desc_i: desc_i + 2500])[:600] if desc_i > 0 else None
        photos = re.findall(r'(https://cdn\.pap\.fr/photos/pap/[^"\s]+\.(?:jpg|webp))', t)
        tags = strip(t[t.find('class="item-tags'):][:600])
        m_bed = re.search(r"(\d+)\s*chambres?", tags)
        price = num(m_price.group(1).replace(".", "")) if m_price else None
        rooms = int(m_rooms.group(1)) if m_rooms else None
        surface = num(m_surf.group(1)) if m_surf else None
        if (rooms and rooms < MIN_ROOMS) or (surface and surface < MIN_SURFACE) or (price and price > MAX_PRICE):
            continue
        city_label = m_city.group(1) if m_city else None
        zipc = re.search(r"(\d{5})", path).group(1)
        out.append({
            "id": pid,
            "source": "PAP (particulier)",
            "url": "https://www.pap.fr" + path,
            "price": price,
            "chargesIncluded": True,
            "surface": surface,
            "rooms": rooms,
            "bedrooms": int(m_bed.group(1)) if m_bed else None,
            "zip": zipc,
            "city": re.sub(r"\s*\(\d{5}\)", "", city_label) if city_label else COMMUNES.get(zipc, {}).get("name"),
            "district": None,
            "title": head.split("€")[0][:120] if head else None,
            "description": desc,
            "photo": photos[0] if photos else None,
            "photos": list(dict.fromkeys(photos))[:6],
            "published": parse_pap_date(head),
            "agency": "Particulier",
            "privateOwner": True,
            "phone": clean_phone(tel.group(1)) if tel else None,
            "lat": float(center.group(1)) if center else None,
            "lng": float(center.group(2)) if center else None,
        })
    log(f"PAP : {len(out)} annonces")
    return out


# ------------------------------------------------------------- Post-traitement
def in_sector(it):
    """Secteur cible : 12e côté bois, Saint-Mandé, Vincennes côté château, Charenton."""
    lat, lng, z = it.get("lat"), it.get("lng"), it.get("zip")
    if z in ("94160", "94220"):
        return True
    if lat is None or lng is None:
        return None  # inconnu
    if z == "75012":
        return lng >= 2.392  # à l'est de Daumesnil / Picpus : Bel-Air, Bizot, Porte Dorée, Fécamp
    if z == "94300":
        return lat <= 48.8490  # sud de Vincennes (château, bois, Diderot) vs nord (Vignerons, Rigollots)
    return None


def dedupe(items):
    """Fusionne la même annonce publiée sur plusieurs sites."""
    kept = []
    for it in items:
        dup = None
        for k in kept:
            if (k["id"].split("-")[0] != it["id"].split("-")[0] and k.get("zip") == it.get("zip") and k.get("price") and it.get("price") and k.get("surface")
                    and it.get("surface") and abs(k["price"] - it["price"]) <= 15
                    and abs(k["surface"] - it["surface"]) <= 1.0 and k.get("rooms") == it.get("rooms")):
                dup = k
                break
        if dup:
            dup.setdefault("alsoOn", []).append({"source": it["source"], "url": it["url"]})
            for f in ("lat", "lng", "phone", "photo", "district", "agency", "description"):
                if not dup.get(f) and it.get(f):
                    dup[f] = it[f]
            if dup.get("approxPosition") and it.get("lat") and not it.get("approxPosition"):
                dup["lat"], dup["lng"], dup["approxPosition"] = it["lat"], it["lng"], False
            pubs = [p for p in (dup.get("published"), it.get("published")) if p]
            dup["published"] = min(pubs) if pubs else None
        else:
            kept.append(it)
    return kept


def main():
    DATA.mkdir(exist_ok=True)
    prev_list = json.loads(OUT_JSON.read_text())["listings"] if OUT_JSON.exists() else []
    prev = {}
    for p in prev_list:
        prev[p["id"]] = p
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    items, errors = [], []
    for name, fn in (("Logic-Immo", scrape_logicimmo), ("PAP", scrape_pap), ("Bien'ici", scrape_bienici)):
        try:
            items += fn(prev)
        except Exception as e:
            log(f"!! {name} : {e}")
            errors.append(name)

    def relevant(i):
        if i.get("zip") not in COMMUNES:
            return False
        if i.get("rooms") and i["rooms"] < MIN_ROOMS:
            return False
        if i.get("surface") and (i["surface"] < MIN_SURFACE or i["surface"] > 250):
            return False
        # colocations / chambres : loyer anormalement bas pour la surface
        if i.get("price") and i.get("surface") and i["price"] / i["surface"] < 14:
            return False
        return True

    items = [i for i in items if relevant(i)]
    items = dedupe(items)
    for it in items:
        old = prev.get(it["id"])
        it["firstSeen"] = (old or {}).get("firstSeen") or now
        if old and old.get("price") and it.get("price") and it["price"] < old["price"]:
            it["priceDrop"] = old["price"] - it["price"]
        elif old and old.get("priceDrop"):
            it["priceDrop"] = old["priceDrop"]
        it["inSector"] = in_sector(it)
        it["pricePerM2"] = round(it["price"] / it["surface"], 1) if it.get("price") and it.get("surface") else None
        it.pop("altUrl", None) if it.get("url") else None

    # Si une source a planté, on garde ses anciennes annonces plutôt que de les perdre.
    if errors:
        seen = {i["id"] for i in items}
        for p in prev_list:
            if p["id"] not in seen and any(p["source"].startswith(e.split("-")[0]) for e in errors):
                items.append(p)

    items.sort(key=lambda i: i.get("published") or i["firstSeen"], reverse=True)
    payload = {"updated": now, "count": len(items), "criteria": {
        "minRooms": MIN_ROOMS, "minSurface": MIN_SURFACE, "maxPrice": MAX_PRICE,
        "communes": {k: v["name"] for k, v in COMMUNES.items()}}, "errors": errors, "listings": items}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    OUT_JS.write_text("window.APPART_DATA = " + json.dumps(payload, ensure_ascii=False) + ";\n")
    log(f"Total : {len(items)} annonces (dans le secteur : {sum(1 for i in items if i['inSector'])})")


if __name__ == "__main__":
    main()
