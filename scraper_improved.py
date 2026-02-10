import os
import requests
import csv
import re
import json
from bs4 import BeautifulSoup
import fitz
import google.generativeai as genai
from urllib.parse import urljoin, urlparse
from datetime import datetime, timedelta
import logging

# --- CONFIGURATION ---
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
BREVO_KEY = os.environ.get("BREVO_API_KEY")
GOOGLE_SEARCH_KEY = os.environ.get("GOOGLE_SEARCH_KEY")
GOOGLE_SEARCH_CX = os.environ.get("GOOGLE_SEARCH_CX")
LOGO_URL = "https://urban-agency.com/assets/cp-logo.png"
HISTORY_FILE = "download_history.json"

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('scraper.log'),
        logging.StreamHandler()
    ]
)

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

def charger_historique():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r') as f: 
                return json.load(f)
        except: 
            return {}
    return {}

def sauvegarder_historique(hist):
    with open(HISTORY_FILE, 'w') as f: 
        json.dump(hist, f, indent=2)

def extraire_contenu(session, url):
    """Extract content from URL (PDF or HTML)"""
    try:
        r = session.get(url, timeout=12)
        content_type = r.headers.get('Content-Type', '').lower()
        
        if 'pdf' in content_type:
            logging.info(f"Extracting PDF: {url}")
            with fitz.open(stream=r.content, filetype="pdf") as doc:
                return "".join([p.get_text() for p in doc[:8]])
        
        soup = BeautifulSoup(r.text, 'html.parser')
        for t in soup(['nav', 'footer', 'script', 'style', 'header']): 
            t.decompose()
        
        main = soup.find('main') or soup.find('article') or soup.body
        content = re.sub(r'\s+', ' ', main.get_text()).strip()
        logging.info(f"Extracted {len(content)} chars from: {url}")
        return content
    except Exception as e:
        logging.error(f"Error extracting content from {url}: {str(e)}")
        return None

def est_page_pertinente(url, texte):
    """
    Validate if a page is relevant for urban planning projects.
    Returns (is_relevant, confidence_score)
    """
    # Keywords indicating institutional/static pages (to exclude)
    mots_exclusion = [
        'qui-nous-sommes', 'histoire', 'gouvernance', 'equipe', 'mentions', 
        'contact', 'plan-du-site', 'cookies', 'rgpd', 'privacy',
        'mentions-legales', 'accessibilite', 'recrutement', 'emploi',
        'newsletter', 'presse', 'medias'
    ]
    
    # Keywords indicating project/news pages (to include)
    mots_inclusion = [
        'projet', 'actualite', 'news', 'zac', 'amenagement', 'urban', 
        'concours', 'marche', 'consultation', 'appel-offre', 'aap',
        'laureat', 'etude', 'concertation', 'quartier', 'ecoquartier'
    ]
    
    url_lower = url.lower()
    
    # Exclude institutional pages
    if any(mot in url_lower for mot in mots_exclusion):
        return False, 0
    
    # Strong inclusion signals in URL
    url_score = sum(1 for mot in mots_inclusion if mot in url_lower)
    
    # Check content relevance
    texte_lower = texte.lower() if texte else ""
    content_score = sum(1 for mot in mots_inclusion if mot in texte_lower)
    
    # Calculate relevance
    total_score = url_score * 2 + (content_score > 2)
    
    return total_score > 0, total_score

