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

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None

# Configuration des logs pour voir les détails dans GitHub Actions
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Vérification de sécurité pour la clé API
if not SCRAPER_KEY:
    logging.error("❌ La clé SCRAPERAPI_KEY est manquante dans les variables d'environnement.")

# --- 2. FONCTIONS DE LECTURE ---

def extraire_avec_suivi(url, source_type="Web"):
    """Extrait le contenu et mesure la performance."""
    start_time = time.time()
    
    # Vérification de la clé avant l'appel
    if not SCRAPER_KEY:
        return "", "Clé API manquante", 0
    
    try:
        # Paramètres ScraperAPI : rendu JS + attente pour les sites dynamiques
        wait_time = 5000 if "linkedin" in url.lower() else 3000
        proxy_url = "https://api.scraperapi.com/"
        params = {
            'api_key': SCRAPER_KEY,
            'url': url,
            'render': 'true',
            'wait': wait_time
        }
        
        res = requests.get(proxy_url, params=params, timeout=60)
        duration = round(time.time() - start_time, 2)
        
        if res.status_code != 200:
            return "", f"Erreur {res.status_code}", duration
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        if "linkedin.com" in url:
            posts = [p.get_text().strip() for p in soup.find_all(['p', 'span']) if len(p.get_text().strip()) > 100]
            texte = " | ".join(list(set(posts))[:5])
        else:
            for s in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): s.decompose()
            texte = soup.get_text(separator=' ')
            
        status = f"Succès ({len(texte)} chars)" if len(texte) > 150 else "Page vide ou trop courte"
        return texte[:18000], status, duration
        
    except Exception as e:
        return "", f"Exception: {str(e)}", round(time.time() - start_time, 2)

# --- 3. ANALYSE IA ---

def qualifier_ia_ua(nom, titre, texte, source):
    if not client: return None
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    MISSION : Qualifier ce signal pour {nom} (Source: {source}).
    CRITÈRES : Budget > 10M€ HT / Surfaces > 3000m²-5000m².
    FORMAT JSON : {{'projet':'nom', 'score_interne':0, 'analyse_ua':'60 mots', 'action':'conseil'}}
    DATA : {titre} | {texte[:8000]}"""
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return json.loads(resp.text.replace('```json', '').replace('```', '').strip())
    except: return None

# --- 4. MAIN ---

def main():
    leads = []
    logs_controle = []
    logging.info("🚀 Démarrage du Test Lab (Version 2.0 - Correctif 401)")

    try:
        # Encodage cp1252 pour lire votre CSV Windows sans erreur d'accents
        with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

            for row in reader:
                nom = row.get("Nom de l'Organisme", "").strip()
                url_actu = row.get("URL_Directe", "").strip()
                url_linkedin = row.get("LinkedIn_Cible", "").strip()
                if not nom: continue

                # A. SCAN WEB
                if url_actu:
                    logging.info(f"🔎 Scanning Web : {nom}")
                    raw_html, status_index, dur_index = extraire_avec_suivi(url_actu)
                    logs_controle.append({"org": nom, "type": "Index Web", "status": status_index, "dur": dur_index, "url": url_actu})
                    
                    if "Succès" in status_index:
                        soup = BeautifulSoup(raw_html, 'html.parser')
                        liens = [a for a in soup.find_all('a', href=True) if len(a.text.strip()) > 20]
                        if liens:
                            link = liens[0]['href']
                            if not link.startswith('http'): 
                                from urllib.parse import urljoin
                                link = urljoin(url_actu, link)
                            
                            txt, status_art, dur_art = extraire_avec_suivi(link)
                            logs_controle.append({"org": nom, "type": "Article Web", "status": status_art, "dur": dur_art, "url": link})
                            
                            if len(txt) > 400:
                                ana = qualifier_ia_ua(nom, liens[0].text.strip(), txt, "Web")
                                if ana and ana.get('score_interne', 0) >= 2:
                                    ana['url'] = link
                                    leads.append(ana)

                # B. SCAN LINKEDIN
                if url_linkedin:
                    logging.info(f"🔎 Scanning LinkedIn : {nom}")
                    txt_li, status_li, dur_li = extraire_avec_suivi(url_linkedin)
                    logs_controle.append({"org": nom, "type": "LinkedIn", "status": status_li, "dur": dur_li, "url": url_linkedin})
                    
                    if len(txt_li) > 200:
                        ana = qualifier_ia_ua(nom, "Derniers Posts", txt_li, "LinkedIn")
                        if ana and ana.get('score_interne', 0) >= 2:
                            ana['url'] = url_linkedin
                            leads.append(ana)

    except Exception as e:
        logging.error(f"❌ Erreur critique CSV : {e}")

    # --- 5. ENVOI DES RAPPORTS ---
    
    # Rapport Technique
    html_ctrl = "<h2>🛠️ Rapport de Contrôle Technique</h2><table border='1' style='border-collapse:collapse; width:100%; font-size:11px;'>"
    html_ctrl += "<tr style='background:#eee;'><th>Organisme</th><th>Type</th><th>Durée</th><th>Statut</th><th>URL</th></tr>"
    for log in logs_controle:
        color = "green" if "Succès" in log['status'] else "red"
        html_ctrl += f"<tr><td>{log['org']}</td><td>{log['type']}</td><td>{log['dur']}s</td><td style='color:{color};'>{log['status']}</td><td>{log['url']}</td></tr>"
    html_ctrl += "</table>"
    
    if BREVO_KEY:
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
            json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], 
            "subject": "🛠️ LAB : Contrôle Technique", "htmlContent": html_ctrl})

    # Rapport Opportunités
    if leads and BREVO_KEY:
        html_leads = "<h2>🎯 Opportunités Qualifiées</h2>"
        for l in leads:
            html_leads += f"<div style='background:#f9f9f9; padding:15px; border-left:5px solid #27ae60; margin-bottom:10px;'><b>{l['autorite']}</b> : {l['projet']}<br>{l.get('analyse_ua', '')}<br><a href='{l['url']}'>Lien ↗</a></div>"
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
            json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], 
            "subject": "🧪 LAB : Opportunités", "htmlContent": html_leads})

if __name__ == "__main__": main()
