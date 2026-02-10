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
        logging.info("✅ IA Gemini configurée (gemini-pro)")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. FONCTIONS TECHNIQUES ---

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(hist, f, indent=2)

def chercher_serpapi(nom_organisme):
    """Recherche via SerpApi (moteur Google)"""
    if not SERPAPI_KEY:
        logging.warning("⚠️ Clé SerpApi manquante.")
        return []
    
    query = f'"{nom_organisme}" (délibération OR friche OR concours OR aménagement OR ZAC)'
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 10,
        "gl": "fr",
        "hl": "fr",
        "tbs": "qdr:m6" # Résultats des 6 derniers mois
    }
    
    try:
        res = requests.get(url, params=params, timeout=15).json()
        if "error" in res:
            logging.error(f"❌ Erreur SerpApi: {res['error']}")
            return []
        return res.get("organic_results", [])
    except Exception as e:
        logging.error(f"❌ Erreur réseau SerpApi: {e}")
        return []

def analyser_ia(item):
    """Analyse stratégique du résultat par l'IA"""
    texte = f"Titre: {item.get('title')}\nSnippet: {item.get('snippet')}"
    prompt = f"""Analyse ce signal pour un cabinet d'architecture. 
    Score 3: Projet concret, concours, ZAC, reconversion.
    Score 2: Signal faible, étude urbaine, intention politique.
    Score 0: Bruit, RH, information inutile.
    Retourne JSON: {{"titre": "...", "score": 0, "resume": "..."}}
    Texte: {texte}"""
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"score": 0, "titre": item.get('title'), "resume": "Erreur analyse"}

def envoyer_mail(opportunites, nom_teste):
    date_str = datetime.now().strftime('%d/%m/%Y')
    
    if not opportunites:
        subject = f"🔍 Veille UA {date_str} : Aucun signal"
        html = f"<p>Le radar a scanné <b>{nom_teste}</b> mais aucun nouveau signal n'a été détecté.</p>"
    else:
        subject = f"🎯 Veille UA {date_str} : {len(opportunites)} signaux détectés"
        blocs = "".join([f"<li style='margin-bottom:15px;'><b>{o['titre']}</b> (Score {o['score']}/3)<br><small>{o['resume']}</small><br><a href='{o['url']}'>Lien source</a></li>" for o in opportunites])
        html = f"<h3>Signaux identifiés :</h3><ul>{blocs}</ul>"

    full_html = f"""<html><body style="font-family:Arial; padding:20px;">
        <img src="{LOGO_URL}" height="40"><br>
        <h2 style="color:#2c3e50;">Rapport Radar Urban Agency</h2>
        {html}
        <hr><p style="font-size:10px; color:#999;">Généré avec SerpApi & Gemini.</p>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 3. MAIN ---

def main():
    logging.info("🚀 Démarrage du scan SerpApi")
    hist = charger_historique()
    resultats = []
    dernier_nom = "Inconnu"

    if not os.path.exists("cibles.csv"):
        logging.error("❌ Fichier cibles.csv introuvable.")
        return

    with open("cibles.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            dernier_nom = nom
            
            logging.info(f"🔎 Recherche SerpApi : {nom}")
            items = chercher_serpapi(nom)
            
            for i in items:
                url = i.get('link')
                if not url or url in hist: continue
                
                analyse = analyser_ia(i)
                if analyse.get('score', 0) >= 1:
                    resultats.append({"url": url, "nom_source": nom, **analyse})
                
                # CORRECTION SYNTAXE ICI : On ferme bien le dictionnaire
                hist[url] = {
                    "date": datetime.now().strftime('%Y-%m-%d'), 
                    "score": analyse.get('score', 0),
                    "source": nom
                }

    envoyer_mail(resultats, dernier_nom)
    sauvegarder_historique(hist)
    logging.info("🏁 Fin de mission.")

if __name__ == "__main__":
    main()
