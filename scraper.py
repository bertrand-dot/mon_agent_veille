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
        logging.info("✅ IA Gemini 2.0 Flash activée.")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. EXTRACTION HYBRIDE ---

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

# --- 3. ANALYSE IA (CIBLAGE OPÉRATIONNEL UA) ---

def analyser_ia(item, contenu_web):
    if not client: return {"score_etoiles": 0}
    time.sleep(1.5)
    
    contexte = contenu_web if len(contenu_web) > 400 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement pour URBAN AGENCY (Bureaux à Copenhague et Dublin).
    ADN : Architecture iconique, urbanisme nordique durable, régénération de friches complexes.
    
    MISSION : Identifier les leads opérationnels.
    - Score : 5 étoiles pour les dossiers stratégiques.
    - Deadline : EXTRAIRE UNE DATE PRÉCISE uniquement si liée à un AMI, Concours ou Appel d'Offres.
    
    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site",
      "score_etoiles": 0,
      "temperature": "CHAUDE (Action < 12 mois) ou FROIDE (Vision)",
      "procedure": "Type de marché (ZAC, AMI, Concours...)",
      "date_echeance": "Date précise ou 'N/A' si aucune date trouvée",
      "budget": "Surface ou budget",
      "partenaires": "Aménageurs, Promoteurs",
      "analyse_ua": "Valeur ajoutée CPH/DUB pour ce projet",
      "action": "Action pour Bertrand"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        data['score_etoiles'] = min(int(data.get('score_etoiles', 0)), 5)
        return data
    except:
        return {"score_etoiles": 0}

# --- 4. DESIGN DU RAPPORT (DEADLINE CONDITIONNELLE) ---

def envoyer_mail(resultats):
    if not resultats: return
    font_h = "'DIN', 'Alternate Gothic', sans-serif"; font_b = "Arial, Helvetica, sans-serif"
    blocs = ""
    
    for o in sorted(resultats, key=lambda x: x.get('score_etoiles', 0), reverse=True):
        stars = "⭐" * o.get('score_etoiles', 0)
        is_chaude = "CHAUDE" in o.get('temperature', '').upper()
        temp_color = "#e74c3c" if is_chaude else "#3498db"
        temp_label = "🔥 LEAD CHAUDE" if is_chaude else "❄️ VISION STRATÉGIQUE"
        
        # Logique d'affichage de la deadline
        deadline_raw = o.get('date_echeance', 'N/A')
        deadline_html = ""
        if deadline_raw and deadline_raw.upper() != "N/A":
            deadline_html = f"""<td width="25%" style="color:#d35400;">📅 <b>DÉLAI :</b> {deadline_raw}</td>"""
        
        blocs += f"""
        <div style="border:1px solid #e0e0e0; margin-bottom:35px; background:#fff; border-radius:4px; overflow:hidden;">
            <div style="background:#2c3e50; color:#fff; padding:15px 20px; font-family:{font_h}; text-transform:uppercase;">
                <table width="100%"><tr>
                    <td style="font-size:18px;">
                        <span style="background:{temp_color}; padding:2px 8px; border-radius:3px; font-size:10px; vertical-align:middle; margin-right:10px;">{temp_label}</span>
                        {o.get('projet')}
                    </td>
                    <td align="right">{stars}</td>
                </tr></table>
            </div>
            <div style="padding:10px 20px; background:#f8f9fa; border-bottom:1px solid #eee; font-family:{font_b}; font-size:11px; color:#666;">
                <table width="100%"><tr>
                    <td width="25%">📝 <b>TYPE :</b> {o.get('procedure')}</td>
                    {deadline_html}
                    <td width="25%">💰 <b>BUDGET/SURF. :</b> {o.get('budget')}</td>
                    <td width="25%">🤝 <b>ACTEURS :</b> {o.get('partenaires')}</td>
                </tr></table>
            </div>
            <div style="padding:20px; font-family:{font_b};">
                <p style="font-size:14px; margin:0 0 15px 0;"><b>ANALYSE UA :</b> {o.get('analyse_ua')}</p>
                <div style="background:#f0fdf4; padding:15px; border-radius:4px; border-left:4px solid #22c55e; color:#166534; font-size:13px; font-weight:bold;">
                    🎯 ACTION : {o.get('action')}
                </div>
                <div style="margin-top:15px; text-align:right;">
                    <a href="{o.get('url')}" style="color:#3b82f6; text-decoration:none; font-size:11px; font-weight:bold;">VOIR LA SOURCE →</a>
                </div>
            </div>
        </div>"""

    full_html = f"""<html><body style="background:#f3f4f6; padding:20px;">
        <div style="max-width:800px; margin:0 auto;">
            <div style="background:#ffffff; padding:30px; text-align:center; border-bottom:3px solid #2c3e50;"><img src="{LOGO_URL}" height="60"></div>
            <h1 style="font-family:{font_h}; text-align:center; text-transform:uppercase; margin:40px 0; color:#111;">Radar Urban Agency - Bordeaux</h1>
            {blocs}
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🎯 {len(resultats)} Signaux Qualifiés Bordeaux", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. EXECUTION ---

def main():
    logging.info("🚀 Scan UA (Deadline-Filter Mode)")
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
            if isinstance(analyse, dict) and int(analyse.get('score_etoiles', 0)) >= 1:
                resultats.append({"url": url, **analyse})
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
