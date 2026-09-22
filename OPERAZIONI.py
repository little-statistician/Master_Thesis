""" Modulo che implementa le operazioni richieste sul database SQLite generato
da POPOLAMENTO.py (schema: DOCUMENTO, FIRMA, TEGOLA, COMPARE, BANDA,
PARTECIPA, COPPIA).

Le funzioni riutilizzano, dove possibile, il codice già presente in
FUNZIONI.py (estrazione tegole, calcolo MinHash, calcolo firma e bande),
per garantire coerenza con i dati già presenti nel database (stessi
parametri K, NUM_HASHES, ROWS_PER_BAND, SEED, ecc.).

Le 6 funzioni implementate sono:
    1. inserisci_documento
    2. recupera_coppie_sopra_soglia
    3. dati_documento
    4. ricostruisci_documento
    5. coppie_di_confronto_documento
    6. calcola_coppie_da_bande_frequenti
"""

import sqlite3

import FUNZIONI as F

DB_PATH = F.DB_PATH
NUM_HASHES = F.NUM_HASHES
NUM_BANDS = F.NUM_BANDS
SEED = F.SEED

_FUNZIONI_HASH = F.genera_funzioni_hash(NUM_HASHES, SEED) # stesse funzioni hash universali usate in fase di costruzione del DB per l'inserimento di nuovi documenti

# ---------------------------------------------------------------------
# Funzioni di supporto
# ---------------------------------------------------------------------

def _connetti(conn=None):
    """
    Restituisce (connessione, chiudi_alla_fine).
    Se non viene passata una connessione già aperta, ne apre una nuova
    sul database DB_PATH e ne richiede la chiusura al chiamante.
    """
    if conn is not None:
        return conn, False

    connessione = sqlite3.connect(DB_PATH)
    connessione.execute("PRAGMA foreign_keys = ON;")
    return connessione, True


def _calcola_dati_documento_singolo(testo):
    """
    Calcola, per un singolo documento, la lista (tegola, pos), la firma
    e gli identificatori delle bande, riusando le funzioni
    implementate in FUNZIONI.py.
    """
    tegole_pos = F.estrai_tegole(testo)

    insieme_tegole = set()

    for tegola, pos in tegole_pos:
        insieme_tegole.add(tegola)

    tegole_distinte = sorted(insieme_tegole)
    firma_minhash = F.calcola_minhash(tegole_distinte, _FUNZIONI_HASH)
    firma = F.identifica_firma(firma_minhash)
    id_bande = F.identifica_bande(firma)

    return tegole_pos, firma, id_bande


# ---------------------------------------------------------------------
# 1. Inserimento di un documento, della sua firma e delle bande
# ---------------------------------------------------------------------

def inserisci_documento(documento, conn=None):
    """
    Inserisce un documento nel database insieme alla sua firma MinHash
    e alle bande da essa derivate e restituisce (id, firma, id_bande), ovvero i dati calcolati e inseriti.
    Parametri:  documento=(id, testo) del documento da inserire, 
                conn = sqlite3.Connection opzionale. Se non fornita, ne viene aperta (e chiusa) una internamente.
    """
    id_doc, testo = documento

    tegole_pos, firma, id_bande = _calcola_dati_documento_singolo(testo)

    connessione, chiudi = _connetti(conn)
    cur = connessione.cursor()

    try:
        connessione.execute("PRAGMA foreign_keys = OFF;")

        # TEGOLA
        cur.executemany(
            "INSERT OR IGNORE INTO TEGOLA(t) VALUES (?)",
            list({(t,) for t, pos in tegole_pos}))

        # BANDA
        cur.executemany(
            "INSERT OR IGNORE INTO BANDA(b) VALUES (?)",
            [(b,) for b in id_bande])

        # FIRMA
        cur.execute(
            "INSERT OR IGNORE INTO FIRMA(f) VALUES (?)",
            (firma,))

        # DOCUMENTO
        cur.execute(
            "INSERT OR IGNORE INTO DOCUMENTO(id, f) VALUES (?, ?)",
            (id_doc, firma))

        # COMPARE (tegole del documento con relativa posizione)
        cur.executemany(
            "INSERT OR IGNORE INTO COMPARE(id, pos, t) VALUES (?, ?, ?)",
            [(id_doc, pos, t) for t, pos in tegole_pos])

        # PARTECIPA (relazione firma -> banda per ciascuna delle NUM_BANDS bande)
        cur.executemany(
            "INSERT OR IGNORE INTO PARTECIPA(f, p, b) VALUES (?, ?, ?)",
            [(firma, p, id_bande[p]) for p in range(NUM_BANDS)])

        connessione.commit()
        connessione.execute("PRAGMA foreign_keys = ON;")

    finally:
        if chiudi:
            connessione.close()

    return id_doc, firma, id_bande


