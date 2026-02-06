import os
import requests
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai

# 1. Configuration des API
# Récupération des clés depuis les secrets GitHub
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# 2. Liste des sites à surveiller
SITES = [
    {"nom": "Grand Paris Aménagement", "url": "https://www.grandparisamenagement.fr/publications"},
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
        print(f"Erreur IA Gemini : {e}")
        return "NÉANT"

def envoyer_email(rapport_final):
    """Envoie le rapport via l'API Brevo."""
    if not BREVO_KEY:
        print("❌ ERREUR : La clé BREVO_API_KEY est manquante dans les secrets GitHub.")
        return

    url = "https://api.brevo.com/v3/smtp/email"
    
    # IMPORTANT : L'email 'sender' doit être validé dans votre compte Brevo
    payload = {
        "sender": {"name": "Agent IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "Rapport Quotidien : Veille Signaux Faibles EPA/EPF",
        "htmlContent": f"""
        <html>
            <body style="font-family: Arial, sans-serif; line-height: 1.6;">
                <h2 style="color: #2c3e50;">Résultats de la veille automatique</h2>
                <div style="padding: 15px; border-left: 4px solid #3498db; background-color: #f9f9f9;">
                    {rapport_final}
                </div>
                <p style="font-size: 11px; color: #95a5a6; margin-top: 20px;">
                    Ceci est un message automatique généré par votre agent de veille Urban Agency.
                </p>
            </body>
        </html>
        """
    }
    
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": BREVO_KEY
    }
    
    print(f"Tentative d'envoi de l'e-mail à bertrand@urban-agency.com...")
    res = requests.post(url, json=payload, headers=headers)
    
    if res.status_code == 201 or res.status_code == 200:
        print("✅ E-mail envoyé avec succès (Accepté par Brevo).")
    else:
        print(f"❌ Erreur lors de l'envoi : {res.status_code} - {res.text}")

def main():
    compte_rendu_global = ""
    du_nouveau = False

    for site in SITES:
        print(f"--- Démarrage du scan : {site['nom']} ---")
        try:
            res = requests.get(site['url'], headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # Recherche des liens PDF
            liens_trouves = 0
            for link in soup.find_all('a', href=True):
                if '.pdf' in link['href'].lower():
                    liens_trouves += 1
                    pdf_url = link['href']
                    if not pdf_url.startswith('http'):
                        domain = site['url'].split('/')[2]
                        pdf_url = f"https://{domain}{pdf_url}"
                    
                    print(f"📄 Analyse du document {liens_trouves} : {pdf_url}")
                    texte_brut = extraire_texte_pdf(pdf_url)
                    
                    if texte_brut:
                        resultat = analyser_signal_faible(texte_brut, site['nom'])
                        if "NÉANT" not in resultat.upper():
                            print(f"🎯 SIGNAL DÉTECTÉ dans {pdf_url}")
                            compte_rendu_global += f"<p style='margin-bottom:10px;'><b>📍 {site['nom']}</b><br>{resultat}<br><small><a href='{pdf_url}'>Lien vers le document</a></small></p><hr>"
                            du_nouveau = True
            
            if liens_trouves == 0:
                print(f"⚠️ Aucun PDF trouvé sur {site['url']}. Vérifiez si la structure du site a changé.")

        except Exception as e:
            print(f"Erreur critique sur le site {site['nom']}: {e}")

    # Préparation du message final
    if not du_nouveau:
        compte_rendu_global = "<p>Aucun nouveau signal faible détecté aujourd'hui sur les sites surveillés.</p>"
    
    # Envoi du mail
    envoyer_email(compte_rendu_global)

if __name__ == "__main__":
    main()
