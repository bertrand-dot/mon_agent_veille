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
JOURS_RETENTION = 180 # On regarde jusqu'à 6 mois en arrière pour les signaux faibles

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

# --- 3. SESSION & OUTILS ---

def creer_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
    })
    return session

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

def extraire_contenu_url(session, target_url):
    try:
        response = session.get(target_url, timeout=10)
        response.raise_for_status()
        ctype = response.headers.get('Content-Type', '').lower()
        
        if 'pdf' in ctype or target_url.endswith('.pdf'):
            if not est_recent_pdf(response.content): return None
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                return "".join([page.get_text() for page in doc[:10]])
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'form', 'header']): tag.decompose()
            # On cherche le contenu principal pour éviter le bruit du menu
            main = soup.find('main') or soup.find('article') or soup.find('div', class_=re.compile('content|main|article')) or soup.body
            return re.sub(r'\s+', ' ', main.get_text()).strip() if main else ""
    except: return None

# --- 4. DEEP SCANNING (La nouveauté) ---

def recuperer_liens_profonds(session, url_liste, domaine_racine, limite=5):
    """
    Visite une page liste (Actualités) et récupère les 5 premiers liens vers des articles.
    """
    liens_articles = []
    try:
        res = session.get(url_liste, timeout=15)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # On cherche tous les liens
        all_links = soup.find_all('a', href=True)
        
        exclude = ['contact', 'mentions', 'plan', 'accès', 'facebook', 'linkedin', 'twitter', 'instagram', 'connexion', 'agenda', 'newsletter']
        
        count = 0
        seen = set()
        
        for link in all_links:
            href = link['href']
            full_url = urljoin(url_liste, href)
            
            # Filtres stricts pour ne garder que les vrais articles
            if full_url in seen: continue
            if urlparse(full_url).netloc != urlparse(domaine_racine).netloc: continue # Reste sur le site
            if any(ex in full_url.lower() for ex in exclude): continue
            if len(link.get_text(strip=True)) < 5: continue # Ignore les liens vides ou icones
            
            # On considère que c'est un article si l'URL est plus longue que la racine + un slug
            if len(urlparse(full_url).path) > len(urlparse(url_liste).path) + 5:
                liens_articles.append(full_url)
                seen.add(full_url)
                count += 1
            
            if count >= limite: break
            
    except Exception as e:
        print(f"Erreur Deep Scan sur {url_liste}: {e}")
    
    return liens_articles

# --- 5. CERVEAU IA (Spécial Signaux Faibles & Administratifs) ---

def analyser_ia_urban_agency(texte, source, type_org):
    date_lim = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    
    prompt = f"""
    RÔLE : Expert Stratégie Urbaine & Développement.
    CONTEXTE : {source} ({type_org}).
    DATE LIMITE : {date_lim}.

    OBJECTIF : DÉTECTER LES ÉTAPES CLÉS D'UN PROJET URBAIN (Même administratives).
    
    CE QUE TU DOIS CHERCHER (SIGNAUX D'AFFAIRES) :
    1. **Le "Top Départ" Administratif** : 
       - "Création de ZAC", "Bilan de concertation", "Déclaration d'Utilité Publique (DUP)", "Arrêté préfectoral".
       - C'est CRITIQUE : cela signifie que le projet est validé et que les marchés vont sortir. SCORE = 3.
    
    2. **Les Études & Intentions (Signal Faible)** :
       - "Lancement d'une étude", "Diagnostic en cours", "Désignation de l'aménageur", "Appel à idées".
       - SCORE = 2.
       
    3. **L'Opérationnel (Signal Fort)** :
       - "Concours", "Appel à projets", "Permis de construire", "Chantier", "Inauguration".
       - SCORE = 2 ou 3 selon la taille.

    IGNORER (SCORE 0) : Vie de quartier, animations, menus cantine, petites voiries, nominations RH.

    FORMAT JSON STRICT :
    {{
      "titre": "Titre précis de l'action (ex: Création de la ZAC Bègles)",
      "theme": "Réglementaire / Étude / Opérationnel",
      "resume": "Explique pourquoi c'est une étape clé pour un architecte/urbaniste.",
      "chiffres_cles": "Surface / Budget / Logements (si dispo)",
      "maturite": "Administrative (ZAC/DUP) | Étude | Opérationnelle",
      "score": 0 | 1 | 2 | 3
    }}

    TEXTE :
    {texte[:15000]}
    """
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

# --- 6. FORMATAGE EMAIL ---

