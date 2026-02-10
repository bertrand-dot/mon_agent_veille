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

# CLÉS GOOGLE (Pour LinkedIn)
GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX")

# LOGO URBAN AGENCY (Votre lien officiel)
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"

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
    
    # Nettoyage automatique des vieux dossiers (> 90 jours)
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

# --- 3. SESSION & OUTILS WEB ---

def creer_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Connection': 'keep-alive'
    })
    return session

def est_recent_pdf(pdf_content):
    """Vérifie si le PDF a été créé il y a moins de 90 jours"""
    try:
        with fitz.open(stream=pdf_content, filetype="pdf") as doc:
            metadata = doc.metadata
            date_str = metadata.get('creationDate', '') or metadata.get('modDate', '')
            if date_str.startswith('D:'):
                d = datetime(int(date_str[2:6]), int(date_str[6:8]), int(date_str[8:10]))
                return (datetime.now() - d).days <= JOURS_RETENTION
    except: return True # Dans le doute, on garde
    return True

def est_grand_organisme(nom):
    """Détermine si on scanne en profondeur (10 liens) ou en surface (5 liens)"""
    return any(m in nom.lower() for m in ['epa', 'grand paris', 'métropole', 'metropole', 'part-dieu', 'défense', 'euratlantique'])

def type_organisme(nom):
    """Aide l'IA à comprendre le contexte"""
    nom_l = nom.lower()
    if any(x in nom_l for x in ['epa', 'epf', 'amenagement', 'aménagement']): return "EPA"
    if any(x in nom_l for x in ['métropole', 'metropole', 'ville', 'mairie']): return "METROPOLE"
    return "AUTRE"

def nettoyer_texte(texte):
    return re.sub(r'\s+', ' ', texte).strip()

def extraire_contenu_url(session, target_url):
    try:
        response = session.get(target_url, timeout=20)
        response.raise_for_status()
        content_type = response.headers.get('Content-Type', '').lower()
        texte_final = ""
        
        if 'pdf' in content_type or target_url.lower().endswith('.pdf'):
            if not est_recent_pdf(response.content): return None
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                # On lit les 6 premières pages max
                texte_final = "".join([page.get_text() for page in doc[:6]])
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            # On retire le bruit (menus, pubs, scripts)
            for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'form', 'iframe', 'header']): tag.decompose()
            contenu = soup.find('main') or soup.find('article') or soup.body
            if contenu: texte_final = contenu.get_text(separator=' ')
        return nettoyer_texte(texte_final)
    except: return None

# --- 4. GOOGLE DORKING (LINKEDIN) ---

def scan_google_linkedin(nom_organisme):
    """Recherche les posts récents sur LinkedIn via Google API"""
    if not GOOGLE_SEARCH_KEY or not GOOGLE_SEARCH_CX:
        return []

    # Requête : site:linkedin.com/company/ "Nom" + Mots clés immo
    query = f'site:linkedin.com/company/ "{nom_organisme}" ("appel à projets" OR "concours" OR "friche" OR "consultation" OR "lauréat")'
    
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_SEARCH_KEY,
        'cx': GOOGLE_SEARCH_CX,
        'q': query,
        'dateRestrict': 'm1', # Uniquement le dernier mois
        'num': 3 # Max 3 résultats par organisme
    }
    
    results = []
    try:
        res = requests.get(url, params=params).json()
        if 'items' in res:
            for item in res['items']:
                results.append({
                    'titre': item['title'],
                    'url': item['link'],
                    'snippet': item['snippet']
                })
        time.sleep(0.5) # Pause anti-ban Google
    except Exception as e:
        print(f"   ⚠️ Erreur Google API: {e}")
    
    return results

# --- 5. CERVEAU IA (WEB + LINKEDIN) ---

