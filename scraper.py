import os
import requests
import json
import logging
import time
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from collections import defaultdict

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
        logging.info("✅ Moteur Gemini 2.5 Pro opérationnel.")
    except Exception as e:
        logging.error(f"❌ Erreur Gemini: {e}")

# --- 2. EXTRACTION (HYBRIDE PDF/HTML) ---

def extraire_texte(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, timeout=12, headers=headers)
        if res.status_code != 200: return ""
        if 'application/pdf' in res.headers.get('Content-Type', '').lower() or url.lower().endswith('.pdf'):
            doc = fitz.open(stream=res.content, filetype="pdf")
            text = "".join([p.get_text() for p in doc[:10]])
            doc.close()
            return " ".join(text.split())[:15000]
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'footer', 'header']): s.decompose()
        return " ".join(soup.get_text(separator=' ').split())[:12000]
    except: return ""

def chercher_serpapi(cible):
    query = f'"{cible}" (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 15, "gl": "fr", "hl": "fr", "tbs": "qdr:m6"}
    try:
        return requests.get("https://serpapi.com/search", params=params, timeout=20).json().get("organic_results", [])
    except: return []

# --- 3. ANALYSE IA (STRATÉGIE UA) ---

def analyser_ia(item, contenu_web):
    if not client: return None
    time.sleep(1) # Utilisation du quota payant/crédits
    
    prompt = f"""RÔLE : Directeur du Développement pour URBAN AGENCY (Copenhague/Dublin).
    ADN : Architecture iconique, densité qualitative, régénération de friches, design nordique.
    
    MISSION : Analyser ce dossier.
    - Score : Sur 5 (Priorité Urban Agency).
    - Lead CHAUDE : Uniquement si date limite de soumission détectée (Concours, AMI, Offre).
    - Lead FROIDE : Vision stratégique, mutation foncière, étude urbaine.

    FORMAT JSON STRICT :
    {{
      "projet": "Nom précis",
      "autorite": "Donneur d'ordre (ex: EPA, Ville, La Fabrique)",
      "score_etoiles": 0,
      "temperature": "CHAUDE ou FROIDE",
      "date_deadline": "Date précise ou N/A",
      "procedure": "Type de procédure",
      "expertise_ua": "Valeur ajoutée CPH/DUB",
      "analyse": "Pourquoi ce dossier est majeur pour UA ?",
      "action": "Action concrète pour Bertrand"
    }}
    DATA : {item.get('title')} | {contenu_web[:8000]}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return json.loads(response.text.replace('```json', '').replace('```', '').strip())
    except: return None

# --- 4. RÉSUMÉS STRATÉGIQUES ---

def generer_synthese(resultats, type_resume="priorite"):
    if not resultats: return ""
    consigne = "résume les priorités d'appel immédiat" if type_resume == "priorite" else "fais une synthèse des visions stratégiques à long terme pour Bordeaux"
    prompt = f"En tant qu'associé UA, {consigne} à partir de ces dossiers : {json.dumps(resultats)}"
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return response.text
    except: return "Synthèse indisponible."

# --- 5. DESIGN ET ENVOI ---

def envoyer_mail(top_10, resume_priorites, resume_visions):
    font_h = "'DIN', sans-serif"; font_b = "Arial, sans-serif"
    
    # Couplage par autorité
    grouped = defaultdict(list)
    for r in top_10: grouped[r.get('autorite', 'Autres')].append(r)
    
    content_grouped = ""
    for autorite, leads in grouped.items():
        content_grouped += f"<h2 style='font-family:{font_h}; color:#2c3e50; border-bottom:2px solid #2c3e50; margin-top:30px;'>🏢 {autorite}</h2>"
        for o in leads:
            stars = "⭐" * o.get('score_etoiles', 0)
            is_hot = o.get('temperature') == 'CHAUDE'
            color = "#e74c3c" if is_hot else "#3498db"
            deadline_html = f"<span style='color:#d35400; font-weight:bold;'>📅 DÉLAI : {o.get('date_deadline')}</span>" if o.get('date_deadline') != "N/A" else ""
            
            content_grouped += f"""
            <div style="border:1px solid #ddd; margin-bottom:20px; background:#fff; border-radius:4px; overflow:hidden; font-family:{font_b};">
                <div style="background:#2c3e50; color:#fff; padding:12px 18px; font-family:{font_h};">
                    <table width="100%"><tr>
                        <td><span style="background:{color}; padding:2px 6px; border-radius:3px; font-size:10px; margin-right:8px;">{o.get('temperature')}</span> <b>{o.get('projet')}</b></td>
                        <td align="right">
                            <a href="{o.get('url')}" style="color:#fff; text-decoration:underline; font-size:10px; margin-right:15px;">SOURCE ↗</a>
                            {stars}
                        </td>
                    </tr></table>
                </div>
                <div style="padding:15px; font-size:13px;">
                    <p style="margin:0 0 10px 0;"><b>{o.get('procedure')}</b> {f'| {deadline_html}' if deadline_html else ''}</p>
                    <p style="margin:0 0 10px 0;"><b>EXPERTISE :</b> {o.get('expertise_ua')} | <i>{o.get('analyse')}</i></p>
                    <div style="background:#f0fdf4; padding:10px; border-left:4px solid #22c55e; color:#166534; font-weight:bold;">🎯 ACTION : {o.get('action')}</div>
                </div>
            </div>"""

    full_html = f"""<html><body style="background:#f3f4f6; padding:20px; font-family:{font_b}; color:#333;">
        <div style="max-width:850px; margin:auto; background:#fff; padding:40px; border-radius:8px; box-shadow:0 10px 25px rgba(0,0,0,0.05);">
            <div style="text-align:center;"><img src="{LOGO_URL}" height="60"></div>
            
            <div style="background:#fff3cd; border:1px solid #ffeeba; padding:20px; border-radius:4px; margin:30px 0;">
                <h3 style="margin-top:0; font-family:{font_h};">📋 RÉSUMÉ & PRIORISATION</h3>
                <div style="font-size:14px; line-height:1.5;">{resume_priorites.replace('\\n', '<br>')}</div>
            </div>

            {content_grouped}

            <div style="background:#e1f5fe; border:1px solid #b3e5fc; padding:20px; border-radius:4px; margin-top:40px;">
                <h3 style="margin-top:0; font-family:{font_h};">🔭 SYNTHÈSE DES VISIONS STRATÉGIQUES</h3>
                <div style="font-size:14px; line-height:1.5; color:#01579b;">{resume_visions.replace('\\n', '<br>')}</div>
            </div>
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🎯 Top 10 UA Bordeaux : Signaux Qualifiés", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    all_leads = []
    cibles = ["Bordeaux Métropole", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation : {cible}")
        for i in chercher_serpapi(cible):
            url = i.get('link')
            if not url or url in hist: continue
            texte = extraire_texte(url)
            analyse = analyser_ia(i, texte)
            if analyse and analyse.get('score_etoiles', 0) >= 2:
                analyse['url'] = url
                all_leads.append(analyse)
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    # Limitation aux 10 projets les plus impactants
    top_10 = sorted(all_leads, key=lambda x: x.get('score_etoiles', 0), reverse=True)[:10]
    
    leads_froids = [r for r in all_leads if r.get('temperature') == 'FROIDE']
    resume_p = generer_synthese(top_10, "priorite")
    resume_v = generer_synthese(leads_froids, "vision")
    
    envoyer_mail(top_10, resume_p, resume_v)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
