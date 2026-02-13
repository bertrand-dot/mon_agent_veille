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

# Liste noire pour ignorer les pages techniques ou légales
BLACKLIST = ['cookie', 'recherche', 'search', 'mentions', 'legales', 'contact', 'plan', 'login', 'politique', 'accessibilite']

# --- 2. FONCTIONS DE LECTURE ---

def extraire_contenu_complet(url, logs_list, organisme):
    """Extrait le texte et les PDF en enregistrant chaque étape dans les logs."""
    start_time = time.time()
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        dur = round(time.time() - start_time, 2)
        
        if res.status_code != 200:
            logs_list.append({"org": organisme, "type": "Web", "status": f"Erreur {res.status_code}", "dur": dur, "url": url})
            return "", ""

        soup = BeautifulSoup(res.text, 'html.parser')
        titre = soup.title.string.strip() if soup.title else "Sans titre"
        
        # Nettoyage
        for tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style']):
            tag.decompose()
        
        texte = soup.get_text(separator=' ')
        
        # Scan PDF (Signaux faibles majeurs)
        pdf_links = [urljoin(url, a['href']) for a in soup.find_all('a', href=True) if a['href'].lower().endswith('.pdf')]
        for p_url in pdf_links[:3]: # Limite à 3 PDF par page pour le test
            try:
                p_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={p_url}")
                doc = fitz.open(stream=p_res.content, filetype="pdf")
                texte += f" [PDF: {p_url}] " + "".join([p.get_text() for p in doc[:5]])
                logs_list.append({"org": organisme, "type": "PDF", "status": "Succès", "dur": "-", "url": p_url})
            except:
                logs_list.append({"org": organisme, "type": "PDF", "status": "Échec lecture", "dur": "-", "url": p_url})

        status_final = f"Succès ({len(texte)} chars)" if len(texte) > 200 else "Contenu trop court"
        logs_list.append({"org": organisme, "type": "Web", "status": status_final, "dur": dur, "url": url})
        
        return texte[:18000], titre
    except Exception as e:
        logs_list.append({"org": organisme, "type": "Web", "status": f"Exception: {str(e)}", "dur": 0, "url": url})
        return "", ""

def recherche_linkedin_serp(nom_org, url_li, logs_list):
    """Recherche LinkedIn via Google et log le résultat."""
    start_time = time.time()
    try:
        query = f'"{nom_org}" site:linkedin.com/company'
        params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 5}
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        dur = round(time.time() - start_time, 2)
        
        data = res.json()
        snippets = [f"{r.get('title')} : {r.get('snippet')}" for r in data.get("organic_results", [])]
        
        status = f"Succès ({len(snippets)} extraits)" if snippets else "0 résultat Google"
        logs_list.append({"org": nom_org, "type": "LinkedIn (Serp)", "status": status, "dur": dur, "url": url_li})
        
        return " | ".join(snippets)
    except Exception as e:
        logs_list.append({"org": nom_org, "type": "LinkedIn (Serp)", "status": f"Erreur: {str(e)}", "dur": 0, "url": url_li})
        return ""

# --- 3. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte, url):
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal pour {nom} au regard de notre ADN.

    --- ADN VALORISÉ ---
    Iconique, Régénération friches, Densité qualitative, Construction Bois, Waterfront/Résilience.

    --- MATRICE DE CLASSEMENT ---
    1. SPRINT : Appel d'offre et candidature MOE / AMI officiel. Deadline < 30j. Budget > 10M€ HT.
    2. RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois. Signaux faibles (concertation, programmiste).
    3. EXPLORATION : Innovation (Bas-carbone, réemploi, circularité).
    4. RÉSEAU : Partenaires (Promoteurs/Bailleurs) mentionnés.

    CRITÈRES STRICTS : Budget > 10M€ HT / Surfaces > 3000m²-5000m².

    FORMAT JSON :
    {{
      "projet": "Nom précis",
      "autorite": "{nom}",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "matching_dna": "Lien ADN",
      "analyse_ua": "Analyse tactique et signaux faibles (80 mots)",
      "action": "Conseil pour Bertrand"
    }}
    DATA : {titre} | {texte[:8000]}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        raw = resp.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(raw)
        if isinstance(data, list): data = data[0]
        data['url'] = url
        return data
    except: return None

