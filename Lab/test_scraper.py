import os
import requests
import json
import logging
import csv
import time
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from urllib.parse import urljoin

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")
SERPAPI_KEY = os.environ.get("SERPAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# --- 2. FONCTIONS DE LECTURE ---

def extraire_web(url):
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if res.status_code != 200: return "", f"Erreur {res.status_code}"
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['nav', 'footer', 'script', 'style', 'header', 'aside']): s.decompose()
        return soup.get_text(separator=' ')[:15000], "OK"
    except Exception as e: return "", str(e)

def recherche_linkedin_serp(url_li):
    try:
        params = {"engine": "google", "q": f"site:{url_li}", "api_key": SERPAPI_KEY, "num": 3}
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = res.json()
        snippets = [f"{r.get('title')} : {r.get('snippet')}" for r in data.get("organic_results", [])]
        return " | ".join(snippets), f"{len(snippets)} extraits" if snippets else "0 résultat"
    except Exception as e: return "", str(e)

# --- 3. ANALYSE IA (AVEC LOG DE REFUS) ---

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
    resultats_complets = []
    
    with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

        for row in reader:
            nom = row.get("Nom de l'Organisme", "").strip()
            url_actu = row.get("URL_Directe", "").strip()
            url_li = row.get("LinkedIn_Cible", "").strip()
            if not nom: continue

            # A. WEB
            if url_actu:
                txt_idx, status_idx = extraire_web(url_actu)
                if txt_idx:
                    soup = BeautifulSoup(txt_idx, 'html.parser')
                    # On prend les 2 liens les plus longs pour tester
                    liens = [urljoin(url_actu, a['href']) for a in BeautifulSoup(requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_actu}").text, 'html.parser').find_all('a', href=True) if len(a.get_text()) > 25][:2]
                    
                    for link in liens:
                        txt_art, _ = extraire_web(link)
                        if len(txt_art) > 400:
                            ana = qualifier_ia_ua(nom, "Article Web", txt_art)
                            ana['url'] = link
                            ana['type'] = "Web"
                            resultats_complets.append(ana)

            # B. LINKEDIN
            if url_li:
                txt_li, status_li = recherche_linkedin_serp(nom, url_li)
                if txt_li:
                    ana = qualifier_ia_ua(nom, "LinkedIn Posts", txt_li)
                    ana['url'] = url_li
                    ana['type'] = "LinkedIn"
                    resultats_complets.append(ana)

    # --- 5. ENVOI DU RAPPORT DE DIAGNOSTIC ---
    html = "<h2>🛠️ Diagnostic Lab : Pourquoi pas de leads ?</h2>"
    html += "<table border='1' style='border-collapse:collapse; width:100%; font-size:12px;'>"
    html += "<tr style='background:#eee;'><th>Organisme</th><th>Type</th><th>Score</th><th>Verdict / Raison Refus</th><th>Projet détecté</th></tr>"
    
    for r in resultats_complets:
        bg = "#e8f5e9" if r['score_interne'] >= 2 else "#ffebee"
        html += f"<tr style='background:{bg};'><td>{r.get('autorite', 'N/A')}</td><td>{r['type']}</td><td>{r['score_interne']}/5</td>"
        html += f"<td>{r['analyse_ua'] if r['score_interne'] >= 2 else r.get('raison_refus', 'N/A')}</td>"
        html += f"<td><a href='{r['url']}'>{r.get('projet', 'Lien')}</a></td></tr>"
    html += "</table>"
    
    requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
        json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": "🛠️ LAB : Diagnostic Qualification", "htmlContent": html})

if __name__ == "__main__": main()