# ---------------------------------------------------------------------
# 2. Recupero di tutte le COPPIE con valore di similarità >= soglia s
# ---------------------------------------------------------------------

def recupera_coppie_sopra_soglia(s, conn=None):
    """
    Restituisce tutte le righe della tabella COPPIA il cui coefficiente
    di similarità è maggiore o uguale alla soglia "s" e 
    restituisce una lista di tuple (doc1, doc2, j).
    """
    connessione, chiudi = _connetti(conn)

    try:
        cur = connessione.cursor()
        cur.execute(
            "SELECT doc1, doc2, j FROM COPPIA WHERE j >= ? ORDER BY j DESC",
            (s,))
        risultati = cur.fetchall()
    finally:
        if chiudi:
            connessione.close()

    return risultati


# ---------------------------------------------------------------------
# 3. Ricerca e recupero dei dati di un documento
#    (firma, coppie e coefficienti di similarità a cui partecipa)
# ---------------------------------------------------------------------

def dati_documento(id_doc, conn=None):
    """
    Recupera i dati relativi ad un documento:
        - la sua firma MinHash,
        - le coppie (e i relativi coefficienti di similarità) in cui
          la firma del documento compare, come primo o secondo elemento.
    Restituisce un dizionario:
        {
            "id": id_doc,
            "firma": firma,
            "coppie": [(doc1, doc2, j), ...]
        }
    oppure None se il documento non esiste nel database.
    """
    connessione, chiudi = _connetti(conn)

    try:
        cur = connessione.cursor()

        cur.execute("SELECT f FROM DOCUMENTO WHERE id = ?", (id_doc,))
        riga = cur.fetchone()

        if riga is None:  # documento non trovato
            print(f"Documento con URI {id_doc} non trovato.")
            return None

        firma = riga[0]

        cur.execute(
            """
            SELECT doc1, doc2, j FROM COPPIA WHERE doc1 = ?
            UNION ALL
            SELECT doc1, doc2, j FROM COPPIA WHERE doc2 = ?
            """,
            (id_doc, id_doc))
        coppie = cur.fetchall()

    finally:
        if chiudi:
            connessione.close()

    return {"id": id_doc, "firma": firma, "coppie": coppie}


# ---------------------------------------------------------------------
# 4. Ricostruzione del contenuto di un documento
#    (concatenazione delle tegole di indice multiplo di 5 (K))
# ---------------------------------------------------------------------

def ricostruisci_documento(id_doc, conn=None):
    """
    Ricostruisce il contenuto di un documento concatenando
    le tegole (colonna t di COMPARE) le cui posizioni (pos) sono multiple
    di F.K, in modo da non avere
    sovrapposizioni fra tegole consecutive, in ordine crescente di posizione.
    
    Restituisce la stringa ricostruita (stringa vuota se il documento
    non ha tegole in COMPARE).
    """
    connessione, chiudi = _connetti(conn)

    try:
        cur = connessione.cursor()
        cur.execute(
            "SELECT pos, t FROM COMPARE WHERE id = ? ORDER BY pos ASC",
            (id_doc,))
        righe = cur.fetchall()
    finally:
        if chiudi:
            connessione.close()

    if not righe: 
        return ""

    K = F.K
    pezzi = []
    ultima_pos_inclusa = None

    for pos, t in righe:
        if pos % K == 0:  # tegole a passo K, senza sovrapposizioni
            pezzi.append(t)
            ultima_pos_inclusa = pos

    # ultima tegola disponibile in assoluto (posizione massima): è quella
    # che arriva fino all'ultimo carattere del documento
    pos_max, t_max = righe[-1]

    if ultima_pos_inclusa is None:
        pezzi.append(t_max) # nessuna tegola a passo K selezionata (documento molto corto)
    
    elif pos_max > ultima_pos_inclusa:
        # recupero solo la porzione finale non già coperta dall'ultima
        # tegola inclusa, per chiudere il testo senza duplicare caratteri
        sovrapposizione = (ultima_pos_inclusa + K) - pos_max
        pezzi.append(t_max[sovrapposizione:])

    testo_ricostruito = "".join(pezzi) # ricostruzione del testo tramite concatenazione di tegole

    return testo_ricostruito


