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

# --- IA CONFIGURATION ---

model = None
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-pro")
        logging.info("✅ IA Gemini configurée (gemini-pro)")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. UTILITAIRES ---

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
        json.dump(hist, f, indent=2, ensure_ascii=False)

# --- 3. RECHERCHE WEB (SerpAPI) ---

def chercher_serpapi(nom_organisme):
    """Recherche Google réelle via SerpAPI (veille / signaux faibles)"""

    if not SERPAPI_KEY:
        logging.warning("⚠️ Clé SERPAPI manquante.")
        return []

    query = f'"{nom_organisme}" (délibération OR friche OR concours OR reconversion OR ZAC)'

    params = {
        "engine": "google",
        "q": query,
        "hl": "fr",
        "gl": "fr",
        "num": 5,
        "tbs": "qdr:m",  # last month
        "api_key": SERPAPI_KEY,
    }

    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20)
        data = res.json()

        if "error" in data:
            logging.error(f"❌ ERREUR SERPAPI: {data['error']}")
            return []

        return data.get("organic_results", [])

    except Exception as e:
        logging.error(f"❌ Erreur réseau SerpAPI: {e}")
        return []

# --- 4. ANALYSE IA ---

def analyser_ia(item):
    """Analyse de l'opportunité par l'IA"""

    if not model:
        return {"score": 0, "titre": item.get("title"), "resume": "IA indisponible"}

    texte = f"Titre: {item.get('title')}\nExtrait: {item.get('snippet')}"

    prompt = f"""
Analyse ce signal pour un cabinet d'architecture.

Score 3 : Concours lancé, délibération officielle, appel d'offres
Score 2 : Étude préalable, friche identifiée, intention publique
Score 0 : Bruit, information non exploitable

Retourne STRICTEMENT un JSON valide :
{{"titre": "...", "score": 0, "resume": "..."}}

Texte :
{texte}
"""

    try:
        res = model.generate_content(prompt)
        clean = res.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean)
    except Exception as e:
        logging.error(f"❌ Erreur analyse IA: {e}")
        return {"score": 0, "titre": item.get("title"), "resume": "Erreur analyse IA"}

# --- 5. EMAIL ---

def envoyer_mail(opportunites, dernier_nom):
    date_str = datetime.now().strftime("%d/%m/%Y")

    if not opportunites:
        subject = f"🔍 Veille UA {date_str} : Aucun nouveau signal"
        html = f"<p>Aucun signal détecté aujourd’hui pour <b>{dernier_nom}</b>.</p>"
    else:
        subject = f"🎯 Veille UA {date_str} : {len(opportunites)} opportunités"
        blocs = "".join(
            f"<li><b>{o['titre']}</b> (Score {o['score']})<br>"
            f"<a href='{o['url']}'>Lien source</a></li>"
            for o in opportunites
        )
        html = f"<h3>Nouveaux signaux détectés :</h3><ul>{blocs}</ul>"

    full_html = f"""
    <html>
    <body style="font-family:Arial; color:#333; padding:20px;">
        <img src="{LOGO_URL}" height="40"><br>
        <h2>Rapport Radar Urban Agency</h2>
        {html}
        <hr>
        <p style="font-size:10px;color:#999;">Rapport généré automatiquement.</p>
    </body>
    </html>
    """

    requests.post(
        "https://api.brevo.com/v3/smtp/email",
        headers={"api-key": BREVO_KEY},
        json={
            "sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"},
            "to": [{"email": "bertrand@urban-agency.com"}],
            "subject": subject,
            "htmlContent": full_html,
        },
        timeout=20,
    )

# --- 6. MAIN ---

def main():
    logging.info("🚀 Démarrage du scan")
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
            if not nom:
                continue

            dernier_nom = nom
            logging.info(f"🔎 Recherche web : {nom}")

            items = chercher_serpapi(nom)

            for item in items:
                url = item.get("link")
                if not url or url in hist:
                    continue

                analyse = analyser_ia(item)
                if analyse.get("score", 0) >= 1:
                    resultats.append({"url": url, **analyse})
                    logging.info(f"🔥 Signal détecté : {analyse['titre']}")

                hist[url] = {
                    "date": datetime.now().st
