import os
import requests

def test_final():
    api_key = os.environ.get("BREVO_API_KEY")
    
    # Debug pour voir si la clé est bien chargée
    if not api_key:
        print("❌ ERREUR : Le Secret GitHub 'BREVO_API_KEY' est introuvable ou vide.")
        return

    print(f"Clé détectée (début) : {api_key[:5]}...")

    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent Urban", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "TEST CONNEXION REUSSIE",
        "htmlContent": "<html><body><h1>Le pont est établi !</h1></body></html>"
    }
    headers = {
        "accept": "application/json",
        "content-type": "application/json",
        "api-key": api_key
    }
    
    res = requests.post(url, json=payload, headers=headers)
    
    if res.status_code == 201:
        print("✅ SUCCÈS : L'e-mail a été accepté par Brevo !")
    else:
        print(f"❌ ÉCHEC : Erreur {res.status_code}")
        print(f"Message de Brevo : {res.text}")

if __name__ == "__main__":
    test_final()
