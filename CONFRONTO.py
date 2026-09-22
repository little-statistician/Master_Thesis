"""
CONFRONTO.py

Reimplementazione, basata esclusivamente sul file system,
delle stesse operazioni svolte da POPOLAMENTO.py (popolamento) e da
run3_OPERAZIONI.py.

Obiettivo: isolare la sola differenza "livello di persistenza/interrogazione
dei dati" (SGBD relazionale con indici VS file system), lasciando invariata
ogni fase di calcolo. Per questo motivo tutte le funzioni di libreria
(estrazione tegole, funzioni hash, MinHash, bande, acquisizione documenti)
sono importate senza modifiche da FUNZIONI.py.

Le "tabelle" del modello logico (DOCUMENTO, FIRMA, TEGOLA, BANDA, COMPARE,
PARTECIPA, COPPIA) vengono qui rappresentate come semplici file di testo
nella cartella FS_FOLDER:

    documento.jsonl   -> una riga JSON {"id":..., "f":...} per documento
    firma.txt         -> un valore di firma per riga (insieme, deduplicato)
    tegola.txt        -> una tegola per riga (insieme, deduplicato)
    banda.txt         -> un identificativo di banda per riga (deduplicato)
    compare.jsonl     -> una riga JSON {"id":..,"pos":..,"t":..} per tegola
    partecipa.jsonl   -> una riga JSON {"f":..,"p":..,"b":..} per banda
    coppia.jsonl      -> una riga JSON {"doc1":..,"doc2":..,"j":..}

A differenza delle tabelle SQLite, questi file non hanno alcuna forma di
indice: ogni interrogazione che nella versione SQL sfrutta una chiave
primaria o un indice secondario (idx_partecipa_b_p_f, idx_coppia_j, ecc.)
qui deve essere realizzata mediante scansione sequenziale (o al più
mediante il caricamento in memoria dell'intero file), così da rendere
misurabile ed esplicito il costo che il DBMS, tramite gli indici, evita.
"""

import os
import json
import time

from concurrent.futures import ProcessPoolExecutor

import FUNZIONI as F

# ── CONFIGURAZIONE ──────────────────────────────────────────────────────
FS_FOLDER = "dati_fs"  # cartella che sostituisce il file .db

_FILES = {
    "documento": "documento.jsonl",
    "firma": "firma.txt",
    "tegola": "tegola.txt",
    "banda": "banda.txt",
    "compare": "compare.jsonl",
    "partecipa": "partecipa.jsonl",
    "coppia": "coppia.jsonl",
}


def _path(nome):
    return os.path.join(FS_FOLDER, _FILES[nome])


def init_filesystem():
    """
    Equivalente file system della creazione dello schema (FASE 0 di
    POPOLAMENTO.py): crea la cartella e i file vuoti se non esistono già.
    A differenza di "CREATE TABLE ... ; CREATE INDEX ...", qui non viene
    creata alcuna struttura di accesso: solo contenitori di testo.
    """
    os.makedirs(FS_FOLDER, exist_ok=True)
    for nome in _FILES:
        percorso = _path(nome)
        if not os.path.exists(percorso):
            open(percorso, "w", encoding="utf-8").close()


def _leggi_righe(nome):
    """Generatore che legge, una riga alla volta, un file di testo (set)."""
    percorso = _path(nome)
    if not os.path.exists(percorso):
        return
    with open(percorso, "r", encoding="utf-8") as f:
        for riga in f:
            riga = riga.rstrip("\n")
            if riga:
                yield riga


def _leggi_jsonl(nome):
    """Generatore che legge, una riga alla volta, un file .jsonl."""
    percorso = _path(nome)
    if not os.path.exists(percorso):
        return
    with open(percorso, "r", encoding="utf-8") as f:
        for riga in f:
            riga = riga.strip()
            if riga:
                yield json.loads(riga)


# =========================================================================
# POPOLAMENTO (equivalente file system di popola_database() in POPOLAMENTO.py)
# =========================================================================

