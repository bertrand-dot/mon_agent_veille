import os
import requests
import csv
import re
import json
import time
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
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
JOURS_RETENTION = 180 # Radar sur 6 mois pour capter l'évolution des ZAC

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. GESTION MÉMOIRE ---

def charger_historique():
    data = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: data = json.load(f)
        except: pass
    return data

def sauvegarder_historique(historique):
    try:
        with open(HISTORY_FILE, 'w') as f: json.dump(historique, f, indent=2)
    except: pass

# --- 3. OUTILS EXTRACTION ---

def creer_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    })
    return session

def extraire_contenu_url(session, target_url):
    try:
        response = session.get(target_url, timeout=12)
        response.raise_for_status()
        ctype = response.headers.get('Content-Type', '').lower()
        
        if 'pdf' in ctype or target_url.lower().endswith('.pdf'):
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                return "".join([page.get_text() for page in doc[:10]])
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'form', 'header']): tag.decompose()
            main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile('content|main|article')) or soup.body
            return re.sub(r'\s+', ' ', main.get_text()).strip() if main else ""
    except: return None

def recuperer_liens_articles(session, url_liste, racine, limite=5):
    """Identifie les liens vers les articles individuels sur une page liste"""
    try:
        res = session.get(url_liste, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        liens = []
        vu = set()
        
        # Filtre pour ne pas cliquer sur n'importe quoi
        exclude = ['contact', 'mentions', 'facebook', 'linkedin', 'twitter', 'instagram', 'connexion']
        
        for a in soup.find_all('a', href=True):
            url = urljoin(url_liste, a['href'])
            # On reste sur le même domaine et on évite les doublons/liens inutiles
            if urlparse(url).netloc == urlparse(racine).netloc and url not in vu:
                if not any(ex in url.lower() for ex in exclude) and len(url) > len(url_liste) + 3:
                    liens.append(url)
                    vu.add(url)
            if len(liens) >= limite: break
        return liens
    except: return []

# --- 4. GOOGLE DORKING (LINKEDIN) ---

def scan_google_linkedin(nom_organisme):
    if not GOOGLE_SEARCH_KEY or not GOOGLE_SEARCH_CX: return []
    query = f'site:linkedin.com/company/ "{nom_organisme}" ("appel à projets" OR "concours" OR "friche" OR "consultation" OR "lauréat" OR "ZAC" OR "étude urbaine")'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': GOOGLE_SEARCH_KEY, 'cx': GOOGLE_SEARCH_CX, 'q': query, 'dateRestrict': 'm1', 'num': 3}
    try:
        res = requests.get(url, params=params).json()
        return [{'titre': i['title'], 'url': i['link'], 'snippet': i['snippet']} for i in res.get('items', [])]
    except: return []

# --- 5. CERVEAU IA (RADAR SIGNAUX FAIBLES) ---

def analyser_ia_urban_agency(texte, source, type_org):
    date_lim = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    prompt = f"""
    RÔLE : Directeur Dév. Urban Agency.
    SOURCE : {source} ({type_org}). DATE LIMITE : {date_lim}.

    OBJECTIF : DÉTECTER LES ÉTAPES CLÉS ET SIGNAUX FAIBLES.
    
    CRITÈRES DE SCORE :
    - SCORE 3 (IMMINENT 🔥) : Création de ZAC, Bilan de concertation, Concours d'archi, Marché de MOE lancé, DUP, Budget travaux voté > 5M€.
    - SCORE 2 (SIGNAL FAIBLE ⚡) : Lancement étude urbaine, Diagnostic, Plan Guide, AMO, Volonté politique affichée de mutation, Préemption stratégique.
    - SCORE 1 (VEILLE 👁️) : Orientations générales, PLU, Stratégie climat sans site précis.
    - SCORE 0 (SANS INTÉRÊT) : Menus cantine, RH, vœux, voirie courante, éducation (petites réparations).

    JSON STRICT :
    {{
      "titre": "Titre explicite de l'opportunité",
      "theme": "Réglementaire / Étude / Opérationnel",
      "resume": "Pourquoi c'est stratégique pour un archi/urba ? (2 phrases)",
      "chiffres_cles": "Budget/Surface/Logements (ou 'Non précisé')",
      "maturite": "Intention | Étude | Opérationnel",
      "score": 0 | 1 | 2 | 3
    }}

    TEXTE : {texte[:15000]}
    """
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

# --- 6. FORMATAGE & ENVOI ---

def generer_html(item, is_new):
    colors = {3: "#e74c3c", 2: "#f39c12", 1: "#27ae60"}
    border = colors.get(item['score'], "#95a5a6")
    badge = "🔥 IMMINENT" if item['score'] == 3 else "⚡ SIGNAL FAIBLE" if item['score'] == 2 else "👀 VEILLE"
    
    icon = "🏗️" if "RESTRUCT" in item.get('theme','').upper() else "📋" if "ÉTUDE" in item.get('theme','').upper() else "🏭"
    font_h = "'DIN', 'DIN Pro', 'Roboto', Arial, sans-serif"

    return f"""
    <div style="border-left: 4px solid {border}; background: {'#ffffff' if is_new else '#f9f9f9'}; padding: 20px; margin-bottom: 20px; font-family:Arial, sans-serif; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
            <div style="color:#7f8c8d; font-size:11px; font-weight:bold; text-transform:uppercase;">{icon} {item['nom_source']}</div>
            <div style="background:{border}; color:white; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:bold;">{badge}</div>
        </div>
        <div style="font-family:{font_h}; font-weight:700; color:#2c3e50; font-size:16px; margin-bottom:8px;">{item['titre']}</div>
        <div style="font-size:13px; color:#444; line-height:1.4;">{item['resume']}</div>
        <div style="margin-top:10px; font-size:11px; color:#c0392b; font-weight:bold; background:#fff5f5; padding:4px; display:inline-block;">📊 {item.get('chiffres_cles','')}</div>
        <div style="margin-top:10px; padding-top:10px; border-top:1px solid #eee; text-align:right;">
             <a href="{item['url']}" style="color:{border}; font-family:{font_h}; font-size:11px; text-decoration:none; font-weight:bold; text-transform:uppercase;">LIRE LA SOURCE →</a>
        </div>
    </div>
    """

def envoyer_mail(nouveaux, anciens):
    url = "https://api.brevo.com/v3/smtp/email"
    html = "".join([generer_html(x, True) for x in nouveaux])
    if anciens:
        html += '<div style="margin:40px 0 20px 0; border-top:1px dashed #ddd; text-align:center;"><span style="background:white; padding:0 10px; font-size:10px; color:#bdc3c7;">RAPPEL HISTORIQUE</span></div>'
        html += "".join([generer_html(x, False) for x in anciens])
    
    body = f"""<html><body style='background:#f4f4f4; padding:20px;'><div style='max-width:650px; margin:auto; background:white; padding:20px;'><div style="text-align:center; padding-bottom:20px; border-bottom:1px solid #eee;"><img src="{LOGO_URL}" height="45"></div><div style="padding-top:20px;">{html}</div><div style="background:#2c3e50; color:white; padding:15px; text-align:center; font-size:10px; margin-top:20px;">URBAN AGENCY • RADAR IA</div></div></body></html>"""
    
    requests.post(url, json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], "subject": f"UA_Veille_{datetime.now().strftime('%d/%m')}: {len(nouveaux)} Signaux", "htmlContent": body}, headers={"api-key": BREVO_KEY})

