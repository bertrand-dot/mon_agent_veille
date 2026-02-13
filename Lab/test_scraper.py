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

# Liste noire pour éviter les pages "parasites"
BLACKLIST = ['cookie', 'recherche', 'search', 'mentions', 'legales', 'contact', 'plan', 'login', 'politique']

# --- 2. FONCTIONS D'EXTRACTION ---

def extraire_propre(url):
    """Extrait le texte utile et le titre via ScraperAPI (Mode Rendu)."""
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if res.status_code != 200: return "", "Erreur", ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        titre = soup.title.string.strip() if soup.title else "Article"
        
        # Nettoyage des zones de bruit (menu, footer)
        for tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style']):
            tag.decompose()
            
        return soup.get_text(separator=' ')[:15000], "OK", titre
    except: return "", "Erreur", ""

def recherche_linkedin_google(nom_organisme, url_li):
    """Capture les signaux faibles LinkedIn via les snippets Google."""
    try:
        query = f'"{nom_organisme}" site:linkedin.com/company'
        params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 5}
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = res.json()
        snippets = [f"{r.get('title')} : {r.get('snippet')}" for r in data.get("organic_results", [])]
        return " | ".join(snippets)
    except: return ""

# --- 3. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte, source_type):
    """Analyse stratégique incluant la détection de signaux faibles."""
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal pour {nom} (Source: {source_type}) au regard de notre ADN.

    --- ADN VALORISÉ ---
    Iconique, Régénération friches, Densité qualitative, Construction Bois, Waterfront/Résilience.

    --- MATRICE DE CLASSEMENT ---
    1. SPRINT : Appel d'offre et candidature MOE / AMI officiel. Deadline < 30j. Budget > 10M€ HT.
    2. RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois. Signaux faibles de programmation.
    3. EXPLORATION : Innovation (Bas-carbone, réemploi). Programmistes désignés.
    4. RÉSEAU : Partenaires (Promoteurs/Bailleurs) mentionnés.

    CRITÈRES STRICTS : Budget > 10M€ HT / Surfaces > 3000m²-5000m².

    FORMAT JSON :
    {{
      "projet": "Nom précis",
      "autorite": "{nom}",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "matching_dna": "Lien avec notre vision",
      "analyse_ua": "Analyse tactique et signaux faibles (80 mots)",
      "action": "Conseil pour Bertrand"
    }}
    DATA : {titre} | {texte[:8000]}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        raw_json = resp.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw_json)
        if isinstance(data, list): data = data[0]
        return data
    except: return None

# --- 4. MAIN ---

def main():
    leads = []
    logs_diag = []
    
    with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

        for row in reader:
            nom = row.get("Nom de l'Organisme", "").strip()
            url_web = row.get("URL_Directe", "").strip()
            url_li = row.get("LinkedIn_Cible", "").strip()
            if not nom: continue

            # A. SCAN WEB
            if url_web:
                idx_txt, _, idx_titre = extraire_propre(url_web)
                # Si c'est une page liste (Index), on va chercher l'article le plus riche
                soup_idx = BeautifulSoup(requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_web}").text, 'html.parser')
                liens_valides = []
                for a in soup_idx.find_all('a', href=True):
                    href = a['href'].lower()
                    if len(a.get_text().strip()) > 30 and not any(w in href for w in BLACKLIST):
                        liens_valides.append(urljoin(url_web, a['href']))
                
                for art_url in liens_valides[:2]:
                    txt, _, titre = extraire_propre(art_url)
                    if len(txt) > 500:
                        ana = qualifier_ia_ua(nom, titre, txt, "Web")
                        if ana:
                            ana['url'] = art_url
                            leads.append(ana)
                            logs_diag.append({'org': nom, 'score': ana['score_interne'], 'url': art_url})

            # B. SCAN LINKEDIN (via Google)
            if url_li:
                txt_li = recherche_linkedin_google(nom, url_li)
                if len(txt_li) > 100:
                    ana = qualifier_ia_ua(nom, "Signaux LinkedIn", txt_li, "LinkedIn")
                    if ana:
                        ana['url'] = url_li
                        leads.append(ana)
                        logs_diag.append({'org': nom, 'score': ana['score_interne'], 'url': url_li})

    # --- 5. ENVOI DES MAILS ---
    if leads:
        # Mail d'Analyse (Signaux Faibles)
        html_anal = "<h2>🎯 Lab UA : Analyse des Signaux Faibles</h2>"
        for l in leads:
            color = "#27ae60" if l['score_interne'] >= 3 else "#f39c12"
            html_anal += f"""
            <div style='border-left:5px solid {color}; padding:15px; background:#f9f9f9; margin-bottom:20px;'>
                <h3>{l['autorite']} : {l['projet']}</h3>
                <p><b>Catégorie :</b> {l['categorie']} | <b>Score :</b> {l['score_interne']}/5</p>
                <p><b>Matching ADN :</b> {l['matching_dna']}</p>
                <p><b>Analyse UA :</b> {l['analyse_ua']}</p>
                <p style='color:green;'><b>Action :</b> {l['action']}</p>
                <a href='{l['url']}'>Consulter la source ↗</a>
            </div><hr>"""
        
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
            json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, 
                  "to":[{"email":"bertrand@urban-agency.com"}], 
                  "subject":"🧪 LAB : Analyse & Signaux Faibles", "htmlContent": html_anal})

    # Mail de Contrôle Technique
    html_ctrl = "<h2>🛠️ Contrôle Technique des URLs lues</h2><ul>"
    for log in logs_diag:
        html_ctrl += f"<li>{log['org']} (Score: {log['score']}/5) - <a href='{log['url']}'>{log['url']}</a></li>"
    html_ctrl += "</ul>"
    requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
        json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, 
              "to":[{"email":"bertrand@urban-agency.com"}], 
              "subject":"🛠️ LAB : Contrôle Technique", "htmlContent": html_ctrl})

if __name__ == "__main__": main()
