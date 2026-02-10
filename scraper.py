import os
import requests
import csv
import json
import logging
import google.generativeai as genai
from datetime import datetime

# --- 1. CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-pro")
    except Exception as e:
        logging.error(f"Erreur Gemini: {e}")

# --- 2. FONCTIONS ---

def chercher_serpapi(nom):
    """Scan 20 résultats sur 6 mois"""
    params = {
        "engine": "google",
        "q": f'"{nom}" (délibération OR friche OR concours OR aménagement OR ZAC OR "avis de marché")',
        "api_key": SERPAPI_KEY,
        "num": 20,
        "gl": "fr", "hl": "fr", "tbs": "qdr:m6"
    }
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

def analyser_ia_strategique(item, source):
    """Le cerveau 'Développement Urban Agency'"""
    prompt = f"""RÔLE : Tu es le Directeur du Développement d'Urban Agency. 
    Tu analyses les signaux web pour détecter des futurs marchés d'architecture ou d'urbanisme.

    MISSION : Evaluer le potentiel business de ce lien pour l'agence.
    
    GRILLE DE SCORE ($S \in [0, 3]$):
    - 3 : Opportunité immédiate (Concours, Marché public publié, Lauréat à contacter).
    - 2 : Signal fort (ZAC créée, dépollution de friche, étude pré-opérationnelle).
    - 1 : Signal faible (Délibération de principe, concertation, article sur une mutation urbaine).
    - 0 : Bruit (Archives, annuaire, RH).

    CONSIGNES :
    1. Résumé : Explique l'opportunité cachée (ex: 'La phase de concertation indique un lancement de concours d'ici 6 mois').
    2. Action : Propose une action (ex: 'Surveiller le profil acheteur', 'Identifier les partenaires promoteurs').

    FORMAT JSON : 
    {{
      "titre": "Nom du projet/sujet",
      "score": 0,
      "analyse": "Ton raisonnement stratégique",
      "action": "Action recommandée"
    }}

    TEXTE : {item.get('title')} - {item.get('snippet')}"""
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

def envoyer_mail(resultats):
    if not resultats: return
    
    date_str = datetime.now().strftime('%d/%m/%Y')
    subject = f"🎯 Radar Stratégique UA : {len(resultats)} Opportunités détectées"
    
    blocs = ""
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        color = "#e74c3c" if o['score'] == 3 else "#3498db" if o['score'] == 2 else "#95a5a6"
        blocs += f"""
        <div style="border-left:5px solid {color}; padding:15px; margin-bottom:20px; background:#fff; border-radius:5px;">
            <b style="font-size:16px; color:#2c3e50;">{o['titre']}</b> (Score {o['score']}/3)<br>
            <p style="margin:10px 0; color:#333;"><b>Opportunité :</b> {o['analyse']}</p>
            <p style="margin:5px 0; color:#27ae60;"><b>Action UA :</b> {o['action']}</p>
            <a href="{o['url']}" style="color:{color}; font-weight:bold; text-decoration:none; font-size:12px;">CONSULTER LA SOURCE →</a>
        </div>"""

    full_html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:Arial;">
        <div style="max-width:600px; margin:auto;">
            <img src="{LOGO_URL}" height="40" style="margin-bottom:20px;">
            <h2 style="color:#2c3e50; border-bottom:2px solid #ddd; padding-bottom:10px;">Intelligence Territoriale</h2>
            {blocs}
        </div>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

def main():
    if not os.path.exists("cibles.csv"): return
    
    logging.info("🚀 Lancement du scan stratégique...")
    hist = {} # On repart de zéro pour ce test
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        
    resultats = []
    with open("cibles.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            
            items = chercher_serpapi(nom)
            for i in items:
                url = i.get('link')
                if url in hist: continue
                
                analyse = analyser_ia_strategique(i, nom)
                if analyse.get('score', 0) >= 1: # On capture tout ce qui n'est pas 0
                    resultats.append({"url": url, **analyse})
                
                hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)
    logging.info("🏁 Mission terminée.")

if __name__ == "__main__": main()
