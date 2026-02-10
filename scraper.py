import os
import requests
import csv
import json
import logging
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime

# --- 1. CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- IA CONFIGURATION (FIX STABLE) ---
model = None
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        
        # Liste les modèles disponibles pour vérifier le nom exact
        available_models = [m["name"] for m in genai.list_models()]
        logging.info(f"📄 Modèles Gemini disponibles : {available_models}")
        
        # On utilise un modèle stable et supporté pour generate_content
        preferred_model = "gemini-1.5"  # remplacer par un autre modèle disponible si nécessaire
        if preferred_model in available_models:
            model = genai.GenerativeModel(model_name=preferred_model)
            logging.info(f"✅ IA Gemini {preferred_model} activée.")
        else:
            logging.warning(f"⚠️ Modèle {preferred_model} non trouvé. Veuillez choisir un modèle dans la liste ci-dessus.")
            
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. EXTRACTION PROFONDE ---

def extraire_texte_page(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, timeout=12, headers=headers)
        if res.status_code != 200: return ""
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
        text = soup.get_text(separator=' ')
        return " ".join(text.split())[:6000]
    except: return ""

def chercher_serpapi(cible):
    # Requête élargie Bordeaux Régénération
    query = f'"{cible}" (Bordeaux OR Métropole) (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 30, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. ANALYSE AVEC SECURITE ANTI-ERREUR ---

def analyser_ia(item, contenu_web):
    if not model: return {"score": 0}
    contexte = contenu_web if len(contenu_web) > 300 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    MISSION : Analyser le potentiel de régénération urbaine à Bordeaux.
    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site ou projet",
      "score": 0,
      "analyse": "Ton raisonnement stratégique sur l'opportunité",
      "action": "Action concrète recommandée"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        # generate_content est la méthode stable
        res = model.generate_content(prompt)
        text_json = res.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(text_json)
        return {
            "projet": data.get("projet", item.get("title", "Projet inconnu")),
            "score": int(data.get("score", 0)),
            "analyse": data.get("analyse") or data.get("analyse_strategique") or "Consulter la source.",
            "action": data.get("action") or data.get("action_recommandee") or "Surveiller le dossier."
        }
    except Exception as e:
        logging.warning(f"⚠️ Erreur analyse IA : {e}")
        return {"score": 0}

# --- 4. ENVOI DU RAPPORT ---

def envoyer_mail(resultats):
    if not resultats: return
    date_str = datetime.now().strftime('%d/%m/%Y')
    subject = f"🎯 Radar UA Bordeaux : {len(resultats)} Signaux"
    
    blocs = ""
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        color = "#e74c3c" if o['score'] >= 2 else "#3498db"
        blocs += f"""
        <div style="border-left:5px solid {color}; padding:15px; margin-bottom:15px; background:#fff; border-radius:4px; box-shadow:0 1px 3px rgba(0,0,0,0.1);">
            <b style="font-size:17px; color:#2c3e50;">{o['projet']}</b> <span style="font-size:12px;">(Score {o['score']}/3)</span><br>
            <p style="margin:10px 0; font-size:14px; color:#333;"><b>Analyse :</b> {o['analyse']}</p>
            <p style="margin:5px 0; font-size:14px; color:#27ae60;"><b>Action :</b> {o['action']}</p>
            <a href="{o['url']}" style="color:{color}; font-weight:bold; text-decoration:none; font-size:12px;">VOIR LA SOURCE →</a>
        </div>"""

    full_html = f"""<html><body style="font-family:Arial; background:#f4f4f4; padding:20px;">
        <div style="max-width:650px; margin:auto;">
            <img src="{LOGO_URL}" height="45" style="margin-bottom:20px;">
            <h2 style="color:#2c3e50; border-bottom:2px solid #ddd; padding-bottom:10px;">Radar Stratégique Bordeaux</h2>
            {blocs}
        </div>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. MAIN ---

def main():
    logging.info("🚀 Scan final - Version Stabilisée")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation : {cible}")
        items = chercher_serpapi(cible)
        for i in items:
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            if analyse.get('score', 0) >= 1:
                resultats.append({"url": url, **analyse})
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)
    logging.info("🏁 Mission terminée.")

if __name__ == "__main__": main()
