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
    """Recherche étendue via SerpApi"""
    if not SERPAPI_KEY:
        logging.warning("⚠️ Clé SerpApi manquante.")
        return []
    
    # Requête orientée 'Marchés Publics et Urbanisme'
    query = f'"{nom_organisme}" (délibération OR friche OR concours OR "avis de marché" OR ZAC)'
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 20, # AUGMENTÉ : On passe à 20 résultats
        "gl": "fr",
        "hl": "fr",
        "tbs": "qdr:m6" # 6 derniers mois pour capter les signaux récents
    }
    
    try:
        res = requests.get(url, params=params, timeout=20).json()
        if "error" in res:
            logging.error(f"❌ Erreur SerpApi: {res['error']}")
            return []
        return res.get("organic_results", [])
    except Exception as e:
        logging.error(f"❌ Erreur réseau SerpApi: {e}")
        return []

def analyser_ia(item):
    """Analyse stratégique avec priorité aux annonces légales"""
    texte = f"Titre: {item.get('title')}\nSnippet: {item.get('snippet')}"
    
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    TACHE : Analyser ce signal pour identifier une opportunité de concours ou de projet urbain.
    
    GRILLE DE SCORE :
    - SCORE 3 (HAUTE PRIORITÉ) : Annonce légale, Avis de marché, Lancement de concours, Création de ZAC.
    - SCORE 2 (SIGNAL FAIBLE) : Étude urbaine, Reconversion de friche, Intention de projet, Délibération.
    - SCORE 1 (VEILLE) : Article de presse urbanisme, information de contexte.
    - SCORE 0 (IGNORER) : RH, Administration pure, Annuaire.
    
    ATTENTION : Si le texte mentionne une 'Annonce Légale' ou un 'Marché Public', attribue un score de 3.
    
    RETOURNE JSON STRICT : {{"titre": "...", "score": 0, "resume": "..."}}
    TEXTE : {texte}"""
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"score": 0, "titre": item.get('title'), "resume": "Erreur analyse"}

def envoyer_mail(opportunites, nom_teste):
    date_str = datetime.now().strftime('%d/%m/%Y')
    
    if not opportunites:
        subject = f"🔍 Veille UA {date_str} : RAS"
        html = f"<p>Le radar a scanné 20 résultats pour <b>{nom_teste}</b>. Aucun nouveau signal pertinent détecté.</p>"
    else:
        # Tri : les plus hauts scores en premier
        opportunites.sort(key=lambda x: x['score'], reverse=True)
        subject = f"🎯 Veille UA {date_str} : {len(opportunites)} opportunités détectées"
        
        blocs = ""
        for o in opportunites:
            color = "#e74c3c" if o['score'] == 3 else "#3498db" if o['score'] == 2 else "#95a5a6"
            blocs += f"""
            <li style='margin-bottom:20px; list-style:none; border-left:4px solid {color}; padding-left:15px;'>
                <b style='font-size:16px;'>{o['titre']}</b> <span style='color:{color}; font-size:12px;'>(Score {o['score']}/3)</span><br>
                <i style='font-size:13px; color:#555;'>{o['resume']}</i><br>
                <a href='{o['url']}' style='color:{color}; font-size:12px; font-weight:bold;'>VOIR LA SOURCE →</a>
            </li>"""
        html = f"<h3>Signaux identifiés (Top 20 résultats Google) :</h3><ul>{blocs}</ul>"

    full_html = f"""<html><body style="font-family:Arial; padding:20px; background:#f9f9f9;">
        <div style="max-width:600px; margin:auto; background:white; padding:20px; border-radius:8px; border:1px solid #eee;">
            <img src="{LOGO_URL}" height="40"><br>
            <h2 style="color:#2c3e50; border-bottom:1px solid #eee; padding-bottom:10px;">Radar Stratégique Urban Agency</h2>
            {html}
        </div>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 3. MAIN ---

def main():
    logging.info("🚀 Démarrage du scan haute-performance (20 résultats)")
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
            
            logging.info(f"🔎 Analyse intensive : {nom}")
            items = chercher_serpapi(nom)
            
            for i in items:
                url = i.get('link')
                if not url or url in hist: continue
                
                analyse = analyser_ia(i)
                # On mémorise dans l'historique
                hist[url] = {
                    "date": datetime.now().strftime('%Y-%m-%d'), 
                    "score": analyse.get('score', 0),
                    "source": nom
                }

                # On n'ajoute au mail que si le score est significatif (1, 2 ou 3)
                if analyse.get('score', 0) >= 1:
                    resultats.append({"url": url, "nom_source": nom, **analyse})
                    logging.info(f"   🔥 Opportunité détectée : {analyse['titre']} (Score {analyse['score']})")

    envoyer_mail(resultats, dernier_nom)
    sauvegarder_historique(hist)
    logging.info("🏁 Fin de mission.")

if __name__ == "__main__":
    main()