def generer_html(item, is_new):
    if item['score'] == 3: border, badge = "#e74c3c", "🔥 IMMINENT"
    elif item['score'] == 2: border, badge = "#f39c12", "⚡ STRATÉGIQUE"
    else: border, badge = "#27ae60", "👀 VEILLE"

    font_heading = "'DIN', 'DIN Pro', 'Roboto', Arial, sans-serif"
    
    return f"""
    <div style="border-left: 4px solid {border}; background: {'white' if is_new else '#f9f9f9'}; padding: 20px; margin-bottom: 20px; font-family:Arial, sans-serif;">
        <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
            <div style="color:#7f8c8d; font-size:12px; font-weight:bold; text-transform:uppercase;">{item['nom_source']}</div>
            <div style="background:{border}; color:white; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:bold;">{badge}</div>
        </div>
        <div style="font-family:{font_heading}; font-weight:700; color:#2c3e50; font-size:16px; margin-bottom:8px;">{item['titre']}</div>
        <div style="font-size:13px; color:#444; line-height:1.4;">{item['resume']}</div>
        <div style="margin-top:10px; font-size:11px; color:#c0392b; font-weight:bold;">📊 {item.get('chiffres_cles','')}</div>
        <div style="margin-top:8px; padding-top:8px; border-top:1px solid #eee; text-align:right;">
             <a href="{item['url']}" style="color:{border}; font-size:11px; text-decoration:none; font-weight:bold;">LIRE L'ACTE / L'ARTICLE →</a>
        </div>
    </div>
    """

def envoyer_mail(nouveaux, anciens):
    if not nouveaux and not anciens: return
    url = "https://api.brevo.com/v3/smtp/email"
    html = "".join([generer_html(x, True) for x in nouveaux]) + "<br><h3>HISTORIQUE</h3>" + "".join([generer_html(x, False) for x in anciens])
    
    body = f"""<html><body style='background:#f4f4f4; padding:20px;'><div style='max-width:600px; margin:auto; background:white; padding:20px;'><div style="text-align:center; padding-bottom:20px;"><img src="{LOGO_URL}" height="40"></div>{html}</div></body></html>"""
    
    requests.post(url, json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], "subject": f"UA_Veille_{datetime.now().strftime('%d/%m')}: {len(nouveaux)} Détections", "htmlContent": body}, headers={"api-key": BREVO_KEY})

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

    print("--- DÉMARRAGE DU DEEP SCAN ---")

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme")
        if not nom: continue
        
        # On prend juste une URL principale (Actu ou Presse) et on va fouiller dedans
        url_root = ligne.get("URL Actualités / Projets") or ligne.get("URL Communiqués de Presse")
        if not url_root: continue

        print(f"👉 Analyse Profonde : {nom}...")
        
        # 1. On récupère les liens des articles (Niveau 1)
        liens_a_scanner = recuperer_liens_profonds(session, url_root, url_root, limite=4)
        
        # 2. On scanne chaque article (Niveau 2)
        for lien in liens_a_scanner:
            if lien in historique: continue
            
            texte = extraire_contenu_url(session, lien)
            if texte and len(texte) > 500:
                print(f"   📖 Lecture : {lien}")
                data = analyser_ia_urban_agency(texte, nom, "Web Deep Scan")
                
                if data.get('score', 0) >= 2: # On ne garde que le significatif
                    info = {
                        "url": lien, "date_detection": datetime.now().strftime('%Y-%m-%d'),
                        "nom_source": nom, "titre": data.get('titre', 'Projet'),
                        "resume": data.get('resume', ''), "chiffres_cles": data.get('chiffres_cles', ''),
                        "score": data['score'], "maturite": data.get('maturite', '')
                    }
                    leads_new.append(info)
                    historique[lien] = info
                    print(f"   ✅ DÉTECTION : {info['titre']}")
                else:
                    # On marque comme vu pour ne pas le rescanner demain
                    historique[lien] = {"date_detection": datetime.now().strftime('%Y-%m-%d'), "score": 0}

    # Sauvegarde et Envoi
    leads_old = [v for k,v in historique.items() if k not in [x['url'] for x in leads_new] and v['score'] >= 2]
    leads_old.sort(key=lambda x: x['date_detection'], reverse=True)
    
    sauvegarder_historique(historique)
    envoyer_mail(leads_new, leads_old[:10]) # Top 10 historique
    print("✅ Terminé.")

if __name__ == "__main__":
    main()
