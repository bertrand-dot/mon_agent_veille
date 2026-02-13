import os
import requests
import json
import logging
import csv
import time
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from urllib.parse import urljoin

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- 2. FONCTIONS DE LECTURE WEB (ScraperAPI) ---

def extraire_web_profond(url):
    """Lecture des articles et PDF via ScraperAPI."""
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if res.status_code != 200: return "", f"Erreur {res.status_code}"
        
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): s.decompose()
        texte = soup.get_text(separator=' ')
        
        # Scan PDF
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                try:
                    pdf_url = urljoin(url, a['href'])
                    pdf_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={pdf_url}")
                    doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                    texte += " [DOC PDF] " + "".join([p.get_text() for p in doc[:5]])
                except: continue
        return texte[:18000], f"Succès ({len(texte)} chars)"
    except Exception as e:
        return "", str(e)

# --- 3. FONCTION LINKEDIN (SerpApi) ---

def recherche_linkedin_serpapi(nom_organisme, url_linkedin):
    """Utilise Google via SerpApi pour lire les actualités LinkedIn sans blocage."""
    try:
        # On demande à Google les résultats récents pour cette URL spécifique
        params = {
            "engine": "google",
            "q": f"site:{url_linkedin}",
            "api_key": SERPAPI_KEY,
            "num": 5
        }
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = res.json()
        
        snippets = []
        if "organic_results" in data:
            for result in data["organic_results"]:
                snippets.append(f"{result.get('title')} : {result.get('snippet')}")
        
        content = " | ".join(snippets)
        status = f"Succès ({len(snippets)} extraits)" if snippets else "Aucun résultat Google"
        return content, status
    except Exception as e:
        return "", str(e)

# --- 4. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte, source_url):
    if not client: return None
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    MISSION : Qualifier ce signal pour {nom}.
    CRITÈRES : Budget > 10M€ HT / Surfaces > 3000m²-5000m².
    FORMAT JSON : {{'projet':'nom', 'score_interne':0, 'analyse_ua':'60 mots', 'action':'conseil'}}
    DATA : {titre} | {texte[:8000]}"""
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        data = json.loads(resp.text.replace('```json', '').replace('```', '').strip())
        data['url'] = source_url
        data['autorite'] = nom
        return data
    except: return None

# --- 5. MAIN ---

def main():
    leads = []
    logs_controle = []
    
    with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

        for row in reader:
            nom = row.get("Nom de l'Organisme", "").strip()
            url_actu = row.get("URL_Directe", "").strip()
            url_li = row.get("LinkedIn_Cible", "").strip()
            if not nom: continue

            # A. WEB (ScraperAPI)
            if url_actu:
                logging.info(f"🔎 Web : {nom}")
                raw, status = extraire_web_profond(url_actu)
                logs_controle.append({"org": nom, "type": "Web", "status": status, "url": url_actu})
                if raw:
                    soup = BeautifulSoup(raw, 'html.parser')
                    liens = [a for a in soup.find_all('a', href=True) if len(a.get_text().strip()) > 25]
                    for art in liens[:2]:
                        full_art = urljoin(url_actu, art['href'])
                        txt_art, status_art = extraire_web_profond(full_art)
                        if txt_art:
                            ana = qualifier_ia_ua(nom, art.get_text(), txt_art, full_art)
                            if ana and ana.get('score_interne', 0) >= 2: leads.append(ana)

            # B. LINKEDIN (SerpApi)
            if url_li:
                logging.info(f"🔎 LinkedIn (via SerpApi) : {nom}")
                txt_li, status_li = recherche_linkedin_serpapi(nom, url_li)
                logs_controle.append({"org": nom, "type": "LinkedIn (SerpApi)", "status": status_li, "url": url_li})
                if txt_li:
                    ana = qualifier_ia_ua(nom, "Actualités Google/LinkedIn", txt_li, url_li)
                    if ana and ana.get('score_interne', 0) >= 2: leads.append(ana)

    # --- ENVOI RAPPORTS ---
    # (Logique d'envoi Brevo identique - Rapport technique + Opportunités)
    # [Code d'envoi simplifié ici pour la clarté]
    if BREVO_KEY:
        # Rapport de Contrôle
        html_ctrl = "<h2>🛠️ Contrôle Technique (Hybride Scraper/SerpApi)</h2><table border='1'>"
        for log in logs_controle:
            html_ctrl += f"<tr><td>{log['org']}</td><td>{log['type']}</td><td>{log['status']}</td></tr>"
        html_ctrl += "</table>"
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, "to":[{"email":"bertrand@urban-agency.com"}], "subject":"🛠️ LAB : Contrôle Hybride", "htmlContent":html_ctrl})
        
        # Rapport Opportunités
        if leads:
            html_leads = "<h2>🎯 Opportunités Qualifiées</h2>"
            for l in leads: html_leads += f"<p><b>{l['autorite']}</b> : {l['projet']}<br>{l.get('analyse_ua')}</p>"
            requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, "to":[{"email":"bertrand@urban-agency.com"}], "subject":"🧪 LAB : Résultats", "htmlContent":html_leads})

if __name__ == "__main__": main()
