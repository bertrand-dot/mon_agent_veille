import os
import requests
import csv
import re
import json
import time
from bs4 import BeautifulSoup
import fitz
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX")

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"
JOURS_RETENTION = 180 # Surveillance sur 6 mois

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

# --- 3. OUTILS D'EXTRACTION CIBLÉE ---

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
        # Nettoyage pour l'IA
        for t in soup(['nav', 'footer', 'script', 'style', 'header']): t.decompose()
        main = soup.find('main') or soup.find('article') or soup.body
        return re.sub(r'\s+', ' ', main.get_text()).strip()
    except: return None

def recuperer_liens_projets(session, url_liste, racine):
    """Récupère les liens en ignorant les pages institutionnelles 'mortes'"""
    try:
        r = session.get(url_liste, timeout=10)
        soup = BeautifulSoup(r.text, 'html.parser')
        liens_utiles = []
        
        # FILTRE ANTI-INSTITUTIONNEL : On ignore ces mots-clés dans l'URL
        exclude = [
            'qui-nous-sommes', 'loperation-dinteret-national', 'histoire', 
            'letablissement-public-damenagement', 'gouvernance', 'equipe', 
            'mentions-legales', 'contact', 'plan-du-site', 'recrutement',
            'presse', 'recherche', 'cookies', 'faq'
        ]
        
        for a in soup.find_all('a', href=True):
            href = a['href']
            full_url = urljoin(url_liste, href)
            
            # Conditions pour cliquer : même site + pas dans la liste d'exclusion
            if urlparse(full_url).netloc == urlparse(racine).netloc:
                if not any(ex in full_url.lower() for ex in exclude):
                    if len(full_url) > len(url_liste) + 3:
                        liens_utiles.append(full_url)
        
        # On garde les 6 liens les plus récents/pertinents
        return list(dict.fromkeys(liens_utiles))[:6]
    except: return []

# --- 4. CERVEAU IA (ANALYSE HIÉRARCHISÉE) ---

def analyser_ia(texte, source):
    prompt = f"""
    RÔLE : Directeur du Développement d'Urban Agency. 
    TACHE : Analyser si ce texte contient une opportunité commerciale.
    
    GRILLE DE SCORE :
    - SCORE 3 (SIGNAL FORT) : ZAC créée, Concours lancé, Marché public de maîtrise d'œuvre, Lauréat désigné, Budget > 5M€ voté.
    - SCORE 2 (SIGNAL FAIBLE) : Étude urbaine lancée, Bilan de concertation, Plan Guide, AMO, Diagnostic stratégique, Volonté politique de mutation.
    - SCORE 1 (VEILLE GÉNÉRALE) : Information institutionnelle, stratégie climat globale, modification PLU générale.
    - SCORE 0 (AUCUN INTÉRÊT) : Vie de l'agence, RH, Histoire, Administration pure.

    RETOURNE UN JSON STRICT :
    {{
      "titre": "Titre de l'opportunité",
      "theme": "Réglementaire / Étude / Opérationnel",
      "resume": "En quoi c'est une opportunité pour un architecte/urbaniste ?",
      "chiffres": "Budget/Surface/Nombre de logements",
      "score": 0 | 1 | 2 | 3
    }}
    TEXTE : {texte[:15000]}
    """
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

# --- 5. FORMATAGE EMAIL URBAN AGENCY ---

def bloc_html(item, color):
    badge = "🔥 PRIORITÉ" if item['score'] == 3 else "⚡ SIGNAL FAIBLE" if item['score'] == 2 else "👁️ VEILLE"
    return f"""
    <div style="border-left: 4px solid {color}; background:#ffffff; padding:15px; margin-bottom:15px; font-family:Arial, sans-serif; border-radius:0 4px 4px 0; box-shadow: 0 1px 2px rgba(0,0,0,0.05);">
        <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
            <span style="font-size:10px; color:#95a5a6; text-transform:uppercase; font-weight:bold;">{item['nom_source']}</span>
            <span style="background:{color}; color:white; padding:1px 5px; border-radius:3px; font-size:9px; font-weight:bold;">{badge}</span>
        </div>
        <div style="font-weight:bold; color:#2c3e50; font-size:15px; margin-bottom:5px;">{item['titre']}</div>
        <div style="font-size:13px; color:#555; line-height:1.4;">{item['resume']}</div>
        <div style="margin-top:8px; font-size:11px; font-weight:bold; color:#c0392b; background:#fff5f5; display:inline-block; padding:2px 5px;">📊 {item.get('chiffres','Non précisé')}</div>
        <div style="text-align:right; margin-top:10px;"><a href="{item['url']}" style="color:{color}; font-size:11px; text-decoration:none; font-weight:bold; text-transform:uppercase;">VOIR LA SOURCE →</a></div>
    </div>
    """

def envoyer_mail(forts, faibles):
    if not forts and not faibles: return
    
    html_forts = "".join([bloc_html(x, "#e74c3c") for x in forts])
    html_faibles = "".join([bloc_html(x, "#3498db") for x in faibles])
    
    section_forts = f"<h2 style='color:#e74c3c; font-size:16px; border-bottom:2px solid #e74c3c; padding-bottom:5px; font-family:Arial;'>🔴 ACTIONS IMMINENTES</h2>{html_forts}" if forts else ""
    section_faibles = f"<h2 style='color:#3498db; font-size:16px; border-bottom:2px solid #3498db; padding-bottom:5px; margin-top:30px; font-family:Arial;'>🔵 VEILLE & SIGNAUX FAIBLES</h2>{html_faibles}" if faibles else ""

    body = f"""<html><body style='background:#f4f4f4; padding:20px;'><div style='max-width:620px; margin:auto; background:white; padding:20px; border-radius:8px;'>
    <div style='text-align:center; margin-bottom:30px; border-bottom:1px solid #eee; padding-bottom:20px;'><img src='{LOGO_URL}' height='45'></div>
    {section_forts}
    {section_faibles}
    <div style='text-align:center; font-size:10px; color:#bdc3c7; margin-top:40px; border-top:1px solid #eee; padding-top:20px;'>URBAN AGENCY • RADAR STRATÉGIQUE IA</div>
    </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"UA_Veille: {len(forts)} Priorités | {len(faibles)} Signaux", 
              "htmlContent": body}, 
        headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return
    hist = charger_historique()
    session = creer_session()
    leads_forts, leads_faibles = [], []

    # Lecture robuste du CSV
    lignes = []
    for enc in ['utf-8', 'latin-1']:
        try:
            with open('cibles.csv', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    lecteur = csv.DictReader(lignes, delimiter=';' if ';' in lignes[0] else ',')

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme")
        url_actu = ligne.get("URL Actualités / Projets")
        if not nom or not url_actu: continue
        
        print(f"🔎 Analyse profonde de {nom}...")
        
        # 1. On ignore les pages institutionnelles et on cherche les vrais articles
        liens = recuperer_liens_projets(session, url_actu, url_actu)
        
        for l in liens:
            if l in hist: continue
            
            txt = extraire_contenu(session, l)
            if txt and len(txt) > 400:
                res = analyser_ia(txt, nom)
                item = {"url": l, "nom_source": nom, **res}
                
                if res['score'] == 3: 
                    leads_forts.append(item)
                elif res['score'] >= 1: 
                    leads_faibles.append(item)
                
                # On mémorise pour ne pas rescanner demain
                hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res['score']}
    
    # Envoi du rapport hiérarchisé
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)
    print("✅ Rapport envoyé.")

if __name__ == "__main__":
    main()