# ---------------------------------------------------------------------
# 5. Recupero delle coppie di confronto associate ad un documento
# ---------------------------------------------------------------------

def coppie_di_confronto_documento(id_doc, conn=None):
    """
    Recupera tutte le coppie di confronto (tabella COPPIA) in cui la
    firma del documento "id_doc" compare, come primo o secondo elemento
    della coppia e restituisce una lista di tuple (doc1, doc2, j), oppure None se il
    documento non esiste nel database.
    """
    connessione, chiudi = _connetti(conn)

    try:
        cur = connessione.cursor()

        cur.execute("SELECT f FROM DOCUMENTO WHERE id = ?", (id_doc,))
        riga = cur.fetchone()

        if riga is None:  # documento non trovato
            print(f"Documento con URI {id_doc} non trovato.")
            return None

        firma = riga[0]

        cur.execute(
            """
            SELECT doc1, doc2, j FROM COPPIA WHERE doc1 = ?
            UNION ALL
            SELECT doc1, doc2, j FROM COPPIA WHERE doc2 = ?
            """,
            (id_doc, id_doc))
        coppie = cur.fetchall()

    finally:
        if chiudi:
            connessione.close()

    return coppie
 
# ---------------------------------------------------------------------
# 6. Calcolo e memorizzazione delle coppie candidate di un documento
#    (documenti che condividono almeno una banda con esso)
# ---------------------------------------------------------------------
 
def calcola_coppie_documento(id_doc, conn=None):
    """
    Individua tutti i documenti che condividono almeno una banda con il
    documento "id_doc", calcola per ciascuno di essi l'indice di Jaccard stimato come
    rapporto tra i valori MinHash concordanti (stessa posizione nella
    firma) e il numero totale di valori MinHash (NUM_HASHES), e
    memorizza i risultati nella tabella COPPIA.
    Le coppie sono sempre salvate con doc1 < doc2 (confronto sugli id),
    così da evitare duplicati.
    
    Parametri:
    id_doc = id del documento di riferimento.
    conn = sqlite3.Connection, opzionale.
 
    Output:
    Lista di tuple (doc1, doc2, j) inserite (o già presenti) in COPPIA,
    oppure None se il documento non esiste nel database.
    """
    connessione, chiudi = _connetti(conn)
 
    try:
        cur = connessione.cursor()
 
        # firma del documento di riferimento
        cur.execute("SELECT f FROM DOCUMENTO WHERE id = ?", (id_doc,))
        riga = cur.fetchone()
 
        if riga is None:  # documento non trovato
            print(f"Documento con URI {id_doc} non trovato.")
            return None
 
        firma_originale = riga[0]
 
        # bande (p, b) a cui appartiene la firma del documento
        cur.execute(
            "SELECT p, b FROM PARTECIPA WHERE f = ?",
            (firma_originale,))
        bande_originali = cur.fetchall()
 
        # Firme di altri documenti che condividono almeno una banda
        # (stessa posizione p e stesso valore di banda b)
        firme_candidate = set()
 
        for p, b in bande_originali:
            # clausola WHERE ordinata come le colonne dell'indice
            # idx_partecipa_b_p_f(b, p, f): essendo un covering index,
            # la query viene risolta interamente sull'indice (SEARCH),
            # senza toccare le pagine della tabella PARTECIPA.
            cur.execute(
                "SELECT f FROM PARTECIPA WHERE b = ? AND p = ? AND f != ?",
                (b, p, firma_originale))
 
            for (f_candidata,) in cur.fetchall():
                firme_candidate.add(f_candidata)
 
        # conversione delle firme candidate in id documento
        # (più documenti possono condividere la stessa firma)
        documenti_candidati = set()
 
        for f_candidata in firme_candidate:
            cur.execute(
                "SELECT id FROM DOCUMENTO WHERE f = ?",
                (f_candidata,))
 
            for (id_candidato,) in cur.fetchall():
                if id_candidato != id_doc:
                    documenti_candidati.add(id_candidato)
 
        # valori MinHash del documento di riferimento
        minhash_originale = F.estrai_minhash(firma_originale)
 
        righe_coppia = []
 
        for id_candidato in documenti_candidati:
 
            cur.execute(
                "SELECT f FROM DOCUMENTO WHERE id = ?",
                (id_candidato,))
            firma_candidata = cur.fetchone()[0]
 
            minhash_candidato = F.estrai_minhash(firma_candidata)
 
            # conteggio dei valori MinHash concordanti (stessa posizione)
            concordanti = 0
            for v1, v2 in zip(minhash_originale, minhash_candidato):
                if v1 == v2:
                    concordanti += 1
 
            j = concordanti / NUM_HASHES
 
            # memorizzazione con doc1 < doc2
            if id_doc < id_candidato:
                doc1, doc2 = id_doc, id_candidato
            else:
                doc1, doc2 = id_candidato, id_doc
 
            righe_coppia.append((doc1, doc2, j))
 
        cur.executemany(
            "INSERT OR IGNORE INTO COPPIA(doc1, doc2, j) VALUES (?, ?, ?)",
            righe_coppia)
 
        connessione.commit()
 
    finally:
        if chiudi:
            connessione.close()
 
    return righe_coppia

