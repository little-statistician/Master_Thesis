"""
Contiene esclusivamente il codice relativo al popolamento del database
(creazione schema, acquisizione documenti, calcolo firme MinHash e bande,
scrittura su DB).

Tutti i parametri di configurazione e le funzioni di calcolo (estrazione
tegole, MinHash, bande, ecc.) sono importati da FUNZIONI.py.
"""

import sqlite3
import time
from concurrent.futures import ProcessPoolExecutor
import FUNZIONI as F


def popola_database():
    """
    Crea lo schema del database (se non esiste) e lo popola a partire
    dai documenti presenti nella cartella WET_FOLDER.
    """
    start_time = time.perf_counter()

    print("=" * 70)
    print("FASE 0 - Creazione schema del database")
    print("=" * 70)

    conn = sqlite3.connect(F.DB_PATH) # creazione o apertura del db

    conn.execute("PRAGMA journal_mode = WAL;") # impostazione della modalità WAL (Write Ahead Logging)
    conn.execute("PRAGMA synchronous = NORMAL;") # livello di sincronizzazione
    conn.execute("PRAGMA temp_store = MEMORY;") # RAM per operazioni temporanee
    conn.execute("PRAGMA cache_size = -64000;")  # ~64MB di cache
    conn.execute("PRAGMA foreign_keys = ON;")

    cur = conn.cursor() # cursore per eseguire comandi SQL

    with open(F.SCHEMA_PATH, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    cur.executescript(schema_sql) # esecuzione dei comandi SQL

    print(f"Schema creato ({F.DB_PATH}) a partire da {F.SCHEMA_PATH}\n")

    # ================================================================
    # FASE 1 - DOWNLOAD DOCUMENTI
    # ================================================================

    print("=" * 70)
    print("FASE 1 - Download documenti")
    print("=" * 70)

    # lettura file:
    documenti = F.acquisisci_documenti(F.WET_FOLDER, F.LINGUE_FILE)

    if not documenti:
        print("Nessun documento trovato")
        conn.close()
        return

    # ================================================================
    # FASE 2 - GENERAZIONE FUNZIONI HASH E PARAMETRI MINHASH
    # ================================================================

    print("=" * 70)
    print(f"FASE 2 - Struttura a bande "
          f"({F.NUM_HASHES} minhash / {F.ROWS_PER_BAND} per banda = {F.NUM_BANDS} bande)")
    print("=" * 70)

    # generazione delle funzioni hash universali
    funzioni_hash = F.genera_funzioni_hash(F.NUM_HASHES)
    print(f"Generate {F.NUM_HASHES} funzioni hash universali h(x) = (a*x+b) mod p "
          f"(seed={F.SEED})\n")

    # ================================================================
    # FASE 3a - ESTRAZIONE TEGOLE E CALCOLO FIRME MINHASH
    # ================================================================

    print("=" * 70)
    print(f"FASE 3 - Estrazione tegole ({F.K}-grammi) e calcolo firme MinHash "
          f"(parallelo, {F.MAX_WORKERS} processi)")
    print("=" * 70)

    with ProcessPoolExecutor(
        max_workers=F.MAX_WORKERS,
        initializer=F.init_worker_minhash,
        initargs=(funzioni_hash,)
    ) as executor:

        # distribuzione dei documenti ai processi paralleli per il calcolo
        # di tegole, firma e identificativo firma
        risultati = list(executor.map(
            F.calcola_dati_documento,
            documenti,
            chunksize=50))

    print("\nFine estrazione e calcolo firme.")

    # ================================================================
    # FASE 3b - SCRITTURA DEI DATI NEL DATABASE
    # ================================================================

    print("=" * 70)
    print("FASE 3b - Scrittura su DB (batch/executemany)")
    print("=" * 70)

    tegole_globali = set()
    bande_globali = set()

    # liste da inserire poi nelle varie tabelle:
    righe_firma = []
    righe_documento = []
    righe_compare = []
    righe_partecipa = []

    for uri, tegole_pos, firma, id_bande in risultati:

        righe_firma.append((firma,)) # id_firma
        righe_documento.append((uri, firma)) # relazione tra documento e firma

        for t, pos in tegole_pos: # analisi delle tegole
            tegole_globali.add(t) # aggiunta delle tegole all'insieme complessivo. Eventuali duplicati vengono eliminati in automatico.
            righe_compare.append((uri, pos, t)) # dati di COMPARE

        # analisi delle bande
        for p in range(F.NUM_BANDS):
            bande_globali.add(id_bande[p])
            righe_partecipa.append((firma, p, id_bande[p])) #dati di PARTECIPA

    print(f"\nTegole distinte nel corpus: {len(tegole_globali)}")
    print(f"Bande distinte nel corpus: {len(bande_globali)}")
    print(f"Righe COMPARE da inserire: {len(righe_compare)}")
    print(f"Righe PARTECIPA da inserire: {len(righe_partecipa)}")

    # Disattiviamo temporaneamente il controllo delle FK.
    # l'ordine di scrittura sotto rispetta comunque le dipendenze
    # (dizionari -> FIRMA/DOCUMENTO -> COMPARE/PARTECIPA), quindi il check
    # per-riga è evitabile
    conn.execute("PRAGMA foreign_keys = OFF;")

    cur.executemany(
        "INSERT OR IGNORE INTO TEGOLA(t) VALUES (?)",
        [(t,) for t in tegole_globali])

    cur.executemany(
        "INSERT OR IGNORE INTO BANDA(b) VALUES (?)",
        [(b,) for b in bande_globali])

    cur.executemany(
        "INSERT OR IGNORE INTO FIRMA(f) VALUES (?)",
        righe_firma)

    print("Firme calcolate:", len(righe_firma))
    print("Firme uniche:",
        cur.execute("SELECT COUNT(*) FROM FIRMA").fetchone()[0])

    cur.executemany(
        "INSERT OR IGNORE INTO DOCUMENTO(id, f) VALUES (?, ?)",
        righe_documento)

    cur.executemany(
        "INSERT OR IGNORE INTO COMPARE(id, pos, t) VALUES (?, ?, ?)",
        righe_compare)

    cur.executemany(
        "INSERT OR IGNORE INTO PARTECIPA(f, p, b) VALUES (?, ?, ?)",
        righe_partecipa)

    conn.commit()
    conn.execute("PRAGMA foreign_keys = ON;") # riattiva il controllo delle chiavi esterne

    print(f"\n{len(risultati)} documenti scritti su DB in un'unica transazione batch.")

    # ================================================================
    # FASE 6 - RIEPILOGO E CONTEGGI
    # ================================================================

    print("\n" + "=" * 70)
    print("FASE 6 - Riepilogo tabelle popolate e dei parametri di configurazione")
    print("=" * 70)
    for tabella in ["DOCUMENTO", "FIRMA", "TEGOLA", "COMPARE", "BANDA",
                    "PARTECIPA", "COPPIA"]:
        n = cur.execute(f"SELECT COUNT(*) FROM {tabella}").fetchone()[0]
        print(f"  {tabella:12s}: {n} righe")

    conn.close()
    print(f"\nDatabase salvato in: {F.DB_PATH}")

    elapsed = time.perf_counter() - start_time
    print(f"\nTempo totale: {elapsed/60:.4f} minuti")

    print("\nSoglia dimensione del documento:", F.MIN_DIM,
          "\nLunghezza delle firme:", F.NUM_HASHES,
          "\nLunghezza delle bande:", F.ROWS_PER_BAND,
          "\nNumero di bande:", F.NUM_BANDS,
          "\nLunghezza tegole:", F.K,
          "\nSoglia di Jaccard stimata per coppie candidate:", round((1/F.NUM_BANDS)**(1/F.ROWS_PER_BAND), 4),
          "\nNumero di processi paralleli:", F.MAX_WORKERS)


if __name__ == "__main__":
    popola_database()
