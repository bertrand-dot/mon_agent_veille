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
        logging.info("✅ Moteur Gemini 2.5 Flash activé (Haute Disponibilité).")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. EXTRACTION EXPERTE ---

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
    # Requête ciblée sur les friches et l'urbanisme
    query = f'"{cible}" (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 10, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

# --- 3. ANALYSE IA AVEC GESTION DE QUOTA ---

def analyser_ia(item, contenu_web):
    if not client: return {"score_etoiles": 0}
    
    # Pause de sécurité pour rester sous les 5-15 RPM du palier gratuit
    time.sleep(15) 
    
    contexte = contenu_web if len(contenu_web) > 400 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement pour l'agence URBAN AGENCY (Copenhague/Dublin).
    ADN : Projets iconiques, haute densité qualitative, régénération durable.
    MISSION : Évaluer si ce projet est une opportunité pour UA.
    
    FORMAT JSON STRICT :
    {{
      "projet": "Nom",
      "score_etoiles": 0,
      "temperature": "CHAUDE ou FROIDE",
      "procedure": "Type de procédure",
      "deadline": "Horizon",
      "budget": "Volume",
      "partenaires": "Acteurs",
      "analyse_ua": "Analyse critique (Valeur ajoutée Nordique)",
      "action": "Action immédiate"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            # Passage sur 2.5 Flash pour plus de quota journalier
            response = client.models.generate_content(model="gemini-2.5-flash", contents=prompt)
            clean_json = response.text.replace('```json', '').replace('```', '').strip()
            data = json.loads(clean_json)
            data['score_etoiles'] = min(int(data.get('score_etoiles', 0)), 5)
            return data
        except Exception as e:
            if "429" in str(e):
                logging.warning(f"⚠️ Quota atteint (429). Tentative {attempt+1}/{max_retries}. Pause 60s...")
                time.sleep(60) # Attente d'une minute complète
            else:
                logging.error(f"❌ Erreur IA : {e}")
                break
    return {"score_etoiles": 0}

# --- 4. ENVOI RAPPORT ---

def envoyer_mail(resultats):
    if not resultats: 
        logging.info("📭 Aucun lead qualifié trouvé aujourd'hui.")
        return
        
    font_h = "'Arial Black', sans-serif"; font_b = "Arial, sans-serif"
    blocs = ""
    
    for o in sorted(resultats, key=lambda x: x.get('score_etoiles', 0), reverse=True):
        stars = "⭐" * o.get('score_etoiles', 0)
        is_hot = "CHAUDE" in o.get('temperature', '').upper()
        badge_color = "#e74c3c" if is_hot else "#3498db"
        
        blocs += f"""
        <div style="border: 1px solid #ddd; margin-bottom: 20px; background: #fff; border-radius: 5px; font-family: {font_b};">
            <div style="background: #2c3e50; color: #fff; padding: 10px 15px;">
                <b>{o.get('projet')}</b> | {stars}
            </div>
            <div style="padding: 15px;">
                <p><span style="background:{badge_color}; color:#fff; padding:3px 7px; font-size:10px;">{o.get('temperature')}</span></p>
                <p style="font-size: 13px;"><b>ANALYSE :</b> {o.get('analyse_ua')}</p>
                <p style="color: #27ae60;"><b>🎯 ACTION :</b> {o.get('action')}</p>
                <a href="{o.get('url')}" style="font-size: 11px; color: #3498db;">Lien source</a>
            </div>
        </div>"""

    full_html = f"<html><body><h1 style='font-family:{font_h}'>RADAR STRATÉGIQUE UA</h1>{blocs}</body></html>"

    try:
        requests.post("https://api.brevo.com/v3/smtp/email", 
            json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": f"🔥 {len(resultats)} Opportunités qualifiées", "htmlContent": full_html}, 
            headers={"api-key": BREVO_KEY}, timeout=20)
        logging.info("📧 Rapport envoyé avec succès.")
    except Exception as e:
        logging.error(f"❌ Erreur envoi mail: {e}")

# --- 5. MAIN ---

def main():
    logging.info("🚀 Lancement du Radar UA (Bordeaux)")
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    cibles = ["Bordeaux Métropole", "EPA Bordeaux Euratlantique", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Scan : {cible}")
        for i in chercher_serpapi(cible):
            url = i.get('link')
            if not url or url in hist: continue
            
            texte = extraire_texte_page(url)
            analyse = analyser_ia(i, texte)
            
            if analyse.get('score_etoiles', 0) >= 3:
                resultats.append({"url": url, **analyse})
                logging.info(f"   ✨ Lead trouvé : {analyse.get('projet')} ({analyse.get('score_etoiles')}*)")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
