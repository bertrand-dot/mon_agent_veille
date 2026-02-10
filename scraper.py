import os
import requests
import csv
import json
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
import time

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_CX = os.environ.get("GOOGLE_SEARCH_CX")
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

# Initialize Gemini client with new package
client = genai.Client(api_key=GEMINI_KEY)

def load_history():
    """Charge l'historique des opportunités déjà traitées"""
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {"processed_urls": [], "last_run": None}

def save_history(history):
    """Sauvegarde l'historique"""
    history["last_run"] = datetime.now().isoformat()
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)

def chercher_signaux_google(nom_organisme):
    """Effectue une recherche ciblée sur les signaux faibles"""
    if not GOOGLE_KEY or not GOOGLE_CX: 
        return []
    
    query = f'site:*.fr "{nom_organisme}" (délibération OR "friche industrielle" OR "appel à projets" OR "concours d\'architecture" OR "reconversion")'
    url = "https://www.googleapis.com/customsearch/v1"
    params = {
        'key': GOOGLE_KEY, 
        'cx': GOOGLE_CX, 
        'q': query, 
        'dateRestrict': 'm2', 
        'num': 5
    }
    
    try:
        time.sleep(1)  # Rate limiting
        res = requests.get(url, params=params, timeout=10).json()
        return [
            {
                'titre': i['title'], 
                'url': i['link'], 
                'snippet': i['snippet']
            } 
            for i in res.get('items', [])
        ]
    except Exception as e:
        print(f"⚠️  Erreur recherche Google: {e}")
        return []

def analyser_ia_strategique(texte, source):
    """Analyse IA pour scorer les opportunités"""
    prompt = f"""RÔLE : Directeur du Développement Urban Agency.
    ÉVALUE le potentiel de ce texte pour gagner un concours ou une mission de reconversion urbaine.
    
    POINTS CLÉS :
    - Score 3 : Projet concret mentionné, friche identifiée, concours imminent, délibération de budget.
    - Score 2 : Étude de faisabilité lancée, signal faible de mutation urbaine.
    - Score 1 : Veille institutionnelle simple.
    
    RETOURNE JSON : {{"titre": "...", "resume": "Explique l'opportunité commerciale", "score": 0-3}}
    SOURCE : {source}
    TEXTE : {texte[:12000]}"""
    
    try:
        time.sleep(1)  # Rate limiting Gemini
        response = client.models.generate_content(
            model='gemini-2.0-flash-exp',
            contents=prompt
        )
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"⚠️  Erreur analyse IA: {e}")
        return {"titre": "Erreur analyse", "resume": "", "score": 0}

def fetch_page_content(url, session):
    """Récupère le contenu d'une page web"""
    try:
        response = session.get(url, timeout=10)
        soup = BeautifulSoup(response.text, 'html.parser')
        # Extrait le texte principal
        for script in soup(["script", "style"]):
            script.decompose()
        return soup.get_text()[:12000]
    except Exception as e:
        print(f"⚠️  Erreur récupération {url}: {e}")
        return ""

def envoyer_mail_strategique(opportunites):
    """Envoie l'email récapitulatif"""
    if not opportunites or not BREVO_KEY: 
        return
    
    corps = ""
    for op in opportunites:
        color = "#e74c3c" if op['score'] == 3 else "#3498db"
        corps += f"""<div style="border-left:5px solid {color}; padding:15px; margin-bottom:20px; background:#fff;">
            <b style="font-size:16px; color:#2c3e50;">{op['titre']}</b><br>
            <i style="color:#7f8c8d;">Source : {op['nom_source']}</i>
            <p style="font-size:14px; color:#333;">{op['resume']}</p>
            <a href="{op['url']}" style="color:{color}; font-weight:bold;">VOIR L'OPPORTUNITÉ →</a>
        </div>"""

    html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:Arial;">
        <div style="max-width:600px; margin:auto; background:white; padding:20px; border-radius:10px;">
            <img src="{LOGO_URL}" height="40"><br>
            <h2 style="color:#2c3e50; border-bottom:2px solid #eee; padding-bottom:10px;">
                RADAR OPPORTUNITÉS HAUTE-PRÉCISION
            </h2>
            {corps}
        </div>
    </body></html>"""

    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json={
                "sender": {"name": "Radar Urban Agency", "email": "bertrand@urban-agency.com"},
                "to": [{"email": "bertrand@urban-agency.com"}],
                "subject": f"🎯 {len(opportunites)} Signaux de Marché Détectés",
                "htmlContent": html
            },
            headers={"api-key": BREVO_KEY},
            timeout=10
        )
        print(f"✅ Email envoyé (status: {response.status_code})")
    except Exception as e:
        print(f"⚠️  Erreur envoi email: {e}")

def main():
    if not os.path.exists('cibles.csv'):
        print("❌ Fichier cibles.csv introuvable")
        return
    
    # Charger l'historique
    history = load_history()
    print(f"📁 Historique chargé: {len(history['processed_urls'])} URLs déjà traitées")
    
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (compatible; UrbanAgencyBot/1.0)'})
    resultats = []

    with open('cibles.csv', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            nom = row.get("Nom de l'Organisme")
            if not nom: 
                continue
            
            print(f"\n🔍 Intelligence sur {nom}...")
            
            # Méthode 1 : Recherche Google (Signaux Faibles)
            signaux = chercher_signaux_google(nom)
            print(f"   → {len(signaux)} signaux Google trouvés")
            
            for s in signaux:
                # Éviter les doublons
                if s['url'] in history['processed_urls']:
                    print(f"   ⏭️  Déjà traité: {s['url'][:50]}...")
                    continue
                
                res = analyser_ia_strategique(s['snippet'] + " " + s['titre'], nom)
                if res['score'] >= 2:
                    resultats.append({
                        "url": s['url'],
                        "nom_source": nom,
                        **res
                    })
                    history['processed_urls'].append(s['url'])
                    print(f"   ✨ Opportunité détectée (score {res['score']}): {res['titre'][:50]}...")
            
            # Méthode 2 : Scan Direct (si URL fournie)
            url_direct = row.get("URL Actualités / Projets")
            if url_direct and url_direct not in history['processed_urls']:
                print(f"   → Scan direct de {url_direct[:50]}...")
                contenu = fetch_page_content(url_direct, session)
                if contenu:
                    res_direct = analyser_ia_strategique(contenu, nom)
                    if res_direct['score'] >= 2:
                        resultats.append({
                            "url": url_direct,
                            "nom_source": nom,
                            **res_direct
                        })
                        history['processed_urls'].append(url_direct)
                        print(f"   ✨ Opportunité détectée (score {res_direct['score']})")

    # Sauvegarder l'historique
    save_history(history)
    print(f"\n💾 Historique sauvegardé: {len(history['processed_urls'])} URLs totales")
    
    # Envoyer le rapport
    if resultats:
        envoyer_mail_strategique(resultats)
        print(f"✅ {len(resultats)} opportunités envoyées par email")
    else:
        print("ℹ️  Aucune nouvelle opportunité détectée")

if __name__ == "__main__":
    main()
