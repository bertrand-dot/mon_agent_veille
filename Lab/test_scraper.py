import os
import requests
import json
import logging
import csv
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# --- 2. EXTRACTION PROFONDE (WEB + PDF) ---

def extraire_contenu_profond(url):
    """Ouvre l'article, extrait le texte et scanne les PDF."""
    try:
        # On utilise ScraperAPI sans rendu pour les articles pour économiser du temps
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}"
        res = requests.get(proxy_url, timeout=30)
        if res.status_code != 200: return ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        # Nettoyage
        for s in soup(['nav', 'footer', 'script', 'style', 'header']): s.decompose()
        
        texte = soup.get_text(separator=' ')
        
        # Scan des PDF (stratégique pour les bilans de concertation)
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                pdf_url = a['href']
                if not pdf_url.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_url = urljoin(url, pdf_url)
                try:
                    pdf_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={pdf_url}")
                    doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                    texte += " [DOCUMENT PDF] " + "".join([p.get_text() for p in doc[:5]])
                except: continue
        
        return texte[:18000]
    except: return ""

# --- 3. ANALYSE IA (PROMPT UA RESTAURÉ) ---

def qualifier_ia_ua(nom, titre, texte):
    """Qualification selon l'ADN et les seuils URBAN AGENCY."""
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal pour {nom} au regard de notre ADN.

    --- ADN VALORISÉ ---
    Iconique, Régénération friches, Densité qualitative, Construction Bois, Waterfront/Résilience.

    --- MATRICE DE CLASSEMENT ---
    1. SPRINT : Appel d'offre et candidature MOE / AMI officiel. Deadline < 30j. Budget > 10M€ + archi non désigné.
    2. RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois.
    3. EXPLORATION : Innovation (Bas-carbone, réemploi). Designation d'un programmiste.
    4. RÉSEAU : Partenaire identifié ayant un interet pour URBAN AGENCY.

    --- RÈGLES D'EXCLUSION STRICTES ---
    1. NATURE : Rénovation énergétique isolée, PMR, infrastructures pures, expertises/études de sol.
    2. VOLUME : Budget < 10M€ HT. Surfaces < 3000m² (logement/tertiaire) ou < 5000m² (équipement).
    3. PROGRAMME : Micro-Équipements, Tertiaire proximité, Logement diffus < 15 lots.

    FORMAT JSON (Analyse 60-80 mots) :
    {{
      "projet": "Nom précis",
      "autorite": "{nom}",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "deadline": "Date ou N/A",
      "matching_dna": "Lien ADN",
      "analyse_ua": "Analyse détaillée de l'enjeu architectural et urbain",
      "action": "Action concrète pour Bertrand"
    }}
    DATA : {titre} | {texte}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        data = json.loads(resp.text.replace('```json', '').replace('```', '').strip())
        if isinstance(data, list): data = data[0]
        return data
    except Exception as e:
        logging.error(f"Erreur IA : {e}")
        return None

# --- 4. MAIN ---

def main():
    leads = []
    logging.info("🚀 Démarrage du Test Laser (Mode Rendu Activé)")
    
    try:
        with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
            sample = f.read(2048)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample)
            reader = csv.DictReader(f, dialect=dialect)
            reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

            for row in reader:
                nom = row.get("Nom de l'Organisme", "").strip()
                url_actu = row.get("URL_Directe", "").strip()
                if not nom or not url_actu: continue

                logging.info(f"🔎 Scanning source : {nom}")
                
                # Correction : Ajout de render=true pour charger les contenus dynamiques (25 crédits)
                search_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_actu}&render=true"
                res = requests.get(search_url, timeout=45)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                # Détection de liens avec au moins 20 caractères
                liens = [a for a in soup.find_all('a', href=True) if len(a.text.strip()) > 20]
                logging.info(f"   -> {len(liens)} liens potentiels trouvés.")
                
                processed_urls = set()
                for lien in liens:
                    full_url = lien['href'] if lien['href'].startswith('http') else url_actu
                    if full_url in processed_urls: continue
                    processed_urls.add(full_url)
                    
                    txt = extraire_contenu_profond(full_url)
                    if len(txt) > 300:
                        ana = qualifier_ia_ua(nom, lien.text.strip(), txt)
                        # On ne garde que les leads qui matchent nos scores UA
                        if ana and ana.get('score_interne', 0) >= 2:
                            ana['url'] = full_url
                            leads.append(ana)
                            logging.info(f"   ✅ Lead Qualifié : {ana['projet']} (Score: {ana['score_internal'] if 'score_internal' in ana else ana.get('score_interne')})")
                            if len(leads) >= 10: break # Limite de test
                
    except Exception as e:
        logging.error(f"❌ Erreur CSV : {e}")

    # --- 5. ENVOI DU RAPPORT ---
    if leads:
        html = "<h2>Rapport Lab : Qualification Laser UA</h2>"
        for l in leads:
            score = l.get('score_interne', 0)
            html += f"""
            <div style='border-left:4px solid #f1c40f; padding:15px; margin-bottom:20px; background:#fafafa;'>
                <h3>{l['autorite']} : {l['projet']}</h3>
                <p><b>Catégorie :</b> {l['categorie']} | <b>Score :</b> {score}/5</p>
                <p><b>Analyse UA :</b> {l['analyse_ua']}</p>
                <p style='color:green;'><b>Action :</b> {l['action']}</p>
                <a href='{l['url']}'>Source Documentaire ↗</a>
            </div><hr>"""
            
        requests.post("https://api.brevo.com/v3/smtp/email", 
            json={"sender": {"name": "Lab Radar", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": "🧪 TEST LAB : Résultats UA Laser", "htmlContent": html}, 
            headers={"api-key": BREVO_KEY})
        logging.info("📧 Rapport envoyé avec succès !")
    else:
        logging.info("∅ Aucun lead trouvé répondant aux critères UA.")

if __name__ == "__main__": main()
