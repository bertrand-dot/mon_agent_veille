import os
import requests
import csv
import json
import logging
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

# Initialisation du client IA (Standard 2026)
client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        logging.info("✅ Moteur Gemini 2.5 Flash activé.")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. FONCTIONS DE COLLECTE ---

def extraire_texte_page(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, timeout=12, headers=headers)
        if res.status_code != 200: return ""
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
        text = soup.get_text(separator=' ')
        return " ".join(text.split())[:7000]
    except: return ""

def chercher_serpapi(cible):
    query = f'"{cible}" (Bordeaux OR Métropole) (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 30, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. MOTEUR DE RAISONNEMENT ---

def analyser_ia(item, contenu_web):
    if not client: return {"score": 0}
    contexte = contenu_web if len(contenu_web) > 300 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    MISSION : Extraire les données CRITIQUES d'un projet urbain à Bordeaux.
    
    CONSIGNES :
    - Score : Sur 5 (1: Veille, 5: Priorité absolue).
    - Analyse : 3 phrases maximum.
    - Identification précise de la PROCEDURE, DEADLINE et BUDGET.

    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site",
      "score": 0,
      "procedure": "Type de procédure",
      "deadline": "Horizon temporel",
      "budget": "Budget ou surface",
      "analyse": "Analyse stratégique",
      "action": "Action recommandée"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
        text_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_json)
        return {
            "projet": data.get("projet", item.get("title", "Projet inconnu")),
            "score": int(data.get("score", 0)),
            "procedure": data.get("procedure", "N/A"),
            "deadline": data.get("deadline", "N/A"),
            "budget": data.get("budget", "N/A"),
            "analyse": data.get("analyse", "Analyse en consultant la source."),
            "action": data.get("action", "Surveiller le dossier.")
        }
    except:
        return {"score": 0}

# --- 4. INTERFACE GRAPHIQUE (FONTS DIN & ARIAL) ---

def envoyer_mail(resultats):
    if not resultats: return
    date_str = datetime.now().strftime('%d/%m/%Y')
    
    # Font-stacks
    font_header = "'DIN', 'Alternate Gothic', 'Impact', sans-serif"
    font_body = "Arial, Helvetica, sans-serif"
    
    blocs = ""
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        stars = "⭐" * int(o.get('score', 0))
        color = "#2c3e50" # Couleur Urban Agency
        
        blocs += f"""
        <div style="border: 1px solid #e0e0e0; margin-bottom: 30px; background: #ffffff; border-radius: 4px; overflow: hidden; box-shadow: 0 4px 6px rgba(0,0,0,0.02);">
            <div style="background: #2c3e50; color: #ffffff; padding: 15px 20px; font-family: {font_header}; text-transform: uppercase;">
                <table width="100%">
                    <tr>
                        <td style="font-size: 18px; letter-spacing: 1px;">🏗️ {o.get('projet')}</td>
                        <td align="right" style="font-size: 16px;">{stars}</td>
                    </tr>
                </table>
            </div>
            
            <div style="padding: 12px 20px; background: #f8f9fa; border-bottom: 1px solid #eeeeee; font-family: {font_body}; font-size: 12px; color: #666666;">
                <table width="100%">
                    <tr>
                        <td width="33%">📝 <b>PROCÉDURE :</b> {o.get('procedure')}</td>
                        <td width="33%">📅 <b>DEADLINE :</b> <span style="color: #d35400; font-weight: bold;">{o.get('deadline')}</span></td>
                        <td width="33%">💰 <b>BUDGET/SURFACE :</b> {o.get('budget')}</td>
                    </tr>
                </table>
            </div>
            
            <div style="padding: 20px; font-family: {font_body};">
                <p style="margin: 0 0 15px 0; font-size: 14px; color: #333333; line-height: 1.6;">{o.get('analyse')}</p>
                
                <div style="background: #f0fdf4; padding: 15px; border-radius: 4px; border-left: 4px solid #22c55e; color: #166534; font-size: 13px;">
                    💡 <b>ACTION :</b> {o.get('action')}
                </div>
                
                <div style="margin-top: 15px; text-align: right;">
                    <a href="{o.get('url')}" style="color: #3b82f6; text-decoration: none; font-size: 12px; font-weight: bold;">CONSULTER LA SOURCE →</a>
                </div>
            </div>
        </div>"""

    full_html = f"""
    <html>
    <body style="background: #f3f4f6; margin: 0; padding: 0;">
        <div style="background: #ffffff; padding: 30px 0; text-align: center; border-bottom: 1px solid #e5e7eb;">
            <img src="{LOGO_URL}" height="60" alt="Urban Agency Logo">
        </div>
        
        <div style="max-width: 750px; margin: 40px auto; padding: 0 20px;">
            <h1 style="font-family: {font_header}; color: #111827; text-align: center; text-transform: uppercase; letter-spacing: 2px; margin-bottom: 40px;">
                Intelligence Territoriale - Bordeaux
            </h1>
            
            {blocs}
            
            <div style="text-align: center; margin-top: 50px; padding-bottom: 40px; font-family: {font_body}; font-size: 11px; color: #9ca3af;">
                Rapport généré par IA Urban Agency 2.5 Flash • {date_str}
            </div>
        </div>
    </body>
    </html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. MAIN ---

def main():
    logging.info("🚀 Scan Stratégique Urban Agency (UX Optimized)")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Enquête : {cible}")
        items = chercher_serpapi(cible)
        for i in items:
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            if analyse.get('score', 0) >= 1:
                resultats.append({"url": url, **analyse})
                logging.info(f"   🔥 {analyse['projet']} (Score {analyse['score']})")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)
    logging.info("🏁 Fin du scan.")

if __name__ == "__main__": main()
