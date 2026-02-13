import os
import requests
import json
import logging
import csv
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
SCRAPER_KEY = os.environ.get("SCRAPERAPI_KEY")

client = genai.Client(api_key=GEMINI_KEY) if GEMINI_KEY else None
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(message)s")

def extraire_contenu_profond(url):
    """Ouvre l'article et nettoie le texte (Coût: 1 crédit)."""
    try:
        proxy_url = f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url}"
        res = requests.get(proxy_url, timeout=30)
        if res.status_code != 200: return ""
        
        soup = BeautifulSoup(res.text, 'html.parser')
        # Nettoyage des éléments inutiles
        for s in soup(['nav', 'footer', 'script', 'style', 'header']): s.decompose()
        
        # Détection de PDF
        texte = soup.get_text(separator=' ')
        for a in soup.find_all('a', href=True):
            if a['href'].lower().endswith('.pdf'):
                pdf_url = a['href']
                if not pdf_url.startswith('http'):
                    from urllib.parse import urljoin
                    pdf_url = urljoin(url, pdf_url)
                try:
                    pdf_res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={pdf_url}")
                    doc = fitz.open(stream=pdf_res.content, filetype="pdf")
                    texte += " [CONTENU PDF] " + "".join([p.get_text() for p in doc[:5]])
                except: continue
        
        return texte[:15000]
    except: return ""

def main():
    leads = []
    logging.info("🚀 Démarrage du Test Laser (Version Blindée)")
    
    try:
        # On force l'encodage cp1252 (Western Europe) et on nettoie les espaces
        with open('Lab/test_cibles.csv', mode='r', encoding='cp1252') as f:
            # Sniffer pour détecter si c'est , ou ;
            sample = f.read(2048)
            f.seek(0)
            dialect = csv.Sniffer().sniff(sample)
            reader = csv.DictReader(f, dialect=dialect)
            
            # NETTOYAGE DES EN-TÊTES (enlève les espaces invisibles)
            reader.fieldnames = [fn.strip() for fn in reader.fieldnames]
            logging.info(f"📋 Colonnes nettoyées : {reader.fieldnames}")

            for row in reader:
                # Accès aux colonnes avec nettoyage des valeurs
                nom = row.get("Nom de l'Organisme", "").strip()
                url_actu = row.get("URL_Directe", "").strip()
                
                if not nom or not url_actu:
                    continue

                logging.info(f"🔎 Analyse de : {nom}")
                
                # 1. On va sur la page d'actualités
                res = requests.get(f"https://api.scraperapi.com/?api_key={SCRAPER_KEY}&url={url_actu}")
                soup = BeautifulSoup(res.text, 'html.parser')
                
                # 2. On cherche les 3 premiers liens "longs" (probablement des articles)
                liens = [a for a in soup.find_all('a', href=True) if len(a.text.strip()) > 30]
                
                for lien in liens[:2]: # Test sur 2 articles par cible
                    full_url = lien['href'] if lien['href'].startswith('http') else url_actu
                    txt = extraire_contenu_profond(full_url)
                    
                    if len(txt) > 300:
                        prompt = f"Analyse ce projet pour {nom}. Est-ce un projet d'envergure (>10M€) ? Réponse JSON : {{'projet':'nom', 'analyse':'60 mots', 'score':4}}. DATA: {txt[:7000]}"
                        resp = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
                        
                        try:
                            ana = json.loads(resp.text.replace('```json', '').replace('```', '').strip())
                            ana['url'] = full_url
                            ana['autorite'] = nom
                            leads.append(ana)
                            logging.info(f"✅ Lead trouvé : {ana['projet']}")
                        except: continue
                        
    except Exception as e:
        logging.error(f"❌ Erreur critique : {e}")

    # 3. Envoi du rapport
    if leads:
        corps = "".join([f"<div style='margin-bottom:20px; border-bottom:1px solid #eee;'><h3>{l['autorite']} : {l['projet']}</h3><p>{l['analyse']}</p><a href='{l['url']}'>Source ↗</a></div>" for l in leads])
        requests.post("https://api.brevo.com/v3/smtp/email", 
            json={"sender": {"name": "Lab UA", "email": "bertrand@urban-agency.com"}, 
                  "to": [{"email": "bertrand@urban-agency.com"}], 
                  "subject": "🧪 TEST LAB : Résultats Laser OK", "htmlContent": corps}, 
            headers={"api-key": BREVO_KEY})
        logging.info("📧 Mail de test envoyé avec succès !")
    else:
        logging.info("∅ Aucun lead qualifié trouvé.")

if __name__ == "__main__": main()
