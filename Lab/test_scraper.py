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
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Liste noire pour éviter les pages inutiles (Cookies, Recherche, etc.)
BLACKLIST = [
    'cookie', 'recherche', 'search', 'mentions', 'legales', 'contact', 
    'plan-du-site', 'accessibilite', 'facebook', 'twitter', 'linkedin', 
    'instagram', 'newsletter', 'connexion', 'login', 'politique'
]

# --- 2. FONCTIONS DE LECTURE ---

def extraire_contenu_propre(url):
    """Extrait le texte en isolant le contenu principal via ScraperAPI."""
    try:
        params = {'api_key': SCRAPER_KEY, 'url': url, 'render': 'true', 'wait': 3000}
        res = requests.get("https://api.scraperapi.com/", params=params, timeout=60)
        if res.status_code != 200: return "", f"Erreur {res.status_code}", ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        titre_page = soup.title.string if soup.title else "Sans titre"
        
        # Suppression des éléments de navigation et de structure
        for tag in soup(['nav', 'footer', 'header', 'aside', 'script', 'style', 'form']):
            tag.decompose()
            
        texte = soup.get_text(separator=' ')
        return texte[:15000], "OK", titre_page
    except Exception as e:
        return "", str(e), ""

def recherche_linkedin_serp(nom_organisme, url_li):
    """Lit LinkedIn via les résultats Google (SerpApi)."""
    try:
        # On cherche les actualités LinkedIn indexées par Google
        query = f'"{nom_organisme}" site:linkedin.com/company'
        params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 5}
        res = requests.get("https://serpapi.com/search", params=params, timeout=30)
        data = res.json()
        
        snippets = [f"{r.get('title')} : {r.get('snippet')}" for r in data.get("organic_results", [])]
        return " | ".join(snippets), f"{len(snippets)} extraits" if snippets else "0 résultat"
    except Exception as e:
        return "", str(e)

# --- 3. ANALYSE IA (PROMPT ASSOCIÉ SENIOR) ---

def qualifier_ia_ua(nom, titre, texte):
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal pour {nom} au regard de notre ADN.

    --- ADN VALORISÉ ---
    Iconique, Régénération friches, Densité qualitative, Construction Bois, Waterfront/Résilience.

    --- MATRICE DE CLASSEMENT ---
    1. SPRINT : Appel d'offre et candidature MOE / AMI officiel. Deadline < 30j. Budget > 10M€ HT + archi non désigné.
    2. RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois.
    3. EXPLORATION : Innovation (Bas-carbone, réemploi). Designation d'un programmiste.
    4. RÉSEAU : Partenaire identifié ayant un interet pour URBAN AGENCY.

    --- RÈGLES D'EXCLUSION STRICTES ---
    1. NATURE : Rénovation énergétique isolée, PMR, infrastructures pures, expertises/études de sol.
    2. VOLUME : Budget < 10M€ HT. Surfaces < 3000m² (logement/tertiaire) ou < 5000m² (équipement).
    3. PROGRAMME : Micro-Équipements, Tertiaire proximité, Logement diffus < 15 lots.

    FORMAT JSON (Analyse 60-80 mots) :
    {{
      "projet": "Nom précis",
      "autorite": "{nom}",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "deadline": "Date ou N/A",
      "matching_dna": "Lien ADN",
      "analyse_ua": "Analyse détaillée de l'enjeu architectural et urbain",
      "raison_refus": "Si score < 2, pourquoi ?"
    }}
    DATA : {titre} | {texte[:8000]}"""
    
    try:
        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        res_text = resp.text.replace('```json', '').replace('```', '').strip()
        data = json.loads(res_text)
        # Correction du TypeError : si l'IA renvoie une liste, on prend le premier élément
        if isinstance(data, list): data = data[0]
        return data
    except: 
        return {'score_interne': 0, 'raison_refus': 'Erreur de lecture IA (JSON)'}

# --- 4. MAIN ---

def main():
    resultats_diag = []
    logging.info("🚀 Lancement du Scan Laser (Mode Correction Technique)")
    
    with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]

        for row in reader:
            nom = row.get("Nom de l'Organisme", "").strip()
            url_web = row.get("URL_Directe", "").strip()
            url_li = row.get("LinkedIn_Cible", "").strip()
            if not nom: continue

            # A. ANALYSE WEB
            if url_web:
                txt, status, titre_reel = extraire_contenu_propre(url_web)
                if len(txt) > 500:
                    # On vérifie s'il faut creuser ou analyser la page directement
                    is_index = any(x in titre_reel.lower() or x in url_web.lower() for x in ["actualités", "agenda", "actu"])
                    
                    if is_index:
                        logging.info(f"🔎 Index détecté pour {nom}, recherche d'un article...")
                        soup = BeautifulSoup(requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_web}").text, 'html.parser')
                        for a in soup.find_all('a', href=True):
                            href = a['href'].lower()
                            if len(a.get_text().strip()) > 30 and not any(word in href for word in BLACKLIST):
                                full_url = urljoin(url_web, a['href'])
                                txt_art, _, titre_art = extraire_contenu_propre(full_url)
                                ana = qualifier_ia_ua(nom, titre_art, txt_art)
                                ana.update({'url': full_url, 'type': 'Web (Profondeur)', 'titre_lu': titre_art})
                                resultats_diag.append(ana)
                                break
                    else:
                        ana = qualifier_ia_ua(nom, titre_reel, txt)
                        ana.update({'url': url_web, 'type': 'Web (Direct)', 'titre_lu': titre_reel})
                        resultats_diag.append(ana)

            # B. ANALYSE LINKEDIN
            if url_li:
                txt_li, status_li = recherche_linkedin_serp(nom, url_li)
                if len(txt_li) > 50:
                    ana = qualifier_ia_ua(nom, "Actualités LinkedIn", txt_li)
                    ana.update({'url': url_li, 'type': 'LinkedIn', 'titre_lu': f"Extraits Google ({status_li})"})
                    resultats_diag.append(ana)

    # --- 5. ENVOI DU DIAGNOSTIC ---
    if resultats_diag and BREVO_KEY:
        html = "<h2>🛠️ Diagnostic Qualification Lab</h2><table border='1' style='border-collapse:collapse; width:100%; font-size:12px; font-family:sans-serif;'>"
        html += "<tr style='background:#2c3e50; color:white;'><th>Organisme</th><th>Type</th><th>Titre lu</th><th>Score</th><th>Verdict</th></tr>"
        for r in resultats_diag:
            bg = "#e8f5e9" if r.get('score_interne', 0) >= 2 else "#ffebee"
            html += f"<tr style='background:{bg};'><td>{r.get('autorite')}</td><td>{r.get('type')}</td><td>{r.get('titre_lu')}</td>"
            html += f"<td style='text-align:center;'><b>{r.get('score_interne')}/5</b></td>"
            html += f"<td>{r.get('analyse_ua') if r.get('score_interne', 0) >= 2 else r.get('raison_refus')}</td></tr>"
        html += "</table>"
        requests.post("https://api.brevo.com/v3/smtp/email", headers={"api-key": BREVO_KEY}, 
            json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, "to": [{"email": "bertrand@urban-agency.com"}], 
            "subject": "🛠️ LAB : Rapport de Qualification", "htmlContent": html})

if __name__ == "__main__": main()
