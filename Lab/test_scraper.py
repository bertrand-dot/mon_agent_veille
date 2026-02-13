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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# --- 2. FONCTIONS DE LECTURE ---

def extraire_avec_suivi(url, type_source="Web"):
    """Extrait le contenu et mesure la performance."""
    start_time = time.time()
    try:
        # Utilisation de render=true et wait pour forcer ScraperAPI à travailler
        wait_time = 5000 if "linkedin" in url.lower() else 3000
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}&render=true&wait={wait_time}"
        
        res = requests.get(proxy_url, timeout=60)
        duration = round(time.time() - start_time, 2)
        
        if res.status_code != 200:
            return "", f"Erreur {res.status_code}", duration
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        if "linkedin.com" in url:
            # Extraction spécifique LinkedIn
            posts = [p.get_text().strip() for p in soup.find_all(['p', 'span']) if len(p.get_text().strip()) > 100]
            texte = " | ".join(list(set(posts))[:5])
        else:
            # Extraction Web
            for s in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): s.decompose()
            texte = soup.get_text(separator=' ')
            
        status = f"Succès ({len(texte)} chars)" if len(texte) > 100 else "Page vide (JS non chargé)"
        return texte[:18000], status, duration
    except Exception as e:
        return "", f"Erreur: {str(e)}", round(time.time() - start_time, 2)

# --- 3. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte, source):
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    MISSION : Qualifier ce signal pour {nom} (Source: {source}).
    CRITÈRES : Budget > 10M€ HT / Surfaces > 3000m²-5000m².
    ADN : Iconique, Bois, Waterfront, Résilience.
    FORMAT JSON : {{'projet':'nom', 'score_interne':0, 'analyse_ua':'60 mots', 'action':'conseil'}}
    DATA : {titre} | {texte[:8000]}"""
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        data = json.loads(resp.text.replace('```json', '').replace('```', '').strip())
        return data
    except: return None

# --- 4. MAIN ---

def main():
    leads = []
    logs_controle = []
    logging.info("🚀 Démarrage du Test Lab (Double Rapport)")

    try:
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
                    # On commence par lire la liste pour trouver 1 lien
                    raw_html, status_index, dur_index = extraire_avec_suivi(url_actu)
                    logs_controle.append({"organisme": nom, "type": "Index Web", "status": status_index, "duration": dur_index, "url": url_actu})
                    
                    if "Succès" in status_index:
                        soup = BeautifulSoup(raw_html, 'html.parser')
                        liens = [a for a in soup.find_all('a', href=True) if len(a.text.strip()) > 20]
                        if liens:
                            link = liens[0]['href']
                            if not link.startswith('http'): 
                                from urllib.parse import urljoin
                                link = urljoin(url_actu, link)
                            
                            txt, status_art, dur_art = extraire_avec_suivi(link)
                            logs_controle.append({"organisme": nom, "type": "Article Web", "status": status_art, "duration": dur_art, "url": link})
                            
                            if len(txt) > 400:
                                ana = qualifier_ia_ua(nom, liens[0].text.strip(), txt, "Web")
                                if ana and ana.get('score_interne', 0) >= 2:
                                    ana['url'] = link
                                    leads.append(ana)

                # B. SCAN LINKEDIN
                if url_linkedin:
                    logging.info(f"🔎 Scanning LinkedIn : {nom}")
                    txt_li, status_li, dur_li = extraire_avec_suivi(url_linkedin)
                    logs_controle.append({"organisme": nom, "type": "LinkedIn", "status": status_li, "duration": dur_li, "url": url_linkedin})
                    
                    if len(txt_li) > 200:
                        ana = qualifier_ia_ua(nom, "Derniers Posts", txt_li, "LinkedIn")
                        if ana and ana.get('score_interne', 0) >= 2:
                            ana['url'] = url_linkedin
                            leads.append(ana)

    except Exception as e:
        logging.error(f"❌ Erreur CSV : {e}")

    # --- ENVOI DES RAPPORTS ---
    
    # 1. Mail Opportunités
    if leads:
        html_leads = "<h2>🎯 Opportunités Qualifiées (Score >= 2)</h2>"
        for l in leads:
            html_leads += f"<div style='background:#f9f9f9; padding:15px; border-left:5px solid #27ae60; margin-bottom:10px;'><b>{l['autorite']}</b> : {l['projet']}<br>{l.get('analyse_ua', '')}<br><a href='{l['url']}'>Lien ↗</a></div>"
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], "subject": "🧪 LAB : Opportunités", "htmlContent": html_leads})

    # 2. Mail de Contrôle Technique (Systématique)
    html_ctrl = "<h2>🛠️ Rapport de Contrôle Technique</h2><table border='1' style='border-collapse:collapse; width:100%; font-size:11px;'>"
    html_ctrl += "<tr style='background:#eee;'><th>Organisme</th><th>Type</th><th>Durée</th><th>Statut</th><th>URL</th></tr>"
    for log in logs_controle:
        color = "green" if "Succès" in log['status'] else "red"
        html_ctrl += f"<tr><td>{log['organisme']}</td><td>{log['type']}</td><td>{log['duration']}s</td><td style='color:{color};'>{log['status']}</td><td><a href='{log['url']}'>Lien</a></td></tr>"
    html_ctrl += "</table>"
    requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], "subject": "🛠️ LAB : Contrôle Technique", "htmlContent": html_ctrl})

if __name__ == "__main__": main()
