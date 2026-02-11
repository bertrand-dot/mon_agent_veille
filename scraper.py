import os
import requests
import json
import logging
import time
import csv
import fitz
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
    except Exception as e:
        logging.error(f"❌ Erreur Gemini : {e}")

# --- 2. ROTATION ET CHARGEMENT ---

def obtenir_fichier_du_jour():
    jours = {0: "cibles_idf.csv", 1: "cibles_nord_est.csv", 2: "cibles_nord_ouest.csv", 3: "cibles_sud_ouest.csv", 4: "cibles_sud_est.csv"}
    return jours.get(datetime.now().weekday(), "cibles_sud_ouest.csv")

def charger_organismes(nom_fichier):
    cibles = []
    if os.path.exists(nom_fichier):
        with open(nom_fichier, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                cibles.append(row['Nom de l\'Organisme'])
    return cibles

# --- 3. ANALYSE IA : LE CERVEAU UA ---

def analyser_opportunite(item, texte):
    if not client: return None
    time.sleep(1)
    
    prompt = f"""RÔLE : Expert en Business Intelligence pour URBAN AGENCY.
    MISSION : Qualifier ce signal. Style pro, précis, sans émojis dans 'analyse_ua' et 'action'.

    FORMAT JSON :
    {{
      "projet": "Nom précis",
      "autorite": "Donneur d'ordre",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "deadline": "Date ou N/A",
      "matching_dna": "Expertise clé (Bois, Densité, Waterfront)",
      "analyse_ua": "Analyse de l'enjeu architectural et urbain (30 mots max)",
      "action": "Action concrète pour Bertrand"
    }}
    DATA : {item.get('title')} | {texte[:8000]}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        data['url'] = item.get('link')
        return data
    except: return None

# --- 4. SYNTHÈSES STRATÉGIQUES (VERSION PARTAGEABLE) ---

def generer_synthese(leads, mode="executif"):
    if not leads: return "Veille territoriale en cours."
    
    if mode == "executif":
        consigne = """Rédige une note de synthèse tactique courte (3 puces max). 
        Utilise des émojis. L'objectif est de donner une 'température' du marché actuelle : 
        quelles sont les forces en présence, les types de projets qui accélèrent, et les opportunités de partenariat."""
    else:
        consigne = """Rédige une analyse stratégique prospective (1 paragraphe de 3-4 lignes). 
        Doit être instructif et valorisant pour UA. Analyse les tendances lourdes du territoire 
        (ex: transition écologique, mutation des friches, nouveaux usages). 
        Le ton doit être expert, partageable avec un client potentiel pour démontrer notre vision."""
    
    try:
        prompt = f"En tant qu'associé UA, {consigne}. Données : {json.dumps(leads)}"
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return response.text
    except: return "Analyse indisponible."

# --- 5. INTERFACE ET ENVOI ---

def envoyer_rapport(top_10, res_exec, res_strat, cluster_name):
    # Sécurisation HTML
    exec_html = res_exec.replace('\n', '<br>')
    strat_html = res_strat.replace('\n', '<br>')
    
    grouped = defaultdict(list)
    for r in top_10: grouped[r.get('autorite', 'Autres')].append(r)
    
    content_grouped = ""
    font_h = "'Arial Black', sans-serif"; font_b = "Arial, sans-serif"
    
    for autorite, items in grouped.items():
        content_grouped += f"<div style='margin-top:20px; font-family:{font_h}; color:#999; font-size:11px; text-transform:uppercase; border-bottom:1px solid #eee;'>{autorite}</div>"
        for o in items:
            cat = o.get('categorie', 'RADAR')
            colors = {"SPRINT": "#e74c3c", "RADAR": "#e67e22", "EXPLORATION": "#3498db", "RÉSEAU": "#9b59b6"}
            bg_color = colors.get(cat, "#7f8c8d")
            
            content_grouped += f"""
            <div style="border:1px solid #eee; margin:12px 0; background:#fff; overflow:hidden; font-family:{font_b}; border-left:4px solid {bg_color};">
                <div style="background:#f8f9fa; padding:8px 15px; border-bottom:1px solid #eee;">
                    <table width="100%"><tr>
                        <td style="font-size:13px;"><b>{o.get('projet')}</b></td>
                        <td align="right"><span style="background:{bg_color}; color:#fff; padding:1px 5px; font-size:9px; border-radius:2px;">{cat}</span></td>
                    </tr></table>
                </div>
                <div style="padding:15px; font-size:12px; line-height:1.5;">
                    <table width="100%"><tr>
                        <td width="30%">📅 <b>DÉLAI :</b> {o.get('deadline')}</td>
                        <td width="70%">🧬 <b>ADN :</b> {o.get('matching_dna')}</td>
                    </tr></table>
                    <p style="margin:10px 0; color:#444;"><b>ANALYSE :</b> {o.get('analyse_ua')}</p>
                    <div style="margin-top:10px; border-top:1px dashed #eee; padding-top:10px; font-weight:bold; color:#166534;">
                        🎯 ACTION : {o.get('action')}
                    </div>
                    <div style="text-align:right; margin-top:5px;"><a href="{o.get('url')}" style="color:#3498db; font-size:10px; text-decoration:none;">Lien Source ↗</a></div>
                </div>
            </div>"""

    full_html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:{font_b}; color:#333;">
        <div style="max-width:750px; margin:auto; background:#fff; padding:40px; border-radius:3px; border:1px solid #ddd;">
            <div style="text-align:center; margin-bottom:30px;"><img src="{LOGO_URL}" height="50"></div>
            
            <div style="background:#fff3cd; padding:25px; border-radius:2px; margin-bottom:35px; border-left:5px solid #f1c40f; font-size:13px;">
                <b style="font-family:{font_h}; font-size:12px; color:#856404; text-transform:uppercase;">🚀 Résumé Exécutif - Intelligence {cluster_name}</b><br><br>{exec_html}
            </div>

            {content_grouped}

            <div style="margin-top:40px; padding:25px; background:#e1f5fe; border-radius:2px; border-left:5px solid #0288d1; font-size:13px; color:#01579b;">
                <b style="font-family:{font_h}; font-size:12px; color:#0288d1; text-transform:uppercase;">🔬 Vision & Tendances Marché</b><br><br>{strat_html}
            </div>
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🎯 Intelligence Territoriale : {cluster_name} - {datetime.now().strftime('%d/%m')}", "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 6. MAIN (IDENTIQUE AVEC ROTATION) ---
