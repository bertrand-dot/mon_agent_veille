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
    
    # Nettoyage automatique des vieux dossiers
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

# --- 3. SESSION & OUTILS ---

def creer_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
        'Connection': 'keep-alive'
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

def est_grand_organisme(nom):
    return any(m in nom.lower() for m in ['epa', 'grand paris', 'métropole', 'metropole', 'part-dieu', 'défense', 'euratlantique'])

def type_organisme(nom):
    """Définit le type pour orienter l'IA"""
    nom_l = nom.lower()
    if any(x in nom_l for x in ['epa', 'epf', 'amenagement', 'aménagement']):
        return "EPA"
    if any(x in nom_l for x in ['métropole', 'metropole', 'ville', 'mairie', 'communauté']):
        return "METROPOLE"
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
                texte_final = "".join([page.get_text() for page in doc[:6]])
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'form', 'iframe']): tag.decompose()
            contenu = soup.find('main') or soup.find('article') or soup.body
            if contenu: texte_final = contenu.get_text(separator=' ')
                
        return nettoyer_texte(texte_final)
    except: return None

# --- 4. CERVEAU IA (PROMPT AVEC MATURITÉ) ---

def analyser_ia_urban_agency(texte, source, categorie, type_org):
    date_lim = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    
    prompt = f"""
    RÔLE
    Tu es Directeur du Développement d’Urban Agency (architecture / urbanisme).

    CONTEXTE
    Source : {source}
    Catégorie : {categorie}
    Type d’organisme : {type_org}
    Date limite validité : {date_lim} (Si antérieur -> SCORE 0)

    ADAPTATION STRATÉGIQUE
    - EPA / EPF : Prioriser restructuration lourde, friches, ZAC, actifs complexes.
    - MÉTROPOLE / VILLE : Prioriser équipements publics, concours, AMI.
    - AUTRE : Grille standard.

    GRILLE DE SCORE
    3 = Priorité forte (Alignement parfait + Maturité Moyenne/Elevée)
    2 = Intérêt modéré OU Maturité faible
    1 = Veille stratégique
    0 = Non pertinent / Trop vieux

    MATURITÉ (Critère clé)
    - Faible : intention, étude amont, pas de calendrier
    - Moyen : programmation, budget évoqué
    - Eleve : consultation, concours, calendrier annoncé

    THÈMES AUTORISÉS
    - Restructuration / Réhabilitation
    - Friches / ZAC / Waterfront
    - Équipement public
    - Logement
    - Autre

    FORMAT JSON STRICT
    {{
      "titre": "Titre court",
      "theme": "Thème choisi",
      "resume": "Résumé analytique",
      "maturite": "Faible | Moyen | Eleve",
      "score": 0 | 1 | 2 | 3
    }}

    TEXTE :
    {texte[:12000]}
    """
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

# --- 5. ENVOI EMAIL (DESIGN PRO) ---

def generer_html(item, is_new):
    # Couleurs Score
    if item['score'] == 3:
        border, badge_txt = "#e74c3c", "🔥 PRIORITÉ"
    elif item['score'] == 2:
        border, badge_txt = "#3498db", "✅ INTÉRÊT"
    else:
        border, badge_txt = "#27ae60", "👀 VEILLE"

    # Style Maturité
    mat = item.get('maturite', 'Inconnue').capitalize()
    color_mat = "#d35400" if "Eleve" in mat else "#f39c12" if "Moyen" in mat else "#7f8c8d"

    bg, txt, opac = ("white", "#2c3e50", "1") if is_new else ("#f9f9f9", "#95a5a6", "0.7")
    date_badge = "NOUVEAU" if is_new else f"Vu le {item['date_detection']}"
    
    icon = "🏗️" if "RESTRUCT" in item.get('theme','').upper() else "🏭" if "FRICHE" in item.get('theme','').upper() else "📌"
    
    return f"""
    <div style="opacity:{opac}; border-left: 5px solid {border}; background: {bg}; padding: 15px; margin-bottom: 10px; border-radius: 4px;">
        <div style="display:flex; justify-content:space-between; align-items:center;">
            <strong style="color:{txt}; font-size:14px;">{icon} {item['nom_source']}</strong>
            <div style="text-align:right;">
                <span style="background:{border}; color:white; padding:2px 6px; border-radius:3px; font-size:10px; font-weight:bold;">{badge_txt}</span>
                <span style="border:1px solid {color_mat}; color:{color_mat}; padding:1px 5px; border-radius:3px; font-size:10px; margin-left:3px;">Maturité {mat}</span>
            </div>
        </div>
        <div style="font-weight:bold; color:{txt}; font-size:15px; margin:8px 0;">{item['titre']}</div>
        <div style="font-size:13px; color:{txt}; line-height:1.4;">{item['resume']}</div>
        <div style="margin-top:8px; display:flex; justify-content:space-between; align-items:center;">
             <span style="font-size:10px; background:#eee; padding:2px 5px; border-radius:3px; color:#555;">{item['theme']}</span>
             <a href="{item['url']}" style="color:{border}; font-size:11px; text-decoration:none; font-weight:bold;">Voir Source →</a>
        </div>
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
    session = creer_session()

    lignes = []
    # Lecture CSV Robuste (Multi-encodage)
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open('cibles.csv', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    
    sep = ';' if lignes and ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=sep)
    
    exclude = ['contact', 'mentions', 'legales', 'connexion', 'login', 'cookies']
    print(f"--- Scan Démarré ({len(historique)} en mémoire) ---")

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme") or ligne.get("Nom de l'organisme")
        if not nom: continue
        
        org_type = type_organisme(nom)
        limite = 10 if est_grand_organisme(nom) else 5
        cpt = 0
        urls = {"Actu": ligne.get("URL Actualités / Projets"), "Presse": ligne.get("URL Communiqués de Presse"), "RAA": ligne.get("URL Délibérations / Actes (RAA)")}
        
        print(f"👉 {nom} ({org_type})")
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
                    if texte and len(texte) > 300:
                        data = analyser_ia_urban_agency(texte, nom, cat, org_type)
                        
                        if data.get('score', 0) >= 1:
                            info = {
                                "url": full_url, "date_detection": datetime.now().strftime('%Y-%m-%d'),
                                "nom_source": nom, "titre": data.get('titre', 'Projet'),
                                "theme": data.get('theme', 'Divers'), "resume": data.get('resume', ''),
                                "maturite": data.get('maturite', 'Non précisé'),
                                "score": data['score']
                            }
                            leads_new.append(info)
                            historique[full_url] = info
                            cpt += 1
                            print(f"   🔥 {info['titre']} (Maturité: {info['maturite']})")
            except: pass

    # TRI & SAUVEGARDE
    leads_old = [v for k,v in historique.items() if k not in [x['url'] for x in leads_new]]
    leads_old.sort(key=lambda x: x['date_detection'], reverse=True)
    
    sauvegarder_historique(historique)
    envoyer_mail(leads_new, leads_old)
    print("✅ Terminé & Rapport envoyé.")

if __name__ == "__main__":
    main()