# --- 4. MAIN ---

def main():
    leads = []
    logs_audit = [] # Liste exhaustive de TOUTES les URLs
    
    logging.info("🚀 Démarrage de l'Audit Laser UA (Zéro Historique)")

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
                    logging.info(f"🔎 Analyse Web : {nom}")
                    # 1. On lit l'index pour trouver les liens
                    res_idx = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_web}&render=true")
                    soup_idx = BeautifulSoup(res_idx.text, 'html.parser')
                    
                    liens_trouves = []
                    for a in soup_idx.find_all('a', href=True):
                        href = a['href'].lower()
                        if len(a.get_text().strip()) > 30 and not any(w in href for w in BLACKLIST):
                            liens_trouves.append(urljoin(url_web, a['href']))
                    
                    # 2. On analyse les 5 derniers articles (Audit exhaustif)
                    for art_url in liens_trouves[:5]:
                        txt, titre = extraire_contenu_complet(art_url, logs_audit, nom)
                        if len(txt) > 500:
                            ana = qualifier_ia_ua(nom, titre, txt, art_url)
                            if ana and ana.get('score_interne', 0) >= 2:
                                leads.append(ana)

                # B. EXPLORATION LINKEDIN
                if url_li:
                    logging.info(f"🔎 Analyse LinkedIn : {nom}")
                    txt_li = recherche_linkedin_serp(nom, url_li, logs_audit)
                    if len(txt_li) > 100:
                        ana = qualifier_ia_ua(nom, "Flux LinkedIn", txt_li, url_li)
                        if ana and ana.get('score_interne', 0) >= 2:
                            leads.append(ana)

    except Exception as e:
        logging.error(f"❌ Erreur : {e}")

    # --- 5. ENVOI DES RAPPORTS ---
    
    # RAPPORT 1 : ANALYSE STRATÉGIQUE (Filtré score >= 2)
    if leads:
        html_leads = "<h2>🎯 Lab UA : Signaux & Opportunités</h2>"
        for l in leads:
            html_leads += f"<div style='border-left:5px solid #27ae60; padding:15px; background:#f9f9f9; margin-bottom:20px;'><h3>{l['autorite']} : {l['projet']}</h3><p><b>{l['categorie']}</b> (Score {l['score_interne']}/5)</p><p>{l['analyse_ua']}</p><a href='{l['url']}'>Source ↗</a></div>"
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, "to":[{"email":"bertrand@urban-agency.com"}], "subject":"🧪 LAB : Analyses Stratégiques", "htmlContent":html_leads})

    # RAPPORT 2 : AUDIT TECHNIQUE COMPLET (TOUTES les pages lues)
    html_audit = "<h2>🛠️ Audit Technique : Intégralité des pages lues</h2>"
    html_audit += "<table border='1' style='border-collapse:collapse; width:100%; font-size:11px; font-family:sans-serif;'>"
    html_audit += "<tr style='background:#eee;'><th>Organisme</th><th>Type</th><th>Statut</th><th>Durée</th><th>URL Analysée</th></tr>"
    for log in logs_audit:
        color = "green" if "Succès" in log['status'] else "red"
        html_audit += f"<tr><td>{log['org']}</td><td>{log['type']}</td><td style='color:{color};'>{log['status']}</td><td>{log['dur']}s</td><td><a href='{log['url']}'>{log['url']}</a></td></tr>"
    html_audit += "</table>"
    
    requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
        json={"sender": {"name":"Lab UA", "email":"bertrand@urban-agency.com"}, 
              "to":[{"email":"bertrand@urban-agency.com"}], 
              "subject":"🛠️ LAB : Audit de Navigation Complet", "htmlContent":html_audit})

if __name__ == "__main__": main()