def analyser_ia_urban_agency(texte, source, categorie, type_org):
    date_lim = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    
    prompt = f"""
    RÔLE : Directeur Dév. Urban Agency (Archi/Urba).
    CONTEXTE : {source} ({type_org}) - Source : {categorie}
    DATE LIMITE : {date_lim} (Si document antérieur -> SCORE 0)

    STRATÉGIE
    - Priorité absolue : Restructuration lourde, Friches, ZAC complexes, Équipements publics >10M€.
    - Secondaire : Logement, Études urbaines.

    TACHE
    Analyse ce texte. Est-ce une opportunité commerciale réelle ?
    Extrais le Budget et la Surface si disponibles.

    FORMAT JSON STRICT :
    {{
      "titre": "Titre court et clair",
      "theme": "Restructuration / Friche / Waterfront / Équipement public / Logement / Autre",
      "resume": "Résumé analytique en 2 phrases max",
      "chiffres_cles": "Ex: 'Budget 15M€ / 4500m2 SDP' ou 'Non précisé'",
      "maturite": "Faible (étude) | Moyen (prog) | Eleve (concours/marché)",
      "score": 0 (rien) | 1 (veille) | 2 (intéressant) | 3 (chaud/prioritaire)
    }}

    TEXTE :
    {texte[:12000]}
    """
    try:
        res = model.generate_content(prompt)
        clean_json = res.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except: return {"score": 0}

# --- 6. EMAIL (DESIGN URBAN AGENCY) ---

def generer_html(item, is_new):
    # Couleurs selon Score
    if item['score'] == 3: border = "#e74c3c" # Rouge
    elif item['score'] == 2: border = "#2980b9" # Bleu
    else: border = "#27ae60" # Vert

    # Maturité
    mat = item.get('maturite', 'Inconnue').capitalize()
    color_mat = "#d35400" if "Eleve" in mat else "#f39c12" if "Moyen" in mat else "#95a5a6"
    
    # Styles Nouveau/Ancien
    bg, txt, opac = ("white", "#2c3e50", "1") if is_new else ("#f9f9f9", "#95a5a6", "0.7")
    date_label = "NOUVEAU" if is_new else f"Vu le {item['date_detection']}"
    date_color = "#e74c3c" if is_new else "#bdc3c7"
    
    # Icone Thème
    icon = "🏗️" if "RESTRUCT" in item.get('theme','').upper() else "🏭" if "FRICHE" in item.get('theme','').upper() else "📌"
    
    # Badge Source (LinkedIn ou Web)
    source_label = "LINKEDIN" if "linkedin.com" in item['url'] else "WEB/PDF"
    source_style = "background:#0077b5; color:white;" if "linkedin" in item['url'] else "background:#eee; color:#555;"

    # Polices
    font_heading = "'DIN', 'DIN Pro', 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif"
    font_body = "Arial, sans-serif"

    return f"""
    <div style="opacity:{opac}; border-left: 4px solid {border}; background: {bg}; padding: 20px; margin-bottom: 20px; font-family:{font_body}; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
            <div style="font-family:{font_heading}; text-transform:uppercase; font-size:12px; letter-spacing:1px; color:#7f8c8d;">
                {icon} {item['nom_source']}
            </div>
            <div style="text-align:right;">
                <span style="font-family:{font_heading}; color:{date_color}; font-size:10px; font-weight:bold;">{date_label}</span><br>
                <span style="{source_style} padding:1px 4px; border-radius:3px; font-size:9px; font-weight:bold;">{source_label}</span>
            </div>
        </div>
        
        <div style="font-family:{font_heading}; font-weight:700; color:#2c3e50; font-size:16px; margin-bottom:8px;">{item['titre']}</div>
        <div style="font-size:13px; color:#444; line-height:1.5; margin-bottom:10px;">{item['resume']}</div>
        
        <div style="background-color:#f4f6f7; padding:8px 12px; border-radius:2px; font-size:12px; color:#2c3e50; font-weight:bold; display:inline-block; margin-bottom:10px; border-left:2px solid #bdc3c7;">
            📊 {item.get('chiffres_cles', 'Non précisé')}
        </div>

        <div style="margin-top:5px; padding-top:10px; border-top:1px solid #eee; display:flex; justify-content:space-between; align-items:center;">
             <span style="font-size:10px; color:#95a5a6; text-transform:uppercase;">{item['theme']} - Mat. {mat}</span>
             <a href="{item['url']}" style="color:{border}; font-family:{font_heading}; font-size:11px; text-decoration:none; font-weight:bold;">ACCÉDER À LA SOURCE →</a>
        </div>
    </div>
    """

