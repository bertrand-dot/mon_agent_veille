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
            # On prend les 3 premières pages pour l'analyse
            texte = "".join([page.get_text() for page in doc[:3]])
            return texte
    except Exception as e:
        print(f"Erreur lecture PDF {pdf_url}: {e}")
        return None

def analyser_signal_faible(texte_pdf, source_nom):
    prompt = f"""
    Tu es un expert en développement immobilier. Analyse ce communiqué de presse de {source_nom}.
    RECHERCHE : Lancement de consultation, désignation de lauréat (promoteur/architecte), signature de vente foncière ou nouveau projet urbain.
    
    SI TU TROUVES : Fais un résumé très court (3 phrases max) avec le lieu précis, le type de projet et les acteurs cités.
    SI TU NE TROUVES RIEN : Réponds exactement par le mot 'NÉANT'.
    
    TEXTE : {texte_pdf[:8000]}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "NÉANT"

def envoyer_email(rapport_final):
    if not BREVO_KEY:
        print("❌ ERREUR : BREVO_API_KEY manquante.")
        return
    
    url = "
