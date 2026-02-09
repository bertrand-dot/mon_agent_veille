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
JOURS_RETENTION = 90  # Recherche sur 3 mois glissants

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

    # Nettoyage automatique > 90 jours
    limit_date = datetime.now() - timedelta(days=JOURS_RETENTION)
    clean_data = {}
    for url, info in data.items():
        try:
            date_saved = datetime.strptime(info['date_detection'], '%Y-%m-%d')
            if date_saved > limit_date:
                clean_data[url] = info
        except: continue
    return clean_data

def sauvegarder_historique(historique):
    try:
        with open(HISTORY_FILE, 'w') as f: json.dump(historique, f, indent=2)
    except Exception as e: print(f"Erreur sauvegarde : {e}")

# --- 3. FILTRES TEMPORELS ---

def est_recent_pdf(pdf_content):
    """Vérifie métadonnées PDF < 90 jours."""
    try:
        with fitz.open(stream=pdf_content, filetype="pdf") as doc:
            metadata = doc.metadata
            date_str = metadata.get('creationDate', '') or metadata.get('modDate', '')
            if date_str.startswith('D:'):
                annee = int(date_str[2:6])
                mois = int(date_str[6:8])
                jour = int(date_str[8:10])
                date_pdf = datetime(annee, mois, jour)
                delta = datetime.now() - date_pdf
                return delta.days <= JOURS_RETENTION
    except: return True
    return True

# --- 4. EXTRACTION & ANALYSE ---

def est_grand_organisme(nom):
    mots = ['EPA', 'Grand Paris', 'Métropole', 'Eurométropole', 'Part-Dieu', 'La Défense', 'Euratlantique']
    return any(m.lower() in nom.lower() for m in mots)

def nettoyer_texte(texte):
    return re.sub(r'\s+', ' ', texte).strip()

def extraire_contenu_url(target_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(target_url, timeout=20, headers=headers)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        texte_final = ""
        
        if 'pdf' in content_type or target_url.lower().endswith('.pdf'):
            if not est_recent_pdf(response.content): return None
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                texte_final = "".join([page.get_text() for page in doc[:6]])
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'aside']): tag.decompose()
            contenu = soup.find('main') or soup.find('article') or soup.body
            if contenu: texte_final = contenu.get_text(separator=' ')
                
        return nettoyer_texte(texte_final)
    except: return None

def analyser_ia_urban_agency(texte, source, categorie):
    date_limite = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    prompt = f"""
    Rôle : Directeur Développement Urban Agency. Analyse ce texte ({source}).
    
    🚨 CRITÈRE TEMPOREL : Si document avant le {date_limite} -> Score 0 ("Trop vieux").

    ADN URBAN AGENCY :
    1. RESTRUCTURATION D'ACTIF / RÉHABILITATION (Priorité 🔥) -> Score 3
    2. FRICHES / ZAC / WATERFRONT -> Score 3
    3. ÉDUCATION / SPORT (>10M€) -> Score 3 (Sinon 0)
    4. LOGEMENT / QUARTIERS -> Score 2
    
    FORMAT JSON :
    {{
        "titre": "Titre court",
        "theme": "Restructuration / Friche / Waterfront / Éducation / Logement",
        "resume": "Résumé 1 phrase",
        "score": 0, 1, 2 ou 3
    }}
    TEXTE : {texte[:12000]}
    """
    try:
        res = model.generate_content(prompt)
        clean_json = res.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except: return {"score": 0}

# --- 5. EMAILING (Systématique) ---

def generer_bloc_html(item, is_new):
    if is_new:
        border, bg, txt, opac = "#e74c3c" if item['score']==3 else "#3498db", "white", "#2c3e50", "1"
        badge = "<span style='color:red; font-weight:bold; font-size:11px;'>🔥 NOUVEAU</span>"
    else:
        border, bg, txt, opac = "#bdc3c7", "#f9f9f9", "#95a5a6", "0.7"
        badge = f"<span style='color:#95a5a6; font-size:10px;'>Vu le {item['date_detection']}</span>"

    theme = item.get('theme', '').upper()
    icon = "🏗️" if "RESTRUCT" in theme else "🏭" if "FRICHE" in theme else "💧" if "WATER" in theme else "🎓" if "ÉDUC" in theme else "📌"

    return f"""
    <div style="opacity:{opac}; border-left: 5px solid {border}; background: {bg}; padding: 15px; margin-bottom: 10px; border-radius: 4px;">
        <div style="display:flex; justify-content:space-between;">
            <strong style="color:{txt}; font-size:14px;">{icon} {item['nom_source']}</strong>
            <div>{badge}</div>
        </div>
        <div style="font-weight:bold; color:{txt}; font-size:15px; margin:5px 0;">{item['titre']}</div>
        <div style="font-size:13px; color:{txt};">{item['resume']}</div>
        <div style="margin-top:8px; text-align:right;">
            <a href="{item['url']}" style="color:{border}; font-weight:bold; text-decoration:none; font-size:11px;">Voir Source →</a>
        </div>
    </div>
    """

