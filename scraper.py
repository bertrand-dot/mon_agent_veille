import os
import requests
import csv
import re
import json
import logging
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime

# --- CONFIGURATION ---
# On récupère les clés avec une sécurité (strip) pour éviter les espaces invisibles
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
GOOGLE_KEY = (os.environ.get("GOOGLE_SEARCH_KEY") or "").strip()
GOOGLE_CX = (os.environ.get("GOOGLE_SEARCH_CX") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

# Configuration des Logs
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Configuration IA (On passe sur le modèle STABLE)
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    # On utilise gemini-pro qui est le standard actuel pour éviter l'erreur 404
    model = genai.GenerativeModel('gemini-pro')
else:
    logging.error("⛔ CLÉ GEMINI MANQUANTE !")

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: return json.load(f)
        except: return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

def chercher_signaux_google(nom_organisme):
    """Recherche Google de haute précision"""
    if not GOOGLE_KEY or not GOOGLE_CX:
        logging.warning("⚠️  Clés Google Search manquantes ou vides.")
        return []
    
    # On cherche large : Friches, ZAC, Concours, Délibérations
    query = f'site:*.fr "{nom_organisme}" ("friche" OR "concours" OR "ZAC" OR "délibération" OR "appel à projets")'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_KEY, 
        'cx': GOOGLE_CX, 
        'q': query, 
        'dateRestrict': 'm3', # 3 derniers mois
        'num': 4 # Top 4 résultats
    }
    
    try:
        res = requests.get(url, params=params)
        data = res.json()
        
        # Petit debug pour voir si Google répond
        if 'error' in data:
            logging.error(f"Erreur Google API: {data['error']['message']}")
            return []
            
        items = data.get('items', [])
        logging.info(f"   → {len(items)} résultats trouvés via Google.")
        return [{'titre': i.get('title'), 'url': i.get('link'), 'snippet': i.get('snippet')} for i in items]
    except Exception as e: 
        logging.error(f"Erreur connexion Google: {e}")
        return []

def analyser_ia_strategique(texte, source):
    """Cerveau IA pour détecter les opportunités"""
    prompt = f"""RÔLE: Expert Développement Foncier.
    ANALYSE ce texte pour identifier une opportunité d'affaires (Archi/Urba).
    
    GRILLE DE SCORE:
    - 3 (HOT): Concours, Appel d'offre, Création ZAC, Achat Foncier, Délibération budget travaux.
    - 2 (WARM): Étude faisabilité, Diagnostic, Concertation publique, Vente friche.
    - 1 (COLD): Veille générique, nomination.
    - 0 (NULL): Bruit, menu, contact.

    FORMAT JSON STRICT:
    {{"titre": "Titre court", "resume": "Résumé en 1 phrase", "score": 0}}
    
    SOURCE: {source}
    TEXTE: {texte[:8000]}""" # On limite la taille pour éviter les erreurs
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except Exception as e:
        logging.error(f"⚠️  Erreur IA sur {source}: {e}")
        return {"score": 0}

def envoyer_mail_strategique(opportunites):
    if not opportunites: 
        logging.info("📭 Pas d'opportunités à envoyer.")
        return
    
    html_content = ""
    for op in opportunites:
        color = "#e74c3c" if op['score'] == 3 else "#3498db"
        html_content += f"""
        <div style="border-left:5px solid {color}; padding:15px; margin-bottom:20px; background:#fff; box-shadow:0 2px 4px rgba(0,0,0,0.1);">
            <div style="color:#7f8c8d; font-size:11px; text-transform:uppercase;">{op['nom_source']} • SCORE {op['score']}/3</div>
            <b style="font-size:16px; color:#2c3e50;">{op['titre']}</b>
            <p style="font-size:14px; color:#333; margin:5px 0;">{op['resume']}</p>
            <a href="{op['url']}" style="color:{color}; font-weight:bold; text-decoration:none; font-size:12px;">VOIR LA SOURCE →</a>
        </div>"""

    body = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:Arial, sans-serif;">
        <div style="max-width:600px; margin:auto; background:white; padding:30px; border-radius:10px;">
            <img src="{LOGO_URL}" height="50" style="margin-bottom:20px;">
            <h2 style="color:#2c3e50; border-bottom:1px solid #eee; padding-bottom:10px; margin-top:0;">RADAR STRATÉGIQUE</h2>
            {html_content}
        </div>
    </body></html>"""

    response = requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": f"🎯 {len(opportunites)} Nouveaux Signaux Détectés", "htmlContent": body}, 
        headers={"api-key": BREVO_KEY})
    
    if response.status_code in [200, 201]:
        logging.info("✅ Email envoyé avec succès.")
    else:
        logging.error(f"❌ Erreur envoi email: {response.text}")

def main():
    if not os.path.exists('cibles.csv'): 
        logging.error("❌ Fichier cibles.csv introuvable.")
        return
        
    logging.info("🚀 Démarrage du Radar...")
    hist = charger_historique()
    opportunites = []

    # Lecture sécurisée du CSV
    lignes = []
    for enc in ['utf-8', 'latin-1']:
        try:
            with open('cibles.csv', encoding=enc) as f: lignes = f.readlines(); break
        except: continue
        
    if not lignes: return
    sep = ';' if ';' in lignes[0] else ','
    reader = csv.DictReader(lignes, delimiter=sep)

    for row in reader:
        nom = row.get("Nom de l'Organisme")
        if not nom: continue
        
        logging.info(f"🔎 Analyse de : {nom}")
        
        # 1. Recherche Google (Signaux Faibles)
        google_results = chercher_signaux_google(nom)
        for res in google_results:
            if res['url'] in hist: continue # Déjà vu
            
            # Analyse IA du snippet Google (rapide et efficace)
            analyse = analyser_ia_strategique(res['snippet'] + " " + res['titre'], nom)
            
            if analyse['score'] >= 2: # On ne garde que le pertinent
                item = {"url": res['url'], "nom_source": nom, **analyse}
                opportunites.append(item)
                logging.info(f"   🔥 Opportunité détectée : {analyse['titre']}")
            
            # On mémorise
            hist[res['url']] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse['score']}

    envoyer_mail_strategique(opportunites)
    sauvegarder_historique(hist)
    logging.info("🏁 Mission terminée.")

if __name__ == "__main__":
    main()
