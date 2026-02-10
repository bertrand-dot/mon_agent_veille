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
        logging.info("✅ IA Gemini prête.")
    except Exception as e:
        logging.error(f"❌ Erreur Gemini: {e}")

# --- 2. FONCTIONS ---

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: return json.load(f)
        except: return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, "w", encoding="utf-8") as f: json.dump(hist, f, indent=2)

def chercher_serpapi(nom_organisme):
    """Recherche sur 6 mois - 20 résultats"""
    if not SERPAPI_KEY: return []
    query = f'"{nom_organisme}" (délibération OR friche OR concours OR aménagement OR ZAC OR "avis de marché")'
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 20,
        "gl": "fr",
        "hl": "fr",
        "tbs": "qdr:m6" # 6 MOIS
    }
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except: return []

def analyser_ia(item, source_name):
    """Raisonnement IA approfondi"""
    texte = f"Titre: {item.get('title')}\nExtrait: {item.get('snippet')}"
    
    prompt = f"""RÔLE : Expert en stratégie foncière pour Urban Agency.
    CONTEXTE : Tu analyses les signaux web pour détecter des futurs projets d'architecture.
    
    MISSION : Analyse ce résultat pour {source_name}.
    
    GRILLE DE SCORE :
    3 : Opportunité immédiate (Concours, Marché public, Annonce légale de ZAC).
    2 : Signal faible (Étude de faisabilité, dépollution de friche, intention politique).
    1 : Veille contextuelle (Article presse, vie du quartier).
    0 : Hors-sujet (RH, annuaire, archives).
    
    TON RAISONNEMENT : 
    Pourquoi est-ce pertinent pour Urban Agency ? Quelle est l'opportunité cachée ?
    
    RETOURNE UN JSON STRICT :
    {{
      "titre": "Titre pro et court",
      "score": 0,
      "opportunite": "Ton analyse stratégique en 1 phrase",
      "action": "L'action recommandée (ex: Surveiller le BOAMP, Contacter l'EPA)"
    }}
    
    TEXTE : {texte}"""
    
    try:
        res = model.generate_content(prompt)
        data = json.loads(res.text.replace('```json', '').replace('```', '').strip())
        return data
    except:
        return {"score": 0, "titre": item.get('title'), "opportunite": "Analyse impossible", "action": "Vérifier manuellement"}

def envoyer_mail(resultats, nom_teste):
    date_str = datetime.now().strftime('%d/%m/%Y')
    
    # MODIFICATION : On envoie l'e-mail même s'il n'y a que des scores 1 ou 2
    if not resultats:
        # On force l'envoi d'un mail de statut pour confirmer que le robot tourne
        subject = f"🔍 Radar UA {date_str} : Statut Opérationnel (0 signal)"
        content = f"<p>Le scan de <b>{nom_teste}</b> n'a rien révélé de nouveau ce jour.</p>"
    else:
        subject = f"🎯 Radar UA {date_str} : {len(resultats)} Signaux détectés"
        blocs = ""
        for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
            color = "#e74c3c" if o['score'] == 3 else "#3498db" if o['score'] == 2 else "#95a5a6"
            blocs += f"""
            <div style="border-left:5px solid {color}; padding:15px; margin-bottom:15px; background:#fff;">
                <b style="font-size:16px;">{o['titre']}</b> (Score {o['score']}/3)<br>
                <p style="margin:10px 0;"><b>Analyse :</b> {o.get('opportunite')}</p>
                <p style="margin:5px 0; color:#27ae60;"><b>Action :</b> {o.get('action')}</p>
                <a href="{o['url']}" style="color:{color}; text-decoration:none; font-weight:bold;">VOIR LA SOURCE →</a>
            </div>"""
        content = f"<h3>Analyse des 20 derniers résultats Google :</h3>{blocs}"

    full_html = f"<html><body style='font-family:Arial; background:#f4f4f4; padding:20px;'><div style='max-width:600px; margin:auto;'>{content}</div></body></html>"

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

def main():
    logging.info("🚀 Scan 6 mois / 20 résultats")
    hist = charger_historique()
    resultats = []
    dernier_nom = "Multi-Cibles"

    if not os.path.exists("cibles.csv"): return

    with open("cibles.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            dernier_nom = nom
            
            items = chercher_serpapi(nom)
            for i in items:
                url = i.get('link')
                if not url or url in hist: continue
                
                analyse = analyser_ia(i, nom)
                # On capture tout ce qui est >= 1 pour être sûr de ne rien rater
                if analyse.get('score', 0) >= 1:
                    resultats.append({"url": url, "nom_source": nom, **analyse})
                
                hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats, dernier_nom)
    sauvegarder_historique(hist)
    logging.info("🏁 Terminé.")

if __name__ == "__main__": main()
