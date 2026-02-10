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

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX")

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"
JOURS_RETENTION = 180 

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

def creer_session():
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36'})
    return s

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

def est_page_pertinente(url):
    """Filtre pour ignorer le bruit institutionnel et les pages de présentation figées"""
    exclure = [
        'carte-interactive', 'annuaire', 'mentions', 'cookies', 'qui-nous-sommes', 
        'gouvernance', 'histoire', 'contact', 'faq', 'recherche', 'nos-realisations',
        'loperation-dinteret-national', 'equipe', 'recrutement'
    ]
    url_lower = url.lower()
    return not any(mot in url_lower for mot in exclure)

def recuperer_liens_projets(session, url_liste, racine):
    try:
        r = session.get(url_liste, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        liens = []
        # On cible le contenu principal pour éviter les liens de menu
        zone_contenu = soup.find('main') or soup.find('article') or soup
        for a in zone_contenu.find_all('a', href=True):
            full_url = urljoin(url_liste, a['href'])
            if urlparse(full_url).netloc == urlparse(racine).netloc:
                if est_page_pertinente(full_url) and len(full_url) > len(url_liste) + 3:
                    liens.append(full_url)
        return list(dict.fromkeys(liens))[:10]
    except: return []

# --- 4. ANALYSE IA ---

def analyser_ia(texte, source):
    prompt = f"""RÔLE : Directeur du Développement d'Urban Agency. 
    TACHE : Analyser le potentiel commercial de cette info (urbanisme, archi, aménagement).
    
    GRILLE DE SCORE :
    - 3 : SIGNAL FORT (ZAC créée, Concours lancé, Marché public, Lauréat).
    - 2 : SIGNAL FAIBLE (Étude urbaine, Concertation, Plan Guide, AMO, Diagnostic).
    - 1 : VEILLE (Info institutionnelle, stratégie climat, orientations).
    - 0 : AUCUN INTERET (RH, Histoire, Administration pure).

    RETOURNE JSON STRICT :
    {{"titre": "...", "theme": "...", "resume": "...", "chiffres": "...", "score": 0-3}}
    
    SOURCE : {source}
    TEXTE : {texte[:12000]}"""
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

# --- 5. EMAIL HIÉRARCHISÉ ---

def bloc_html(item, color):
    badge = "🔥 PRIORITÉ" if item['score'] == 3 else "⚡ SIGNAL" if item['score'] == 2 else "👁️ VEILLE"
    return f"""
    <div style="border-left: 4px solid {color}; background:#ffffff; padding:15px; margin-bottom:15px; font-family:Arial, sans-serif; border-radius:0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
            <span style="font-size:10px; color:#95a5a6; text-transform:uppercase; font-weight:bold;">{item['nom_source']}</span>
            <span style="background:{color}; color:white; padding:1px 5px; border-radius:3px; font-size:9px; font-weight:bold;">{badge}</span>
        </div>
        <div style="font-weight:bold; color:#2c3e50; font-size:15px; margin-bottom:5px;">{item['titre']}</div>
        <div style="font-size:13px; color:#555; line-height:1.4;">{item['resume']}</div>
        <div style="margin-top:8px; font-size:11px; font-weight:bold; color:#c0392b;">📊 {item.get('chiffres','Non précisé')}</div>
        <div style="text-align:right; margin-top:10px;"><a href="{item['url']}" style="color:{color}; font-size:11px; text-decoration:none; font-weight:bold; text-transform:uppercase;">SOURCE →</a></div>
    </div>"""

def envoyer_mail(forts, faibles):
    # Sécurité : on n'envoie rien si les deux listes sont vides pour ne pas polluer
    if not forts and not faibles: 
        logging.info("Aucun signal détecté, pas d'envoi d'email.")
        return
    
    html_forts = "".join([bloc_html(x, "#e74c3c") for x in forts])
    html_faibles = "".join([bloc_html(x, "#3498db") for x in faibles])
    
    body = f"""<html><body style='background:#f4f4f4; padding:20px;'><div style='max-width:620px; margin:auto; background:white; padding:20px; border-radius:8px;'>
    <div style='text-align:center; margin-bottom:30px; border-bottom:1px solid #eee; padding-bottom:20px;'><img src='{LOGO_URL}' height='45'></div>
    {f"<h2 style='color:#e74c3c; font-size:16px; font-family:Arial;'>🔴 PRIORITÉS</h2>{html_forts}" if forts else ""}
    {f"<h2 style='color:#3498db; font-size:16px; margin-top:30px; font-family:Arial;'>🔵 VEILLE & SIGNAUX FAIBLES</h2>{html_faibles}" if faibles else ""}
    <div style='text-align:center; font-size:10px; color:#bdc3c7; margin-top:40px; border-top:1px solid #eee; padding-top:20px;'>URBAN AGENCY • RADAR IA</div>
    </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"UA_Veille: {len(forts)} Priorités | {len(faibles)} Signaux", "htmlContent": body}, 
        headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return
    hist = charger_historique()
    session = creer_session()
    leads_forts, leads_faibles = [], []

    lignes = []
    for enc in ['utf-8', 'latin-1']:
        try:
            with open('cibles.csv', encoding=enc) as f: 
                lignes = f.readlines()
                break
        except: continue
    
    if not lignes: return
    sep = ';' if ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=sep)

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme")
        url_actu = ligne.get("URL Actualités / Projets")
        if not nom or not url_actu: continue
        
        print(f"🔎 Analyse de {nom}...")
        # On teste l'URL principale + les liens trouvés
        liens = [url_actu] + recuperer_liens_projets(session, url_actu, url_actu)
        
        for l in liens:
            if l in hist: continue
            
            txt = extraire_contenu(session, l)
            if txt and len(txt) > 400:
                res = analyser_ia(txt, nom)
                item = {"url": l, "nom_source": nom, **res}
                
                # Distribution dans les catégories du mail
                if res['score'] == 3: 
                    leads_forts.append(item)
                elif res['score'] >= 1: # On accepte désormais les scores 1 et 2
                    leads_faibles.append(item)
                
                hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res['score'], "source": nom}
    
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)
    print("✅ Rapport terminé.")

if __name__ == "__main__":
    main()
