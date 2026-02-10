import os
import requests
import csv
import re
import json
import warnings
from bs4 import BeautifulSoup
import fitz
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
import logging

# On ignore les messages d'avertissement de version Python dans les logs
warnings.filterwarnings("ignore", category=FutureWarning)

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. GESTION MÉMOIRE ---

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

# --- 3. OUTILS D'EXTRACTION ---

def extraire_contenu(session, url):
    try:
        r = session.get(url, timeout=12)
        if 'pdf' in r.headers.get('Content-Type', '').lower():
            with fitz.open(stream=r.content, filetype="pdf") as doc:
                return "".join([p.get_text() for p in doc[:8]])
        soup = BeautifulSoup(r.text, 'html.parser')
        # On supprime tout ce qui n'est pas l'article lui-même
        for t in soup(['nav', 'footer', 'script', 'style', 'header', 'aside', 'form']): t.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        return re.sub(r'\s+', ' ', main.get_text()).strip()
    except: return None

def recuperer_vrais_articles(session, url_liste):
    """Cible uniquement les liens présents dans les blocs d'articles (News Grid)"""
    try:
        r = session.get(url_liste, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        liens = []
        
        # Mots-clés de rubriques à IGNORER ABSOLUMENT
        exclure = ['faq', 'poser-une-question', 'annuaire', 'contact', 'mentions', 'cookies', 'recherche', 'mediation']
        
        # Sur Bordeaux Euratlantique, les articles sont souvent dans des <article> ou des div avec classes spécifiques
        # On cherche les liens à l'intérieur du conteneur de résultats
        conteneur = soup.find('main') or soup.find('body')
        
        for a in conteneur.find_all('a', href=True):
            url = urljoin(url_liste, a['href'])
            path = urlparse(url).path.lower()
            
            # 1. On vérifie que c'est le même site
            if urlparse(url).netloc == urlparse(url_liste).netloc:
                # 2. On vérifie que ce n'est pas une page d'aide/FAQ/Contact
                if not any(word in path for word in exclure):
                    # 3. On évite les URLs trop courtes (rubriques)
                    if len(path.strip('/')) > 5:
                        liens.append(url)
        
        # Suppression des doublons et on garde les 10 plus pertinents
        return list(dict.fromkeys(liens))[:10]
    except Exception as e:
        logging.error(f"Erreur extraction : {e}")
        return []

# --- 4. ANALYSE IA ---

def analyser_ia(texte, source):
    prompt = f"""RÔLE : Expert Urbanisme pour Urban Agency.
    ANALYSE ce texte pour trouver des opportunités (ZAC, Concours, Études, Marchés).
    SCORE : 3 (Marché/Lauréat), 2 (Étude/Concertation), 1 (Veille), 0 (Inutile).
    RETOURNE JSON : {{"titre": "...", "resume": "...", "score": 0-3}}
    SOURCE : {source}
    TEXTE : {texte[:12000]}"""
    try:
        res = model.generate_content(prompt)
        # Nettoyage du JSON renvoyé par l'IA
        clean_json = re.search(r'\{.*\}', res.text, re.DOTALL).group()
        return json.loads(clean_json)
    except: return {"score": 0}

# --- 5. EMAIL ---

def envoyer_mail(forts, faibles):
    if not forts and not faibles: 
        logging.info("Aucun signal détecté. Pas d'envoi.")
        return
    
    def bloc(item, color):
        return f"""<div style="border-left:4px solid {color}; padding:10px; margin-bottom:10px; background:#fff;">
        <b>{item['titre']}</b><br><small>{item['nom_source']}</small><br>
        <p style="font-size:12px; color:#444;">{item.get('resume','')}</p>
        <a href="{item['url']}" style="font-size:11px; font-weight:bold; color:{color};">LIRE LA SOURCE →</a></div>"""

    html = "".join([bloc(x, "#e74c3c") for x in forts]) + "".join([bloc(x, "#3498db") for x in faibles])
    
    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"UA_Veille : {len(forts)} Priorités | {len(faibles)} Signaux", 
              "htmlContent": f"<html><body style='background:#f4f4f4; padding:20px;'><img src='{LOGO_URL}' height='40'><br>{html}</body></html>"}, 
        headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return
    hist = charger_historique()
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    leads_forts, leads_faibles = [], []

    with open('cibles.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom, url = row.get("Nom de l'Organisme"), row.get("URL Actualités / Projets")
            if not nom or not url: continue
            
            print(f"🔎 Scan des actualités pour {nom}...")
            articles = recuperer_vrais_articles(session, url)
            
            for l in articles:
                if l in hist: continue
                print(f"  --> Analyse approfondie : {l}")
                txt = extraire_contenu(session, l)
                if txt and len(txt) > 400:
                    res = analyser_ia(txt, nom)
                    if res.get('score', 0) >= 1:
                        item = {"url": l, "nom_source": nom, **res}
                        if res['score'] == 3: leads_forts.append(item)
                        else: leads_faibles.append(item)
                    hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res.get('score', 0)}
    
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)
    print("✅ Session terminée.")

if __name__ == "__main__":
    main()
