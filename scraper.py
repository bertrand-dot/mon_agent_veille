import os
import requests
import json
import logging
import time
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
        logging.info("✅ IA Gemini 3 Flash Preview activée.")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. COLLECTE ---

def extraire_texte_page(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, timeout=12, headers=headers)
        if res.status_code != 200: return ""
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
        return " ".join(soup.get_text(separator=' ').split())[:8000]
    except: return ""

def chercher_serpapi(cible):
    query = f'"{cible}" (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 20, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. ANALYSE IA (MODÈLE 3-FLASH) ---

def analyser_ia(item, contenu_web):
    if not client: return {"score": 0}
    time.sleep(1) # Cadencement de sécurité
    
    contexte = contenu_web if len(contenu_web) > 300 else item.get('snippet', '')
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    MISSION : Analyser l'opportunité urbaine à Bordeaux.
    
    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site",
      "score": 0,
      "procedure": "Type de procédure",
      "deadline": "Horizon temporel",
      "budget": "Budget/Surface",
      "partenaires": "Bailleurs, Promoteurs ou BET cités ou logiques",
      "analyse": "Analyse stratégique (3 phrases max)",
      "action": "Action recommandée"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        # Utilisation du modèle gemini-3-flash-preview
        response = client.models.generate_content(
            model="gemini-3-flash-preview", 
            contents=prompt
        )
        text_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_json)
        return data
    except Exception as e:
        logging.warning(f"⚠️ Erreur IA : {e}")
        return {"score": 0}

# --- 4. DESIGN DU RAPPORT ---

def envoyer_mail(resultats):
    if not resultats: 
        logging.info("📩 Aucun signal pertinent (Score < 1).")
        return
    
    font_header = "'DIN', 'Alternate Gothic', 'Impact', sans-serif"
    font_body = "Arial, Helvetica, sans-serif"
    
    blocs = ""
    for o in sorted(resultats, key=lambda x: x.get('score', 0), reverse=True):
        stars = "⭐" * int(o.get('score', 0))
        blocs += f"""
        <div style="border: 1px solid #e0e0e0; margin-bottom: 30px; background: #ffffff; border-radius: 4px; overflow: hidden;">
            <div style="background: #2c3e50; color: #ffffff; padding: 15px 20px; font-family: {font_header}; text-transform: uppercase;">
                <table width="100%"><tr>
                    <td style="font-size: 18px; letter-spacing: 1px;">🏗️ {o.get('projet')}</td>
                    <td align="right">{stars}</td>
                </tr></table>
            </div>
            <div style="padding: 12px 20px; background: #f8f9fa; border-bottom: 1px solid #eee; font-family: {font_body}; font-size: 11px; color: #666;">
                <table width="100%"><tr>
                    <td width="25%">📝 <b>PROCÉDURE:</b> {o.get('procedure')}</td>
                    <td width="25%">📅 <b>DEADLINE:</b> {o.get('deadline')}</td>
                    <td width="25%">💰 <b>BUDGET:</b> {o.get('budget')}</td>
                    <td width="25%">🤝 <b>PARTENAIRES:</b> {o.get('partenaires')}</td>
                </tr></table>
            </div>
            <div style="padding: 20px; font-family: {font_body};">
                <p style="font-size: 14px; color: #333; line-height: 1.6;">{o.get('analyse')}</p>
                <div style="background: #f0fdf4; padding: 15px; border-radius: 4px; border-left: 4px solid #22c55e; color: #166534; font-size: 13px; font-weight: bold;">
                    💡 ACTION : {o.get('action')}
                </div>
            </div>
        </div>"""

    full_html = f"""<html><body style="background: #f3f4f6; margin: 0; padding: 0;">
        <div style="background: #ffffff; padding: 30px 0; text-align: center; border-bottom: 1px solid #e5e7eb;">
            <img src="{LOGO_URL}" height="60">
        </div>
        <div style="max-width: 800px; margin: 40px auto; padding: 0 20px;">
            <h1 style="font-family: {font_header}; text-align: center; text-transform: uppercase;">Radar UA - Bordeaux</h1>
            {blocs}
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🎯 Radar UA : {len(resultats)} Signaux Bordeaux", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. EXECUTION ---

def main():
    logging.info("🚀 Scan final avec Gemini 3-Flash-Preview...")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "Mairie de Bordeaux", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation : {cible}")
        items = chercher_serpapi(cible)
        for i in items:
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            if isinstance(analyse, dict) and int(analyse.get('score', 0)) >= 1:
                resultats.append({"url": url, **analyse})
                logging.info(f"   🎯 Signal identifié : {analyse.get('projet')}")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
