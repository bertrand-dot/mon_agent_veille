import os
import requests
import json
import logging
import time
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime

# --- 1. CONFIGURATION ---
# Assurez-vous que vos secrets GitHub (API Keys) sont à jour
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

HISTORY_FILE = "download_history.json"
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        logging.info("✅ Moteur Gemini 2.5 Pro activé (Analyse de Haute Précision).")
    except Exception as e:
        logging.error(f"❌ Erreur configuration Gemini: {e}")

# --- 2. EXTRACTION DE CONTENU (WEB & PDF) ---

def extraire_texte(url):
    """Extrait le texte brut d'une page HTML ou d'un document PDF"""
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, timeout=15, headers=headers)
        if res.status_code != 200: return ""
        
        content_type = res.headers.get('Content-Type', '').lower()
        
        # Cas PDF : Extraction avec PyMuPDF
        if 'application/pdf' in content_type or url.lower().endswith('.pdf'):
            doc = fitz.open(stream=res.content, filetype="pdf")
            text = "".join([page.get_text() for page in doc[:10]]) # 10 premières pages
            doc.close()
            return " ".join(text.split())[:15000] # Capacité accrue pour le modèle Pro

        # Cas HTML : Nettoyage avec BeautifulSoup
        else:
            soup = BeautifulSoup(res.text, 'html.parser')
            for s in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']): s.decompose()
            return " ".join(soup.get_text(separator=' ').split())[:12000]
    except Exception as e:
        logging.warning(f"⚠️ Erreur lors de l'extraction de {url[:40]}: {e}")
        return ""

# --- 3. ANALYSE IA (MODÈLE 2.5 PRO) ---

def analyser_ia(item, contenu_web):
    if not client: return {"score": 0}
    
    # Pause de sécurité pour respecter les quotas du modèle Pro
    # (Peut être réduite à 1-2s si vous avez un compte payant/crédits actifs)
    time.sleep(12) 
    
    contexte = contenu_web if len(contenu_web) > 400 else item.get('snippet', '')
    
    prompt = f"""RÔLE : Expert en analyse de données stratégiques.
    MISSION : Extraire les informations critiques et évaluer la pertinence opérationnelle.
    
    CRITÈRES D'ANALYSE :
    - Score : Sur 5 (5 étant une priorité absolue).
    - Procédure : Identifier le type de marché ou de consultation.
    - Échéance : Extraire une date précise uniquement si mentionnée.
    
    FORMAT JSON STRICT :
    {{
      "projet": "Nom du projet identifié",
      "score": 0,
      "temperature": "CHAUDE (Action immédiate) ou FROIDE (Veille)",
      "procedure": "Type de procédure",
      "deadline": "Date limite (ou N/A)",
      "analyse": "Synthèse stratégique (max 3 phrases)",
      "action": "Recommandation concrète"
    }}
    DONNÉES : {item.get('title')} | {contexte}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        text_json = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(text_json)
    except Exception as e:
        logging.warning(f"⚠️ Erreur IA : {e}")
        return {"score": 0}

# --- 4. EXÉCUTION PRINCIPALE ---

def main():
    logging.info("🚀 Lancement du scan haute précision...")
    
    # Chargement de l'historique
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    resultats = []
    # Configurez vos cibles ici
    cibles = ["Cible 1", "Cible 2"] 
    
    for cible in cibles:
        logging.info(f"🔎 Investigation : {cible}")
        # (Logique de recherche via SerpApi ici)
        # ...
        
    # (Logique d'envoi d'email via Brevo ici)
    # ...

    # Sauvegarde de l'historique
    with open(HISTORY_FILE, 'w') as f:
        json.dump(hist, f, indent=2)

if __name__ == "__main__":
    main()