def popola_filesystem(documenti=None):
    """
    Esegue le stesse fasi di popola_database() (acquisizione documenti,
    generazione funzioni hash, calcolo parallelo di tegole/firme/bande),
    ma scrive i risultati su file di testo invece che in un database
    SQLite.

    Parametri:
        documenti = lista opzionale di coppie (uri, testo). Se non fornita,
        viene chiamata F.acquisisci_documenti(), esattamente come fa
        POPOLAMENTO.py, leggendo i file WET dalla cartella F.WET_FOLDER.

    Restituisce il tempo impiegato (secondi).
    """
    start_time = time.perf_counter()

    init_filesystem()

    # FASE 1 - ACQUISIZIONE DOCUMENTI (identica a POPOLAMENTO.py)
    if documenti is None:
        documenti = F.acquisisci_documenti(F.WET_FOLDER, F.LINGUE_FILE)

    if not documenti:
        print("[FS] Nessun documento trovato")
        return None

    # FASE 2 - GENERAZIONE FUNZIONI HASH (identica a POPOLAMENTO.py)
    funzioni_hash = F.genera_funzioni_hash(F.NUM_HASHES)

    # FASE 3a - ESTRAZIONE TEGOLE E CALCOLO FIRME MINHASH (identica, in parallelo)
    with ProcessPoolExecutor(
        max_workers=F.MAX_WORKERS,
        initializer=F.init_worker_minhash,
        initargs=(funzioni_hash,)
    ) as executor:
        risultati = list(executor.map(
            F.calcola_dati_documento,
            documenti,
            chunksize=50))

    # FASE 3b - SCRITTURA DEI DATI SU FILE (qui sta l'unica differenza
    # rispetto a POPOLAMENTO.py: invece di INSERT OR IGNORE su tabelle
    # SQLite, i duplicati vengono eliminati "a mano" tramite insiemi in
    # memoria e poi scritti una sola volta su file)
    tegole_globali = set()
    bande_globali = set()

    righe_documento = []
    righe_compare = []
    righe_partecipa = []

    for uri, tegole_pos, firma, id_bande in risultati:
        righe_documento.append({"id": uri, "f": firma})

        for t, pos in tegole_pos:
            tegole_globali.add(t)
            righe_compare.append({"id": uri, "pos": pos, "t": t})

        for p in range(F.NUM_BANDS):
            bande_globali.add(id_bande[p])
            righe_partecipa.append({"f": firma, "p": p, "b": id_bande[p]})

    firme_globali = {r["f"] for r in righe_documento}

    with open(_path("tegola"), "a", encoding="utf-8") as f:
        for t in tegole_globali:
            f.write(t + "\n")

    with open(_path("banda"), "a", encoding="utf-8") as f:
        for b in bande_globali:
            f.write(b + "\n")

    with open(_path("firma"), "a", encoding="utf-8") as f:
        for fi in firme_globali:
            f.write(fi + "\n")

    with open(_path("documento"), "a", encoding="utf-8") as f:
        for r in righe_documento:
            f.write(json.dumps(r) + "\n")

    with open(_path("compare"), "a", encoding="utf-8") as f:
        for r in righe_compare:
            f.write(json.dumps(r) + "\n")

    with open(_path("partecipa"), "a", encoding="utf-8") as f:
        for r in righe_partecipa:
            f.write(json.dumps(r) + "\n")

    elapsed = time.perf_counter() - start_time

    print(f"[FS] Popolamento completato in {elapsed:.4f}s "
          f"({len(righe_documento)} documenti, {len(righe_compare)} righe COMPARE, "
          f"{len(righe_partecipa)} righe PARTECIPA, {len(tegole_globali)} tegole distinte)")

    return elapsed


# =========================================================================
# LE 6 OPERAZIONI (equivalenti file system di quelle in run3_OPERAZIONI.py)
# =========================================================================

