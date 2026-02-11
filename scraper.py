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
        logging.info("✅ Moteur Gemini 2.5 Pro activé.")
    except Exception as e:
        logging.error(f"❌ Erreur Gemini : {e}")

# --- 2. EXTRACTION EXPERTE ---

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

# --- 3. ANALYSE IA STRATÉGIQUE ---

def analyser_ia(item, contenu_web):
    if not client: return None
    time.sleep(1) # Utilisation du quota turbo
    
    prompt = f"""RÔLE : Associé Senior chez URBAN AGENCY (CPH/DUB).
    EXPERTISE : Architecture iconique, régénération de friches, design nordique durable.

    MISSION : Qualifier ce signal selon la matrice stratégique UA.

    MATRICE DE CLASSEMENT :
    1. LE SPRINT : Officiel (Concours, AMI, Offre). Deadline < 30j. Budget > 10M€. 
    2. LE RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois.
    3. L'EXPLORATION : Nouveau territoire ou innovation (Bas-carbone, réemploi).
    4. RÉSEAU : Partenaire (BET/Paysagiste) identifié mais architecte non nommé.

    FORMAT JSON STRICT :
    {{
      "projet": "Nom précis",
      "autorite": "Donneur d'ordre (ex: EPA, Ville, La Fabrique)",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_etoiles": 0,
      "deadline": "Date précise ou N/A",
      "budget": "Budget estimé",
      "partenaires": "Acteurs détectés",
      "analyse_ua": "Valeur ajoutée CPH/DUB (max 2 phrases)",
      "action": "Action concrète immédiate"
    }}
    DATA : {item.get('title')} | {contenu_web[:8000]}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        data['url'] = item.get('link')
        return data
    except: return None

# --- 4. GÉNÉRATION DES SYNTHÈSES ---

def generer_synthese(leads, type_synthese="executif"):
    if not leads: return "Aucune donnée majeure détectée."
    consigne = "Rédige un résumé exécutif tactique : priorités d'appel et mobilisation immédiate." if type_synthese == "executif" else "Rédige une analyse stratégique des visions long terme et opportunités d'influence."
    try:
        prompt = f"En tant qu'associé UA, {consigne}. Données : {json.dumps(leads)}"
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return response.text
    except: return "Synthèse indisponible."

# --- 5. INTERFACE MAIL (TOP 10 + GROUPAGE) ---

def envoyer_mail(top_10, resume_exec, analyse_strat):
    font_h = "'DIN', sans-serif"; font_b = "Arial, sans-serif"
    
    grouped = defaultdict(list)
    for r in top_10: grouped[r.get('autorite', 'Autres')].append(r)
    
    content_grouped = ""
    for autorite, leads in grouped.items():
        content_grouped += f"<h2 style='font-family:{font_h}; color:#2c3e50; border-bottom:2px solid #2c3e50; padding-top:20px;'>🏢 {autorite}</h2>"
        for o in leads:
            stars = "⭐" * o.get('score_etoiles', 0)
            cat = o.get('categorie', 'RADAR')
            colors = {"SPRINT": "#e74c3c", "RADAR": "#e67e22", "EXPLORATION": "#3498db", "RÉSEAU": "#9b59b6"}
            bg_color = colors.get(cat, "#7f8c8d")
            deadline_txt = f"<span style='color:#e74c3c; font-weight:bold;'>[ÉCHÉANCE: {o.get('deadline')}]</span>" if o.get('deadline') != "N/A" else ""

            content_grouped += f"""
            <div style="border:1px solid #ddd; margin-bottom:25px; background:#fff; border-radius:4px; overflow:hidden; font-family:{font_b};">
                <div style="background:#2c3e50; color:#fff; padding:12px 18px; font-family:{font_h};">
                    <table width="100%"><tr>
                        <td style="font-size:16px;">
                            <span style="background:{bg_color}; padding:2px 6px; border-radius:3px; font-size:10px; margin-right:8px;">{cat}</span>
                            <b>{o.get('projet')}</b>
                        </td>
                        <td align="right">
                            <a href="{o.get('url')}" style="color:#fff; text-decoration:underline; font-size:10px; margin-right:15px;">SOURCE DIRECTE ↗</a>
                            {stars}
                        </td>
                    </tr></table>
                </div>
                <div style="padding:15px; font-size:13px;">
                    <p><b>INFO :</b> {deadline_txt} {o.get('budget')} | <b>RÉSEAU :</b> {o.get('partenaires')}</p>
                    <p><b>ANALYSE UA :</b> <i>{o.get('analyse_ua')}</i></p>
                    <div style="background:#f0fdf4; padding:10px; border-left:4px solid #22c55e; color:#166534; font-weight:bold;">🎯 ACTION : {o.get('action')}</div>
                </div>
            </div>"""

    full_html = f"""<html><body style="background:#f3f4f6; padding:20px; font-family:{font_b}; color:#333;">
        <div style="max-width:850px; margin:auto; background:#fff; padding:40px; border-radius:8px;">
            <div style="text-align:center;"><img src="{LOGO_URL}" height="60"></div>
            
            <div style="background:#fff3cd; border:1px solid #ffeeba; padding:25px; border-radius:4px; margin:30px 0;">
                <h3 style="margin-top:0; font-family:{font_h}; color:#856404; text-transform:uppercase;">📜 Résumé Exécutif & Priorités</h3>
                <div style="font-size:14px; line-height:1.6;">{resume_exec.replace('\\n', '<br>')}</div>
            </div>

            {content_grouped}

            <div style="background:#e1f5fe; border:1px solid #b3e5fc; padding:25px; border-radius:4px; margin-top:40px;">
                <h3 style="margin-top:0; font-family:{font_h}; color:#01579b; text-transform:uppercase;">🔬 Analyse Stratégique & Visions</h3>
                <div style="font-size:14px; line-height:1.6; color:#01579b;">{analyse_strat.replace('\\n', '<br>')}</div>
            </div>
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🎯 Top 10 Intelligence Bordeaux : {datetime.now().strftime('%d/%m')}", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 6. MAIN ---

def main():
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    leads = []
    cibles = ["Bordeaux Métropole", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    for cible in cibles:
        logging.info(f"🔎 Investigation : {cible}")
        for i in chercher_serpapi(cible):
            url = i.get('link')
            if not url or url in hist: continue
            texte = extraire_texte(url)
            analyse = analyser_ia(i, texte)
            if analyse and analyse.get('score_etoiles', 0) >= 2:
                leads.append(analyse)
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    top_10 = sorted(leads, key=lambda x: x.get('score_etoiles', 0), reverse=True)[:10]
    visions = [a for a in leads if a.get('categorie') in ['RADAR', 'EXPLORATION'] and a not in top_10]
    
    resume_exec = generer_synthese(top_10, "executif")
    analyse_strat = generer_synthese(visions, "strategique")
    
    envoyer_mail(top_10, resume_exec, analyse_strat)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