# --- 7. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return
    historique = charger_historique()
    leads_new = []
    session = creer_session()

    lignes = []
    for enc in ['utf-8', 'latin-1']:
        try:
            with open('cibles.csv', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    lecteur = csv.DictReader(lignes, delimiter=';' if ';' in lignes[0] else ',')

    print("--- DÉMARRAGE RADAR SIGNAUX FAIBLES (DEEP SCAN) ---")

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme")
        url_actu = ligne.get("URL Actualités / Projets") or ligne.get("URL Communiqués de Presse")
        if not nom or not url_actu: continue

        print(f"👉 Scan Profond : {nom}...")
        
        # 1. On va sur la page liste et on récupère les liens vers les détails
        articles = recuperer_liens_articles(session, url_actu, url_actu, limite=5)
        
        # 2. On scanne chaque page article trouvée
        for lien in articles:
            if lien in historique: continue
            
            texte = extraire_contenu_url(session, lien)
            if texte and len(texte) > 400:
                data = analyser_ia_urban_agency(texte, nom, "Deep Scan Article")
                if data.get('score', 0) >= 2:
                    info = {"url": lien, "date_detection": datetime.now().strftime('%Y-%m-%d'), "nom_source": nom, "titre": data['titre'], "resume": data['resume'], "chiffres_cles": data['chiffres_cles'], "score": data['score'], "theme": data['theme'], "maturite": data['maturite']}
                    leads_new.append(info)
                    historique[lien] = info
                    print(f"   ✅ TROUVÉ : {info['titre']}")
                else:
                    historique[lien] = {"date_detection": datetime.now().strftime('%Y-%m-%d'), "score": 0}

        # 3. On ajoute LinkedIn pour compléter
        linkedin_results = scan_google_linkedin(nom)
        for item in linkedin_results:
            if item['url'] in historique: continue
            data = analyser_ia_urban_agency(item['snippet'], nom, "LinkedIn")
            if data.get('score', 0) >= 2:
                info = {"url": item['url'], "date_detection": datetime.now().strftime('%Y-%m-%d'), "nom_source": nom, "titre": item['titre'], "resume": data['resume'], "chiffres_cles": "Via LinkedIn", "score": data['score'], "theme": data['theme'], "maturite": data['maturite']}
                leads_new.append(info)
                historique[item['url']] = info
                print(f"   👔 LINKEDIN : {info['titre']}")

    leads_old = [v for k,v in historique.items() if k not in [x['url'] for x in leads_new] and v.get('score', 0) >= 2]
    leads_old.sort(key=lambda x: x['date_detection'], reverse=True)
    
    sauvegarder_historique(historique)
    envoyer_mail(leads_new, leads_old[:10])
    print("✅ Terminé.")

if __name__ == "__main__":
    main()
