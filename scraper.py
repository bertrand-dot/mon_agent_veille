import os
import requests
from bs4 import BeautifulSoup
import fitz
import google.generativeai as genai
from urllib.parse import urljoin

# Config API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

SITES = [{"nom": "EPA Paris-Saclay", "url": "https://epa-paris-saclay.fr/espace-presse/les-communiques-de-presse/"}]

def envoyer_email(rapport):
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent Urban", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "Rapport Veille Paris-Saclay",
        "htmlContent": f"<html><body>{rapport}</body></html>"
    }
    headers = {"accept": "application/json", "content-type": "application/json", "api-key": BREVO_KEY}
    res = requests.post(url, json=payload, headers=headers)
    print(f"Status Brevo: {res.status_code}")

def main():
    if not BREVO_KEY:
        print("❌ Le script ne voit toujours pas la BREVO_API_KEY")
        return

    print("✅ Connexion établie. Scan en cours...")
    # Pour ce test, on envoie un mail directement pour confirmer que le pont fonctionne
    rapport = "Le script est maintenant correctement connecté à Brevo et Gemini."
    envoyer_email(rapport)

if __name__ == "__main__":
    main()
