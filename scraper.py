import os
import requests
import csv
import json
import logging
from bs4 import BeautifulSoup
import google.generativeai as genai
from datetime import datetime

# --- 1. CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# Configuration IA
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-pro")
        logging.info("✅ Intelligence Artificielle activée.")
    except Exception as e:
        logging.error(f"❌ Erreur config Gemini: {e}")

# --- 2. FONCTIONS DE LECTURE PROFONDE ---

def extraire_texte_page(url):
    """Télécharge la page et extrait le contenu textuel utile"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        response = requests.get(url, timeout=12, headers=headers)
        if response.status_code != 200: return ""
        
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # Nettoyage : on enlève le code inutile
        for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
            element.decompose()
            
        text = soup.get_text(separator=' ')
        # Nettoyage des espaces et limitation à 4000 caractères pour l'IA
        lines = (line.strip() for line in text.splitlines())
        chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
        clean_text = '\n'.join(chunk for chunk in chunks if chunk)
        
        return clean_text[:4000]
    except Exception as e:
        logging.warning(f"⚠️ Impossible de lire le contenu de {url}")
        return ""

def chercher_serpapi(nom_organisme):
    """Recherche 20 résultats sur 6 mois via SerpApi"""
    if not SERPAPI_KEY: return []
    query = f'"{nom_organisme}" (délibération OR friche OR concours OR "appel à projets" OR ZAC)'
    url = "https://serpapi.com/search"
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 20,
        "gl": "fr",
        "hl": "fr",
        "tbs": "qdr:m6" 
    }
    try:
        res = requests.get(url, params=params, timeout=20).json()
        return res.get("organic_results", [])
    except:
        return []

# --- 3. ANALYSE STRATÉGIQUE ---

def analyser_opportunite(item, texte_complet):
    """L'IA analyse le texte profond pour en extraire la valeur métier"""
    source_info = texte_complet if len(texte_complet) > 200 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Directeur du Développement chez Urban Agency.
    CONTEXTE : Tu analyses des signaux faibles pour détecter des futurs projets d'architecture ou d'urbanisme.
    
    MISSION : Evaluer le potentiel de ce signal.
    
    GRILLE DE SCORE :
    3 : Opportunité immédiate (Concours lancé, Avis de marché, Lauréat cité).
    2 : Signal stratégique (ZAC créée, étude de friche, délibération de mutation).
    1 : Veille territoriale (Article de presse, vie du quartier).
    0 : Bruit (Archives, RH, annuaire).

    CONSIGNES :
    - Identifie l'ACTEUR clé.
    - Explique l'OPPORTUNITÉ cachée (ex: 'Dépollution en cours, donc concours de maîtrise d'œuvre probable sous 12 mois').
    - Recommande une ACTION concrète.

    FORMAT JSON : 
    {{
      "titre": "...",
      "score": 0,
      "analyse": "...",
      "action": "..."
    }}

    CONTENU : {item.get('title')} | {source_info}"""
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"score": 0}

# --- 4. COMMUNICATION ---

def envoyer_mail(resultats):
    if not resultats: return
    
    date_str = datetime.now().strftime('%d/%m/%Y')
    subject = f"🎯 Radar Stratégique : {len(resultats)} Signaux Détectés"
    
    blocs = ""
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        color = "#e74c3c" if o['score'] == 3 else "#3498db" if o['score'] == 2 else "#95a5a6"
        blocs += f"""
        <div style="border-left:5px solid {color}; padding:20px; margin-bottom:20px; background:#fff; border-radius:4px; box-shadow:0 2px 5px rgba(0,0,0,0.05);">
            <div style="color:{color}; font-size:11px; font-weight:bold; text-transform:uppercase;">Score {o['score']}/3</div>
            <h3 style="margin:5px 0; color:#2c3e50;">{o['titre']}</h3>
            <p style="font-size:14px; color:#333;"><b>Analyse :</b> {o['analyse']}</p>
            <p style="font-size:14px; color:#27ae60;"><b>Action recommandée :</b> {o['action']}</p>
            <a href="{o['url']}" style="display:inline-block; margin-top:10px; color:{color}; text-decoration:none; font-weight:bold; font-size:12px;">ACCÉDER À LA SOURCE →</a>
        </div>"""

    full_html = f"""<html><body style="background:#f8f9fa; padding:20px; font-family:Helvetica, Arial, sans-serif;">
        <div style="max-width:650px; margin:auto;">
            <img src="{LOGO_URL}" height="45" style="margin-bottom:25px;">
            <h2 style="color:#2c3e50; border-bottom:1px solid #ddd; padding-bottom:10px;">Intelligence Territoriale & Opportunités</h2>
            {blocs}
            <p style="font-size:10px; color:#999; text-align:center; margin-top:30px;">Analyse automatisée par IA pour Urban Agency.</p>
        </div>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 5. MAIN ---

def main():
    if not os.path.exists("cibles.csv"):
        logging.error("Fichier cibles.csv manquant.")
        return
        
    logging.info("🚀 Lancement du scan Deep Intelligence...")
    
    # Gestion historique
    hist = {}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        
    resultats = []
    with open("cibles.csv", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: continue
            
            logging.info(f"🔎 Analyse profonde de : {nom}")
            items = chercher_serpapi(nom)
            
            for i in items:
                url = i.get('link')
                if not url or url in hist: continue
                
                # ÉTAPE CRUCIALE : Lecture du site
                texte_page = extraire_texte_page(url)
                
                # Analyse IA
                analyse = analyser_opportunite(i, texte_page)
                
                if analyse.get('score', 0) >= 1:
                    resultats.append({"url": url, **analyse})
                    logging.info(f"   🔥 Opportunité trouvée : {analyse['titre']}")
                
                hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_mail(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)
    logging.info("🏁 Mission terminée.")

if __name__ == "__main__":
    main()
