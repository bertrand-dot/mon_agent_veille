import os
import requests

def test_envoi():
    api_key = os.environ.get("BREVO_API_KEY")
    print(f"Clé API détectée (longueur) : {len(api_key) if api_key else '0 (VIDE !)'}")
    
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Test IA", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "TEST TECHNIQUE BREVO",
        "htmlContent": "<html><body><h1>Le pont fonctionne !</h1></body></html>"
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key
    }
    
    res = requests.post(url, json=payload, headers=headers)
    print(f"Code retour Brevo : {res.status_code}")
    print(f"Réponse Brevo : {res.text}")

if __name__ == "__main__":
    test_envoi()
