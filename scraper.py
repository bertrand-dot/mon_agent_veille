import os
import requests
import csv
import re
import json
from bs4 import BeautifulSoup
import fitz  # PyMuPDF
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta

# --- 1. CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
HISTORY_FILE = "download_history.json"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. GESTION MÉMOIRE INTELLIGENTE (JSON COMPLET) ---

def charger_historique():
    """Charge l'historique et nettoie les entrées > 3 mois."""
    data = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f:
                content = json.load(f)
                # Compatibilité : si l'ancien fichier était une liste, on le convertit
                if isinstance(content, list):
                    return {} 
                data = content
        except:
            return {}

    # Nettoyage des vieux dossiers (> 90 jours)
    limit_date = datetime.now() - timedelta(days=90)
    clean_data = {}
    for url, info in data.items():
        try:
            date_saved = datetime.strptime(info['date_detection'], '%Y-%m-%d')
            if date_saved > limit_date:
                clean_data[url] = info
        except:
            continue # Si erreur de format date, on supprime
            
    return clean_data

def sauvegarder_historique(historique):
    try:
        with open(HISTORY_FILE, 'w') as f:
            json.dump(historique, f, indent=2)
    except Exception as e:
        print(f"Erreur sauvegarde : {e}")

# --- 3. FONCTIONS D'EXTRACTION ---

def est_grand_organisme(nom):
    mots_cles = ['EPA', 'Grand Paris', 'Métropole', 'Eurométropole', 'Part-Dieu', 'La Défense', 'Euratlantique']
    return any(m.lower() in nom.lower() for m in mots_cles)

def nettoyer_texte(texte):
    return re.sub(r'\s+', ' ', texte).strip()

def extraire_contenu_url(target_url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(target_url, timeout=20, headers=headers)
        response.raise_for_status()
        
        content_type = response.headers.get('Content-Type', '').lower()
        texte_final = ""
        
        # PDF
        if 'pdf' in content_type or target_url.lower().endswith('.pdf'):
            with fitz.open(stream=response.content, filetype="pdf") as doc:
                texte_final = "".join([page.get_text() for page in doc[:6]])
        # WEB
        else:
            soup = BeautifulSoup(response.text, 'html.parser')
            for tag in soup(['script', 'style', 'nav', 'footer', 'header', 'aside']):
                tag.decompose()
            contenu = soup.find('main') or soup.find('article') or soup.body
            if contenu:
                texte_final = contenu.get_text(separator=' ')
                
        return nettoyer_texte(texte_final)
    except:
        return None

def analyser_ia_urban_agency(texte, source, categorie):
    prompt = f"""
    Directeur Développement Urban Agency. Analyse ce texte ({source} - {categorie}).
    
    ADN :
    1. RESTRUCTURATION D'ACTIF (Bureaux->Logements, Réhab lourde) = PRIORITÉ ABSOLUE.
    2. FRICHES / WATERFRONT / ZAC.
    3. ÉQUIPEMENTS PUBLIC (Écoles/Sport) : UNIQUEMENT SI > 10M€.
    
    FORMAT JSON STRICT ATTENDU (sans markdown) :
    {{
        "titre": "Titre court du projet",
        "theme": "Restructuration / Friche / Waterfront / Éducation / Logement",
        "resume": "Résumé en 1 phrase avec budget si dispo",
        "score": 1, 2 ou 3
    }}
    
    Si hors sujet, renvoie juste : {{"score": 0}}
    
    TEXTE : {texte[:10000]}
    """
    try:
        res = model.generate_content(prompt)
        # Nettoyage pour récupérer le JSON pur
        clean_json = res.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_json)
    except:
        return {"score": 0}

