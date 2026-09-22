""" Modulo che contiene esclusivamente i PARAMETRI di configurazione e le
FUNZIONI di libreria:
    - acquisizione e filtraggio dei documenti dai file WET,
    - estrazione delle tegole (k-grammi),
    - calcolo delle funzioni hash universali e della firma MinHash,
    - calcolo degli identificatori di banda.

Non contiene codice di popolamento del database né logica di "main":
questo modulo è pensato per essere importato sia da POPOLAMENTO.py
(fase di costruzione del database) sia da OPERAZIONI.py (operazioni
sul database già costruito).
"""

import os
import gzip
import random
import hashlib
from concurrent.futures import ProcessPoolExecutor, as_completed

import regex as re
from warcio.archiveiterator import ArchiveIterator

# ----------------------- PARAMETRI ---------------------------------------------

WET_FOLDER  = "dati_2025"
LINGUE_FILE = "lingue_alfabeto_latino.txt"
SCHEMA_PATH = "tabelle.sql"
DB_PATH = "confronto.db"
MIN_DIM  = 200 #dim minima del documento (Content-Length) per essere mantenuto
K = 5 # lunghezza delle tegole
NUM_HASHES = 300 # lunghezza della firma MinHash (numero di funzioni hash universali)
ROWS_PER_BAND = 20 # lunghezza delle bande
#NUM_HASHES = 6 # lunghezza della firma MinHash (numero di funzioni hash universali)
#ROWS_PER_BAND = 2 # lunghezza delle bande

NUM_BANDS = int(NUM_HASHES / ROWS_PER_BAND) # numero di bande
BIG_PRIME = 37**5 + 22 # 37**5 è il numero totale di tegole possibili, mentre 37^5 +22 è un numero primo vicino a quello di partenza.
H_CIFRE = len(str(BIG_PRIME)) # Cifre decimali occupate da ogni singolo valore MinHash all'interno della firma
SEED = 1

MAX_WORKERS = 5
MAX_DOCS_PER_BATCH = 500

_latin_set = None
_funzioni_hash_worker = None

# ----------------------- FUNZIONI ---------------------------------------------

def init_worker(latin_set):
    """
    Inizializzazione dell'insieme globale di calcolo delle lingue latine per i worker paralleli.
    """
    global _latin_set
    _latin_set = latin_set


def load_latin_languages(filepath):
    """
    Caricamento dell'insieme delle lingue latine da un file di testo ad un insieme.
    """
    with open(filepath, "r", encoding="utf-8") as f:

        lingue = set()

        for riga in f:
            riga = riga.strip()

            if riga == "": #ignora eventuali righe vuote
                continue

            lingue.add(riga)

        return lingue


def is_latin_language(lang_value, latin_set):
    """
    Verifica se tutte le lingue associate ad un documento appartengono all'insieme delle lingue latine
    """
    if not lang_value: #campo assente o vuoto -> documento non valido
        return False

    elenco = lang_value.split(",")
    sigle = []

    for elemento in elenco:
        elemento = elemento.strip()

        if elemento == "":
            continue

        sigle.append(elemento)

    # esclusione del documento se
    if len(sigle) == 0: #nessuna sigla valida
        return False

    for sigla in sigle: #una sigla non appartenente all'insieme
        if sigla not in latin_set:
            return False

    # se tutte le sigle appartengono all'insieme
    return True


def normalizzazione_testo(testo):
    """
    Normalizzazione del testo: rimozione dei caratteri escluse
    - lettere maiuscole A-Z,
    - lettere minuscole a-z,
    - cifle 0-9,
    - spazi.
    """
    #testo = testo.strip()
    pattern = re.compile(r"[^A-Za-z0-9 ]") # caratteri ammessi
    testo = pattern.sub("", testo) # i caratteri non ammessi sono sostituiti con la stringa vuota
    testo = testo.strip()
    testo = testo.lower() # conversione in minuscolo per uniformare le tegole

    return testo


def open_wet_stream(filepath):
    """
    Apertura del file WET (.warc.wet.gz.) mediante la libreria gzip di Python.
    """
    stream = gzip.open(filepath, "rb") # apertura del file in modalità binaria
    return stream


