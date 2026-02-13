import os
import requests
import json
import logging
import csv
import time
from bs4 import BeautifulSoup
from google import genai
from urllib.parse import urljoin

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

# Mots-clés à bannir pour éviter les pages inutiles
BLACKLIST = [
    'cookie', 'recherche', 'search', 'mentions', 'legales', 'contact', 
    'plan-du-site', 'accessibilite', 'facebook', 'twitter', 'linkedin', 
    'instagram', 'newsletter', 'connexion', 'login'
]

# --- 2. FONCTIONS DE LECTURE NETTOYÉE ---

def extraire_contenu_propre(url):
    """Extrait le texte en ignorant la navigation et les zones parasites."""
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if res.status_code != 200: return "", f"Erreur {res.status_code}", ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Capture du titre de la page pour le rapport
        titre_page = soup.title.string if soup.title else "Sans titre"
        
        # Nettoyage radical des zones de "bruit"
        for tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style', 'form']):
            tag.decompose()
            
        texte = soup.get_text(separator=' ')
        return texte[:15000], "OK", titre_page
    except Exception as e:
        return "", str(e), ""

# --- 3. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte):
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    MISSION : Qualifier pour {nom}. 
    CRITÈRES : Budget > 10M€ HT / Surfaces > 3000m²-5000m².
    FORMAT JSON : {{'projet':'nom', 'score_interne':0, 'analyse_ua':'60 mots', 'raison_refus':'si score < 2, pourquoi ?'}}
    DATA : {titre} | {texte[:8000]}"""
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return json.loads(resp.text.replace('```json', '').replace('```', '').strip())
    except: return {'score_interne': 0, 'raison_refus': 'Erreur IA'}

# --- 4. MAIN ---

def main():
    resultats_diag = []
    logging.info("🚀 Démarrage du Scan Laser Précis")
    
    with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

        for row in reader:
            nom = row.get("Nom de l'Organisme", "").strip()
            url_cible = row.get("URL_Directe", "").strip()
            if not nom or not url_cible: continue

            logging.info(f"🔎 Analyse de : {nom}")
            
            # 1. Analyse DIRECTE de l'URL du CSV (pour éviter de "chercher" ailleurs)
            txt, status, titre_reel = extraire_contenu_propre(url_cible)
            
            if len(txt) > 500:
                # Si la page contient beaucoup de liens, c'est un index, on va chercher 1 article
                if "actualités" in titre_reel.lower() or "agenda" in url_cible:
                    logging.info(f"   Structure 'Index' détectée, recherche d'un article valide...")
                    soup = BeautifulSoup(requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_cible}").text, 'html.parser')
                    
                    for a in soup.find_all('a', href=True):
                        href = a['href'].lower()
                        titre_lien = a.get_text().strip()
                        
                        # Filtre : Lien long + Pas dans la blacklist
                        if len(titre_lien) > 30 and not any(word in href for word in BLACKLIST):
                            full_url = urljoin(url_cible, a['href'])
                            txt_art, _, titre_art = extraire_contenu_propre(full_url)
                            
                            ana = qualifier_ia_ua(nom, titre_art, txt_art)
                            ana['url'] = full_url
                            ana['titre_lu'] = titre_art
                            ana['autorite'] = nom
                            resultats_diag.append(ana)
                            break # On n'en prend qu'un seul de valide pour le test
                else:
                    # C'est une page de contenu direct
                    ana = qualifier_ia_ua(nom, titre_reel, txt)
                    ana['url'] = url_cible
                    ana['titre_lu'] = titre_reel
                    ana['autorite'] = nom
                    resultats_diag.append(ana)

    # --- 5. ENVOI DU RAPPORT DE DIAGNOSTIC ---
    if resultats_diag and BREVO_KEY:
        html = "<h2>🛠️ Diagnostic Lab : Vérification des pages lues</h2>"
        html += "<table border='1' style='border-collapse:collapse; width:100%; font-size:12px; font-family:sans-serif;'>"
        html += "<tr style='background:#2c3e50; color:white;'><th>Organisme</th><th>Titre lu par l'IA</th><th>Score</th><th>Verdict / Raison Refus</th><th>URL analysée</th></tr>"
        
        for r in resultats_diag:
            bg = "#e8f5e9" if r.get('score_interne', 0) >= 2 else "#ffebee"
            html += f"<tr style='background:{bg};'><td>{r.get('autorite')}</td>"
            html += f"<td>{r.get('titre_lu', 'Sans titre')}</td>"
            html += f"<td style='text-align:center;'><b>{r.get('score_interne')}/5</b></td>"
            html += f"<td>{r.get('analyse_ua') if r.get('score_interne', 0) >= 2 else r.get('raison_refus')}</td>"
            html += f"<td><a href='{r.get('url')}'>Voir la page</a></td></tr>"
        html += "</table>"
        
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
            json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": "🛠️ LAB : Diagnostic des URLs lues", "htmlContent": html})

if __name__ == "__main__": main()
