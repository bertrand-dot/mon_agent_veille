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

# Initialisation du client IA (Modèle 2.5 Flash)
client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        logging.info("✅ IA Gemini 2.5 Flash activée.")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. FONCTIONS DE COLLECTE ---

def extraire_texte_page(url):
    """Scraping profond du contenu du site"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, timeout=12, headers=headers)
        if res.status_code != 200: return ""
        soup = BeautifulSoup(res.text, 'html.parser')
        # Nettoyage des éléments superflus
        for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
        text = soup.get_text(separator=' ')
        return " ".join(text.split())[:7000]
    except: return ""

def chercher_serpapi(cible):
    """Recherche Google focalisée sur les friches et la régénération à Bordeaux"""
    query = f'"{cible}" (Bordeaux OR Métropole) (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {
        "engine": "google", 
        "q": query, 
        "api_key": SERPAPI_KEY, 
        "num": 30, 
        "gl": "fr", 
        "hl": "fr", 
        "tbs": "qdr:m6" # 6 derniers mois
    }
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. MOTEUR DE RAISONNEMENT (PROMPT UA) ---

def analyser_ia(item, contenu_web):
    if not client: return {"score": 0}
    contexte = contenu_web if len(contenu_web) > 300 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    MISSION : Extraire les données CRITIQUES d'un projet urbain à Bordeaux.
    
    CONSIGNES :
    - Score : Sur 5 (1: Veille, 3: Fort potentiel, 5: Priorité absolue).
    - Analyse : 3 phrases maximum. Focus sur la mutation architecturale.
    - Identification précise de la PROCEDURE, DEADLINE et BUDGET.

    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site ou projet",
      "score": 0,
      "procedure": "Type de procédure (ex: ZAC, PUP, Concours MOE)",
      "deadline": "Date clé ou horizon temporel",
      "budget": "Budget ou surface (ex: 15M€ / 10ha)",
      "analyse": "Ton analyse synthétique UA",
      "action": "Action concrète recommandée"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )
        # Nettoyage et parsing
        text_json = response.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_json)
        
        return {
            "projet": data.get("projet", item.get("title", "Projet inconnu")),
            "score": int(data.get("score", 0)),
            "procedure": data.get("procedure", "Non spécifiée"),
            "deadline": data.get("deadline", "Horizon non défini"),
            "budget": data.get("budget", "Non mentionné"),
            "analyse": data.get("analyse", "Analyse en consultant la source."),
            "action": data.get("action", "Surveiller le dossier.")
        }
    except Exception as e:
        logging.warning(f"⚠️ Erreur analyse : {e}")
        return {"score": 0}

# --- 4. INTERFACE GRAPHIQUE DU MAIL ---

def envoyer_mail(resultats):
    if not resultats: return
    date_str = datetime.now().strftime('%d/%m/%Y')
    subject = f"🎯 Radar UA : {len(resultats)} Signaux Stratégiques"
    
    blocs = ""
    # Tri par score (décroissant)
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        stars = "⭐️" * int(o.get('score', 0))
        color = "#e74c3c" if o['score'] >= 4 else "#3498db"
        
        blocs += f"""
        <div style="border: 1px solid #ddd; margin-bottom: 25px; background: #fff; border-radius: 8px; overflow: hidden; font-family: Arial, sans-serif; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
            <div style="background: #2c3e50; color: #fff; padding: 12px 18px; display: flex; justify-content: space-between; align-items: center;">
                <b style="font-size: 16px; text-transform: uppercase; letter-spacing: 0.5px;">{o.get('projet')}</b>
                <span style="font-size: 14px;">{stars}</span>
            </div>
            <div style="padding: 12px 18px; background: #f1f3f4; border-bottom: 1px solid #eee; font-size: 12px; color: #555;">
                <table style="width: 100%;">
                    <tr>
                        <td style="width: 33%;"><b>PROCÉDURE :</b> {o.get('procedure')}</td>
                        <td style="width: 33%;"><b>DEADLINE :</b> <span style="color: #d35400; font-weight: bold;">{o.get('deadline')}</span></td>
                        <td style="width: 33%;"><b>BUDGET/SURFACE :</b> {o.get('budget')}</td>
                    </tr>
                </table>
            </div>
            <div style="padding: 18px;">
                <p style="margin: 0 0 15px 0; font-size: 14px; color: #333; line-height: 1.5;">{o.get('analyse')}</p>
                <div style="background: #eafaf1; padding: 12px; border-radius: 4px; border-left: 4px solid #27ae60; color: #1d8348; font-size: 13px; font-weight: bold;">
                    Action conseillée : {o.get('action')}
                </div>
                <div style="margin-top: 15px; text-align: right;">
                    <a href="{o.get('url')}" style="color: {color}; text-decoration: none; font-weight: bold; font-size: 12px;">VOIR LA SOURCE →</a>
                </div>
            </div>
        </div>"""

    full_html = f"""
    <html>
    <body style="background: #f4f7f6; padding: 20px;">
        <div style="max-width: 700px; margin: auto;">
            <div style="text-align: center; margin-bottom: 30px;">
                <img src="{LOGO_URL}" height="50">
                <h2 style="color: #2c3e50; font-family: Georgia, serif; margin-top: 10px; border-bottom: 2px solid #2c3e50; padding-bottom: 10px;">
                    Intelligence Territoriale & Régénération
                </h2>
            </div>
            {blocs}
            <p style="text-align: center; font-size: 10px; color: #999;">Généré par IA Urban Agency 2.5 Flash</p>
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
    logging.info("🚀 Lancement du Scan UA Bordeaux (Génération 2.5 Flash)")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation stratégique : {cible}")
        items = chercher_serpapi(cible)
        for i in items:
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            if analyse.get('score', 0) >= 1:
                resultats.append({"url": url, **analyse})
                logging.info(f"   🎯 Signal identifié (Score {analyse['score']}): {analyse['projet']}")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)
    logging.info("🏁 Mission terminée.")

if __name__ == "__main__": main()