def envoyer_mail(nouveaux, anciens):
    url = "https://api.brevo.com/v3/smtp/email"
    date_jour = datetime.now().strftime('%d/%m/%Y')
    sujet = f"UA_Veille Opportunités_{date_jour}"
    
    titre_principal = f"{len(nouveaux)} OPPORTUNITÉS" if nouveaux else "R.A.S - CALME PLAT"
    couleur_titre = "#2c3e50" if nouveaux else "#bdc3c7"

    html_content = "".join([generer_html(x, True) for x in nouveaux])
    html_history = "".join([generer_html(x, False) for x in anciens]) if anciens else "<p style='font-size:12px; color:#ccc; text-align:center;'>Historique vide.</p>"
    
    font_heading = "'DIN', 'DIN Pro', 'Roboto', 'Helvetica', Arial, sans-serif"

    body = f"""
    <html>
    <head><link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
    <body style="margin:0; padding:0; background-color:#f4f4f4; font-family:Arial, sans-serif;">
        <div style="max-width:650px; margin:0 auto; background-color:#ffffff; min-height:100vh;">
            
            <div style="padding:30px 20px; text-align:center; border-bottom:1px solid #eeeeee;">
                <img src="{LOGO_URL}" alt="URBAN AGENCY" style="max-height:50px; width:auto;">
            </div>

            <div style="padding:40px 20px 20px 20px; text-align:center;">
                <p style="font-family:{font_heading}; font-size:10px; letter-spacing:2px; text-transform:uppercase; color:#95a5a6; margin:0;">RAPPORT DE VEILLE • {date_jour}</p>
                <h1 style="font-family:{font_heading}; font-size:24px; letter-spacing:1px; text-transform:uppercase; color:{couleur_titre}; margin:10px 0;">{titre_principal}</h1>
            </div>

            <div style="padding:0 20px 40px 20px;">
                {html_content}
                
                <div style="margin:40px 0 20px 0; border-top:1px dashed #ddd; text-align:center;">
                    <span style="background:white; padding:0 10px; position:relative; top:-10px; font-family:{font_heading}; font-size:10px; color:#bdc3c7; letter-spacing:1px;">HISTORIQUE (90J)</span>
                </div>
                
                <div style="opacity:0.8;">{html_history}</div>
            </div>

            <div style="background-color:#2c3e50; color:white; padding:20px; text-align:center; font-size:10px; font-family:{font_heading}; letter-spacing:1px;">URBAN AGENCY • INTELLIGENCE ARTIFICIELLE</div>
        </div>
    </body>
    </html>
    """
    
    payload = {
        "sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": sujet,
        "htmlContent": body
    }
    requests.post(url, json=payload, headers={"api-key": BREVO_KEY})

# --- 7. MAIN (BOUCLE PRINCIPALE) ---

