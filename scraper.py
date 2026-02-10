import os
import requests
import csv
import re
import json
from bs4 import BeautifulSoup
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime
import logging

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_CX = os.environ.get("GOOGLE_SEARCH_CX")
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def chercher_signaux_google(nom_organisme):
    """Effectue une recherche ciblée sur les signaux faibles (friches, délibérations, concours)"""
    if not GOOGLE_KEY or not GOOGLE_CX: return []
    
    # Requête type 'Intelligence Économique'
    query = f'site:*.fr "{nom_organisme}" (délibération OR "friche industrielle" OR "appel à projets" OR "concours d\'architecture" OR "reconversion")'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {'key': GOOGLE_KEY, 'cx': GOOGLE_CX, 'q': query, 'dateRestrict': 'm2', 'num': 5}
    
    try:
        res = requests.get(url, params=params).json()
        return [{'titre': i['title'], 'url': i['link'], 'snippet': i['snippet']} for i in res.get('items', [])]
    except: return []

def analyser_ia_strategique(texte, source):
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    ÉVALUE le potentiel de ce texte pour gagner un concours ou une mission de reconversion urbaine.
    
    POINTS CLÉS :
    - Score 3 : Projet concret mentionné, friche identifiée, concours imminent, délibération de budget.
    - Score 2 : Étude de faisabilité lancée, signal faible de mutation urbaine.
    - Score 1 : Veille institutionnelle simple.
    
    RETOURNE JSON : {{"titre": "...", "resume": "Explique l'opportunité commerciale", "score": 0-3}}
    SOURCE : {source}
    TEXTE : {texte[:12000]}"""
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except: return {"score": 0}

def envoyer_mail_strategique(opportunites):
    if not opportunites: return
    
    corps = ""
    for op in opportunites:
        color = "#e74c3c" if op['score'] == 3 else "#3498db"
        corps += f"""<div style="border-left:5px solid {color}; padding:15px; margin-bottom:20px; background:#fff;">
            <b style="font-size:16px; color:#2c3e50;">{op['titre']}</b><br>
            <i style="color:#7f8c8d;">Source : {op['nom_source']}</i>
            <p style="font-size:14px; color:#333;">{op['resume']}</p>
            <a href="{op['url']}" style="color:{color}; font-weight:bold;">VOIR L'OPPORTUNITÉ →</a>
        </div>"""

    html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:Arial;">
        <div style="max-width:600px; margin:auto; background:white; padding:20px; border-radius:10px;">
            <img src="{LOGO_URL}" height="40"><br>
            <h2 style="color:#2c3e50; border-bottom:2px solid #eee; padding-bottom:10px;">RADAR OPPORTUNITÉS HAUTE-PRÉCISION</h2>
            {corps}
        </div>
    </body></html>"""

    requests.post("https://api.api.brevo.com/v3/smtp/email", 
        json={{"sender": {{"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"}}, 
              "to": [{{"email": "bertrand@urban-agency.com"}}], 
              "subject": f"🎯 {len(opportunites)} Signaux de Marché Détectés", "htmlContent": html}}, 
        headers={{"api-key": BREVO_KEY}})

def main():
    if not os.path.exists('cibles.csv'): return
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0'})
    resultats = []

    with open('cibles.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            
            print(f"Intelligence sur {nom}...")
            
            # Méthode 1 : Recherche Google (Signaux Faibles)
            signaux = chercher_signaux_google(nom)
            for s in signaux:
                res = analyser_ia_strategique(s['snippet'] + " " + s['titre'], nom)
                if res['score'] >= 2:
                    resultats.append({"url": s['url'], "nom_source": nom, **res})
            
            # Méthode 2 : Scan Direct (si URL fournie)
            url_direct = row.get("URL Actualités / Projets")
            if url_direct:
                # Analyse de la page d'accueil des projets
                res_direct = analyser_ia_strategique(url_direct, nom)
                if res_direct['score'] >= 2:
                    resultats.append({"url": url_direct, "nom_source": nom, **res_direct})

    envoyer_mail_strategique(resultats)
    print("✅ Rapport d'intelligence envoyé.")

if __name__ == "__main__": main()
