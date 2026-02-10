import os
import requests
import csv
import json
import logging
import google.generativeai as genai
from datetime import datetime

# --- 1. CONFIGURATION ---
# Nettoyage des clés (supprime les espaces cachés)
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
GOOGLE_KEY = (os.environ.get("GOOGLE_SEARCH_KEY") or "").strip()
GOOGLE_CX = (os.environ.get("GOOGLE_SEARCH_CX") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# IA : Utilisation du modèle stable pour éviter la 404
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel('gemini-pro')
        logging.info("✅ IA Gemini configurée (modèle: gemini-pro)")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. FONCTIONS TECHNIQUES ---

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

def chercher_google(nom_organisme):
    """Recherche Google Haute Précision (Signaux Faibles)"""
    if not GOOGLE_KEY or not GOOGLE_CX:
        logging.warning("⚠️ Clés Google manquantes.")
        return []
    
    # Requête ciblée 'Intelligence Économique'
    query = f'"{nom_organisme}" (délibération OR friche OR concours OR reconversion OR ZAC)'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': GOOGLE_KEY, 'cx': GOOGLE_CX, 'q': query, 'dateRestrict': 'm1', 'num': 5}
    
    try:
        res = requests.get(url, params=params).json()
        if 'error' in res:
            logging.error(f"❌ ERREUR GOOGLE API: {res['error']['message']}")
            return []
        return res.get('items', [])
    except Exception as e:
        logging.error(f"❌ Erreur réseau Google: {e}")
        return []

def analyser_ia(item, source):
    """Analyse de l'opportunité par l'IA"""
    texte = f"Titre: {item.get('title')}\nExtrait: {item.get('snippet')}"
    prompt = f"""Analyse ce signal pour un cabinet d'architecture. 
    Score 3: Concours lancé ou délibération majeure. 
    Score 2: Étude, friche identifiée.
    Score 0: Bruit.
    Retourne JSON: {{"titre": "...", "score": 0, "resume": "..."}}
    Texte: {texte}"""
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"score": 0, "titre": item.get('title'), "resume": "Erreur analyse"}

def envoyer_mail(opportunites, nom_organisme_teste):
    """Envoie un mail de résultats ou de statut"""
    date_str = datetime.now().strftime('%d/%m/%Y')
    
    if not opportunites:
        subject = f"🔍 Veille UA {date_str} : Aucun nouveau signal"
        html = f"<p>Le radar a scanné <b>{nom_organisme_teste}</b> mais Google n'a renvoyé aucun nouveau résultat aujourd'hui.</p>"
    else:
        subject = f"🎯 Veille UA {date_str} : {len(opportunites)} opportunités détectées"
        blocs = "".join([f"<li style='margin-bottom:10px;'><b>{o['titre']}</b> (Score {o['score']})<br><a href='{o['url']}'>Lien vers la source</a></li>" for o in opportunites])
        html = f"<h3>Nouveaux signaux détectés :</h3><ul>{blocs}</ul>"

    full_html = f"""<html><body style="font-family:Arial; color:#333; padding:20px;">
        <img src="{LOGO_URL}" height="40"><br>
        <h2 style="color:#2c3e50;">Rapport Radar Urban Agency</h2>
        {html}
        <hr><p style="font-size:10px; color:#999;">Ceci est un rapport automatique généré par votre IA.</p>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 3. MAIN ---

def main():
    logging.info("🚀 Démarrage du scan...")
    hist = charger_historique()
    resultats = []
    dernier_nom = "Inconnu"

    if not os.path.exists('cibles.csv'):
        logging.error("❌ Fichier cibles.csv introuvable.")
        return

    with open('cibles.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            dernier_nom = nom
            
            logging.info(f"🔎 Recherche Google pour : {nom}")
            items = chercher_google(nom)
            
            for i in items:
                url = i.get('link')
                if url in hist: continue
                
                analyse = analyser_ia(i, nom)
                if analyse['score'] >= 1:
                    resultats.append({"url": url, "nom_source": nom, **analyse})
                    logging.info(f"   🔥 Signal trouvé : {analyse['titre']}")
                
                hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse['score']}

    # On envoie TOUJOURS un mail pour confirmer que le script a tourné
    envoyer_mail(resultats, dernier_nom)
    sauvegarder_historique(hist)
    logging.info("🏁 Fin de mission.")

if __name__ == "__main__":
    main()
