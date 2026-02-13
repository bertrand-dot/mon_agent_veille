import os
import requests
import json
import logging
import csv
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def extraire_contenu_profond(url):
    """Ouvre l'article et nettoie le texte (1 crédit)."""
    try:
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}"
        res = requests.get(proxy_url, timeout=30)
        soup = BeautifulSoup(res.text, 'html.parser')
        # Nettoyage des éléments inutiles
        for s in soup(['nav', 'footer', 'script', 'style', 'header']): s.decompose()
        return soup.get_text(separator=' ')[:15000]
    except: return ""

def main():
    leads = []
    # Lecture avec l'encodage Western Europe (cp1252) de ta capture
    with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            url = row.get("URL_Directe")
            logging.info(f"🔎 Test Laser sur : {nom}")
            
            # Récupération de la page d'accueil des actus
            res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}")
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # On cherche le premier lien d'article pour valider le concept
            lien = soup.find('a', href=True) 
            if lien:
                # Gestion des liens relatifs
                full_url = lien['href'] if lien['href'].startswith('http') else url
                txt = extraire_contenu_profond(full_url)
                
                # Analyse simplifiée pour le test
                prompt = f"Analyse ce projet pour {nom}. Est-ce > 10M€ ? Réponse JSON : {{'projet':'nom', 'analyse':'60 mots'}}. DATA: {txt[:5000]}"
                resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
                
                try:
                    ana = json.loads(resp.text.replace('```json', '').replace('```', '').strip())
                    ana['url'] = full_url
                    leads.append(ana)
                except: continue

    # Envoi du rapport si des résultats existent
    if leads:
        corps = "".join([f"<h3>{l['projet']}</h3><p>{l['analyse']}</p><a href='{l['url']}'>Lien</a><hr>" for l in leads])
        requests.post("https://api.brevo.com/v3/smtp/email", 
            json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": "🧪 TEST LAB : Résultats Laser", "htmlContent": corps}, 
            headers={"api-key": BREVO_KEY})
        logging.info("📧 Mail de test envoyé !")

if __name__ == "__main__": main()