def process_wet_file_worker(filepath):
    """
    Funzione che chiama process_wet_file con la variabile globale _latin_set
    """
    return process_wet_file(filepath, _latin_set)


def process_wet_file(filepath, latin_set):
    """
    Estrazione dei documenti da un singolo file WET.
    """
    inserted = 0 # contatore documenti validi
    skipped = 0 # contantore documenti scartati
    seen = 0 # contatore record analizzati

    documenti = []

    stream = open_wet_stream(filepath) # apertura file

    try:
        for record in ArchiveIterator(stream): # lettura di un WARC alla volta

            if record.rec_type != "conversion": # se il reecord non contiene il testo estratto non lo considero
                continue

            seen += 1
            headers = record.rec_headers # recupero metadati

            try:
                # Filtro per dimensione del documento:
                content_length = int(headers.get_header("Content-Length"))

            except (TypeError, ValueError): # in caso di errore o mancanza del dato
                skipped += 1
                continue

            if content_length <= MIN_DIM: # in caso di documento troppo corto
                skipped += 1
                continue

            # Filtro per lingua del documento:
            lang_value = headers.get_header("WARC-Identified-Content-Language")

            if not is_latin_language(lang_value, latin_set):
                skipped += 1
                continue

            # Recupero dell'URI del documento
            uri_val = headers.get_header("WARC-Target-URI")

            if not uri_val:
                skipped += 1
                continue

            try:

                content = record.content_stream() # stream del testo
                dati = content.read() #lettura dei byte del documento
                text_val = dati.decode("utf-8", errors="replace") # decodifica in UTF-8 e rimpiazzamento caratteri speciali
                text_val = normalizzazione_testo(text_val) # restituzione testo normalizzato

            except Exception: # scarto del documento in caso di errori anomalie
                skipped += 1
                continue

            if not text_val: # in caso di testo vuoto
                skipped += 1
                continue

            documenti.append((uri_val, text_val)) # aggiunta alla lista di cippie (uri, testo)
            inserted += 1

            # restituzione dei risultati raggiunto il numero massimo di documenti
            if (MAX_DOCS_PER_BATCH is not None
                and inserted >= MAX_DOCS_PER_BATCH):
                return inserted, skipped, seen, documenti

    finally:
        stream.close() # chiusura dello stream

    return inserted, skipped, seen, documenti


def acquisisci_documenti(folder, lingue_file):
    """
    Acquisizione dei documenti presenti nel file della cartella specificata e
    restituzione della lista di tuple (URI, testo).
    """
    latin_set = load_latin_languages(lingue_file) # caricamento dei valori validi di lingua
    print(f"Numero di lingue latine: {len(latin_set)}")

    elenco_file = os.listdir(folder) # elenco file nella cartella
    wet_files = []

    for nome_file in elenco_file:
        if nome_file.endswith(".warc.wet.gz"): #à controllo estensione
            percorso = os.path.join(folder, nome_file) # percorso del file
            wet_files.append(percorso)

    wet_files.sort()

    if len(wet_files) == 0: # verifa della presenza di file
        print("Nessun file .warc.wet.gz trovato in", folder)
        return []

    numero_file = len(wet_files)
    print(f"File trovati: {numero_file}\n")

    total_inserted = 0 # contatore documenti validi
    total_skipped = 0 # contatore totale documenti scartati
    total_seen = 0 # contatore record analizzati
    documenti = [] # lista finale dei documenti
    uri_visti = set() # insieme degli uri già visti per scartare eventuali duplicati

    # calcolo in parallelo
    with ProcessPoolExecutor(
        max_workers=MAX_WORKERS, # numero di processi
        initializer=init_worker, # funzione eseguita all'avvio
        initargs=(latin_set,) # argomenti di inizializzazione
    ) as executor:

        futures = []

        for percorso in wet_files: #invio di ogni file ad un processo
            future = executor.submit(process_wet_file_worker, percorso) # avvio dell'elaborazione
            futures.append(future)

        for future in as_completed(futures): # analisi dati una volta disponibili
            inserted, skipped, seen, righe = future.result()

            # aggiornamenti valori complessivi:
            total_inserted += inserted
            total_skipped += skipped
            total_seen += seen

            # analisi dei documenti prodotti:
            for uri, testo in righe:
                if uri in uri_visti: # duplicato
                    continue
                uri_visti.add(uri)
                documenti.append((uri, testo))

            #print(f"File processato -> inseriti: {inserted}, scartati: {skipped}")

    print("\nAcquisizione completata")
    print(f"Record scartati: {total_skipped}")
    print(f"Documenti unici (per URI): {len(documenti)}\n")

    return documenti


