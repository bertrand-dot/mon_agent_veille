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

# --- 2. EXTRACTION PROFONDE (WEB & PDF) ---

def extraire_contenu_profond(url):
    """Ouvre l'article, extrait le texte et scanne les PDF."""
    try:
        # Rendu JS léger pour les articles
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}&render=true"
        res = requests.get(proxy_url, timeout=45)
        if res.status_code != 200: return ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): s.decompose()
        
        texte = soup.get_text(separator=' ')
        
        # Scan PDF (bilans de ZAC, etc.)
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                pdf_url = a['href']
                if not pdf_url.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_url = urljoin(url, pdf_url)
                try:
                    pdf_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={pdf_url}")
                    doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                    texte += " [DOC PDF] " + "".join([p.get_text() for p in doc[:5]])
                except: continue
        
        return texte[:18000]
    except: return ""

# --- 3. SCRAPPING LINKEDIN ---

def extraire_posts_linkedin(url_linkedin):
    """Récupère le texte des derniers posts sur une page entreprise LinkedIn."""
    try:
        # LinkedIn nécessite impérativement render=true et une attente pour charger le flux
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_linkedin}&render=true&wait=5000"
        res = requests.get(proxy_url, timeout=60)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Sur les pages publiques, les posts sont souvent dans des balises 'p' ou des classes 'update-components'
        posts_found = []
        for update in soup.find_all(['p', 'span'], limit=50):
            txt = update.get_text().strip()
            if len(txt) > 100: # On cherche des vrais paragraphes de texte
                posts_found.append(txt)
        
        return " | ".join(list(set(posts_found))[:5]) # Retourne les 5 segments les plus longs
    except Exception as e:
        logging.error(f"Erreur LinkedIn : {e}")
        return ""

# --- 4. ANALYSE IA (PROMPT UA RESTAURÉ) ---

def qualifier_ia_ua(nom, titre, texte, source_type="Site Web"):
    """Qualification selon l'ADN et les seuils URBAN AGENCY."""
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal pour {nom} (Source: {source_type}) au regard de notre ADN.

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
        return data
    except: return None

# --- 5. MAIN ---

def main():
    leads = []
    logging.info("🚀 Lancement du Test Laser (Web + LinkedIn)")
    
    try:
        with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

            for row in reader:
                nom = row.get("Nom de l'Organisme", "").strip()
                url_actu = row.get("URL_Directe", "").strip()
                url_linkedin = row.get("LinkedIn_Cible", "").strip()
                
                if not nom: continue

                # A. SCAN SITE WEB
                if url_actu:
                    logging.info(f"🔎 Scanning Web : {nom}")
                    search_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_actu}&render=true&wait=5000"
                    res = requests.get(search_url, timeout=90)
                    soup = BeautifulSoup(res.text, 'html.parser')
                    
                    liens = [a for a in soup.find_all('a', href=True) if len(a.text.strip()) > 20]
                    for item in liens[:2]:
                        href = item['href'] if item['href'].startswith('http') else url_actu
                        txt = extraire_contenu_profond(href)
                        if len(txt) > 400:
                            ana = qualifier_ia_ua(nom, item.text.strip(), txt, "Web")
                            if ana and ana.get('score_interne', 0) >= 2:
                                ana['url'] = href
                                leads.append(ana)

                # B. SCAN LINKEDIN
                if url_linkedin:
                    logging.info(f"🔎 Scanning LinkedIn : {nom}")
                    txt_linkedin = extraire_posts_linkedin(url_linkedin)
                    if len(txt_linkedin) > 200:
                        ana = qualifier_ia_ua(nom, "Derniers posts LinkedIn", txt_linkedin, "LinkedIn")
                        if ana and ana.get('score_interne', 0) >= 2:
                            ana['url'] = url_linkedin
                            leads.append(ana)

    except Exception as e:
        logging.error(f"❌ Erreur : {e}")

    # --- 6. RAPPORT FINAL ---
    if leads:
        html = "<h2>Rapport Lab : Qualification Laser (Web + LinkedIn)</h2>"
        for l in leads:
            source_tag = "LinkedIn" if "linkedin.com" in l.get('url', '') else "Site Web"
            html += f"""
            <div style='border-left:4px solid #3498db; padding:15px; margin-bottom:20px; background:#f9f9f9;'>
                <small style='color:#666;'>SOURCE : {source_tag}</small>
                <h3>{l['autorite']} : {l['projet']}</h3>
                <p><b>Catégorie :</b> {l['categorie']} | <b>Score :</b> {l.get('score_interne', 0)}/5</p>
                <p>{l.get('analyse_ua', '')}</p>
                <p style='color:green;'><b>Action :</b> {l.get('action', '')}</p>
                <a href='{l['url']}'>Lien vers la source ↗</a>
            </div><hr>"""
            
        requests.post("https://api.brevo.com/v3/smtp/email", 
            json={"sender": {"name": "Lab Radar", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": "🧪 TEST LAB : Résultats Web + LinkedIn", "htmlContent": html}, 
            headers={"api-key": BREVO_KEY})
        logging.info("📧 Mail envoyé !")
    else:
        logging.info("∅ Aucun lead trouvé.")

if __name__ == "__main__": main()