def main():
    if not os.path.exists('cibles.csv'): return
    historique = charger_historique()
    leads_new = []
    session = creer_session()

    lignes = []
    # Lecture CSV robuste (UTF-8, Latin-1...)
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open('cibles.csv', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    sep = ';' if lignes and ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=sep)
    
    # Filtres anti-bruit (Mots clés à ignorer)
    mots_bruit = ['menu', 'cantine', 'vaccination', 'déchets', 'concert', 'exposition', 'cinéma', 'médiathèque', 'piscine', 'vœux']
    exclude = ['contact', 'mentions', 'legales', 'connexion', 'login', 'cookies']
    
    print(f"--- Scan Urban Agency (Web + LinkedIn Dorking) ---")

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme") or ligne.get("Nom de l'organisme")
        if not nom: continue
        
        org_type = type_organisme(nom)
        limite = 10 if est_grand_organisme(nom) else 5
        cpt = 0
        
        # Récupération des URLs (si vides, on passe)
        urls = {
            "Actu": ligne.get("URL Actualités / Projets"), 
            "Presse": ligne.get("URL Communiqués de Presse"), 
            "RAA": ligne.get("URL Délibérations / Actes (RAA)")
        }
        
        print(f"👉 {nom} ({org_type})")

        # ---------------------------------------------------------
        # 1. SCAN CLASSIQUE (SITE WEB & PDF)
        # ---------------------------------------------------------
        for cat, url_source in urls.items():
            if not url_source or "http" not in str(url_source): continue
            try:
                res = session.get(url_source.strip(), timeout=15)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    if cpt >= limite: break
                    full_url = urljoin(url_source.strip(), link['href'])

                    if any(excl in full_url.lower() for excl in exclude): continue
                    if urlparse(full_url).netloc != urlparse(url_source).netloc and 'epa' not in full_url: continue
                    if full_url in historique: continue 
                    
                    texte = extraire_contenu_url(session, full_url)
                    
                    # Si on a du texte et qu'il n'est pas "bruyant"
                    if texte and len(texte) > 300:
                        if any(b in texte.lower() for b in mots_bruit): continue
                        
                        data = analyser_ia_urban_agency(texte, nom, cat, org_type)
                        
                        if data.get('score', 0) >= 1:
                            info = {
                                "url": full_url, 
                                "date_detection": datetime.now().strftime('%Y-%m-%d'),
                                "nom_source": nom, 
                                "titre": data.get('titre', 'Projet'),
                                "theme": data.get('theme', 'Divers'), 
                                "resume": data.get('resume', ''),
                                "chiffres_cles": data.get('chiffres_cles', 'Non précisé'),
                                "maturite": data.get('maturite', 'Non précisé'), 
                                "score": data['score']
                            }
                            leads_new.append(info)
                            historique[full_url] = info
                            cpt += 1
                            print(f"   🔥 WEB: {info['titre']}")
            except: pass
        
        # ---------------------------------------------------------
        # 2. SCAN LINKEDIN (VIA GOOGLE DORKING)
        # ---------------------------------------------------------
        # On lance si les clés sont là et qu'on n'a pas explosé le quota Web
        if GOOGLE_SEARCH_KEY and GOOGLE_SEARCH_CX:
            try:
                linkedin_results = scan_google_linkedin(nom)
                for item in linkedin_results:
                    if item['url'] in historique: continue
                    
                    # On envoie le "Snippet" Google à l'IA
                    data = analyser_ia_urban_agency(item['snippet'] + " " + item['titre'], nom, "LinkedIn", org_type)
                    
                    # Seuil score >= 2 pour LinkedIn (éviter le bruit)
                    if data.get('score', 0) >= 2:
                        info = {
                            "url": item['url'], 
                            "date_detection": datetime.now().strftime('%Y-%m-%d'),
                            "nom_source": nom, 
                            "titre": item['titre'],
                            "theme": data.get('theme', 'Divers'), 
                            "resume": data.get('resume', ''),
                            "chiffres_cles": "Voir post LinkedIn",
                            "maturite": data.get('maturite', 'Non précisé'), 
                            "score": data['score']
                        }
                        leads_new.append(info)
                        historique[item['url']] = info
                        print(f"   👔 LINKEDIN: {info['titre']}")
            except: pass

    # Fin du scan : Tri et Envoi
    leads_old = [v for k,v in historique.items() if k not in [x['url'] for x in leads_new]]
    leads_old.sort(key=lambda x: x['date_detection'], reverse=True)
    
    sauvegarder_historique(historique)
    envoyer_mail(leads_new, leads_old)
    print("✅ Terminé. Rapport envoyé.")

if __name__ == "__main__":
    main()
