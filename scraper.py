def main():
    if not os.path.exists('cibles.csv'): return
    hist = charger_historique()
    session = creer_session()
    leads_forts, leads_faibles = [], []

    # Lecture robuste du CSV (détection automatique du séparateur)
    lignes = []
    for enc in ['utf-8', 'latin-1']:
        try:
            with open('cibles.csv', encoding=enc) as f: 
                lignes = f.readlines()
                break
        except: continue
    
    if not lignes: return
    # Détection du séparateur : ; ou ,
    separateur = ';' if ';' in lignes[0] else ','
    lecteur = csv.DictReader(lignes, delimiter=separateur)

    for ligne in lecteur:
        nom = ligne.get("Nom de l'Organisme")
        url_actu = ligne.get("URL Actualités / Projets")
        if not nom or not url_actu: continue
        
        print(f"🔎 Analyse de {nom}...")
        
        # Le robot ignore maintenant les pages statiques (histoire, gouvernance...)
        liens = recuperer_liens_projets(session, url_actu, url_actu)
        
        for l in liens:
            if l in hist: continue
            
            txt = extraire_contenu(session, l)
            if txt and len(txt) > 400:
                res = analyser_ia(txt, nom)
                item = {"url": l, "nom_source": nom, **res}
                
                # On accepte maintenant les scores 1, 2 et 3 pour remplir le mail
                if res['score'] == 3: 
                    leads_forts.append(item)
                elif res['score'] >= 1: 
                    leads_faibles.append(item)
                
                hist[l] = {"date": datetime.now().strftime('%Y-%m-%d'), "score": res['score']}
    
    envoyer_mail(leads_forts, leads_faibles)
    sauvegarder_historique(hist)
