import os
import requests
import json
import logging
import time
import csv
import fitz  # PyMuPDF
import io
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed

# --- 1. CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        logging.info("✅ Moteur Gemini 2.5 Pro activé.")
    except Exception as e:
        logging.error(f"❌ Erreur Gemini : {e}")

# --- 2. GESTION GÉOGRAPHIQUE ---

def obtenir_secteur_du_jour():
    config_jours = {
        0: {"file": "cibles_idf.csv", "name": "IDF", "emoji": "🗼"},
        1: {"file": "cibles_nord_est.csv", "name": "NORD-EST", "emoji": "🏭"},
        2: {"file": "cibles_nord_ouest.csv", "name": "NORD-OUEST", "emoji": "🌊"},
        3: {"file": "cibles_sud_ouest.csv", "name": "SUD-OUEST", "emoji": "🍷"},
        4: {"file": "cibles_sud_est.csv", "name": "SUD-EST", "emoji": "☀️"}
    }
    return config_jours.get(datetime.now().weekday(), config_jours[3])

def charger_cibles(nom_fichier):
    cibles = []
    if os.path.exists(nom_fichier):
        content = None
        for enc in ['utf-8-sig', 'latin-1', 'cp1252', 'utf-8']:
            try:
                with open(nom_fichier, mode='r', encoding=enc) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        if content:
            reader = csv.DictReader(io.StringIO(content))
            for row in reader:
                nom = row.get('Nom de l\'Organisme') or row.get('nom')
                if nom: cibles.append(nom.strip())
    return cibles

# --- 3. ANALYSE IA : STRUCTURE PROMPT ---

def analyser_opportunite(item, texte):
    if not client: return None
    date_du_jour = datetime.now().strftime("%d/%m/%Y")
    
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal français au regard de notre ADN.
    DATE DU JOUR : {date_du_jour}

    --- ADN VALORISÉ ---
    Iconique, Régénération friches, Densité qualitative, Construction Bois, Waterfront/Résilience.

    --- MATRICE DE CLASSEMENT ---
    1. SPRINT : Appel d'offre et appel à candidature de maitrise d'oeuvre / Appel à projet / AMI officiel. Deadline < 30j. Budget > 10M€ + architecte non designé.
    2. RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois.
    3. EXPLORATION : Innovation sur le territoire (Bas-carbone, réemploi, biodiversité). Designation d'un programmiste.
    4. RÉSEAU : Partenaire identifié ayant un interet pour URBAN AGENCY.

    --- RÈGLES D'EXCLUSION STRICTES ---
    1. NATURE DE MISSION : Rénovation énergétique isolée, mise aux normes seule, infrastructures pures, expertises.
    2. VOLUME : Budget < 10M€ HT. Surfaces < 3000m² (logement/tertiaire) ou < 5000m² (équipement).
    3. PROGRAMME : Micro-Équipements, Tertiaire proximité, Logement diffus < 15 lots.

    --- FILTRES DE SÉVÉRITÉ ---
    - ÉLIMINER si DATE DÉPASSÉE, si ARCHITECTE DÉJÀ DÉSIGNÉ, ou BRUIT INDUSTRIEL.
    - ÉLIMINER RÉSEAUX SOCIAUX (FB/IG). LinkedIn autorisé (posts < 6 mois).

    FORMAT JSON (Analyse 60-80 mots) :
    {{
      "projet": "Nom précis",
      "autorite": "Donneur d'ordre",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "deadline": "Date ou N/A",
      "matching_dna": "Lien ADN",
      "analyse_ua": "Analyse détaillée de l'enjeu architectural et urbain",
      "action": "Action concrète pour Bertrand"
    }}
    DATA : {item.get('title')} | {texte[:9000]}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        raw_text = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_text)
        if isinstance(data, list): data = data[0] if data else None
        if data:
            source_url = item.get('link', '').lower()
            if any(x in source_url for x in ["instagram.com", "facebook.com"]): return None
            data['url'] = item.get('link')
        return data
    except: return None

# --- 4. RECHERCHE & EXTRACTION ---

