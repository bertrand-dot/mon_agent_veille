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
        # Nettoyage agressif des menus pour ne garder que le texte de l'article
        for t in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): t.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        return re.sub(r'\s+', ' ', main.get_text()).strip()
    except: return None

def recuperer_vrais_articles(session, url_liste):
    """Cible spécifiquement les liens qui ressemblent à des articles"""
    try:
        r = session.get(url_liste, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        liens = []
        
        # On cherche tous les liens sur la page
        for a in soup.find_all('a', href=True):
            url = urljoin(url_liste, a['href'])
            path = urlparse(url).path
            
            # FILTRE : On ne veut que des pages profondes (articles), pas les rubriques
            # Sur Euratlantique, les articles ont souvent un chemin plus long
            if urlparse(url).netloc == urlparse(url_liste).netloc:
                # On exclut les pages institutionnelles déjà vues dans votre historique
                exclure = ['carte-interactive', 'gouvernance', 'histoire', 'mentions', 'cookies', 'qui-nous-sommes', 'nos-realisations']
                if not any(ex in url for ex in exclure):
                    # Si l'URL est plus longue que la page de liste, c'est probablement un article
                    if len(path.strip('/')) > len(urlparse(url_liste).path.strip('/')) + 2:
                        liens.append(url)
        
        return list(dict.fromkeys(liens))[:8] # Top 8 articles
    except: return []

def analyser_ia(texte, source):
    prompt = f"""RÔLE : Directeur Dév. Urban Agency. 
    ANALYSE de l'opportunité (architecture, urbanisme, aménagement).
    SCORE : 3 (Priorité/Marché), 2 (Signal Faible/Étude), 1 (Veille), 0 (Inutile).
    RETOURNE JSON : {{"titre": "...", "resume": "...", "score": 0-3}}
    TEXTE : {texte[:12000]}"""
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

def envoyer_mail(forts, faibles):
    if not forts and not faibles: return
    
    def bloc(item, color):
        return f"<div style='border-left:4px solid {color}; padding:10px; margin-bottom:10px; background:#fff;'><b>{item['titre']}</b><br><p style='font-size:12px;'>{item['resume']}</p><a href='{item['url']}'>SOURCE →</a></div>"

    html = "".join([bloc(x, "#e74c3c") for x in forts]) + "".join([bloc(x, "#3498db") for x in faibles])
    
    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"UA_Veille : {len(forts)+len(faibles)} opportunités", "htmlContent": f"<html><body>{html}</body></html>"}, 
        headers={"api-key": BREVO_KEY})

def main():
    hist = charger_historique()
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    leads_forts, leads_faibles = [], []

    if not os.path.exists('cibles.csv'): return
    with open('cibles.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom, url = row.get("Nom de l'Organisme"), row.get("URL Actualités / Projets")
            if not nom or not url: continue
            
            print(f"Extraction des articles pour {nom}...")
            # ÉTAPE CLÉ : On récupère les liens des articles INDIVIDUELS
            articles = recuperer_vrais_articles(session, url)
            
            for l in articles:
                if l in hist: continue
                print(f"  --> Lecture article : {l}")
                txt = extraire_contenu(session, l)
                if txt and len(txt) > 500:
                    res = analyser_ia(txt, nom)
                    if res['score'] >= 1:
                        item = {"url": l, "nom_source": nom, **res}
                        if res['score'] == 3: leads_forts.append(item)
                        else: leads_faibles.append(item)
                    hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res['score']}
    
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)

if __name__ == "__main__": main()
