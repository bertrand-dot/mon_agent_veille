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

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX")
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

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
        for t in soup(['nav', 'footer', 'script', 'style', 'header']): t.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        return re.sub(r'\s+', ' ', main.get_text()).strip()
    except: return None

def recuperer_liens_projets(session, url_liste, racine):
    try:
        r = session.get(url_liste, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        liens_utiles = []
        # FILTRE : On ignore les pages institutionnelles statiques
        exclude = ['qui-nous-sommes', 'histoire', 'gouvernance', 'equipe', 'mentions', 'contact', 'plan-du-site', 'cookies']
        for a in soup.find_all('a', href=True):
            full_url = urljoin(url_liste, a['href'])
            if urlparse(full_url).netloc == urlparse(racine).netloc:
                if not any(ex in full_url.lower() for ex in exclude):
                    if len(full_url) > len(url_liste) + 3:
                        liens_utiles.append(full_url)
        return list(dict.fromkeys(liens_utiles))[:6]
    except: return []

def analyser_ia(texte, source):
    prompt = f"""RÔLE : Directeur Dév. Urban Agency. 
    SCORE : 3 (ZAC créée, Concours, Marché public), 2 (Étude urbaine, Concertation, Plan Guide), 1 (Veille), 0 (Admin/RH).
    RETOURNE JSON : {{"titre": "...", "theme": "...", "resume": "...", "chiffres": "...", "score": 0-3}}
    TEXTE : {texte[:12000]}"""
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

def bloc_html(item, color):
    badge = "🔥 PRIORITÉ" if item['score'] == 3 else "⚡ SIGNAL"
    return f"""<div style="border-left: 4px solid {color}; background:#ffffff; padding:15px; margin-bottom:15px; font-family:Arial;">
        <div style="font-size:10px; color:#95a5a6; font-weight:bold;">{item['nom_source']} | {badge}</div>
        <div style="font-weight:bold; color:#2c3e50; font-size:15px;">{item['titre']}</div>
        <div style="font-size:13px; color:#555;">{item['resume']}</div>
        <div style="text-align:right;"><a href="{item['url']}" style="color:{color}; font-size:11px; font-weight:bold;">SOURCE →</a></div>
    </div>"""

def envoyer_mail(forts, faibles):
    if not forts and not faibles: return
    html_forts = "".join([bloc_html(x, "#e74c3c") for x in forts])
    html_faibles = "".join([bloc_html(x, "#3498db") for x in faibles])
    body = f"""<html><body style='background:#f4f4f4; padding:20px;'><div style='max-width:620px; margin:auto; background:white; padding:20px;'>
    <div style='text-align:center;'><img src='{LOGO_URL}' height='45'></div>
    {f"<h2 style='color:#e74c3c; font-family:Arial;'>🔴 PRIORITÉS</h2>{html_forts}" if forts else ""}
    {f"<h2 style='color:#3498db; font-family:Arial;'>🔵 SIGNAUX FAIBLES</h2>{html_faibles}" if faibles else ""}
    </div></body></html>"""
    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"UA_Veille: {len(forts)} Priorités | {len(faibles)} Signaux", "htmlContent": body}, 
        headers={"api-key": BREVO_KEY})

def main():
    if not os.path.exists('cibles.csv'): return
    hist = charger_historique()
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    leads_forts, leads_faibles = [], []
    with open('cibles.csv', encoding='utf-8') as f:
        lecteur = csv.DictReader(f, delimiter=';' if ';' in f.read(100) else ',')
        f.seek(0)
        next(lecteur)
        for ligne in lecteur:
            nom, url_actu = ligne.get("Nom de l'Organisme"), ligne.get("URL Actualités / Projets")
            if not nom or not url_actu: continue
            liens = recuperer_liens_projets(session, url_actu, url_actu)
            for l in liens:
                if l in hist: continue
                txt = extraire_contenu(session, l)
                if txt and len(txt) > 400:
                    res = analyser_ia(txt, nom)
                    item = {"url": l, "nom_source": nom, **res}
                    if res['score'] == 3: leads_forts.append(item)
                    elif res['score'] >= 1: leads_faibles.append(item)
                    hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res['score']}
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)

if __name__ == "__main__": main()