def recuperer_liens_projets(session, url_liste, racine, mode="auto"):
    """
    Enhanced project link retrieval with multiple strategies:
    - mode="direct": Scan the provided URL directly
    - mode="links": Extract links from the page (original behavior)
    - mode="auto": Try both approaches
    """
    liens_trouves = []
    
    # Strategy 1: Check if the main URL itself is a project page
    if mode in ["direct", "auto"]:
        logging.info(f"Checking main URL directly: {url_liste}")
        texte = extraire_contenu(session, url_liste)
        if texte and len(texte) > 400:
            pertinent, score = est_page_pertinente(url_liste, texte)
            if pertinent:
                logging.info(f"Main URL is relevant (score: {score})")
                liens_trouves.append(url_liste)
    
    # Strategy 2: Extract links from the page
    if mode in ["links", "auto"]:
        try:
            logging.info(f"Extracting links from: {url_liste}")
            r = session.get(url_liste, timeout=10)
            soup = BeautifulSoup(r.text, 'html.parser')
            
            # More specific selectors for project/news listings
            selectors_prioritaires = [
                'article a',
                '.article a',
                '.news a',
                '.projet a',
                '.actualite a',
                'main a',
                '.content a'
            ]
            
            liens_candidats = []
            
            # Try priority selectors first
            for selector in selectors_prioritaires:
                elements = soup.select(selector)
                if elements:
                    logging.info(f"Found {len(elements)} links with selector: {selector}")
                    for a in elements:
                        if a.get('href'):
                            liens_candidats.append(a)
                    break  # Use first successful selector
            
            # Fallback to all links if no priority selector worked
            if not liens_candidats:
                liens_candidats = soup.find_all('a', href=True)
            
            # Process candidate links
            for a in liens_candidats:
                full_url = urljoin(url_liste, a['href'])
                
                # Only keep URLs from same domain
                if urlparse(full_url).netloc != urlparse(racine).netloc:
                    continue
                
                # Skip very short URLs (likely navigation)
                if len(full_url) <= len(url_liste) + 3:
                    continue
                
                # Quick relevance check based on URL
                pertinent, _ = est_page_pertinente(full_url, "")
                if pertinent and full_url not in liens_trouves:
                    liens_trouves.append(full_url)
            
            logging.info(f"Found {len(liens_trouves)} potentially relevant links")
            
        except Exception as e:
            logging.error(f"Error extracting links from {url_liste}: {str(e)}")
    
    # Remove duplicates while preserving order
    liens_uniques = list(dict.fromkeys(liens_trouves))
    
    # Limit to top 10 instead of 6 for better coverage
    return liens_uniques[:10]

def analyser_ia(texte, source):
    """AI analysis of content with improved prompt"""
    prompt = f"""RÔLE : Directeur Développement Urban Agency (urbanisme, aménagement).

SCORING :
- 3 points : ZAC créée, Concours lancé, Marché public, Appel à Projets, Lauréat désigné
- 2 points : Étude urbaine, Concertation publique, Plan Guide, Diagnostic territorial
- 1 point : Veille générale, Annonce sans détail
- 0 point : Administratif, RH, Institutionnel

RETOURNE UNIQUEMENT ce JSON (pas de markdown) :
{{
  "titre": "Titre synthétique (max 80 car)",
  "theme": "ZAC/Concours/Étude/Veille",
  "resume": "Résumé en 2 phrases max",
  "chiffres": "Budget, surface, dates clés si disponibles",
  "score": 0-3
}}

SOURCE : {source}
TEXTE (12000 premiers car) :
{texte[:12000]}"""
    
    try:
        res = model.generate_content(prompt)
        texte_brut = res.text.replace('```json', '').replace('```', '').strip()
        resultat = json.loads(texte_brut)
        logging.info(f"AI Score: {resultat.get('score', 0)} - {resultat.get('titre', 'N/A')[:50]}")
        return resultat
    except Exception as e:
        logging.error(f"AI analysis error: {str(e)}")
        return {"score": 0, "titre": "Erreur analyse", "theme": "", "resume": "", "chiffres": ""}

def bloc_html(item, color):
    """Generate HTML block for email"""
    badge = "🔥 PRIORITÉ" if item['score'] == 3 else "⚡ SIGNAL"
    return f"""<div style="border-left: 4px solid {color}; background:#ffffff; padding:15px; margin-bottom:15px; font-family:Arial;">
        <div style="font-size:10px; color:#95a5a6; font-weight:bold;">{item['nom_source']} | {badge}</div>
        <div style="font-weight:bold; color:#2c3e50; font-size:15px;">{item['titre']}</div>
        <div style="font-size:13px; color:#555; margin:8px 0;">{item['resume']}</div>
        {f"<div style='font-size:12px; color:#7f8c8d;'>{item['chiffres']}</div>" if item.get('chiffres') else ""}
        <div style="text-align:right;"><a href="{item['url']}" style="color:{color}; font-size:11px; font-weight:bold;">VOIR LA SOURCE →</a></div>
    </div>"""

