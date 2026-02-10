import os
import requests
import json
import re
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai
from datetime import datetime, timedelta

# --- 1. PARAMÈTRES DU TEST (À REMPLIR) ---
# Collez vos clés ici pour le test (entre guillemets)
API_GEMINI = "VOTRE_CLE_GEMINI_ICI"
API_BREVO = "VOTRE_CLE_BREVO_ICI"

# La cible unique à tester
URL_CIBLE = "https://www.exemple.com/actualites/projet-zac.pdf"
NOM_ORGANISME = "Mairie de Test"  # Important pour le contexte de l'IA

# --- CONFIGURATION ---
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
JOURS_RETENTION = 90

# Configuration IA
if "VOTRE_CLE" in API_GEMINI:
    print("❌ ERREUR : Vous devez coller vos clés API lignes 12 et 13 !")
    exit()

genai.configure(api_key=API_GEMINI)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. OUTILS (IDENTIQUES AU SCRAPER PRINCIPAL) ---

def creer_session():
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8'
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

def type_organisme(nom):
    nom_l = nom.lower()
    if any(x in nom_l for x in ['epa', 'epf', 'amenagement']): return "EPA"
    if any(x in nom_l for x in ['métropole', 'metropole', 'ville', 'mairie']): return "METROPOLE"
    return "AUTRE"

def nettoyer_texte(texte):
    return re.sub(r'\s+', ' ', texte).strip()

def extraire_contenu_url(session, target_url):
    print(f"🔄 Lecture de : {target_url}")
    try:
        response = session.get(target_url, timeout=20)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        texte_final = ""
        
        if 'pdf' in content_type or target_url.lower().endswith('.pdf'):
            print("   📄 Type : PDF")
            if not est_recent_pdf(response.content):
                print("   ❌ PDF Trop vieux (Date métadata > 90 jours)")
                return None
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                texte_final = "".join([page.get_text() for page in doc[:6]])
        else:
            print("   🌐 Type : Page Web")
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'aside', 'form', 'iframe']): tag.decompose()
            contenu = soup.find('main') or soup.find('article') or soup.body
            if contenu: texte_final = contenu.get_text(separator=' ')
                
        return nettoyer_texte(texte_final)
    except Exception as e:
        print(f"   ❌ Erreur technique : {e}")
        return None

def analyser_ia_urban_agency(texte, source, type_org):
    print("🧠 Analyse IA en cours...")
    date_lim = (datetime.now() - timedelta(days=JOURS_RETENTION)).strftime('%d/%m/%Y')
    
    prompt = f"""
    RÔLE : Directeur Dév. Urban Agency.
    CONTEXTE : {source} ({type_org})
    DATE LIMITE : {date_lim} (Si antérieur -> SCORE 0)

    STRATÉGIE : Priorité Restructuration lourde, Friches, ZAC, Équipements >10M€.

    TACHE : Analyse ce texte isolé pour un test de validation.

    FORMAT JSON STRICT :
    {{
      "titre": "Titre court",
      "theme": "Restructuration / Friche / Waterfront / Équipement public / Logement",
      "resume": "Résumé analytique (2 phrases)",
      "chiffres_cles": "ex: 'Budget 15M€' ou 'Non précisé'",
      "maturite": "Faible | Moyen | Eleve",
      "score": 0 | 1 | 2 | 3
    }}

    TEXTE :
    {texte[:12000]}
    """
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except Exception as e:
        print(f"❌ Erreur IA : {e}")
        return {"score": 0}

# --- 3. FORMATAGE & ENVOI (DESIGN PRO) ---

def generer_html(item):
    # Couleurs
    if item['score'] == 3: border = "#e74c3c"
    elif item['score'] == 2: border = "#2980b9"
    else: border = "#27ae60"

    mat = item.get('maturite', 'Inconnue').capitalize()
    color_mat = "#d35400" if "Eleve" in mat else "#f39c12" if "Moyen" in mat else "#95a5a6"
    
    icon = "🏗️" if "RESTRUCT" in item.get('theme','').upper() else "🏭" if "FRICHE" in item.get('theme','').upper() else "📌"
    font_heading = "'DIN', 'DIN Pro', 'Roboto', 'Helvetica Neue', Helvetica, Arial, sans-serif"
    font_body = "Arial, sans-serif"

    return f"""
    <div style="border-left: 4px solid {border}; background: #ffffff; padding: 20px; margin-bottom: 20px; font-family:{font_body}; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
        <div style="display:flex; justify-content:space-between; align-items:flex-start; margin-bottom:10px;">
            <div style="font-family:{font_heading}; text-transform:uppercase; font-size:12px; letter-spacing:1px; color:#7f8c8d;">
                {icon} {item['nom_source']} (TEST UNITAIRE)
            </div>
            <div style="text-align:right;">
                <span style="font-family:{font_heading}; color:#e74c3c; font-size:10px; font-weight:bold;">NOUVEAU</span><br>
                <span style="font-size:10px; color:{color_mat}; font-weight:bold;">Maturité {mat}</span>
            </div>
        </div>
        <div style="font-family:{font_heading}; font-weight:700; color:#2c3e50; font-size:16px; margin-bottom:8px;">{item['titre']}</div>
        <div style="font-size:13px; color:#444; line-height:1.5; margin-bottom:10px;">{item['resume']}</div>
        <div style="background-color:#f4f6f7; padding:8px 12px; border-radius:2px; font-size:12px; color:#2c3e50; font-weight:bold; display:inline-block; margin-bottom:10px; border-left:2px solid #bdc3c7;">
            📊 {item.get('chiffres_cles', 'Non précisé')}
        </div>
        <div style="margin-top:5px; padding-top:10px; border-top:1px solid #eee; display:flex; justify-content:space-between; align-items:center;">
             <span style="font-size:10px; color:#95a5a6; text-transform:uppercase;">{item['theme']}</span>
             <a href="{item['url']}" style="color:{border}; font-family:{font_heading}; font-size:11px; text-decoration:none; font-weight:bold;">ACCÉDER À LA SOURCE →</a>
        </div>
    </div>
    """