def calcola_coppie_da_bande_frequenti(bande_freq, conn=None):
    """
    Individua coppie candidate partendo dalle bande frequenti. Procedura:
    1) seleziona le bande con frequenza > bande_freq;
    2) recupera le firme associate;
    3) recupera i documenti associati alle firme;
    4) applica calcola_coppie_documento() a tutti i documenti candidati.

    Parametri:
    bande_freq = Numero minimo di firme associate alla banda.
    conn = sqlite3.Connection opzionale

    Output:
    Lista dei documenti analizzati e lista delle coppie generate.
    """
    connessione, chiudi = _connetti(conn)

    try:
        cur = connessione.cursor()

        # 1) recupero bande frequenti
        cur.execute(
            """
            SELECT b
            FROM PARTECIPA
            GROUP BY b
            HAVING COUNT(DISTINCT f) > ?
            """,
            (bande_freq,))

        bande_frequenti = [row[0] for row in cur.fetchall()]

        if not bande_frequenti:
            return [], []
        
        # 2) recupero firme associate alle bande
        firme_candidate = set()

        for b in bande_frequenti:

            # utilizza indice: idx_partecipa_b_p_f ON PARTECIPA(b,p,f)
            cur.execute(
                """
                SELECT DISTINCT f
                FROM PARTECIPA
                WHERE b = ?
                """,
                (b,))

            for (f,) in cur.fetchall():
                firme_candidate.add(f)

        # 3) recupero documenti associati alle firme
        documenti_candidate = set()
        for f in firme_candidate:

            cur.execute(
                """
                SELECT id
                FROM DOCUMENTO
                WHERE f = ?
                """,
                (f,))

            for (id_doc,) in cur.fetchall():
                documenti_candidate.add(id_doc)

        vettore_documenti = list(documenti_candidate)

        #for doc in documenti_candidate: print("\n", doc)

        print(f"\nBande frequenti trovate: {len(bande_frequenti)}")
        print(f"Firme candidate: {len(firme_candidate)}")
        print(f"Documenti candidati: {len(vettore_documenti)}\n")

        # 4) calcolo delle coppie su tutti i documenti candidati
        tutte_le_coppie = []

        for i, id_doc in enumerate(vettore_documenti):
            coppie = calcola_coppie_documento(id_doc, connessione)

            if coppie:
                tutte_le_coppie.extend(coppie)

        return vettore_documenti, tutte_le_coppie

    finally:
        if chiudi:
            connessione.close()
 
# ---------------------------------------------------------------------
# Esempio d'uso
# ---------------------------------------------------------------------