def genera_funzioni_hash(n, seed=SEED):
    """
    Generazione di n funzioni hash universali con formula h(x) = (a*x + b) mod BIG_PRIME
    con a e b valori casuali
    """
    rnd = random.Random(seed)
    funzioni = []

    for i in range(n):
        a = rnd.randint(1, BIG_PRIME - 1) # a != 0
        b = rnd.randint(0, BIG_PRIME - 1)

        coppia = (a, b)
        funzioni.append(coppia)

    return funzioni


def init_worker_minhash(funzioni_hash):
    """
    Inizializzazione per il calcolo parallelo di tegole + firma MinHash mediante le funzioni hash globali.
    """
    global _funzioni_hash_worker
    _funzioni_hash_worker = funzioni_hash


"""def stable_int_hash(s):
    """
"""Conversione deterministica di una stringa in un intero.
    Ogni carattere viene convertito nel corrispondente codice ASCII.
    Ogni codice viene moltiplicato per la posizione del carattere
    all'interno della stringa (partendo da 1).
    Il valore finale viene ridotto modulo BIG_PRIME.
    """
"""valore = 1

    for posizione, carattere in enumerate(s, start=1): # Analizza tutti i caratteri della stringa.

        codice_ascii = ord(carattere) # conversione del carattere nel codice ASCII.
        contributo = posizione * codice_ascii        # contributo del carattere alla somma.
        valore = valore * contributo

    valore = valore % BIG_PRIME # Riduzione del valore nell'intervallo [0, BIG_PRIME-1].

    return valore"""


def estrai_tegole(testo, k=K):
    """
    Estrazione della lista ordinata (t, pos) di tegole di lunghezza k del testo.
    """
    #testo = testo.strip()
    #testo = testo.lower() # conversione in minuscolo per uniformare le tegole

    tegole = []
    lunghezza = len(testo)

    if lunghezza < k: # stringa di default per un eventuale documento vuoto
        tegole.append('0'*k)
        return tegole

    for pos in range(lunghezza - k + 1): # estrazione sottrostringhe di lunghezza k
        tegola = testo[pos:pos + k]
        elemento = (tegola, pos)
        tegole.append(elemento)

    return tegole

def converti_stringa_intero(s, alfabeto = 'abcdefghijklmnopqrstuvwxyz0123456789 '):
    """
    Converte una stringa di lunghezza fissa in un identificativo intero
    deterministico basato sull'ordine lessicografico.
    La stessa stringa restituisce sempre lo stesso valore,
    indipendentemente dall'ordine di elaborazione.

    Esempio:
        aaaaa -> 0
        aaaab -> 1
        aaaac -> 2
    """

    base = len(alfabeto)

    posizione = {} #dizionario che associa ad ogni carattere la sua posizione nell'alfabeto.
    indice = 0

    # associazione di ogni carattere alla sua posizione nell'alfabeto
    for carattere in alfabeto: 
        posizione[carattere] = indice
        indice += 1

    valore = 0 #valore intero della stringa

    for carattere in s:
        valore = valore * base + posizione[carattere]

    return valore


def calcola_minhash(tegole_distinte, funzioni_hash):
    """
    Funzione di calcolo della firma MinHash da un insieme di teole.
    Restituisce la lista di interi MinHash.
    """
    x_values = []
    firma = []

    for tegola in tegole_distinte:
        valore = converti_stringa_intero(tegola) # conversione in intero tramite hash deterministico
        x_values.append(valore)

    for a, b in funzioni_hash:
        minimo = None

        for x in x_values:
            valore_hash = (a * x + b) % BIG_PRIME # applicazione della funzione hash universale

            if minimo is None or valore_hash < minimo: # selezione del minimo tra i valori hash calcolati
                minimo = valore_hash

        firma.append(minimo)

    return firma