def envoyer_mail_test(item):
    url = "https://api.brevo.com/v3/smtp/email"
    date_jour = datetime.now().strftime('%d/%m/%Y')
    
    font_heading = "'DIN', 'DIN Pro', 'Roboto', 'Helvetica', Arial, sans-serif"
    
    html_card = generer_html(item)
    
    body = f"""
    <html>
    <head><link href="https://fonts.googleapis.com/css2?family=Roboto:wght@400;700&display=swap" rel="stylesheet"></head>
    <body style="margin:0; padding:0; background-color:#f4f4f4; font-family:Arial, sans-serif;">
        <div style="max-width:650px; margin:0 auto; background-color:#ffffff; min-height:100vh;">
            <div style="padding:30px 20px; text-align:center; border-bottom:1px solid #eeeeee;">
                <img src="{LOGO_URL}" alt="URBAN AGENCY" style="max-height:50px; width:auto;">
            </div>
            <div style="padding:40px 20px 20px 20px; text-align:center;">
                <p style="font-family:{font_heading}; font-size:10px; letter-spacing:2px; text-transform:uppercase; color:#95a5a6; margin:0;">TEST UNITAIRE • {date_jour}</p>
                <h1 style="font-family:{font_heading}; font-size:24px; letter-spacing:1px; text-transform:uppercase; color:#2c3e50; margin:10px 0;">1 RÉSULTAT DE TEST</h1>
            </div>
            <div style="padding:0 20px 40px 20px;">
                {html_card}
                <div style="margin:20px 0; font-size:12px; color:#7f8c8d; text-align:center; background:#eee; padding:10px; border-radius:4px;">
                    Ceci est un test manuel déclenché pour valider l'URL :<br>
                    <a href="{item['url']}" style="color:#555;">{item['url']}</a>
                </div>
            </div>
            <div style="background-color:#2c3e50; color:white; padding:20px; text-align:center; font-size:10px; font-family:{font_heading}; letter-spacing:1px;">URBAN AGENCY • INTELLIGENCE ARTIFICIELLE</div>
        </div>
    </body>
    </html>
    """
    
    print("📧 Envoi de l'email via Brevo...")
    try:
        r = requests.post(url, json={"sender": {"name": "IA Urban Agency (Test)", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], "subject": f"⚡ TEST CIBLE : {item['titre']}", "htmlContent": body}, headers={"api-key": API_BREVO})
        if r.status_code in [200, 201, 202]:
            print("✅ Email envoyé avec succès ! Vérifiez votre boîte de réception.")
        else:
            print(f"❌ Erreur Brevo : {r.text}")
    except Exception as e:
        print(f"❌ Erreur connexion : {e}")

# --- 4. EXÉCUTION DU TEST ---

if __name__ == "__main__":
    print(f"--- 🧪 DÉMARRAGE DU TEST CIBLÉ SUR : {NOM_ORGANISME} ---")
    
    session = creer_session()
    texte = extraire_contenu_url(session, URL_CIBLE)
    
    if texte and len(texte) > 300:
        print(f"✅ Contenu extrait ({len(texte)} caractères).")
        
        # Filtrage bruit (Optionnel pour le test mais présent dans le main)
        mots_bruit = ['menu', 'cantine', 'vaccination', 'concert']
        if any(b in texte.lower() for b in mots_bruit):
            print("⚠️ Attention : Ce texte contient des mots-clés de 'Bruit' (ex: menu, cantine).")
        
        type_org = type_organisme(NOM_ORGANISME)
        data = analyser_ia_urban_agency(texte, NOM_ORGANISME, type_org)
        
        print("\n📊 RÉSULTAT IA :")
        print(json.dumps(data, indent=4, ensure_ascii=False))
        
        # Préparation de l'objet pour l'email
        item = {
            "url": URL_CIBLE,
            "date_detection": datetime.now().strftime('%Y-%m-%d'),
            "nom_source": NOM_ORGANISME,
            "titre": data.get('titre', 'Sans titre'),
            "theme": data.get('theme', 'Autre'),
            "resume": data.get('resume', 'Pas de résumé'),
            "chiffres_cles": data.get('chiffres_cles', 'Non précisé'),
            "maturite": data.get('maturite', 'Inconnue'),
            "score": data.get('score', 0)
        }
        
        envoyer_mail_test(item)
        
    else:
        print("❌ Échec : Impossible d'extraire le texte (Page vide, bloquée ou trop courte).")
