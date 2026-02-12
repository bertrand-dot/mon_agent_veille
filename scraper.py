import os
import requests
import json
import logging
import time
import csv
import fitz  # PyMuPDF
from bs4 import BeautifulSoup
from google import genai
from datetime import datetime
from collections import defaultdict

# --- 1. CONFIGURATION ---
GEMINI_KEY = (os.environ.get("GEMINI_API_KEY") or "").strip()
BREVO_KEY = (os.environ.get("BREVO_API_KEY") or "").strip()
SERPAPI_KEY = (os.environ.get("SERPAPI_KEY") or "").strip()

LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"
ARCHIVE_FILE = "leads_archive.json"

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

client = None
if GEMINI_KEY:
    try:
        client = genai.Client(api_key=GEMINI_KEY)
        logging.info("✅ Moteur Gemini 2.5 Pro activé.")
    except Exception as e:
        logging.error(f"❌ Erreur Gemini : {e}")

# --- 2. GESTION GÉOGRAPHIQUE & ROTATION ---

def obtenir_secteur_du_jour():
    config_jours = {
        0: {"file": "cibles_idf.csv", "name": "IDF", "emoji": "🗼"},
        1: {"file": "cibles_nord_est.csv", "name": "NORD-EST", "emoji": "🏭"},
        2: {"file": "cibles_nord_ouest.csv", "name": "NORD-OUEST", "emoji": "🌊"}, # Front Atlantique
        3: {"file": "cibles_sud_ouest.csv", "name": "SUD-OUEST", "emoji": "🍷"},
        4: {"file": "cibles_sud_est.csv", "name": "SUD-EST", "emoji": "☀️"}
    }
    return config_jours.get(datetime.now().weekday(), config_jours[3])