def inserisci_documento(documento):
    """
    Equivalente file system di inserisci_documento(). Calcola tegole,
    firma e bande riusando FUNZIONI.py, poi effettua un append ai file
    corrispondenti (nessuna verifica di unicità su TEGOLA/BANDA/FIRMA:
    su file, mantenerla richiederebbe rileggere per intero i file
    esistenti ad ogni singolo inserimento).
    """
    id_doc, testo = documento

    tegole_pos = F.estrai_tegole(testo)
    tegole_distinte = sorted({t for t, _ in tegole_pos})

    funzioni_hash = F.genera_funzioni_hash(F.NUM_HASHES)  # stesso seed -> stesse funzioni
    firma_minhash = F.calcola_minhash(tegole_distinte, funzioni_hash)
    firma = F.identifica_firma(firma_minhash)
    id_bande = F.identifica_bande(firma)

    init_filesystem()

    with open(_path("documento"), "a", encoding="utf-8") as f:
        f.write(json.dumps({"id": id_doc, "f": firma}) + "\n")

    with open(_path("compare"), "a", encoding="utf-8") as f:
        for t, pos in tegole_pos:
            f.write(json.dumps({"id": id_doc, "pos": pos, "t": t}) + "\n")

    with open(_path("partecipa"), "a", encoding="utf-8") as f:
        for p in range(F.NUM_BANDS):
            f.write(json.dumps({"f": firma, "p": p, "b": id_bande[p]}) + "\n")

    return id_doc, firma, id_bande


def recupera_coppie_sopra_soglia(s):
    """
    Equivalente file system di recupera_coppie_sopra_soglia(). Senza
    l'indice idx_coppia_j, l'unico modo per rispondere è leggere per
    intero il file coppia.jsonl (scansione completa, O(n)) e poi
    ordinare in memoria il risultato.
    """
    risultati = [(r["doc1"], r["doc2"], r["j"])
                 for r in _leggi_jsonl("coppia") if r["j"] >= s]
    risultati.sort(key=lambda x: -x[2])
    return risultati


def dati_documento(id_doc):
    """
    Equivalente file system di dati_documento(). Senza una chiave
    primaria indicizzata su DOCUMENTO.id, la ricerca della firma richiede
    una scansione lineare del file fino al primo (o unico) match.
    """
    firma = None
    for r in _leggi_jsonl("documento"):
        if r["id"] == id_doc:
            firma = r["f"]
            break

    if firma is None:
        return None

    coppie = [(r["doc1"], r["doc2"], r["j"])
              for r in _leggi_jsonl("coppia")
              if r["doc1"] == firma or r["doc2"] == firma]

    return {"id": id_doc, "firma": firma, "coppie": coppie}


def ricostruisci_documento(id_doc):
    """
    Equivalente file system di ricostruisci_documento(). Senza l'indice
    su COMPARE(id, pos), occorre scandire l'intero file compare.jsonl,
    filtrando le righe del documento e le posizioni multiple di 5, per
    poi ordinarle in memoria.
    """
    righe = [(r["pos"], r["t"]) for r in _leggi_jsonl("compare")
             if r["id"] == id_doc and r["pos"] % 5 == 0]
    righe.sort(key=lambda x: x[0])
    return "".join(t for _, t in righe)


def coppie_di_confronto_documento(id_doc):
    """Equivalente file system di coppie_di_confronto_documento()."""
    firma = None
    for r in _leggi_jsonl("documento"):
        if r["id"] == id_doc:
            firma = r["f"]
            break

    if firma is None:
        return None

    return [(r["doc1"], r["doc2"], r["j"])
            for r in _leggi_jsonl("coppia")
            if r["doc1"] == firma or r["doc2"] == firma]


