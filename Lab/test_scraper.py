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
    """Lecture via ScraperAPI avec rendu JS."""
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if res.status_code != 200: return "", f"Erreur {res.status_code}"
        
        # On garde le HTML complet pour pouvoir extraire les liens plus tard si besoin
        return res.text, "OK"
    except Exception as e: return "", str(e)

def recherche_linkedin_serp(nom_organisme, url_li):
    """Utilise SerpApi pour contourner les blocages LinkedIn via Google."""
    try:
        params = {
            "engine": "google", 
            "q": f"site:{url_li}", 
            "api_key": SERPAPI_KEY, 
            "num": 3
        }
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = res.json()
        snippets = [f"{r.get('title')} : {r.get('snippet')}" for r in data.get("organic_results", [])]
        return " | ".join(snippets), f"{len(snippets)} extraits" if snippets else "0 résultat"
    except Exception as e: return "", str(e)

# --- 3. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte):
    """Qualification stricte selon les seuils UA."""
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    MISSION : Qualifier pour {nom}. 
    CRITÈRES : Budget > 10M€ HT / Surfaces > 3000m²-5000m².
    ADN : Iconique, Bois, Waterfront, Résilience.
    
    FORMAT JSON : 
    {{
      "projet": "Nom précis",
      "autorite": "{nom}",
      "score_interne": 0,
      "analyse_ua": "Analyse tactique 60 mots",
      "raison_refus": "Si score < 2, expliquer pourquoi (ex: budget non mentionné)"
    }}
    DATA : {titre} | {texte[:8000]}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return json.loads(resp.text.replace('```json', '').replace('```', '').strip())
    except: 
        return {
            "projet": "Erreur analyse",
            "autorite": nom,
            "score_interne": 0,
            "analyse_ua": "N/A",
            "raison_refus": "Échec du parsing JSON de l'IA"
        }

# --- 4. MAIN ---

def main():
    resultats_complets = []
    logging.info("🚀 Démarrage du Diagnostic Lab (Version Hybride Corrigée)")
    
    try:
        with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

            for row in reader:
                nom = row.get("Nom de l'Organisme", "").strip()
                url_actu = row.get("URL_Directe", "").strip()
                url_li = row.get("LinkedIn_Cible", "").strip()
                if not nom: continue

                # A. ANALYSE WEB
                if url_actu:
                    logging.info(f"🔎 Web : {nom}")
                    html_idx, status_idx = extraire_web(url_actu)
                    if html_idx:
                        soup = BeautifulSoup(html_idx, 'html.parser')
                        # Extraction des liens d'articles depuis le HTML déjà chargé
                        liens = []
                        for a in soup.find_all('a', href=True):
                            if len(a.get_text().strip()) > 25:
                                full_url = urljoin(url_actu, a['href'])
                                if full_url not in liens: liens.append(full_url)
                        
                        for link in liens[:2]: # Test sur les 2 premiers articles
                            html_art, _ = extraire_web(link)
                            if html_art:
                                art_soup = BeautifulSoup(html_art, 'html.parser')
                                for s in art_soup(['nav', 'footer', 'script', 'style']): s.decompose()
                                txt_art = art_soup.get_text(separator=' ')
                                
                                if len(txt_art) > 400:
                                    ana = qualifier_ia_ua(nom, "Article Web", txt_art)
                                    ana['url'] = link
                                    ana['type'] = "Web"
                                    resultats_complets.append(ana)

                # B. ANALYSE LINKEDIN
                if url_li:
                    logging.info(f"🔎 LinkedIn : {nom}")
                    txt_li, status_li = recherche_linkedin_serp(nom, url_li)
                    if len(txt_li) > 100:
                        ana = qualifier_ia_ua(nom, "Posts LinkedIn", txt_li)
                        ana['url'] = url_li
                        ana['type'] = "LinkedIn"
                        resultats_complets.append(ana)

    except Exception as e:
        logging.error(f"❌ Erreur critique : {e}")

    # --- 5. ENVOI DU RAPPORT DE DIAGNOSTIC ---
    if resultats_complets and BREVO_KEY:
        html = "<h2>🛠️ Diagnostic Lab : Analyse de la Qualification</h2>"
        html += "<p>Ce tableau récapitule tout ce que l'IA a lu et pourquoi elle a accepté ou refusé les projets.</p>"
        html += "<table border='1' style='border-collapse:collapse; width:100%; font-size:12px; font-family:sans-serif;'>"
        html += "<tr style='background:#34495e; color:white;'><th>Organisme</th><th>Type</th><th>Score</th><th>Verdict / Raison Refus</th><th>Lien</th></tr>"
        
        for r in resultats_complets:
            # Vert si score >= 2, Rouge sinon
            bg_color = "#e8f5e9" if r.get('score_interne', 0) >= 2 else "#ffebee"
            score = r.get('score_interne', 0)
            
            html += f"<tr style='background:{bg_color};'>"
            html += f"<td>{r.get('autorite', 'Inconnu')}</td>"
            html += f"<td>{r.get('type', 'N/A')}</td>"
            html += f"<td style='text-align:center;'><b>{score}/5</b></td>"
            
            # Si accepté on affiche l'analyse, sinon la raison du refus
            verdict = r.get('analyse_ua') if score >= 2 else r.get('raison_refus', 'Critères non atteints')
            html += f"<td>{verdict}</td>"
            html += f"<td><a href='{r.get('url', '#')}'>Voir</a></td></tr>"
        
        html += "</table>"
        
        requests.post("https://api.brevo.com/v3/smtp/email", 
            headers={"api-key": BREVO_KEY}, 
            json={
                "sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, 
                "to": [{"email": "bertrand@urban-agency.com"}], 
                "subject": "🛠️ LAB : Diagnostic Qualification IA", 
                "htmlContent": html
            })
        logging.info("📧 Rapport de diagnostic envoyé !")

if __name__ == "__main__":
    main()
