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
        logging.info("✅ Moteur Gemini 2.5 Pro activé (Analyse Stratégique).")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. EXTRACTION EXPERTE (PDF & HTML) ---

def extraire_texte_page(url):
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    try:
        res = requests.get(url, timeout=15, headers=headers)
        if res.status_code != 200: return ""
        content_type = res.headers.get('Content-Type', '').lower()
        
        if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
            doc = fitz.open(stream=res.content, filetype="pdf")
            text = "".join([page.get_text() for page in doc[:10]])
            doc.close()
            return " ".join(text.split())[:12000]
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
            return " ".join(soup.get_text(separator=' ').split())[:10000]
    except: return ""

def chercher_serpapi(cible):
    query = f'"{cible}" (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 20, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. ANALYSE IA (ADN URBAN AGENCY - CPH/DUB) ---

def analyser_ia(item, contenu_web):
    if not client: return {"score_etoiles": 0}
    # Le modèle Pro demande une pause plus longue pour respecter les quotas Free (2-5 RPM)
    time.sleep(12) 
    
    contexte = contenu_web if len(contenu_web) > 400 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement pour l'agence URBAN AGENCY (Bureaux à Copenhague et Dublin).
    ADN : Nous créons des projets iconiques, à haute densité qualitative, avec une expertise forte en régénération de friches complexes et urbanisme nordique durable.
    
    MISSION : Évaluer si ce projet bordelais est une opportunité opérationnelle pour nous.
    
    VOTRE GRILLE D'ANALYSE (Score sur 5 étoiles) :
    - 1-2⭐ (Bruit) : Projets associatifs, permis de construire mineurs, petites rénovations sans enjeu architectural global.
    - 3⭐ (Intéressant) : Études de programmation, petites ZAC, opportunités de concours restreints.
    - 4-5⭐ (Prioritaire) : Grands ensembles urbains (>10k m²), mutation de sites portuaires/ferroviaires, projets iconiques publics, besoins critiques en résilience climatique.

    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site / dossier",
      "score_etoiles": 0,
      "temperature": "CHAUDE (Marché/Concours < 12 mois) ou FROIDE (Vision/Stratégie 3-5 ans)",
      "procedure": "ZAC, Concours, PUP, MGPE, etc.",
      "deadline": "Horizon temporel de l'action",
      "budget": "Surface ou montant mentionné",
      "partenaires": "Aménageurs, Promoteurs ou Élus impliqués",
      "analyse_ua": "Analyse critique : pourquoi UA doit y aller ? Quelle valeur ajoutée (Nordic/Irish) apporter ?",
      "action": "Action immédiate pour Bertrand"
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

# --- 4. DESIGN DU RAPPORT (DIN & ARIAL - VISUEL HOT/COLD) ---

def envoyer_mail(resultats):
    if not resultats: return
    font_h = "'DIN', 'Alternate Gothic', sans-serif"; font_b = "Arial, Helvetica, sans-serif"
    blocs = ""
    
    for o in sorted(resultats, key=lambda x: x.get('score_etoiles', 0), reverse=True):
        stars = "⭐" * o.get('score_etoiles', 0)
        is_hot = "CHAUDE" in o.get('temperature', '').upper()
        badge_color = "#e74c3c" if is_hot else "#3498db"
        badge_text = "🔥 LEAD CHAUDE" if is_hot else "❄️ VISION LONG TERME"
        
        blocs += f"""
        <div style="border: 1px solid #e0e0e0; margin-bottom: 35px; background: #ffffff; border-radius: 4px; overflow: hidden; box-shadow: 0 4px 10px rgba(0,0,0,0.05);">
            <div style="background: #2c3e50; color: #ffffff; padding: 15px 20px; font-family: {font_h}; text-transform: uppercase;">
                <table width="100%"><tr>
                    <td style="font-size: 18px; letter-spacing: 1px;">
                        <span style="background:{badge_color}; padding:2px 8px; border-radius:3px; font-size:10px; vertical-align:middle; margin-right:12px; font-family:sans-serif;">{badge_text}</span>
                        {o.get('projet')}
                    </td>
                    <td align="right" style="font-size: 16px;">{stars}</td>
                </tr></table>
            </div>
            
            <div style="padding: 10px 20px; background: #f8f9fa; border-bottom: 1px solid #eeeeee; font-family: {font_b}; font-size: 11px; color: #666666;">
                <b>TYPE :</b> {o.get('procedure')} | <b>ÉCHÉANCE :</b> {o.get('deadline')} | <b>ACTEURS :</b> {o.get('partenaires')}
            </div>
            
            <div style="padding: 20px; font-family: {font_b};">
                <p style="font-size: 14px; color: #333; line-height: 1.6; margin: 0 0 15px 0;"><b>ANALYSE UA :</b> {o.get('analyse_ua')}</p>
                <div style="background: #f0fdf4; padding: 15px; border-radius: 4px; border-left: 5px solid #22c55e; color: #166534; font-size: 13px; font-weight: bold;">
                    🎯 ACTION : {o.get('action')}
                </div>
                <div style="text-align: right; margin-top: 15px;">
                    <a href="{o.get('url')}" style="color: #3b82f6; text-decoration: none; font-size: 11px; font-weight: bold; border: 1px solid #3b82f6; padding: 5px 12px; border-radius: 20px;">VOIR LA SOURCE →</a>
                </div>
            </div>
        </div>"""

    full_html = f"""<html><body style="background: #f3f4f6; margin: 0; padding: 20px;">
        <div style="max-width: 800px; margin: 0 auto;">
            <div style="background: #ffffff; padding: 30px; text-align: center; border-bottom: 3px solid #2c3e50;">
                <img src="{LOGO_URL}" height="60">
            </div>
            <h1 style="font-family: {font_h}; text-align: center; text-transform: uppercase; margin: 40px 0; font-size: 28px; color: #111;">Radar Stratégique Bordeaux</h1>
            {blocs}
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🔥 {len(resultats)} Signaux Qualifiés : Urban Agency Bordeaux", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. EXECUTION ---

def main():
    logging.info("🚀 Scan Haute Précision UA (Gemini 2.5 Pro)")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "Mairie de Bordeaux", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation : {cible}")
        for i in chercher_serpapi(cible):
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            # On ne garde que les leads sérieux (Score >= 2)
            if isinstance(analyse, dict) and int(analyse.get('score_etoiles', 0)) >= 2:
                resultats.append({"url": url, **analyse})
                logging.info(f"   🎯 Lead : {analyse.get('projet')} ({analyse.get('score_etoiles')}⭐)")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
