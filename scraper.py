import os
import requests
import csv
import re
import json
from bs4 import BeautifulSoup
import fitz
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
import logging

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX")
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

def extraire_contenu(session, url):
    try:
        r = session.get(url, timeout=12)
        if 'pdf' in r.headers.get('Content-Type', '').lower():
            with fitz.open(stream=r.content, filetype="pdf") as doc:
                return "".join([p.get_text() for p in doc[:8]])
        soup = BeautifulSoup(r.text, 'html.parser')
        for t in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): t.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        return re.sub(r'\s+', ' ', main.get_text()).strip()
    except: return None

def est_page_pertinente(url, texte=""):
    """Filtre amélioré pour ignorer le bruit institutionnel"""
    exclure = ['carte-interactive', 'annuaire', 'mentions', 'cookies', 'qui-nous-sommes', 'gouvernance', 'histoire', 'contact', 'faq', 'recherche']
    url_lower = url.lower()
    if any(mot in url_lower for mot in exclure):
        return False
    return True

def recuperer_liens_projets(session, url_liste, racine):
    try:
        r = session.get(url_liste, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        liens = []
        # On cible les liens dans le contenu principal uniquement
        zone_contenu = soup.find('main') or soup.find('article') or soup
        for a in zone_contenu.find_all('a', href=True):
            full_url = urljoin(url_liste, a['href'])
            if urlparse(full_url).netloc == urlparse(racine).netloc:
                if est_page_pertinente(full_url) and len(full_url) > len(url_liste) + 3:
                    liens.append(full_url)
        return list(dict.fromkeys(liens))[:10]
    except: return []

def analyser_ia(texte, source):
    prompt = f"""RÔLE : Directeur Dév. Urban Agency. 
    ANALYSE de l'opportunité commerciale (aménagement/archi).
    SCORE : 3 (ZAC créée, Marché public, Concours), 2 (Étude, Concertation), 1 (Veille), 0 (Admin/Voeux).
    RETOURNE JSON : {{"titre": "...", "resume": "...", "chiffres": "...", "score": 0-3}}
    TEXTE : {texte[:12000]}"""
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

def envoyer_mail(forts, faibles):
    if not forts and not faibles: return
    
    def bloc(item, color):
        return f"""<div style="border-left:4px solid {color}; padding:10px; margin-bottom:10px; background:#fff;">
            <b style="font-size:14px;">{item['titre']}</b><br><small>{item['nom_source']}</small><br>
            <p style="font-size:12px;">{item['resume']}</p>
            <a href="{item['url']}" style="font-size:11px; color:{color}; font-weight:bold;">LIRE LA SOURCE →</a>
        </div>"""

    html_forts = "".join([bloc(x, "#e74c3c") for x in forts])
    html_faibles = "".join([bloc(x, "#3498db") for x in faibles])
    
    body = f"<html><body style='background:#f4f4f4; padding:20px;'><img src='{LOGO_URL}' height='40'><br>"
    if forts: body += f"<h2 style='color:#e74c3c;'>🔴 PRIORITÉS</h2>{html_forts}"
    if faibles: body += f"<h2 style='color:#3498db;'>🔵 SIGNAUX FAIBLES</h2>{html_faibles}"
    body += "</body></html>"

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"Veille UA : {len(forts)} Priorités", "htmlContent": body}, 
        headers={"api-key": BREVO_KEY})

def main():
    hist = charger_historique()
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    leads_forts, leads_faibles = [], []

    if not os.path.exists('cibles.csv'): return
    with open('cibles.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f, delimiter=';' if ';' in f.read(100) else ',')
        f.seek(0)
        next(reader)
        for row in reader:
            nom, url = row.get("Nom de l'Organisme"), row.get("URL Actualités / Projets")
            if not nom or not url: continue
            
            print(f"Analyse de {nom}...")
            # On vérifie d'abord l'URL principale
            liens = [url] + recuperer_liens_projets(session, url, url)
            
            for l in liens:
                if l in hist: continue
                txt = extraire_contenu(session, l)
                if txt and len(txt) > 400:
                    res = analyser_ia(txt, nom)
                    if res['score'] >= 1:
                        item = {"url": l, "nom_source": nom, **res}
                        if res['score'] == 3: leads_forts.append(item)
                        else: leads_faibles.append(item)
                    hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res['score']}
    
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)

if __name__ == "__main__": main()