def identifica_firma(firma):
    """
    Costruisce un identificatore univoco della firma MinHash.
    Ogni valore MinHash occupa un numero fisso di cifre pari al numero
    di cifre decimali di BIG_PRIME. Se necessario vengono aggiunti zeri
    iniziali.
    Esempio:
        BIG_PRIME = 137
        firma = [100, 3, 59]
        restituisce
        100003059
    """

    firma_stringa = ""

    for valore in firma:
        testo = str(valore)
        testo = testo.zfill(H_CIFRE)
        firma_stringa = firma_stringa + testo

    return firma_stringa

def estrai_minhash(firma):
    """
    Estrae la lista dei valori MinHash da una firma ottenuta
    mediante concatenazione e restituisce una lista di NUM_HASHES interi.
    Ogni valore MinHash occupa H_CIFRE cifre.
    """

    firma = str(firma)
    lunghezza_totale = NUM_HASHES * H_CIFRE # Numero totale di cifre della firma.
    firma = firma.zfill(lunghezza_totale) # Ripristina gli eventuali zeri iniziali.

    minhashes = []

    for i in range(NUM_HASHES): # Estrae un valore MinHash alla volta.

        start = i * H_CIFRE # Posizione iniziale del valore.
        end = start + H_CIFRE # Posizione finale del valore.
        valore = firma[start:end] # !!!!!!!!!!!!
        minhashes.append(valore)

    return minhashes

def estrai_bande(firma):
    """
    Estrae le bande da una firma ottenuta mediante concatenazione
    dei valori MinHash e restituisce una lista di bande.
    Ogni valore MinHash occupa h cifre, dove h = len(str(BIG_PRIME))
    Ogni banda contiene ROWS_PER_BAND valori MinHash.
    """
    lunghezza_totale = NUM_HASHES * H_CIFRE
    firma = firma.zfill(lunghezza_totale)
    bande = []

    for banda in range(NUM_BANDS):

        valori_banda = []
        for i in range(ROWS_PER_BAND):
            indice = banda * ROWS_PER_BAND + i
            start = indice * H_CIFRE
            end = start + H_CIFRE
            valore = int(firma[start:end])
            valori_banda.append(valore)

        bande.append(valori_banda)

    return bande

def identifica_bande(firma):
    """
    Estrae gli identificatori delle bande direttamente
    dalla firma concatenata.
    Ogni banda è costituita da ROWS_PER_BAND valori MinHash,
    ciascuno lungo H_CIFRE cifre.
    Restituisce una lista di stringhe, una per ogni banda.
    """
    lunghezza_totale = NUM_HASHES * H_CIFRE
    identificatori = []
    cifre_banda = ROWS_PER_BAND * H_CIFRE # Numero di cifre contenute in una banda.

    # Estrazione di una banda alla volta.
    for b in range(NUM_BANDS):

        start = b * cifre_banda # Posizione iniziale della banda.
        end = start + cifre_banda # Posizione finale della banda.
        banda = firma[start:end] # Estrae la sottostringa corrispondente alla banda.
        identificatori.append(banda)

    return identificatori

def calcola_dati_documento(args):
    """
    Calcolo dei dati relativi ad un singolo documento.
    Restituisce uri, lista (tegola, pos), firma (lista di interi),
    f_val (stringa: la firma stessa codificata, NON un identificativo hash).
    """
    uri, testo = args
    tegole_pos = estrai_tegole(testo)

    insieme_tegole = set()
    for elemento in tegole_pos:
        insieme_tegole.add(elemento[0])

    tegole_distinte = sorted(insieme_tegole)
    firma_minhash = calcola_minhash(tegole_distinte, _funzioni_hash_worker)
    firma = identifica_firma(firma_minhash)
    id_bande = identifica_bande(firma)

    return uri, tegole_pos, firma, id_bande


#modifiche : stable_int_hash() -> converti_stringa_intero()
#ho usato il numero primo successivo