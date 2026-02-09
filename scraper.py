import os
import requests
import csv
import re
import json
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
HISTORY_FILE = "download_history.json"
JOURS_RETENTION = 90

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. GESTION MÉMOIRE ---

def charger_historique():
    data = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                content = json.load(f)
                if isinstance(content, dict): data = content
        except: pass
    limit_date = datetime.now() - timedelta(days=JOURS_RETENTION)
    clean_data = {}
    for url, info in data.items():
        try:
            date_saved = datetime.strptime(info['date_detection'], '%Y-%m-%d')
            if date_saved > limit_date: clean_data[url] = info
        except: continue
    return clean_data

def sauvegarder_historique(historique):
    try:
        with open(HISTORY_FILE, 'w') as f: json.dump(historique, f, indent=2)
    except: pass

# --- 3. SESSION NAVIGATEUR (NOUVEAU) ---

def creer_session():
    """Crée une session qui garde les cookies comme un vrai navigateur."""
    session = requests.Session()
    # On se fait passer pour un vrai navigateur Chrome sur Windows
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Accept-Language': 'fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7',
        'Connection': 'keep-alive'
    })
    return session

# --- 4. ANALYSE ET FILTRES ---

def est_recent_pdf(pdf_content):
    try:
        with fitz.open(stream=pdf_content, filetype="pdf") as doc:
            metadata = doc.metadata
            date_str = metadata.get('creationDate', '') or metadata.get('modDate', '')
            if date_str.startswith('D:'):
                d = datetime(int(date_str[2:6]), int(date_str[6:8]), int(date_str[8:10]))
                return (datetime.now() - d).days <= JOURS_RETENTION
    except: return True
    return True

def est_grand_organisme(nom):
    return any(m in nom.lower() for m in ['epa', 'grand paris', 'métropole', 'part-dieu', 'défense', 'euratlantique'])

def nettoyer_texte(texte):
    return re.sub(r'\s+', ' ', texte).strip()

def extraire_contenu_url(session, target_url):
    try:
        # On utilise la SESSION ici au lieu de requests direct
        response = session.get(target_url, timeout=20)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        texte_final = ""
        
        if 'pdf' in content_type or target_url.lower().endswith('.pdf'):
            if not est_recent_pdf(response.content): return None
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                texte_final = "".join([page.get_text() for page in doc[:6]])
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'form']): tag.decompose()
            contenu = soup.find('main') or soup.find('article') or soup.body
            if contenu: texte_final = contenu.get_text(separator=' ')
                
        return nettoyer_texte(texte_final)
    except: return None

def analyser_ia_urban_agency(texte, source, categorie):
    date_lim = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    prompt = f"""
    Rôle : Directeur Dév. Urban Agency. Analyse ce texte ({source}).
    DATE LIMITE : {date_lim}. Si document plus vieux -> Score 0.
    
    ADN : 
    1. RESTRUCTURATION ACTIF / RÉHAB (Priorité 🔥) -> Score 3
    2. FRICHES / ZAC / WATERFRONT -> Score 3
    3. ÉDUCATION / SPORT (>10M€) -> Score 3
    4. LOGEMENT -> Score 2

    JSON : {{"titre": "...", "theme": "...", "resume": "...", "score": 0/1/2/3}}
    TEXTE : {texte[:12000]}
    """
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

# --- 5. ENVOI EMAIL ---