def envoyer_mail(forts, faibles):
    """Send email with results"""
    if not forts and not faibles: 
        logging.info("No results to send")
        return
    
    html_forts = "".join([bloc_html(x, "#e74c3c") for x in forts])
    html_faibles = "".join([bloc_html(x, "#3498db") for x in faibles])
    
    body = f"""<html><body style='background:#f4f4f4; padding:20px;'>
    <div style='max-width:620px; margin:auto; background:white; padding:20px;'>
        <div style='text-align:center;'><img src='{LOGO_URL}' height='45'></div>
        <div style='color:#7f8c8d; font-size:12px; text-align:center; margin:10px 0;'>
            Veille automatisée - {datetime.now().strftime('%d/%m/%Y %H:%M')}
        </div>
        {f"<h2 style='color:#e74c3c; font-family:Arial;'>🔴 PRIORITÉS ({len(forts)})</h2>{html_forts}" if forts else ""}
        {f"<h2 style='color:#3498db; font-family:Arial;'>🔵 SIGNAUX FAIBLES ({len(faibles)})</h2>{html_faibles}" if faibles else ""}
    </div>
    </body></html>"""
    
    try:
        response = requests.post(
            "https://api.brevo.com/v3/smtp/email",
            json={
                "sender": {"name": "IA Urban Agency", "email": "bertrand@urban-agency.com"},
                "to": [{"email": "bertrand@urban-agency.com"}],
                "subject": f"UA_Veille: {len(forts)} Priorités | {len(faibles)} Signaux",
                "htmlContent": body
            },
            headers={"api-key": BREVO_KEY}
        )
        logging.info(f"Email sent: {response.status_code}")
    except Exception as e:
        logging.error(f"Error sending email: {str(e)}")

def main():
    """Main execution function"""
    if not os.path.exists('cibles.csv'):
        logging.error("File cibles.csv not found!")
        return
    
    logging.info("=" * 60)
    logging.info("STARTING URBAN AGENCY SCRAPER")
    logging.info("=" * 60)
    
    hist = charger_historique()
    session = requests.Session()
    session.headers.update({'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'})
    
    leads_forts, leads_faibles = [], []
    stats = {"total_sources": 0, "total_liens": 0, "nouveaux": 0, "score_3": 0, "score_2": 0, "score_1": 0}
    
    with open('cibles.csv', encoding='utf-8') as f:
        # Auto-detect delimiter
        sample = f.read(200)
        delimiter = ';' if ';' in sample else ','
        f.seek(0)
        
        lecteur = csv.DictReader(f, delimiter=delimiter)
        
        for ligne in lecteur:
            nom = ligne.get("Nom de l'Organisme", "").strip()
            url_actu = ligne.get("URL Actualités / Projets", "").strip()
            
            if not nom or not url_actu:
                continue
            
            stats["total_sources"] += 1
            logging.info(f"\n{'='*60}")
            logging.info(f"Processing: {nom}")
            logging.info(f"URL: {url_actu}")
            logging.info(f"{'='*60}")
            
            # Use "auto" mode to try both direct and link extraction
            liens = recuperer_liens_projets(session, url_actu, url_actu, mode="auto")
            stats["total_liens"] += len(liens)
            
            for l in liens:
                # Skip if already processed
                if l in hist:
                    logging.info(f"Skipping (already in history): {l}")
                    continue
                
                stats["nouveaux"] += 1
                
                # Extract content
                txt = extraire_contenu(session, l)
                
                if txt and len(txt) > 400:
                    # AI analysis
                    res = analyser_ia(txt, nom)
                    item = {
                        "url": l,
                        "nom_source": nom,
                        **res
                    }
                    
                    # Categorize by score
                    score = res.get('score', 0)
                    if score == 3:
                        leads_forts.append(item)
                        stats["score_3"] += 1
                    elif score >= 1:
                        leads_faibles.append(item)
                        if score == 2:
                            stats["score_2"] += 1
                        else:
                            stats["score_1"] += 1
                    
                    # Save to history
                    hist[l] = {
                        "date": datetime.now().strftime('%Y-%m-%d'),
                        "score": score,
                        "source": nom
                    }
                else:
                    logging.warning(f"Content too short or empty: {l}")
    
    # Send results
    logging.info("\n" + "=" * 60)
    logging.info("STATISTICS")
    logging.info("=" * 60)
    for key, value in stats.items():
        logging.info(f"{key}: {value}")
    logging.info("=" * 60)
    
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)
    
    logging.info("\nScraping completed successfully!")

if __name__ == "__main__":
    main()