def charger_cibles(nom_fichier):
    cibles = []
    if os.path.exists(nom_fichier):
        try:
            with open(nom_fichier, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    nom = row.get('Nom de l\'Organisme') or row.get('nom')
                    if nom: cibles.append(nom.strip())
        except Exception as e:
            logging.error(f"❌ Erreur CSV : {e}")
    return cibles

# --- 3. ANALYSE IA : LE CERVEAU UA (STRUCTURE CONSERVÉE ET DURCIE) ---

def analyser_opportunite(item, texte):
    if not client: return None
    time.sleep(1)
    
    date_du_jour = datetime.now().strftime("%d/%m/%Y")
    
    prompt = f"""RÔLE : Associé Senior URBAN AGENCY (Copenhague/Dublin).
    MISSION : Qualifier ce signal français au regard de notre ADN.
    DATE DU JOUR : {date_du_jour}

    --- ADN VALORISÉ ---
    Iconique, Régénération friches, Densité qualitative, Construction Bois, Waterfront/Résilience.

    --- MATRICE DE CLASSEMENT ---
    1. SPRINT : AO/AMI officiel. Deadline < 30j. Budget > 10M€. Focus: Références.
    2. RADAR : Anticipation (Délibération, ZAC, PIN). Horizon 3-9 mois.
    3. EXPLORATION : Innovation (Bas-carbone, réemploi, biodiversité).
    4. RÉSEAU : Partenaire identifié mais architecte non nommé.

    --- RÈGLES D'EXCLUSION STRICTES (NE PAS RETENIR SI) ---
    1. MISSION TECHNIQUE : Rénovation énergétique seule (ITE, menuiseries, CVC), mise aux normes PMR/Incendie, infrastructures pures (pylônes, parking surface), diagnostics.
    2. BUDGET/SURFACE : < 10M€ HT ou < 2000m2 (logement/tertiaire) / < 1000m2 (équipement), sauf exception iconique.
    3. PETIT PROGRAMME : Micro-équipements (abribus, sanitaires), Tertiaire local (agences, cabinets médicaux), Logement < 15 lots.
    4. COMMERCIAL STANDARD : Hangars, box de stockage, supermarchés isolés.

    --- CRITÈRES DE SÉVÉRITÉ SUPPLÉMENTAIRES (RÈGLES D'OR) ---
    - ÉLIMINER si DATE DÉPASSÉE : Si la date limite de réponse est antérieure au {date_du_jour}. (Ex: Centre Jean-Rostand = REJET).
    - ÉLIMINER si ARCHITECTE DÉJÀ DÉSIGNÉ : Si un lauréat ou attributaire est nommé. (Ex: 13ème Folie Montpellier = REJET).
    - ÉLIMINER le BRUIT INDUSTRIEL : Pas d'actualités économiques pures sans projet urbain/architectural défini.
    - ÉLIMINER RÉSEAUX SOCIAUX BRUYANTS : Aucun lead issu d'Instagram ou Facebook. LinkedIn autorisé.
    - ANCIENNETÉ : Rejeter tout document ou article de plus de 12 mois.

    --- FORMAT DE SORTIE JSON ---
    IMPORTANT : L'analyse doit être riche et instructive pour nos partenaires. Pas d'émojis dans les champs 'analyse_ua' et 'action'.
    {{
      "projet": "Nom précis du projet",
      "autorite": "Donneur d'ordre",
      "categorie": "SPRINT, RADAR, EXPLORATION ou RÉSEAU",
      "score_interne": 0,
      "deadline": "Date précise (vérifier validité)",
      "matching_dna": "Lien ADN court",
      "analyse_ua": "Analyse détaillée de l'enjeu architectural et urbain (60-80 mots)",
      "action": "Action concrète et détaillée pour Bertrand (sans émoji)"
    }}
    DATA : {item.get('title')} | {texte[:9000]}"""
    
    try:
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        data = json.loads(response.text.replace('```json', '').replace('```', '').strip())
        
        # Filtre de sécurité URL supplémentaire
        source_url = item.get('link', '').lower()
        if any(x in source_url for x in ["instagram.com", "facebook.com"]): return None
            
        return data
    except: return None

# --- 4. RECHERCHE CIBLÉE (LINKEDIN + WEB) ---

def chercher_serpapi(cible):
    resultats = []
    # Mix de recherche Web et LinkedIn (limite 6 mois pour LinkedIn)
    queries = [
        f'"{cible}" (friche OR "régénération urbaine" OR délibération OR "avis de marché") -site:facebook.com -site:instagram.com',
        f'site:linkedin.com/posts/ "{cible}" (concours OR projet OR aménagement OR foncier)'
    ]
    for q in queries:
        params = {"engine": "google", "q": q, "api_key": SERPAPI_KEY, "num": 12, "gl": "fr", "hl": "fr", "tbs": "qdr:y" if "linkedin" not in q else "qdr:m6"}
        try:
            res = requests.get("https://serpapi.com/search", params=params, timeout=20).json().get("organic_results", [])
            resultats.extend(res)
        except: continue
    return resultats

# --- 5. SYNTHÈSES STRATÉGIQUES ---

def generer_synthese(leads, mode="executif"):
    if not leads: return "Veille territoriale : aucun dossier majeur qualifié (dates dépassées ou lauréats déjà nommés écartés)."
    
    consigne = (
        "Rédige une note tactique courte (3 puces max). Utilise des émojis. Analyse la température du marché. "
        "IMPORTANT : Ne commence JAMAIS par 'Voici la note tactique...' ou toute phrase d'introduction similaire."
    ) if mode == "executif" else (
        "Analyse prospective (3-4 lignes). Ton expert, instructif et partageable. Analyse les tendances lourdes. "
        "IMPORTANT : Ne commence JAMAIS par 'Voici l'analyse stratégique...'."
    )
    
    try:
        prompt = f"En tant qu'associé UA, {consigne}. Données : {json.dumps(leads)}"
        response = client.models.generate_content(model="gemini-2.5-pro", contents=prompt)
        return response.text.strip()
    except: return "Analyse indisponible."

# --- 6. INTERFACE ET ENVOI ---

def envoyer_rapport(top_leads, archive_leads, res_exec, res_strat, secteur):
    exec_html = res_exec.replace('\n', '<br>')
    strat_html = res_strat.replace('\n', '<br>')
    
    grouped = defaultdict(list)
    for r in top_leads: grouped[r.get('autorite', 'Autres')].append(r)
    
    content_grouped = ""
    font_h = "'Arial Black', sans-serif"; font_b = "Arial, sans-serif"
    
    for autorite, items in grouped.items():
        content_grouped += f"<div style='margin-top:20px; font-family:{font_h}; color:#999; font-size:11px; text-transform:uppercase; border-bottom:1px solid #eee;'>{autorite}</div>"
        for o in items:
            cat = o.get('categorie', 'RADAR')
            colors = {"SPRINT": "#e74c3c", "RADAR": "#e67e22", "EXPLORATION": "#3498db", "RÉSEAU": "#9b59b6"}
            bg_color = colors.get(cat, "#7f8c8d")
            
            content_grouped += f"""
            <div style="border:1px solid #eee; margin:12px 0; background:#fff; overflow:hidden; font-family:{font_b}; border-left:4px solid {bg_color};">
                <div style="background:#f8f9fa; padding:8px 15px; border-bottom:1px solid #eee;">
                    <table width="100%"><tr>
                        <td style="font-size:13px;"><b>{o.get('projet')}</b></td>
                        <td align="right"><span style="background:{bg_color}; color:#fff; padding:1px 5px; font-size:9px; border-radius:2px;">{cat}</span></td>
                    </tr></table>
                </div>
                <div style="padding:15px; font-size:12px; line-height:1.5;">
                    <table width="100%"><tr><td width="30%">📅 <b>DÉLAI :</b> {o.get('deadline')}</td><td width="70%">🧬 <b>ADN :</b> {o.get('matching_dna')}</td></tr></table>
                    <p style="margin:10px 0; color:#444;"><b>ANALYSE :</b> {o.get('analyse_ua')}</p>
                    <div style="margin-top:10px; border-top:1px dashed #eee; padding-top:10px; font-weight:bold; color:#166534;">🎯 ACTION : {o.get('action')}</div>
                    <div style="text-align:right; margin-top:5px;"><a href="{o.get('url')}" style="color:#3498db; font-size:10px; text-decoration:none;">Source Documentaire ↗</a></div>
                </div>
            </div>"""

    # Bloc Archive Gris
    archive_html = ""
    for a in archive_leads:
        archive_html += f"<div style='border-bottom:1px solid #ddd; padding:8px 0; font-size:11px; color:#555;'>• <b>{a['projet']}</b> : {a['analyse_ua'][:100]}... <a href='{a['url']}' style='color:#3498db; text-decoration:none;'>[Fiche ↗]</a></div>"

    semaine = datetime.now().isocalendar()[1]
    subject = f"{secteur['emoji']} UA Radar {secteur['name']} / Sem. {semaine}"

    full_html = f"""<html><body style="background:#f4f4f4; padding:20px; font-family:{font_b}; color:#333;">
        <div style="max-width:750px; margin:auto; background:#fff; padding:40px; border-radius:3px; border:1px solid #ddd;">
            <div style="text-align:center; margin-bottom:30px;"><img src="{LOGO_URL}" height="50"></div>
            
            <div style="background:#fff3cd; padding:25px; border-radius:2px; margin-bottom:35px; border-left:5px solid #f1c40f; font-size:13px;">
                <b style="font-family:{font_h}; font-size:12px; color:#856404; text-transform:uppercase;">🚀 Résumé Exécutif - {secteur['name']}</b><br><br>{exec_html}
            </div>

            {content_grouped}

            <div style="margin-top:40px; padding:25px; background:#e1f5fe; border-radius:2px; border-left:5px solid #0288d1; font-size:13px; color:#01579b;">
                <b style="font-family:{font_h}; font-size:12px; color:#0288d1; text-transform:uppercase;">🔬 Vision & Tendances Stratégiques</b><br><br>{strat_html}
            </div>

            <div style="margin-top:50px; padding:25px; background:#f9f9f9; border-radius:2px; border:1px solid #eee; color:#666;">
                <b style="text-transform:uppercase; font-size:10px; color:#999; font-family:{font_h};">📚 Archive : Rappel des 20 derniers leads qualifiés</b>
                <div style="margin-top:15px;">{archive_html}</div>
            </div>
        </div></body></html>"""

    requests.post("https://api.brevo.com/v3/smtp/email", 
        json={"sender": {"name": "Radar UA Elite", "email": "bertrand@urban-agency.com"}, 
              "to": [{"email": "bertrand@urban-agency.com"}], 
              "subject": subject, "htmlContent": full_html}, 
        headers={"api-key": BREVO_KEY})

# --- 7. EXTRACTION & MAIN ---

def extraire_contenu(url):
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        res = requests.get(url, timeout=12, headers=headers)
        if res.status_code != 200: return ""
        if 'application/pdf' in res.headers.get('Content-Type', '').lower() or url.lower().endswith('.pdf'):
            doc = fitz.open(stream=res.content, filetype="pdf")
            text = "".join([p.get_text() for p in doc[:10]])
            doc.close()
            return " ".join(text.split())[:15000]
        soup = BeautifulSoup(res.text, 'html.parser')
        for s in soup(['script', 'style', 'nav', 'footer', 'header']): s.decompose()
        return " ".join(soup.get_text(separator=' ').split())[:12000]
    except: return ""

def mettre_a_jour_archive(nouveaux_leads):
    archive = []
    if os.path.exists(ARCHIVE_FILE):
        try:
            with open(ARCHIVE_FILE, 'r') as f: archive = json.load(f)
        except: archive = []
    for l in nouveaux_leads:
        if not any(a['url'] == l['url'] for a in archive): archive.insert(0, l)
    with open(ARCHIVE_FILE, 'w') as f: json.dump(archive[:50], f, indent=2)
    return archive[:20]

def main():
    secteur = obtenir_secteur_du_jour()
    cibles = charger_cibles(secteur['file'])
    if not cibles: return
    
    hist = {}
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: hist = json.load(f)
        except: hist = {}
        
    leads_du_jour = []
    for cible in cibles:
        logging.info(f"🔎 Scan : {cible}")
        for i in chercher_serpapi(cible):
            url = i.get('link')
            if not url or url in hist: continue
            texte = extraire_contenu(url)
            analyse = analyser_opportunite(i, texte)
            if analyse and analyse.get('score_interne', 0) >= 2:
                leads_du_jour.append(analyse)
            hist[url] = {"date": datetime.now().strftime('%Y-%m-%d')}

    # Réglage dynamique du nombre de leads
    limit = 15 if secteur['name'] in ["IDF", "NORD-OUEST"] else 10
    top_leads = sorted(leads_du_jour, key=lambda x: x.get('score_interne', 0), reverse=True)[:limit]
    
    archive_20 = mettre_a_jour_archive(leads_du_jour)
    res_exec = generer_synthese(top_leads, "executif")
    res_strat = generer_synthese(leads_du_jour, "strat")

    envoyer_rapport(top_leads, archive_20, res_exec, res_strat, secteur)
    with open(HISTORY_FILE, 'w') as f: json.dump(hist, f, indent=2)

if __name__ == "__main__": main()
