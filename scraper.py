import os
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai

# 1. Configuration des API
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. Liste des sites à surveiller
SITES = [
    {"nom": "Grand Paris Aménagement", "url": "https://www.grandparisamenagement.fr/publications"},
    # Vous pourrez ajouter d'autres sites ici sur le même modèle
]

def extraire_texte_pdf(pdf_url):
    """Télécharge le PDF et extrait le texte des 5 premières pages."""
    try:
        response = requests.get(pdf_url, timeout=15)
        with fitz.open(stream=response.content, filetype="pdf") as doc:
            texte = ""
            for page in doc[:5]:
                texte += page.get_text()
            return texte
    except Exception as e:
        print(f"Erreur lecture PDF {pdf_url}: {e}")
        return None

def analyser_signal_faible(texte_pdf, source_nom):
    """Analyse le texte avec Gemini pour détecter des opportunités immo/foncier."""
    prompt = f"""
    Tu es un expert en développement immobilier. Analyse ce document de {source_nom}.
    RECHERCHE : Lancement de concours d'architecture, désignation de promoteurs, études de faisabilité urbaine, ou avis de préemption.
    
    SI TU TROUVES : Fais un résumé très court (3 phrases max) avec le lieu, le type de projet et l'échéance.
    SI TU NE TROUVES RIEN : Réponds exactement par le mot 'NÉANT'.
    
    TEXTE : {texte_pdf[:8000]}
    """
    try:
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        print(f"Erreur IA : {e}")
        return "NÉANT"

def envoyer_email(rapport_final):
    """Envoie le rapport via l'API Brevo."""
    api_key = os.environ.get("BREVO_API_KEY")
    if not api_key:
        print("Erreur : Clé API Brevo manquante dans les Secrets GitHub.")
        return

    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "Rapport Quotidien : Veille Signaux Faibles EPA/EPF",
        "htmlContent": f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <h2 style="color: #2c3e50;">Résultats de la veille automatique</h2>
                <div style="padding: 15px; border: 1px solid #ecf0f1; border-radius: 5px;">
                    {rapport_final}
                </div>
                <p style="font-size: 12px; color: #7f8c8d; margin-top: 20px;">
                    Cet e-mail a été généré automatiquement par votre agent IA GitHub Actions.
                </p>
            </body>
        </html>
        """
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key
    }
    res = requests.post(url, json=payload, headers=headers)
    if res.status_code == 201:
        print("E-mail envoyé avec succès.")
    else:
        print(f"Erreur envoi mail : {res.text}")

def main():
    compte_rendu_global = ""
    du_nouveau = False

    for site in SITES:
        print(f"--- Scan de {site['nom']} ---")
        try:
            res = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # On cherche les liens vers des fichiers PDF
            for link in soup.find_all('a', href=True):
                if '.pdf' in link['href']:
                    pdf_url = link['href']
                    # Reconstitution de l'URL si elle est relative
                    if not pdf_url.startswith('http'):
                        domain = site['url'].split('/')[2]
                        pdf_url = f"https://{domain}{pdf_url}"
                    
                    print(f"Analyse : {pdf_url}")
                    texte_brut = extraire_texte_pdf(pdf_url)
                    
                    if texte_brut:
                        resultat = analyser_signal_faible(texte_brut, site['nom'])
                        if "NÉANT" not in resultat.upper():
                            compte_rendu_global += f"<p><b>📍 {site['nom']}</b><br>{resultat}</p><hr>"
                            du_nouveau = True
        except Exception as e:
            print(f"Erreur sur le site {site['nom']}: {e}")

    if not du_nouveau:
        compte_rendu_global = "<p>Aucun nouveau signal faible détecté aujourd'hui sur les sites surveillés.</p>"
    
    envoyer_email(compte_rendu_global)

if __name__ == "__main__":
    main()
