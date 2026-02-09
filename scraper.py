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

def analyser_ia(texte, source, categorie):
    prompt = f"""
    Expert Immobilier : Analyse ce doc de {source} ({categorie}). 
    Cherche : concours archi, lauréat promoteur, nouveau projet urbain, vente foncière. 
    Si rien de stratégique : réponds 'NÉANT'. Sinon, résumé 3 lignes max. 
    Texte : {texte[:7000]}
    """
    try:
        res = model.generate_content(prompt)
        return res.text
    except:
        return "NÉANT"

def envoyer_mail(corps_html):
    url = "https://api.brevo.com/v3/smtp/email"
    payload = {
        "sender": {"name": "Veille Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": "🎯 Rapport de Veille Multi-Organismes (28 Sources)",
        "htmlContent": f"<html><body style='font-family:Arial;'>{corps_html}</body></html>"
    }
    headers = {"accept": "application/json", "content-type": "application/json", "api-key": BREVO_KEY}
    requests.post(url, json=payload, headers=headers)

def main():
    if not os.path.exists('cibles.csv'):
        print("❌ Fichier 'cibles.csv' introuvable.")
        return

    rapport_global = ""
    projets_trouves = 0

    # SOLUTION : On essaie UTF-8, et si ça échoue, on utilise Latin-1 (format Excel classique)
    try:
        f = open('cibles.csv', mode='r', encoding='utf-8')
        content = f.read(1024)
        f.seek(0)
    except UnicodeDecodeError:
        f = open('cibles.csv', mode='r', encoding='latin-1')
        content = f.read(1024)
        f.seek(0)

    # Détection du séparateur (virgule ou point-virgule)
    dialect = csv.Sniffer().sniff(content)
    lecteur = csv.DictReader(f, dialect=dialect)
    
    for ligne in lecteur:
        # On utilise .get() pour éviter les erreurs si une colonne manque
        nom = ligne.get("Nom de l'Organisme")
        urls = {
            "Actualités": ligne.get("URL Actualités / Projets"),
            "Presse": ligne.get("URL Communiqués de Presse"),
            "Délibérations": ligne.get("URL Délibérations / Actes (RAA)")
        }

        if not nom: continue
        print(f"--- Scan de : {nom} ---")
        
        for cat, url_cible in urls.items():
            if not url_cible or "http" not in url_cible:
                continue
            
            try:
                res = requests.get(url_cible, headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                count_pdf = 0
                for link in soup.find_all('a', href=True):
                    href = link['href']
                    if '.pdf' in href.lower():
                        pdf_url = urljoin(url_cible, href)
                        texte = extraire_texte_pdf(pdf_url)
                        if texte:
                            analyse = analyser_ia(texte, nom, cat)
                            if "NÉANT" not in analyse.upper():
                                projets_trouves += 1
                                rapport_global += f"<div style='margin-bottom:15px;'><b>📍 {nom}</b> ({cat})<br>{analyse}<br><a href='{pdf_url}'>Lien doc</a></div><hr>"
                                count_pdf += 1
                                if count_pdf >= 1: break 
            except Exception as e:
                print(f"Erreur sur {url_cible}: {e}")
    
    f.close()

    if projets_trouves > 0:
        envoyer_mail(rapport_global)
        print(f"✅ Terminé : {projets_trouves} opportunités trouvées.")
    else:
        print("Mise à jour : aucun nouveau signal détecté.")

if __name__ == "__main__":
    main()
