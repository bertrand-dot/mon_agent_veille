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

# 2. Cible : EPA Paris-Saclay
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
            # On analyse les 3 premières pages (souvent suffisant pour un CP)
            texte = "".join([page.get_text() for page in doc[:3]])
            return texte
    except Exception as e:
        print(f"Erreur PDF {pdf_url}: {e}")
        return None

def analyser_signal_faible(texte_pdf, source_nom):
    prompt = f"""
    Tu es un expert en développement immobilier et foncier. 
    Analyse ce communiqué de presse de {source_nom}.
    RECHERCHE EXCLUSIVEMENT : 
    - Lancement de consultations de promoteurs ou d'opérateurs.
    - Désignation de lauréats (architectes, promoteurs, investisseurs).
    - Annonces de nouveaux programmes de logements, bureaux ou équipements.
    - Cessions de charges foncières ou signatures de promesses de vente.

    SI TU TROUVES : Fais un résumé très court (3 phrases max) avec : 
    1. Le lieu précis du projet.
    2. La nature de l'opportunité (ex: Concours lancé, Lauréat désigné).
    3. Les surfaces ou nombres de logements si mentionnés.

    SI TU NE TROUVES RIEN DE PERTINENT : Réponds exactement par le mot 'NÉANT'.
    
    TEXTE DU DOCUMENT :
    {texte_pdf[:8000]}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except:
        return "NÉANT"

def envoyer_email(rapport_final):
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent Veille Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "🎯 Veille Immo : Nouvelles Opportunités Paris-Saclay",
        "htmlContent": f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333;">
                <div style="background-color: #f4f7f6; padding: 20px; border-radius: 10px;">
                    <h2 style="color: #2c3e50; border-bottom: 2px solid #3498db; padding-bottom: 10px;">
                        Rapport de détection IA
                    </h2>
                    <div style="margin-top: 20px;">
                        {rapport_final}
                    </div>
                    <p style="font-size: 11px; color: #7f8c8d; margin-top: 30px;">
                        Analyse automatisée générée par Gemini 1.5 Flash.
                    </p>
                </div>
            </body>
        </html>
        """
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_KEY
    }
    requests.post(url, json=payload, headers=headers)

def main():
    print("--- Début de la veille stratégique ---")
    compte_rendu_final = ""
    projets_trouves = 0

    for site in SITES:
        print(f"Scan de : {site['nom']}...")
        try:
            res = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # On cherche les liens vers les pages de communiqués individuels
            links = soup.select('a.post-link') or soup.find_all('a', href=True)
            
            for link in links:
                href = link.get('href', '')
                if '/les-communiques-de-presse/' in href and href != site['url']:
                    full_url = urljoin(site['url'], href)
                    
                    # On entre dans la page pour trouver le PDF
                    try:
                        sub_res = requests.get(full_url, timeout=10)
                        sub_soup = BeautifulSoup(sub_res.text, 'html.parser')
                        pdf_link = sub_soup.find('a', href=lambda x: x and x.endswith('.pdf'))
                        
                        if pdf_link:
                            pdf_url = urljoin(full_url, pdf_link['href'])
                            print(f"🔍 Analyse IA du document : {pdf_url}")
                            
                            texte = extraire_texte_pdf(pdf_url)
                            if texte:
                                analyse = analyser_signal_faible(texte, site['nom'])
                                if "NÉANT" not in analyse.upper():
                                    projets_trouves += 1
                                    compte_rendu_final += f"""
                                    <div style="margin-bottom: 25px; padding: 15px; background: white; border-radius: 5px;">
                                        <strong style="color: #e67e22;">📍 OPPORTUNITÉ DÉTECTÉE</strong><br>
                                        {analyse}<br>
                                        <a href="{pdf_url}" style="color: #3498db; text-decoration: none; font-size: 13px;">Lien vers le communiqué source →</a>
                                    </div>
                                    """
                                    if projets_trouves >= 3: break # On limite à 3 pour éviter les mails trop longs
                    except:
                        continue
                        
        except Exception as e:
            print(f"Erreur sur le site {site['nom']}: {e}")

    if projets_trouves > 0:
        envoyer_email(compte_rendu_final)
        print(f"✅ Terminé : {projets_trouves} opportunités envoyées.")
    else:
        print("ℹ️ Aucun nouveau signal détecté aujourd'hui.")

if __name__ == "__main__":
    main()
