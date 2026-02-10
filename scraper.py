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

# Configuration IA
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-pro")
        logging.info("✅ IA Gemini configurée.")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. FONCTIONS TECHNIQUES ---

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f: json.dump(hist, f, indent=2)

def chercher_serpapi(nom_organisme):
    """Recherche sur 6 mois avec 20 résultats"""
    if not SERPAPI_KEY: return []
    query = f'"{nom_organisme}" (délibération OR friche OR concours OR aménagement OR ZAC OR "avis de marché")'
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 20, # Volume augmenté
        "gl": "fr",
        "hl": "fr",
        "tbs": "qdr:m6" # ÉLARGISSEMENT À 6 MOIS
    }
    try:
        res = requests.get(url, params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

def analyser_ia(item):
    """Analyse stratégique avec résumé 'Angle Opportunité'"""
    texte = f"Titre: {item.get('title')}\nSnippet: {item.get('snippet')}"
    
    prompt = f"""RÔLE : Directeur du Développement pour Urban Agency (Architecture).
    MISSION : Analyser cet extrait pour détecter une opportunité de projet.
    
    GRILLE DE SCORE :
    - 3 : Annonce légale, Avis de marché, Lancement de concours, ZAC.
    - 2 : Étude de faisabilité, mutation de friche, intention de projet urbain.
    - 1 : Veille générale, information territoriale.
    - 0 : Ignorer (RH, archives, annuaire).
    
    CONSIGNES DE RÉSUMÉ :
    Rédige un résumé d'une phrase expliquant l'ANGLE OPPORTUNITÉ (ex: "Potentiel concours de maîtrise d'œuvre suite à l'annonce de dépollution de la friche").
    
    RETOURNE UN JSON STRICT :
    {{
      "titre": "Titre court",
      "score": 0,
      "resume": "Résumé stratégique"
    }}
    
    TEXTE : {texte}"""
    
    try:
        res = model.generate_content(prompt)
        json_text = res.text.replace('```json', '').replace('```', '').strip()
        return json.loads(json_text)
    except:
        return {"score": 0, "titre": item.get('title'), "resume": "Analyse simplifiée"}

def envoyer_mail(resultats, nom_teste):
    date_str = datetime.now().strftime('%d/%m/%Y')
    if not resultats: return

    subject = f"🎯 Radar UA {date_str} : {len(resultats)} Signaux (6 derniers mois)"
    
    blocs = ""
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        color = "#e74c3c" if o['score'] == 3 else "#3498db" if o['score'] == 2 else "#95a5a6"
        blocs += f"""
        <div style="border-left:5px solid {color}; padding:15px; margin-bottom:15px; background:#fff; border-radius:4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
            <b style="font-size:16px; color:#2c3e50;">{o['titre']}</b> <span style="color:{color}; font-size:12px;">(Score {o['score']}/3)</span><br>
            <p style="font-size:14px; color:#333; margin:10px 0;"><b>Opportunité :</b> {o['resume']}</p>
            <a href="{o['url']}" style="color:{color}; font-weight:bold; text-decoration:none; font-size:12px;">VOIR LA SOURCE →</a>
        </div>"""

    full_html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:Arial;">
        <div style="max-width:600px; margin:auto;">
            <img src="{LOGO_URL}" height="40"><br>
            <h2 style="color:#2c3e50; border-bottom:2px solid #eee; padding-bottom:10px;">Radar Stratégique Urban Agency</h2>
            {blocs}
        </div>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

def main():
    logging.info("🚀 Scan Intensif (20 résultats / 6 mois)")
    hist = charger_historique()
    resultats = []

    if not os.path.exists("cibles.csv"): return

    with open("cibles.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            
            items = chercher_serpapi(nom)
            for i in items:
                url = i.get('link')
                if not url or url in hist: continue
                
                analyse = analyser_ia(i)
                # On ne garde que ce qui est utile (score 1, 2, 3)
                if analyse.get('score', 0) >= 1:
                    resultats.append({"url": url, "nom_source": nom, **analyse})
                
                hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats, "Multi-Cibles")
    sauvegarder_historique(hist)
    logging.info("🏁 Terminé")

if __name__ == "__main__": main()
