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

# Mots-clés pour bannir les pages techniques/légales
BLACKLIST = ['cookie', 'recherche', 'search', 'mentions', 'legales', 'contact', 'login', 'politique', 'accessibilite']

# --- 2. FONCTIONS DE LECTURE (Web & PDF) ---

def extraire_contenu_profond(url, logs, org):
    """Lecture ScraperAPI avec rendu JS + extraction PDF."""
    start_time = time.time()
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        dur = round(time.time() - start_time, 2)
        
        if res.status_code != 200:
            logs.append({"org": org, "type": "Web", "status": f"Erreur {res.status_code}", "url": url})
            return "", "Article"

        soup = BeautifulSoup(res.text, 'html.parser')
        titre = soup.title.string.strip() if soup.title else "Article"
        
        for tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style']):
            tag.decompose()
        
        texte = soup.get_text(separator=' ')
        
        # Scan PDF automatique
        pdf_count = 0
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                try:
                    pdf_url = urljoin(url, a['href'])
                    p_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={pdf_url}")
                    doc = fitz.open(stream=p_res.content, filetype="pdf")
                    texte += " [CONTENU PDF] " + "".join([p.get_text() for p in doc[:5]])
                    pdf_count += 1
                except: continue
                
        logs.append({"org": org, "type": "Web", "status": f"Succès ({len(texte)} chars, {pdf_count} PDF)", "url": url})
        return texte[:18000], titre
    except Exception as e:
        logs.append({"org": org, "type": "Web", "status": f"Exception: {str(e)}", "url": url})
        return "", "Erreur"

def recherche_linkedin_serp(nom_org, url_li, logs):
    """Extraction LinkedIn agressive via Google SerpApi."""
    start_time = time.time()
    try:
        # Requête Laser pour les signaux urbains
        query = f'"{nom_org}" (ZAC OR aménagement OR concours OR lauréat OR "m2") site:linkedin.com'
        params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 5, "tbs": "qdr:m"}
        
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = res.json()
        snippets = [f"TITRE: {r.get('title')}\nEXTRAIT: {r.get('snippet')}" for r in data.get("organic_results", [])]
        
        status = f"Succès ({len(snippets)} signaux)" if snippets else "0 signal trouvé"
        logs.append({"org": nom_org, "type": "LinkedIn (Serp)", "status": status, "url": url_li})
        return "\n---\n".join(snippets)
    except Exception as e:
        logs.append({"org": nom_org, "type": "LinkedIn (Serp)", "status": f"Erreur: {str(e)}", "url": url_li})
        return ""

# --- 3. ANALYSE IA (ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte, source_url):
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY.
    MISSION : Qualifier stratégiquement pour {nom}.
    CRITÈRES : Budget > 10M€ HT / Surfaces > 3000m²-5000m².
    ADN : Iconique, Construction Bois, Waterfront, Résilience.

    FORMAT JSON :
    {{
      "projet": "Nom précis",
      "autorite": "{nom}",
      "categorie": "SPRINT (Appel d'offre), RADAR (Anticipation), EXPLORATION (Innovation) ou RÉSEAU (Partenaire)",
      "score_interne": 0,
      "matching_dna": "Lien ADN UA",
      "analyse_ua": "Analyse stratégique et signaux faibles (80 mots)",
      "action": "Conseil d'approche pour Bertrand"
    }}
    DATA : {titre} | {texte[:8000]}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        raw = resp.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw)
        if isinstance(data, list): data = data[0]
        data['url'] = source_url
        return data
    except: return None

# --- 4. MAIN ---

def main():
    leads = []
    logs_audit = []
    logging.info("🚀 Lancement du Lab Laser Hybride (Web + LinkedIn Agression)")

    try:
        with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
            reader = csv.DictReader(f)
            reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

            for row in reader:
                nom = row.get("Nom de l'Organisme", "").strip()
                url_web = row.get("URL_Directe", "").strip()
                url_li = row.get("LinkedIn_Cible", "").strip()
                if not nom: continue

                # A. EXPLORATION WEB
                if url_web:
                    logging.info(f"🔎 Scanning Web : {nom}")
                    txt_idx, tit_idx = extraire_contenu_profond(url_web, logs_audit, nom)
                    # Extraction des liens profonds pour éviter l'institutionnel
                    soup = BeautifulSoup(requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_web}").text, 'html.parser')
                    liens = [urljoin(url_web, a['href']) for a in soup.find_all('a', href=True) if len(a.get_text().strip()) > 30 and not any(w in a['href'].lower() for w in BLACKLIST)]
                    
                    for link in liens[:3]:
                        txt_art, tit_art = extraire_contenu_profond(link, logs_audit, nom)
                        if len(txt_art) > 500:
                            ana = qualifier_ia_ua(nom, tit_art, txt_art, link)
                            if ana and ana.get('score_interne', 0) >= 2: leads.append(ana)

                # B. EXPLORATION LINKEDIN (SERPAPI LASER)
                if url_li:
                    logging.info(f"🔎 Scanning LinkedIn : {nom}")
                    txt_li = recherche_linkedin_serp(nom, url_li, logs_audit)
                    if len(txt_li) > 100:
                        ana = qualifier_ia_ua(nom, "Signaux LinkedIn", txt_li, url_li)
                        if ana and ana.get('score_interne', 0) >= 2: leads.append(ana)

    except Exception as e: logging.error(f"❌ Erreur : {e}")

    # --- 5. ENVOI DES RAPPORTS ---
    if leads:
        html_anal = "<h2>🎯 Lab UA : Analyse des Opportunités</h2>"
        for l in leads:
            html_anal += f"<div style='border-left:5px solid #27ae60; padding:15px; background:#f9f9f9; margin-bottom:20px;'><h3>{l['autorite']} : {l['projet']}</h3><p><b>{l['categorie']}</b> (Score {l['score_interne']}/5)</p><p>{l['analyse_ua']}</p><a href={l['url']}>Source ↗</a></div>"
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, "to":[{"email":"bertrand@urban-agency.com"}], "subject":"🧪 LAB : Analyses & Opportunités", "htmlContent":html_anal})

    # RAPPORT D'AUDIT COMPLET (Toutes les URLs)
    html_audit = "<h2>🛠️ Audit Technique : Intégralité des pages lues</h2><table border='1' style='border-collapse:collapse; width:100%; font-size:10px;'><thead><tr style='background:#eee;'><th>Organisme</th><th>Type</th><th>Statut</th><th>URL</th></tr></thead><tbody>"
    for log in logs_audit:
        html_audit += f"<tr><td>{log['org']}</td><td>{log['type']}</td><td>{log['status']}</td><td>{log['url']}</td></tr>"
    html_audit += "</tbody></table>"
    requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, "to":[{"email":"bertrand@urban-agency.com"}], "subject":"🛠️ LAB : Audit de Navigation", "htmlContent":html_audit})

if __name__ == "__main__": main()