def calcola_coppie_documento(id_doc):
    """
    Equivalente file system di calcola_coppie_documento(): individua i
    documenti che condividono almeno una banda con id_doc e ne calcola
    la similarità di Jaccard stimata.

    Qui emerge il costo più critico dell'assenza di un indice: nella
    versione SQLite, la ricerca "quali firme condividono la banda b in
    posizione p" sfrutta idx_partecipa_b_p_f (ricerca diretta, SEARCH).
    Qui, invece, per OGNI banda del documento occorre rileggere per
    intero il file partecipa.jsonl: il costo complessivo cresce con
    (numero di bande del documento) x (dimensione dell'intera tabella
    PARTECIPA), invece che restare vicino al costo di un accesso indicizzato.
    """
    firma_originale = None
    for r in _leggi_jsonl("documento"):
        if r["id"] == id_doc:
            firma_originale = r["f"]
            break

    if firma_originale is None:
        print(f"Documento con URI {id_doc} non trovato.")
        return None

    # bande del documento di riferimento (richiede comunque una scansione,
    # come sopra, in assenza di indice su PARTECIPA(f))
    bande_originali = [(r["p"], r["b"]) for r in _leggi_jsonl("partecipa")
                        if r["f"] == firma_originale]

    firme_candidate = set()
    for p, b in bande_originali:
        # scansione COMPLETA del file partecipa.jsonl per ciascuna banda:
        # è l'equivalente "senza indice" della SEARCH su idx_partecipa_b_p_f
        for r in _leggi_jsonl("partecipa"):
            if r["b"] == b and r["p"] == p and r["f"] != firma_originale:
                firme_candidate.add(r["f"])

    if not firme_candidate:
        return []

    # conversione firme candidate -> id documento (ulteriore scansione completa)
    mappa_id_firma = {}
    documenti_candidati = set()
    for r in _leggi_jsonl("documento"):
        if r["f"] in firme_candidate and r["id"] != id_doc:
            documenti_candidati.add(r["id"])
            mappa_id_firma[r["id"]] = r["f"]

    minhash_originale = F.estrai_minhash(firma_originale)

    righe_coppia = []
    for id_candidato in documenti_candidati:
        firma_candidata = mappa_id_firma[id_candidato]
        minhash_candidato = F.estrai_minhash(firma_candidata)

        concordanti = sum(1 for v1, v2 in zip(minhash_originale, minhash_candidato) if v1 == v2)
        j = concordanti / F.NUM_HASHES

        if id_doc < id_candidato:
            doc1, doc2 = id_doc, id_candidato
        else:
            doc1, doc2 = id_candidato, id_doc

        righe_coppia.append((doc1, doc2, j))

    # dedup manuale equivalente a INSERT OR IGNORE: senza chiave primaria
    # indicizzata occorre leggere l'intero file coppia.jsonl per sapere
    # cosa è già presente
    esistenti = {(r["doc1"], r["doc2"]) for r in _leggi_jsonl("coppia")}

    with open(_path("coppia"), "a", encoding="utf-8") as f:
        for doc1, doc2, j in righe_coppia:
            if (doc1, doc2) not in esistenti:
                f.write(json.dumps({"doc1": doc1, "doc2": doc2, "j": j}) + "\n")
                esistenti.add((doc1, doc2))

    return righe_coppia


def calcola_coppie_da_bande_frequenti(bande_freq):
    """
    Equivalente file system di calcola_coppie_da_bande_frequenti().
    Il calcolo "GROUP BY b HAVING COUNT(DISTINCT f) > ?", che in SQLite
    può sfruttare l'indice idx_partecipa_b_p_f, qui richiede di leggere
    l'intero file partecipa.jsonl e costruire in memoria, banda per
    banda, l'insieme delle firme distinte.
    """
    firme_per_banda = {}
    for r in _leggi_jsonl("partecipa"):
        firme_per_banda.setdefault(r["b"], set()).add(r["f"])

    bande_frequenti = [b for b, fs in firme_per_banda.items() if len(fs) > bande_freq]

    if not bande_frequenti:
        return [], []

    firme_candidate = set()
    for b in bande_frequenti:
        firme_candidate |= firme_per_banda[b]

    documenti_candidate = {r["id"] for r in _leggi_jsonl("documento") if r["f"] in firme_candidate}
    vettore_documenti = list(documenti_candidate)

    print(f"\nBande frequenti trovate: {len(bande_frequenti)}")
    print(f"Firme candidate: {len(firme_candidate)}")
    print(f"Documenti candidati: {len(vettore_documenti)}\n")

    tutte_le_coppie = []
    for id_doc in vettore_documenti:
        coppie = calcola_coppie_documento(id_doc)
        if coppie:
            tutte_le_coppie.extend(coppie)

    return vettore_documenti, tutte_le_coppie


def dimensione_totale_fs():
    """Somma (in byte) di tutti i file che compongono il 'database' su file system."""
    totale = 0
    for nome in _FILES:
        p = _path(nome)
        if os.path.exists(p):
            totale += os.path.getsize(p)
    return totale


if __name__ == "__main__":
    # Esempio d'uso, analogo al blocco __main__ di run3_OPERAZIONI.py
    nuovo_documento = ("documento_esempio", "testo di esempio da inserire nel file system")
    id_ins, firma_ins, bande_ins = inserisci_documento(nuovo_documento)
    print(f"Inserito documento '{id_ins}' con firma '{firma_ins[:20]}...' e {len(bande_ins)} bande.")