def chercher_serpapi(cible):
    resultats = []
    queries = [
        f'"{cible}" (site:.fr OR site:.gov.fr OR site:.org) (inurl:actualites OR inurl:presse OR délibération)',
        f'site:linkedin.com/posts/ "{cible}" (projet OR aménagement OR concours OR friche)'
    ]
    for q in queries:
        params = {"engine": "google", "q": q, "api_key": SERPAPI_KEY, "num": 12, "gl": "fr", "hl": "fr", "tbs": "qdr:y"}
        try:
            res = requests.get("https://serpapi.com/search", params=params, timeout=20).json().get("organic_results", [])
            resultats.extend(res)
        except: continue
    return resultats

def extraire_contenu(url):
    try:
        res = requests.get(url, timeout=12, headers={'User-Agent': 'Mozilla/5.0'})
        if res.status_code != 200: return ""
        if 'pdf' in res.headers.get('Content-Type', '').lower() or url.lower().endswith('.pdf'):
            doc = fitz.open(stream=res.content, filetype="pdf")
            text = "".join([p.get_text() for p in doc[:10]])
            doc.close()
            return text[:15000]
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'footer', 'header']): s.decompose()
        return soup.get_text(separator=' ')[:12000]
    except: return ""

def traiter_un_resultat(resultat, hist):
    url = resultat.get('link')
    if not url or url in hist: return None
    texte = extraire_contenu(url)
    if not texte: return None
    return analyser_opportunite(resultat, texte)

# --- 5. SYNTHÈSES SECTORISÉES ---

def generer_synthese(leads, secteur_name, mode="executif"):
    if not leads: return f"Veille active sur le secteur {secteur_name} : aucun dossier majeur qualifié ce jour."
    
    consigne = (
        f"Rédige une note tactique sur le marché {secteur_name} (3 puces max). Émojis. "
        "INTERDICTION : Pas de phrase d'introduction du type 'Voici la note'."
    ) if mode == "executif" else (
        f"Analyse prospective sur les tendances de {secteur_name} (3-4 lignes). Ton expert. "
        "INTERDICTION : Pas de phrase d'introduction."
    )
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=f"En tant qu'associé UA, {consigne}. Données : {json.dumps(leads)}")
        return resp.text.strip()
    except: return "Indisponible."

# --- 6. GESTION DES ARCHIVES SECTORISÉES ---

def mettre_a_jour_archive(nouveaux_leads, archive_file):
    archive = []
    if os.path.exists(archive_file):
        try:
            with open(archive_file, 'r') as f: archive = json.load(f)
        except: archive = []
    for l in nouveaux_leads:
        if not any(a.get('url') == l.get('url') for a in archive):
            archive.insert(0, l)
    with open(archive_file, 'w') as f: json.dump(archive[:50], f, indent=2)
    return archive[:20]

# --- 7. MAIN ---

def main():
    secteur = obtenir_secteur_du_jour()
    cibles = charger_cibles(secteur['file'])
    if not cibles: return
    
    # Silo par secteur pour l'archive
    archive_file = f"leads_archive_{secteur['name'].lower().replace('-', '_')}.json"
    
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    tous_resultats = []
    for cible in cibles:
        logging.info(f"🔎 Scan Sectorisé ({secteur['name']}) : {cible}")
        tous_resultats.extend(chercher_serpapi(cible))
    
    leads_du_jour = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(traiter_un_resultat, r, hist): r for r in tous_resultats}
        for future in as_completed(futures):
            res = future.result()
            if isinstance(res, dict) and res.get('score_interne', 0) >= 2:
                leads_du_jour.append(res)
                hist[res['url']] = {"date": datetime.now().strftime('%Y-%m-%d')}

    limit = 15 if secteur['name'] in ["IDF", "NORD-OUEST"] else 10
    top_leads = sorted(leads_du_jour, key=lambda x: x.get('score_interne', 0), reverse=True)[:limit]
    
    archive_20 = mettre_a_jour_archive(leads_du_jour, archive_file)
    res_exec = generer_synthese(top_leads, secteur['name'], "executif")
    res_strat = generer_synthese(leads_du_jour, secteur['name'], "strat")

    # (Logique d'envoi Brevo utilisant res_exec, res_strat, top_leads et archive_20...)
    # ...
    
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
