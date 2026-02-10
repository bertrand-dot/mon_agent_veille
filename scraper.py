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

# Initialisation Gemini
if GEMINI_KEY:
    try:
        genai.configure(api_key=GEMINI_KEY)
        model = genai.GenerativeModel("gemini-pro")
        logging.info("✅ Moteur de raisonnement Gemini activé.")
    except Exception as e:
        logging.error(f"❌ Erreur Gemini: {e}")

# --- 2. EXTRACTION PROFONDE (DEEP SCRAPING) ---

def extraire_texte_integral(url):
    """Télécharge la page et nettoie le texte pour l'analyse IA"""
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        res = requests.get(url, timeout=15, headers=headers)
        if res.status_code != 200: return ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        # Nettoyage des éléments non textuels
        for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form']):
            tag.decompose()
            
        # Extraction et nettoyage des espaces
        texte = soup.get_text(separator=' ')
        lignes = (line.strip() for line in texte.splitlines())
        clean_text = '\n'.join(line for line in lignes if line)
        
        return clean_text[:5000] # On donne 5000 caractères pour un raisonnement riche
    except Exception as e:
        logging.warning(f"⚠️ Lecture impossible pour {url}: {e}")
        return ""

# --- 3. RECHERCHE CIBLÉE BDX ---

def chercher_opportunites_bordeaux(entite):
    """Recherche 30 résultats sur 6 mois axés sur la mutation urbaine"""
    if not SERPAPI_KEY: return []
    
    # Requête 'Raisonnement' : on cherche les causes (friches, délibérations) plutôt que les effets (concours déjà lancés)
    query = f'"{entite}" (Bordeaux OR Métropole) (friche OR "régénération urbaine" OR délibération OR "portage foncier" OR ZAC OR "avis de marché")'
    
    params = {
        "engine": "google",
        "q": query,
        "api_key": SERPAPI_KEY,
        "num": 30,
        "gl": "fr",
        "hl": "fr",
        "tbs": "qdr:m6" # Scan sur 6 mois
    }
    try:
        res = requests.get("https://serpapi.com/search", params=params, timeout=20).json()
        return res.get("organic_results", [])
    except Exception as e:
        logging.error(f"❌ Erreur SerpApi: {e}")
        return []

# --- 4. LE MOTEUR DE RAISONNEMENT (PROMPT) ---

def analyser_ia_raisonnement(item, texte_complet):
    """Analyse les signaux faibles et identifie le potentiel pour Urban Agency"""
    contexte = texte_complet if len(texte_complet) > 300 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Tu es le Directeur du Développement Stratégique d'Urban Agency. 
    Tu es un expert en régénération urbaine à Bordeaux.
    
    MISSION : Analyser ce contenu pour identifier des opportunités architecturales d'envergure.
    
    TON RAISONNEMENT DOIT SUIVRE CETTE LOGIQUE :
    1. ANALYSE DU SITE : Est-ce une friche industrielle, ferroviaire ou un secteur à fort potentiel de mutation ?
    2. DÉTECTION DU SIGNAL : S'agit-il d'un signal faible (délibération, étude pré-opérationnelle, acquisition foncière EPF/EPA) ?
    3. PROJECTION : Même si "concours" n'est pas écrit, est-ce qu'une compétition architecturale est prévisible (ex: dépollution = concours à +12 mois) ?
    
    FORMAT JSON STRICT :
    {{
      "projet": "Nom du site et localisation précise",
      "score": 0,
      "analyse_strategique": "Ton raisonnement : pourquoi est-ce une pépite ? Quel est l'indice de projet ?",
      "action_recommandee": "Action immédiate pour l'agence",
      "type_signal": "SIGNAL FORT ou SIGNAL FAIBLE"
    }}
    
    TEXTE :
    {item.get('title')} | {contexte}"""
    
    try:
        res = model.generate_content(prompt)
        return json.loads(res.text.replace('```json', '').replace('```', '').strip())
    except:
        return {"score": 0, "projet": item.get('title'), "analyse_strategique": "Signal non exploitable"}

# --- 5. RAPPORT D'INTELLIGENCE ---

def envoyer_rapport_strategique(resultats):
    if not resultats: return
    
    date_str = datetime.now().strftime('%d/%m/%Y')
    subject = f"🎯 Radar Stratégique Bordeaux : {len(resultats)} Signaux Détectés"
    
    lignes = ""
    for o in sorted(resultats, key=lambda x: x['score'], reverse=True):
        color = "#e74c3c" if o['score'] >= 2 else "#3498db"
        lignes += f"""
        <div style="border-left:5px solid {color}; padding:15px; margin-bottom:20px; background:#fff; border-radius:4px;">
            <b style="font-size:18px; color:#2c3e50;">{o['projet']}</b> <span style="font-size:12px; color:{color};">[{o.get('type_signal')}]</span><br>
            <p style="margin:10px 0; font-size:14px;"><b>Analyse Stratégique :</b> {o['analyse_strategique']}</p>
            <p style="margin:5px 0; font-size:14px; color:#27ae60;"><b>Action UA :</b> {o['action_recommandee']}</p>
            <a href="{o['url']}" style="color:{color}; font-weight:bold; font-size:12px; text-decoration:none;">ACCÉDER À LA SOURCE →</a>
        </div>"""

    full_html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:Arial;">
        <div style="max-width:700px; margin:auto;">
            <img src="{LOGO_URL}" height="45" style="margin-bottom:20px;">
            <h2 style="color:#2c3e50;">Intelligence Territoriale & Régénération Urbaine</h2>
            {lignes}
        </div>
    </body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 6. EXECUTION ---

def main():
    logging.info("🚀 Lancement du scan de raisonnement stratégique...")
    
    hist = {}
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        
    resultats = []
    cibles = ["Bordeaux", "Bordeaux Métropole", "EPA Bordeaux Euratlantique", "EPF Nouvelle-Aquitaine", "La Fabrique de Bordeaux Métropole"]
    
    # Priorité au CSV si présent
    if os.path.exists("cibles.csv"):
        with open("cibles.csv", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            cibles = [row.get("Nom de l'Organisme") for row in reader if row.get("Nom de l'Organisme")]

    for cible in cibles:
        logging.info(f"🔎 Enquête profonde sur : {cible}")
        items = chercher_opportunites_bordeaux(cible)
        
        for i in items:
            url = i.get('link')
            if not url or url in hist: continue
            
            # ÉTAPE CLÉ : Lecture intégrale
            contenu = extraire_texte_integral(url)
            
            # Raisonnement IA
            analyse = analyser_ia_raisonnement(i, contenu)
            
            if analyse.get('score', 0) >= 1:
                resultats.append({"url": url, **analyse})
                logging.info(f"   🎯 Signal identifié : {analyse['projet']}")
            
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": analyse.get('score', 0)}

    envoyer_rapport_strategique(resultats)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)
    logging.info("🏁 Fin de mission.")

if __name__ == "__main__":
    main()
