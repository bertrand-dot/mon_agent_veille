import os
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai
from urllib.parse import urljoin

# 1. Configuration des API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. Cible spécifique : EPA Paris-Saclay
SITES = [
    {
        "nom": "EPA Paris-Saclay", 
        "url": "https://epa-paris-saclay.fr/espace-presse/les-communiques-de-presse/"
    },
]

def extraire_texte_pdf(pdf_url):
    try:
        response = requests.get(pdf_url, timeout=15)
        with fitz.open(stream=response.content, filetype="pdf") as doc:
            texte = "".join([page.get_text() for page in doc[:3]])
            return texte
    except Exception as e:
        print(f"Erreur PDF {pdf_url}: {e}")
        return None

def analyser_signal_faible(texte_pdf, source_nom):
    prompt = f"""
    Tu es un expert en développement immobilier. Analyse ce document de {source_nom}.
    RECHERCHE : Lancement de consultation promoteur, concours d'architecte, ou projets urbains stratégiques.
    SI TU TROUVES : Résumé court (3 lignes) avec lieu et type de projet.
    SI RIEN : Réponds 'NÉANT'.
    TEXTE : {texte_pdf[:8000]}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "NÉANT"

def envoyer_email(rapport_final):
    if not BREVO_KEY:
        print("❌ ERREUR : BREVO_API_KEY manquante dans GitHub Secrets.")
        return
    
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "Veille IA Urban Agency : Paris-Saclay",
        "htmlContent": f"<html><body><h2 style='color:#1a5fb4;'>Rapport de Veille Stratégique</h2>{rapport_final}</body></html>"
    }
    headers = {
        "accept": "application/json", 
        "content-type": "application/json", 
        "api-key": BREVO_KEY
    }
    res = requests.post(url, json=payload, headers=headers)
    print(f"Status envoi Brevo: {res.status_code} - {res.text}")

def main():
    compte_rendu = ""
    du_nouveau = False
    
    for site in SITES:
        print(f"--- Scan de {site['nom']} ---")
        try:
            res = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Recherche des liens vers les communiqués
            for link in soup.find_all('a', href=True):
                href = link['href']
                if '/les-communiques-de-presse/' in href and href != site['url']:
                    communique_url = urljoin(site['url'], href)
                    
                    # On va chercher le PDF dans la page du communiqué
                    try:
                        sub_res = requests.get(communique_url, timeout=10)
                        sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
                        pdf_link = sub_soup.find('a', href=lambda x: x and x.endswith('.pdf'))
                        
                        if pdf_link:
                            pdf_url = urljoin(communique_url, pdf_link['href'])
                            print(f"📄 Analyse de : {pdf_url}")
                            texte = extraire_texte_pdf(pdf_url)
                            if texte:
                                res_ia = analyser_signal_faible(texte, site['nom'])
                                if "NÉANT" not in res_ia.upper():
                                    compte_rendu += f"<p><b>📍 {site['nom']}</b> : {res_ia}<br><a href='{pdf_url}'>Document source</a></p><hr>"
                                    du_nouveau = True
                                    break # On teste le premier pour valider
                    except:
                        continue
        except Exception as e:
            print(f"Erreur sur {site['nom']}: {e}")

    if not du_nouveau:
        compte_rendu = "<p>Aucun nouveau signal détecté aujourd'hui sur Paris-Saclay.</p>"
    
    envoyer_email(compte_rendu)

if __name__ == "__main__":
    main()