def envoyer_mail(nouveaux, anciens):
    url = "https://api.brevo.com/v3/smtp/email"
    
    # SUJET DYNAMIQUE
    if len(nouveaux) > 0:
        sujet = f"⚡ Veille Immo : {len(nouveaux)} Opportunités (< 3 mois)"
        intro_text = "Voici les nouvelles détections du jour."
    else:
        sujet = "✅ Rapport Quotidien : R.A.S"
        intro_text = "Aucune nouvelle opportunité détectée ce matin. Voici pour rappel votre portefeuille en cours :"

    html_new = "".join([generer_bloc_html(x, True) for x in nouveaux])
    html_old = "".join([generer_bloc_html(x, False) for x in anciens])
    
    payload = {
        "sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": sujet,
        "htmlContent": f"""
        <html><body style="font-family:Helvetica, sans-serif; background:#f4f4f4; padding:20px;">
            <div style="max-width:600px; margin:auto; background:white; border-radius:8px; overflow:hidden;">
                <div style="background:#2c3e50; padding:20px; text-align:center; color:white;">
                    <h2 style="margin:0;">Urban Agency Dashboard</h2>
                    <p style="font-size:12px; color:#bdc3c7;">{datetime.now().strftime('%d/%m/%Y')}</p>
                </div>
                <div style="padding:20px;">
                    <p style="color:#555; font-style:italic; border-bottom:1px solid #eee; padding-bottom:15px;">
                        {intro_text}
                    </p>

                    {f'<h3 style="color:#e74c3c;">🔥 NOUVEAUTÉS DU JOUR</h3>{html_new}' if html_new else ''}
                    
                    <h3 style="color:#7f8c8d; border-bottom:1px solid #ddd; padding-bottom:5px; margin-top:30px;">🗄️ HISTORIQUE (Actifs)</h3>
                    {html_old if html_old else "<p style='color:#bdc3c7;'>Historique vide.</p>"}
                </div>
            </div>
        </body></html>
        """
    }
    requests.post(url, json=payload, headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return
    historique = charger_historique()
    print(f"🧠 Mémoire chargée : {len(historique)} dossiers.")

    leads_nouveaux = []
    
    lignes = []
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open('cibles.csv', mode='r', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    sep = ';' if lignes and ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=sep)
    
    exclude = ['contact', 'mentions', 'legales', 'connexion', 'login', 'cookies']
    print("--- Scan Temporel (90 jours) ---")

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
                res = requests.get(url_source.strip(), headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                soup = BeautifulSoup(res.text, 'html.parser')
                for link in soup.find_all('a', href=True):
                    if cpt >= limite: break
                    href = link['href']
                    full_url = urljoin(url_source.strip(), href)

                    if any(excl in full_url.lower() for excl in exclude): continue
                    if urlparse(full_url).netloc != urlparse(url_source).netloc and 'epa' not in full_url: continue
                    if full_url in historique: continue 
                    
                    texte = extraire_contenu_url(full_url)
                    if texte and len(texte) > 300:
                        data_ia = analyser_ia_urban_agency(texte, nom, cat)
                        if data_ia.get('score', 0) >= 2:
                            info = {
                                "url": full_url, "date_detection": datetime.now().strftime('%Y-%m-%d'),
                                "nom_source": nom, "titre": data_ia.get('titre', 'Projet'),
                                "theme": data_ia.get('theme', 'Divers'), "resume": data_ia.get('resume', ''),
                                "score": data_ia['score']
                            }
                            leads_nouveaux.append(info)
                            historique[full_url] = info
                            cpt += 1
                            print(f"   🔥 RETENU : {info['titre']}")
            except: pass

    # TRI & SAUVEGARDE
    leads_anciens = [v for k,v in historique.items() if k not in [x['url'] for x in leads_nouveaux]]
    leads_anciens.sort(key=lambda x: x['date_detection'], reverse=True)
    sauvegarder_historique(historique)
    
    # ENVOI SYSTÉMATIQUE (Même si vide)
    envoyer_mail(leads_nouveaux, leads_anciens)
    print("✅ Rapport envoyé (Positif ou Négatif).")

if __name__ == "__main__":
    main()