if __name__ == "__main__":

    # ==============================================================
    # OPERAZIONE 1 - Inserimento di nuovi documenti
    # ==============================================================

    print("\n########################################")
    print("OPERAZIONE 1: inserimento di nuovi documenti")
    print("########################################")

    nuovo_documento = ("documento_esempio","testo di esempio da inserire nel database")

    id_ins, firma_ins, bande_ins = inserisci_documento(nuovo_documento)

    print(f"\nInserito documento '{id_ins}' "
          f"con firma '{str(firma_ins)[:20]}...' "
          f"e {len(bande_ins)} bande.")

    documento_simile = ("documento_esempio_simile","testo di esempio simile da inserire nel database")

    id_ins2, firma_ins2, bande_ins2 = inserisci_documento(documento_simile)

    print(f"Inserito documento '{id_ins2}' "
        f"con firma '{str(firma_ins2)[:20]}...' "
        f"e {len(bande_ins2)} bande.")

    documento_simile2 = ("documento_esempio_simile2","testo di esempio simile da inserire nel database2")

    id_ins3, firma_ins3, bande_ins3 = inserisci_documento(documento_simile2)

    print(f"Inserito documento '{id_ins3}' "
        f"con firma '{str(firma_ins3)[:20]}...' "
        f"e {len(bande_ins3)} bande.")

    # ==============================================================
    # OPERAZIONE 6a - Calcolo delle coppie candidate
    # ==============================================================

    print("\n########################################")
    print("OPERAZIONE 6a: confronto di un documento con tutti i suoi candidati")
    print("########################################")

    print(f"\nDocumento: {id_ins2}")
    coppie_calcolate = calcola_coppie_documento(id_ins2)
    print("Coppie candidate:", coppie_calcolate)

    id_popolare = ("http://agateria.blogspot.com/2012/06/lodowkowa-ozdoba.html")

    print(f"\nDocumento: {id_popolare}")
    coppie_calcolate = calcola_coppie_documento(id_popolare)
    print("Coppie candidate:", coppie_calcolate)

    id_popolare2 = ("http://m.opera.com/?vid=0xfcae9511f29759a4&region=es&tag=mini5&rnd=2383328714&utm_medium=ip&utm_source=opcom_hp_wap"
        "&utm_campaign=hp_to_m_opera_com&cert=none&act=lp")

    print(f"\nDocumento: {id_popolare2}")
    coppie_calcolate = calcola_coppie_documento(id_popolare2)
    print("Coppie candidate:", coppie_calcolate)

    # ==============================================================
    # OPERAZIONE 3 - Recupero dati documento
    # ==============================================================

    print("\n########################################")
    print("OPERAZIONE 3: recupero dei dati di un documento")
    print("########################################")

    dati = dati_documento(id_ins2)

    print(f"\nRecupero dei dati di '{id_ins2}':")
    print(dati)

    dati = dati_documento(id_popolare)

    print(f"\nRecupero dei dati di '{id_popolare}':")
    print(dati)

    # ==============================================================
    # OPERAZIONE 4 - Ricostruzione del documento
    # ==============================================================

    print("\n########################################")
    print("OPERAZIONE 4: ricostruzione del contenuto di un documento")
    print("########################################")

    testo = ricostruisci_documento(id_ins)

    print(f"\nRicostruzione del contenuto di '{id_ins}':")
    print(testo)

    # ==============================================================
    # OPERAZIONE 5 - Recupero delle coppie associate
    # ==============================================================

    print("\n########################################")
    print("OPERAZIONE 5: recupero delle coppie associate ad un documento")
    print("########################################")

    coppie = coppie_di_confronto_documento(id_ins2)

    print(f"\nCoppie associate a '{id_ins2}':")
    print(coppie)

    coppie = coppie_di_confronto_documento(id_popolare)

    print(f"\nCoppie associate a '{id_popolare}':")
    print(coppie)

    # ==============================================================
    # OPERAZIONE 6 - Popolamento della tabella COPPIA
    # ==============================================================

    print("\n########################################")
    print("OPERAZIONE 6b: esempio di auto riempimento di COPPIA su tutta la collezione:")
    print("########################################")
    print("\nRiempimento della tabela COPPIA con i confronti generati da bande condivise in almeno 1 firma...")
    confronti = calcola_coppie_da_bande_frequenti(1)

    print("\nFine.\n")