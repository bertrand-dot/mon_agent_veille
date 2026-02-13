import os
import requests
import json
import logging
import csv
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def extraire_contenu_profond(url):
    """Ouvre l'article, extrait le texte et scanne les PDF (Coût: 1 crédit)."""
    try:
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}"
        res = requests.get(proxy_url, timeout=30)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Texte Web
        for s in soup(['nav', 'footer', 'script', 'style', 'header']): s.decompose()
        texte = soup.get_text(separator=' ')
        
        # Détection et lecture des PDF liés
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                pdf_url = a['href']
                if not pdf_url.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_url = urljoin(url, pdf_url)
                try:
                    pdf_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={pdf_url}")
                    doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                    texte += " [PDF CONTENT] " + "".join([p.get_text() for p in doc[:5]])
                except: continue
        return texte[:15000]
    except: return ""

def qualifier_lead(nom, titre, texte):
    """Analyse IA avec vos critères de surface et budget."""
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    Évalue ce signal pour {nom}. 
    CRITÈRES : Budget > 10M€ HT ET (Surfaces > 3000m² ou > 5000m² équipement).
    
    FORMAT JSON :
    {{
      "projet": "Nom précis",
      "score": "X/5",
      "analyse": "Analyse tactique 60 mots",
      "action": "Conseil pour Bertrand"
    }}
    DATA : {titre} | {texte}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return json.loads(resp.text.replace('```json', '').replace('```', '').strip())
    except: return None

def main():
    leads_trouves = []
    # On lit le fichier CSV du Lab
    with open('lab/test_cibles.csv', mode='r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row['Nom de l\'Organisme']
            url_actu = row['URL_Directe']
            
            logging.info(f"🔎 Scan Laser de {nom}...")
            # 1. On récupère les derniers liens d'actualités
            res_list = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_actu}")
            soup_list = BeautifulSoup(res_list.text, 'html.parser')
            
            for a in soup_list.find_all('a', href=True)[:3]: # Test sur les 3 derniers
                link = a['href']
                if link.startswith('/'): 
                    from urllib.parse import urljoin
                    link = urljoin(url_actu, link)
                
                # 2. On "entre" dans l'article et on lit tout (PDF inclus)
                txt = extraire_contenu_profond(link)
                if len(txt) > 200:
                    ana = qualifier_lead(nom, a.text, txt)
                    if ana:
                        ana['url'] = link
                        ana['autorite'] = nom
                        leads_trouves.append(ana)

    # 3. Envoi du rapport de test par mail
    if leads_trouves:
        html = "<h2>Rapport de Test Lab - Laser Scraping</h2>"
        for l in leads_trouves:
            html += f"<p><b>{l['autorite']}</b> : {l['projet']} (Score: {l['score']})<br>{l['analyse']}<br><a href='{l['url']}'>Voir la source</a></p><hr>"
        
        requests.post("https://api.brevo.com/v3/smtp/email", 
            json={"sender": {"name": "Lab Radar", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": "🧪 Test Lab : Résultats Laser", "htmlContent": html}, 
            headers={"api-key": BREVO_KEY})
        logging.info("📧 Mail de test envoyé !")

if __name__ == "__main__": main()