def generer_bloc_html(item, is_new):
    """Génère le HTML d'une carte, soit en couleur (New), soit en gris (Old)."""
    
    # Styles
    if is_new:
        border_color = "#e74c3c" if item['score'] == 3 else "#3498db"
        bg_color = "white"
        text_color = "#2c3e50"
        opacity = "1"
        badge = "<span style='color:red; font-weight:bold; font-size:11px;'>🔥 NOUVEAU</span>"
        date_display = "Aujourd'hui"
    else:
        border_color = "#bdc3c7"
        bg_color = "#f9f9f9"
        text_color = "#7f8c8d" # Gris
        opacity = "0.8"
        badge = f"<span style='color:#95a5a6; font-size:10px;'>Détecté le {item['date_detection']}</span>"
        date_display = item['date_detection']

    # Icones
    theme = item.get('theme', '').upper()
    if "RESTRUCTURATION" in theme: icon = "🏗️"
    elif "FRICHE" in theme: icon = "🏭"
    elif "WATER" in theme: icon = "💧"
    elif "ÉDUCATION" in theme: icon = "🎓"
    else: icon = "📌"

    return f"""
    <div style="opacity:{opacity}; border-left: 5px solid {border_color}; background: {bg_color}; padding: 15px; margin-bottom: 15px; border-radius: 4px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);">
        <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
            <strong style="color:{text_color}; font-size:14px;">{icon} {item['nom_source']}</strong>
            <div>{badge}</div>
        </div>
        <div style="font-weight:bold; color:{text_color}; font-size:15px; margin-bottom:5px;">
            {item['titre']}
        </div>
        <div style="font-size:13px; color:{text_color}; line-height:1.4;">
            {item['resume']}
        </div>
        <div style="margin-top:10px; display:flex; justify-content:space-between; align-items:center;">
            <span style="font-size:10px; color:#95a5a6; background:#eee; padding:2px 6px; border-radius:4px;">{item['theme']}</span>
            <a href="{item['url']}" style="color:{border_color}; font-weight:bold; text-decoration:none; font-size:12px;">Voir Source →</a>
        </div>
    </div>
    """

def envoyer_mail(nouveaux, anciens):
    url = "https://api.brevo.com/v3/smtp/email"
    date_jour = datetime.now().strftime('%d/%m/%Y')
    
    html_new = "".join([generer_bloc_html(x, True) for x in nouveaux])
    html_old = "".join([generer_bloc_html(x, False) for x in anciens])
    
    if not html_old: html_old = "<p style='color:#bdc3c7; font-style:italic;'>Aucun historique récent (< 3 mois).</p>"
    
    payload = {
        "sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"},
        "to": [{"email": "bertrand@urban-agency.com"}],
        "subject": f"⚡ Veille Immo : {len(nouveaux)} Nouveautés ({date_jour})",
        "htmlContent": f"""
        <html>
            <body style="font-family: 'Helvetica', Arial, sans-serif; background-color: #f4f4f4; padding: 20px;">
                <div style="max-width: 650px; margin: auto; background: white; border-radius: 8px; overflow: hidden;">
                    
                    <div style="background-color: #2c3e50; padding: 20px; text-align: center;">
                        <h2 style="color: white; margin:0;">Urban Agency Dashboard</h2>
                        <p style="color: #bdc3c7; font-size: 12px;">Période : 3 derniers mois</p>
                    </div>

                    <div style="padding: 20px; background-color: #fff;">
                        <h3 style="color: #e74c3c; border-bottom: 2px solid #e74c3c; padding-bottom:5px; margin-top:0;">
                            🔥 NOUVEAUTÉS DU JOUR ({len(nouveaux)})
                        </h3>
                        {html_new if html_new else "<p>Rien de frais ce matin.</p>"}
                    </div>

                    <div style="padding: 20px; background-color: #ecf0f1; border-top:1px solid #ddd;">
                        <h3 style="color: #7f8c8d; border-bottom: 2px solid #bdc3c7; padding-bottom:5px; margin-top:0;">
                            🗄️ EN PORTEFEUILLE (DÉJÀ VU)
                        </h3>
                        {html_old}
                    </div>

                </div>
            </body>
        </html>
        """
    }
    headers = {"accept": "application/json", "content-type": "application/json", "api-key": BREVO_KEY}
    requests.post(url, json=payload, headers=headers)

