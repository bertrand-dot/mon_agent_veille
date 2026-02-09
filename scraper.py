import os
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai
from urllib.parse import urljoin # Pour gérer les URLs proprement

# 1. Configuration des API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. MODIFIEZ CETTE SECTION POUR CHANGER DE SITE
# Vous pouvez mettre l'URL de n'importe quel EPA/EPF/Collectivité
SITES = [
    {
        "nom": "EPA Paris Saclay", 
        "url": "https://epa-paris-saclay.fr/espace-presse/les-communiques-de-presse/"
    },
]

def extraire_texte_pdf(pdf_url):
    try:
        response = requests.get(pdf_url, timeout=15)
        with fitz.open(stream=response.content, filetype="pdf") as doc:
            # Extraction des 3 premières pages
            texte = "".join([page.get_text() for page in doc[:3]])
            return texte
    except Exception as e:
        print(f"Erreur lecture PDF: {e}")
        return None

def analyser_signal_faible(texte_pdf, source_nom):
    prompt = f"Analyse ce document de {source_nom} et liste les projets immobiliers, lancements de concours ou fonciers. Si rien d'important, réponds 'NÉANT'. Texte: {texte_pdf[:5000]}"
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "NÉANT"

def envoyer_email(rapport_final):
    if not BREVO_KEY:
        print("❌ ERREUR : BREVO_API_KEY manquante dans les secrets GitHub.")
        return
    
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "Rapport de Veille Urban Agency",
        "htmlContent": f"<html><body><h2 style='color:#2c3e50;'>Rapport du jour</h2>{rapport_final}</body></html>"
    }
    headers = {"accept": "application/json", "content-type": "application/json", "api-key": BREVO_KEY}
    res = requests.post(url, json=payload, headers=headers)
    print(f"Status envoi Brevo: {res.status_code}")

def main():
    compte_rendu = ""
    du_nouveau = False
    
    for site in SITES:
        print(f"--- Démarrage du scan : {site['nom']} ---")
        try:
            res = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # On cherche tous les liens
            for link in soup.find_all('a', href=True):
                href = link['href']
                
                # On vérifie si c'est un PDF
                if '.pdf' in href.lower():
                    # urljoin gère automatiquement si l'URL est relative ou absolue
                    pdf_url = urljoin(site['url'], href)
                    
                    print(f"📄 Analyse de : {pdf_url}")
                    texte = extraire_texte_pdf(pdf_url)
                    
                    if texte:
                        res_ia = analyser_signal_faible(texte, site['nom'])
                        if "NÉANT" not in res_ia.upper():
                            print(f"🎯 Signal trouvé !")
                            compte_rendu += f"<p><b>📍 {site['nom']}</b> : {res_ia}<br><a href='{pdf_url}'>Consulter le document</a></p><hr>"
                            du_nouveau = True
        
        except Exception as e:
            print(f"Erreur sur {site['nom']}: {e}")

    if not du_nouveau:
        compte_rendu = "<p>Aucun signal détecté sur les sites surveillés aujourd'hui.</p>"
    
    envoyer_email(compte_rendu)

if __name__ == "__main__":
    main()
