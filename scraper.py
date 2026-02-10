import os
import requests
import csv
import json
import logging
import google.generativeai as genai
from datetime import datetime

# --- CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
GOOGLE_KEY = (os.environ.get("GOOGLE_SEARCH_KEY") or "").strip()
GOOGLE_CX = (os.environ.get("GOOGLE_SEARCH_CX") or "").strip()
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# IA : Utilisation du modèle stable 'gemini-pro'
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-pro')

def chercher_google(nom):
    if not GOOGLE_KEY or not GOOGLE_CX: return []
    query = f'site:*.fr "{nom}" ("friche" OR "concours" OR "ZAC" OR "délibération")'
    url = f"https://www.googleapis.com/customsearch/v1?key={GOOGLE_KEY}&cx={GOOGLE_CX}&q={query}&dateRestrict=m1"
    try:
        res = requests.get(url).json()
        if 'error' in res:
            logging.error(f"Erreur Google API: {res['error']['message']}")
            return []
        return res.get('items', [])
    except: return []

def analyser_ia(item, source):
    prompt = f"Analyse cette opportunité d'urbanisme/architecture. Score 3 (Très chaud), 2 (Signal faible), 0 (Inutile). Retourne JSON: {{\"titre\": \"...\", \"score\": 0}}. Texte: {item.get('snippet')}"
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

def envoyer_mail(opportunites):
    # FORCE L'ENVOI d'un mail de confirmation même si 0 résultats
    if not opportunites:
        content = "<p>Le radar a tourné mais n'a trouvé aucun nouveau signal aujourd'hui.</p>"
        subject = "🔍 Radar UA : RAS (0 signal)"
    else:
        content = "".join([f"<li><b>{op['titre']}</b> (Source: {op['nom_source']})</li>" for op in opportunites])
        subject = f"🎯 Radar UA : {len(opportunites)} Signaux détectés"

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": f"<html><body>{content}</body></html>"}, 
        headers={"api-key": BREVO_KEY})

def main():
    logging.info("🚀 Lancement du Radar...")
    resultats = []
    if os.path.exists('cibles.csv'):
        with open('cibles.csv', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                nom = row.get("Nom de l'Organisme")
                if not nom: continue
                items = chercher_google(nom)
                for i in items:
                    analyse = analyser_ia(i, nom)
                    if analyse.get('score', 0) >= 1:
                        resultats.append({"nom_source": nom, "titre": i.get('title'), "url": i.get('link')})
    
    envoyer_mail(resultats)
    logging.info("✅ Mission terminée.")

if __name__ == "__main__": main()
