import os
import requests
import csv
from bs4 import BeautifulSoup
import fitz
import google.generativeai as genai
from urllib.parse import urljoin

# 1. Configuration des API
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def extraire_texte_pdf(pdf_url):
    try:
        response = requests.get(pdf_url, timeout=15)
        with fitz.open(stream=response.content, filetype="pdf") as doc:
            texte = "".join([page.get_text() for page in doc[:3]])
            return texte
    except:
        return None

def analyser_ia(texte, source, type_url):
    prompt = f"""
    Tu es un expert en développement immobilier. Analyse ce document provenant de {source} (section {type_url}).
    RECHERCHE : Lancement de concours, désignation de lauréat, avis de préemption, ou vente foncière.
    
    SI TU TROUVES : Fais un résumé de 3 lignes max avec le lieu, le projet et l'échéance.
    SI RIEN : Réponds 'NÉANT'.
    
    TEXTE : {texte[:7000]}
    """
    try:
        res = model.generate_content(prompt)
        return res.text
    except:
        return "NÉANT"

def envoyer_mail(corps_html):
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Agent Veille Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "🎯 Rapport de Veille Multi-Sources (EPA/EPF/Collectivités)",
        "htmlContent": f"<html><body style='font-family:Arial;'>{corps_html}</body></html>"
    }
    headers = {"accept": "application/json", "content-type": "application/json", "api-key": BREVO_KEY}
    requests.post(url, json=payload, headers=headers)

def main():
    rapport_final = ""
    trouve_global = False
    
    if not os.path.exists('cibles.csv'):
        print("❌ Erreur : 'cibles.csv' est introuvable sur GitHub.")
        return

    # Ouverture du CSV (Adapté à votre fichier avec virgule)
    with open('cibles.csv', mode='r', encoding='utf-8') as f:
        lecteur = csv.DictReader(f)
        
        for ligne in lecteur:
            nom_organisme = ligne.get("Nom de l'Organisme")
            # On liste toutes les colonnes d'URL à scanner
            colonnes_url = {
                "Actualités": ligne.get("URL Actualités / Projets"),
                "Presse": ligne.get("URL Communiqués de Presse"),
                "Délibérations": ligne.get("URL Délibérations / Actes (RAA)")
            }

            print(f"--- Scan de {nom_organisme} ---")
            
            for type_url, url_cible in colonnes_url.items():
                if not url_cible or "http" not in url_cible:
                    continue

                try:
                    print(f"  Vérification section {type_url}...")
                    res = requests.get(url_cible, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                    soup = BeautifulSoup(res.text, 'html.parser')
                    
                    # On cherche les PDF sur la page
                    pdf_scannes = 0
                    for link in soup.find_all('a', href=True):
                        href = link['href']
                        if '.pdf' in href.lower():
                            pdf_url = urljoin(url_cible, href)
                            texte = extraire_texte_pdf(pdf_url)
                            
                            if texte:
                                analyse = analyser_ia(texte, nom_organisme, type_url)
                                if "NÉANT" not in analyse.upper():
                                    trouve_global = True
                                    rapport_final += f"""
                                    <div style='border-left:4px solid #e67e22; padding:10px; margin-bottom:15px; background:#fdf2e9;'>
                                        <b style='color:#d35400;'>📍 {nom_organisme}</b> ({type_url})<br>
                                        {analyse}<br>
                                        <a href='{pdf_url}' style='font-size:12px;'>Ouvrir le document source</a>
                                    </div>
                                    """
                                    pdf_scannes += 1
                                    if pdf_scannes >= 2: break # Max 2 docs par section pour ne pas saturer l'e-mail
                except Exception as e:
                    print(f"  Erreur sur {url_cible}: {e}")

    if trouve_global:
        envoyer_mail(rapport_final)
        print("✅ Rapport complet envoyé !")
    else:
        print("Mise à jour : aucun nouveau signal sur les 28 organismes.")

if __name__ == "__main__":
    main()