# --- 4. MAIN ---

def main():
    if not os.path.exists('cibles.csv'): return

    # 1. Chargement Mémoire
    historique = charger_historique()
    print(f"🧠 Mémoire chargée : {len(historique)} dossiers actifs.")

    leads_nouveaux = []
    
    # Lecture CSV
    lignes = []
    for enc in ['utf-8', 'latin-1', 'cp1252']:
        try:
            with open('cibles.csv', mode='r', encoding=enc) as f: lines=f.readlines(); lignes=lines; break
        except: continue
    
    sep = ';' if lignes and ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=sep)
    
    exclusion = ['contact', 'mentions', 'legales', 'connexion', 'login', 'cookies']

    print("--- Scan en cours ---")

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme") or ligne.get("Nom de l'organisme")
        if not nom: continue

        limite = 10 if est_grand_organisme(nom) else 5
        cpt = 0
        
        urls = {
            "Actu": ligne.get("URL Actualités / Projets"),
            "Presse": ligne.get("URL Communiqués de Presse"),
            "RAA": ligne.get("URL Délibérations / Actes (RAA)")
        }

        print(f"👉 {nom}")

        for cat, url_source in urls.items():
            if not url_source or "http" not in str(url_source): continue
            
            try:
                res = requests.get(url_source.strip(), headers={'User-Agent': 'Mozilla/5.0'}, timeout=15)
                soup = BeautifulSoup(res.text, 'html.parser')
                
                for link in soup.find_all('a', href=True):
                    if cpt >= limite: break
                    
                    href = link['href']
                    full_url = urljoin(url_source.strip(), href)

                    # Filtres techniques
                    if href.startswith('#') or href.startswith('mailto:'): continue
                    if urlparse(full_url).netloc != urlparse(url_source).netloc and 'epa' not in full_url: continue
                    if any(excl in full_url.lower() for excl in exclusion): continue
                    
                    # SI DÉJÀ DANS L'HISTORIQUE : On ne fait rien (on l'a déjà en mémoire pour l'email final)
                    if full_url in historique:
                        continue
                    
                    # NOUVEAU LIEN -> ANALYSE
                    texte = extraire_contenu_url(full_url)
                    if texte and len(texte) > 300:
                        data_ia = analyser_ia_urban_agency(texte, nom, cat)
                        
                        if data_ia.get('score', 0) >= 2: # On ne garde que ce qui est pertinent (Score 2 ou 3)
                            
                            info_lead = {
                                "url": full_url,
                                "date_detection": datetime.now().strftime('%Y-%m-%d'),
                                "nom_source": nom,
                                "titre": data_ia.get('titre', 'Projet détecté'),
                                "theme": data_ia.get('theme', 'Divers'),
                                "resume": data_ia.get('resume', ''),
                                "score": data_ia.get('score', 2)
                            }
                            
                            # On ajoute aux nouveaux ET à l'historique
                            leads_nouveaux.append(info_lead)
                            historique[full_url] = info_lead
                            cpt += 1
                            print(f"   🔥 NOUVEAU ({info_lead['score']}/3) : {info_lead['titre']}")

            except Exception as e:
                pass

    # 2. Préparation de l'email
    # On trie l'historique pour récupérer les "Anciens" (ceux qui ne sont pas dans leads_nouveaux)
    leads_anciens = []
    urls_nouveaux = [x['url'] for x in leads_nouveaux]
    
    for url, data in historique.items():
        if url not in urls_nouveaux:
            leads_anciens.append(data)
            
    # Tri par date décroissante (du plus récent au plus vieux)
    leads_anciens.sort(key=lambda x: x['date_detection'], reverse=True)

    # 3. Sauvegarde et Envoi
    sauvegarder_historique(historique)
    
    if leads_nouveaux or leads_anciens:
        envoyer_mail(leads_nouveaux, leads_anciens)
        print("✅ Rapport envoyé (Nouveaux + Historique).")
    else:
        print("Rien à signaler.")

if __name__ == "__main__":
    main()
