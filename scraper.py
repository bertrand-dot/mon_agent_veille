import os
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF (lecture de PDF)
import google.generativeai as genai

# 1. Configuration de l'IA (utilise votre Secret GEMINI_API_KEY)
genai.configure(api_key=os.environ["GEMINI_API_KEY"])
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. Vos cibles (ajoutez ici les URLs des pages "publications" de vos EPA/EPF)
SITES = [
    {"nom": "Grand Paris Aménagement", "url": "https://www.grandparisamenagement.fr/publications"}
]

def extraire_texte_pdf(pdf_url):
    """Télécharge et lit les 5 premières pages d'un PDF."""
    try:
        response = requests.get(pdf_url, timeout=10)
        with fitz.open(stream=response.content, filetype="pdf") as doc:
            texte = ""
            for page in doc[:5]: # On limite aux 5 premières pages pour la vitesse
                texte += page.get_text()
            return texte
    except Exception as e:
        print(f"Erreur lecture PDF {pdf_url}: {e}")
        return None

def analyser_signal_faible(texte_pdf, source_nom):
    """Envoie le texte à Gemini pour détecter les opportunités."""
    prompt = f"""
    Tu es un expert en développement immobilier et foncier. 
    Analyse cet extrait de compte-rendu provenant de {source_nom}.
    RECHERCHE : Lancement de concours d'archi, désignation de promoteurs, études de faisabilité, ou avis de préemption.
    
    SI TU TROUVES : Fais un résumé très court (3 phrases max) avec le lieu, le projet et l'échéance.
    SI TU NE TROUVES RIEN : Réponds exactement par le mot 'NÉANT'.
    
    TEXTE : {texte_pdf[:8000]}
    """
    response = model.generate_content(prompt)
    return response.text

def main():
    for site in SITES:
        print(f"--- Scan de {site['nom']} ---")
        try:
            res = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Recherche des liens PDF
            for link in soup.find_all('a', href=True):
                if '.pdf' in link['href']:
                    pdf_url = link['href']
                    if not pdf_url.startswith('http'):
                        pdf_url = "https://www.grandparisamenagement.fr" + pdf_url # Ajuster selon le site
                    
                    print(f"Analyse du document : {pdf_url}")
                    texte_brut = extraire_texte_pdf(pdf_url)
                    
                    if texte_brut:
                        resultat = analyser_signal_faible(texte_brut, site['nom'])
                        if "NÉANT" not in resultat.upper():
                            print(f"⚠️ SIGNAL DÉTECTÉ : {resultat}")
                            # Ici, vous pourrez ajouter la fonction d'envoi Discord/Email
        except Exception as e:
            print(f"Erreur sur le site {site['nom']}: {e}")

if __name__ == "__main__":
    main()