def generer_html(item, is_new):
    if is_new:
        border, bg, txt, opac = "#e74c3c" if item['score']==3 else "#3498db", "white", "#2c3e50", "1"
        badge = "🔥 NOUVEAU"
    else:
        border, bg, txt, opac = "#bdc3c7", "#f9f9f9", "#95a5a6", "0.7"
        badge = f"Vu le {item['date_detection']}"

    icon = "🏗️" if "RESTRUCT" in item.get('theme','').upper() else "📌"
    
    return f"""
    <div style="opacity:{opac}; border-left: 5px solid {border}; background: {bg}; padding: 15px; margin-bottom: 10px; border-radius: 4px;">
        <div style="display:flex; justify-content:space-between;">
            <strong style="color:{txt}; font-size:14px;">{icon} {item['nom_source']}</strong>
            <span style="font-size:10px; color:{txt}; font-weight:bold;">{badge}</span>
        </div>
        <div style="font-weight:bold; color:{txt}; font-size:15px; margin:5px 0;">{item['titre']}</div>
        <div style="font-size:13px; color:{txt};">{item['resume']}</div>
        <div style="text-align:right;"><a href="{item['url']}" style="color:{border}; font-size:11px; text-decoration:none;">Voir Source →</a></div>
    </div>
    """

def envoyer_mail(nouveaux, anciens):
    url = "https://api.brevo.com/v3/smtp/email"
    date_jour = datetime.now().strftime('%d/%m/%Y')
    sujet = f"UA_Veille Opportunités_{date_jour}"
    
    intro = f"Voici les {len(nouveaux)} nouvelles détections." if nouveaux else "R.A.S ce matin. Voici l'historique :"
    html = "".join([generer_html(x, True) for x in nouveaux]) + "".join([generer_html(x, False) for x in anciens])
    
    payload = {
        "sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": sujet,
        "htmlContent": f"<html><body style='font-family:Helvetica; background:#f4f4f4; padding:20px;'><div style='max-width:600px; margin:auto; background:white; padding:20px;'><h2>Dashboard {date_jour}</h2><p>{intro}</p>{html}</div></body></html>"
    }
    requests.post(url, json=payload, headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return
    historique = charger_historique()
    leads_new = []
    
    # Init Session
    session = creer_session()

    lignes = []
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open('cibles.csv', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    sep = ';' if lignes and ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=sep)
    
    exclude = ['contact', 'mentions', 'legales', 'connexion', 'login', 'cookies']
    print("--- Scan Démarré (Session Active) ---")

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme") or ligne.get("Nom de l'organisme")
        if not nom: continue
        
        limite = 10 if est_grand_organisme(nom) else 5
        cpt = 0
        urls = {"Actu": ligne.get("URL Actualités / Projets"), "Presse": ligne.get("URL Communiqués de Presse"), "RAA": ligne.get("URL Délibérations / Actes (RAA)")}
        
        print(f"👉 {nom}")
        for cat, url_source in urls.items():
            if not url_source or "http" not in str(url_source): continue
            try:
                # Utilisation de la SESSION pour la requête initiale
                res = session.get(url_source.strip(), timeout=15)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    if cpt >= limite: break
                    full_url = urljoin(url_source.strip(), link['href'])

                    if any(excl in full_url.lower() for excl in exclude): continue
                    if urlparse(full_url).netloc != urlparse(url_source).netloc and 'epa' not in full_url: continue
                    if full_url in historique: continue 
                    
                    # Utilisation de la SESSION pour extraire le contenu
                    texte = extraire_contenu_url(session, full_url)
                    if texte and len(texte) > 300:
                        data = analyser_ia_urban_agency(texte, nom, cat)
                        if data.get('score', 0) >= 2:
                            info = {
                                "url": full_url, "date_detection": datetime.now().strftime('%Y-%m-%d'),
                                "nom_source": nom, "titre": data.get('titre', 'Projet'),
                                "theme": data.get('theme', 'Divers'), "resume": data.get('resume', ''),
                                "score": data['score']
                            }
                            leads_new.append(info)
                            historique[full_url] = info
                            cpt += 1
                            print(f"   🔥 {info['titre']}")
            except: pass

    leads_old = [v for k,v in historique.items() if k not in [x['url'] for x in leads_new]]
    leads_old.sort(key=lambda x: x['date_detection'], reverse=True)
    
    sauvegarder_historique(historique)
    envoyer_mail(leads_new, leads_old)
    print("✅ Terminé.")

if __name__ == "__main__":
    main()
