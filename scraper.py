import os
import requests
import json
import logging
import time
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

# --- 1. CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        logging.info("✅ Moteur Gemini 2.5 Pro activé (Analyse Haute Précision).")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. EXTRACTION EXPERTE (HTML & PDF) ---

def extraire_texte_page(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    try:
        res = requests.get(url, timeout=15, headers=headers)
        if res.status_code != 200: return ""
        content_type = res.headers.get('Content-Type', '').lower()
        
        if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
            doc = fitz.open(stream=res.content, filetype="pdf")
            text = "".join([page.get_text() for page in doc[:10]])
            doc.close()
            return " ".join(text.split())[:12000] # Capacité accrue pour le modèle Pro
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
            return " ".join(soup.get_text(separator=' ').split())[:10000]
    except Exception as e:
        logging.warning(f"⚠️ Erreur extraction : {e}")
        return ""

def chercher_serpapi(cible):
    query = f'"{cible}" (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 20, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. ANALYSE STRATÉGIQUE (GEMINI 2.5 PRO) ---

def analyser_ia(item, contenu_web):
    if not client: return {"score_etoiles": 0}
    # Le modèle Pro demande un cadencement plus lent en version gratuite
    time.sleep(12) 
    
    contexte = contenu_web if len(contenu_web) > 400 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement pour URBAN AGENCY (Copenhague & Dublin).
    CONTEXTE : Nous sommes une agence d'architecture et d'urbanisme experte en régénération de friches, haute densité qualitative, et design iconique nordique.
    
    MISSION : Évaluer si ce projet bordelais justifie une action commerciale ou créative de notre part.
    
    CRITÈRES DE FILTRAGE :
    - Échelle : Priorité aux projets > 5 000 m² ou à fort impact urbain.
    - Expertise UA : Le projet nécessite-t-il une expertise en bois, gestion de l'eau, ou réversibilité (Nordic Added Value) ?
    - Score (1-5⭐) : 5 = Concours de maîtrise d'œuvre ou consultation promoteur imminente sur site majeur. 1 = Info administrative mineure.

    FORMAT JSON STRICT :
    {{
      "projet": "Nom précis du projet",
      "score_etoiles": 0,
      "temperature": "CHAUDE (Action < 12 mois) ou FROIDE (Vision long terme)",
      "expertise_requise": "Compétence spécifique UA à mettre en avant",
      "procedure": "Type de marché ou procédure foncière",
      "deadline": "Échéance opérationnelle",
      "partenaires": "Aménageurs, Promoteurs ou Bailleurs clés",
      "analyse_ua": "Analyse stratégique : pourquoi ce dossier est pour nous ? (max 3 phrases)",
      "action": "Action concrète pour Bertrand"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        text_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_json)
        data['score_etoiles'] = min(int(data.get('score_etoiles', 0)), 5)
        return data
    except Exception as e:
        logging.warning(f"⚠️ Erreur IA : {e}")
        return {"score_etoiles": 0}

# --- 4. INTERFACE MAIL (DESIGN DIN/ARIAL + BADGES) ---

def envoyer_mail(resultats):
    if not resultats: return
    
    font_header = "'DIN', 'Alternate Gothic', 'Impact', sans-serif"
    font_body = "Arial, Helvetica, sans-serif"
    
    blocs = ""
    # Tri par score décroissant
    for o in sorted(resultats, key=lambda x: x.get('score_etoiles', 0), reverse=True):
        stars = "⭐" * o.get('score_etoiles', 0)
        is_chaude = "CHAUDE" in o.get('temperature', '').upper()
        temp_color = "#e74c3c" if is_chaude else "#3498db"
        temp_label = "🔥 LEAD CHAUDE" if is_chaude else "❄️ VISION STRATÉGIQUE"
        
        blocs += f"""
        <div style="border: 1px solid #e0e0e0; margin-bottom: 40px; background: #ffffff; border-radius: 4px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
            <div style="background: #2c3e50; color: #ffffff; padding: 18px 25px; font-family: {font_header}; text-transform: uppercase;">
                <table width="100%"><tr>
                    <td style="font-size: 20px; letter-spacing: 1px;">
                        <span style="background:{temp_color}; padding:2px 10px; border-radius:3px; font-size:11px; vertical-align:middle; margin-right:15px; font-family:sans-serif;">{temp_label}</span>
                        {o.get('projet')}
                    </td>
                    <td align="right" style="font-size: 18px;">{stars}</td>
                </tr></table>
            </div>
            <div style="padding: 15px 25px; background: #f8f9fa; border-bottom: 1px solid #eeeeee; font-family: {font_body}; font-size: 12px; color: #555;">
                <table width="100%"><tr>
                    <td width="33%">📝 <b>PROCÉDURE :</b> {o.get('procedure')}</td>
                    <td width="33%">📅 <b>DEADLINE :</b> {o.get('deadline')}</td>
                    <td width="34%">🤝 <b>ACTEURS :</b> {o.get('partenaires')}</td>
                </tr></table>
            </div>
            <div style="padding: 25px; font-family: {font_body};">
                <p style="margin: 0 0 15px 0; font-size: 15px; color: #333; line-height: 1.7;"><b>L'ANALYSE UA :</b> {o.get('analyse_ua')}</p>
                <div style="margin-bottom: 15px; font-size: 13px; color: #7f8c8d;">💡 <b>ANGLAGE EXPERTISE :</b> {o.get('expertise_requise')}</div>
                <div style="background: #f0fdf4; padding: 18px; border-radius: 4px; border-left: 5px solid #22c55e; color: #166534; font-size: 14px; font-weight: bold;">
                    🎯 ACTION : {o.get('action')}
                </div>
                <div style="margin-top: 20px; text-align: right;">
                    <a href="{o.get('url')}" style="color: #3b82f6; text-decoration: none; font-size: 12px; font-weight: bold; border: 1px solid #3b82f6; padding: 5px 15px; border-radius: 20px;">SOURCE DOCUMENTAIRE →</a>
                </div>
            </div>
        </div>"""

    full_html = f"""<html><body style="background: #f3f4f6; margin: 0; padding: 30px;">
        <div style="max-width: 850px; margin: 0 auto;">
            <div style="background: #ffffff; padding: 30px; text-align: center; border-bottom: 2px solid #2c3e50;">
                <img src="{LOGO_URL}" height="65">
            </div>
            <h1 style="font-family: {font_header}; text-align: center; text-transform: uppercase; margin: 40px 0; font-size: 32px; letter-spacing: 2px; color: #111;">Intelligence Territoriale - Radar UA</h1>
            {blocs}
            <div style="text-align: center; font-family: {font_body}; font-size: 11px; color: #95a5a6; margin-top: 50px;">
                Ce rapport a été généré par le moteur Gemini 2.5 Pro pour Urban Agency Copenhagen/Dublin.
            </div>
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🔥 {len(resultats)} Opportunités UA : Focus Bordeaux", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. EXECUTION ---

def main():
    logging.info("🚀 Lancement du Radar UA Expertise (Modèle 2.5 Pro)")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "Mairie de Bordeaux", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation stratégique : {cible}")
        for i in chercher_serpapi(cible):
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            # On ne garde que les dossiers avec une réelle pertinence (Score >= 2 pour le modèle Pro)
            if isinstance(analyse, dict) and int(analyse.get('score_etoiles', 0)) >= 2:
                resultats.append({"url": url, **analyse})
                logging.info(f"   🎯 Lead Identifié : {analyse.get('projet')} ({analyse.get('score_etoiles')}⭐)")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
