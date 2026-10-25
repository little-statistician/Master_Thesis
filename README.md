# Rilevamento di documenti duplicati e quasi duplicati su Common Crawl

Applicazione di base di dati (SQLite) per individuare documenti duplicati o quasi duplicati in una collezione di pagine web, tramite **tegole (k-grammi), firme MinHash e Locality-Sensitive Hashing (LSH)**. Il progetto comprende il download dei dati da Common Crawl, il popolamento del database, le operazioni di interrogazione e un confronto prestazionale con un'implementazione equivalente basata sul solo file system.

## Struttura del progetto

| File | Contenuto |
| --- | --- |
| `download_dati.py` | Scarica da Common Crawl i primi `N_FILES` file WET di un crawl e li salva in `dati_2025/`. |
| `FUNZIONI.py` | Parametri di configurazione e funzioni di libreria: acquisizione e filtraggio dei documenti, normalizzazione, tegole, funzioni hash, MinHash, firme e bande. |
| `tabelle.sql` | Schema del database: tabelle `DOCUMENTO`, `FIRMA`, `TEGOLA`, `BANDA`, `COMPARE`, `PARTECIPA`, `COPPIA` e indici. |
| `lingue_alfabeto_latino.txt` | Codici delle 81 lingue ad alfabeto latino ammesse dal filtro linguistico. |
| `POPOLAMENTO.py` | Crea lo schema, acquisisce i documenti, calcola tegole, firme e bande in parallelo e scrive tutto nel database. |
| `OPERAZIONI.py` | Operazioni sul database già popolato (vedi sotto). |
| `CONFRONTO.py` | Reimplementazione di popolamento e operazioni su soli file di testo (`dati_fs/*.jsonl`, `*.txt`), senza indici. |
| `run_confronto.py` | Benchmark SGBD vs file system su un corpus sintetico. |

## Dipendenze

```bash
pip install requests regex warcio
```

`sqlite3`, `gzip` e `concurrent.futures` fanno parte della libreria standard.

## Esecuzione

```bash
python download_dati.py     # 1. scarica i file WET in dati_2025/
python POPOLAMENTO.py       # 2. crea e popola collezione.db
python OPERAZIONI.py        # 3. esempi d'uso delle operazioni
python run_confronto.py     # 4. benchmark SGBD vs file system
```

I passi 1–3 vanno eseguiti in ordine. `run_confronto.py` è indipendente: lavora su un corpus sintetico e non richiede il download.

> **Attenzione:** `run_confronto.py` elimina `collezione.db` e svuota `dati_fs/` prima di ogni run. Se serve conservare il database popolato dal passo 2, va copiato altrove prima.

## Pipeline di elaborazione

1. **Acquisizione** (`acquisisci_documenti`): lettura parallela dei file WET; si tengono solo i record `conversion` con `Content-Length` > 200 byte, lingua (anche multipla) interamente contenuta in `lingue_alfabeto_latino.txt` e URI presente. Gli URI duplicati sono scartati.
2. **Normalizzazione**: rimozione dei caratteri diversi da `A-Za-z0-9` e spazio, conversione in minuscolo.
3. **Tegole**: finestra scorrevole di lunghezza `K` → lista `(tegola, posizione)`. Testi più corti di `K` producono la tegola fittizia `00000`.
4. **Tegole → interi**: codifica posizionale in base 37 (`converti_stringa_intero`), iniettiva e deterministica.
5. **MinHash**: `NUM_HASHES` funzioni `h(x) = (a·x + b) mod BIG_PRIME`, con `a`, `b` generati da `random.Random(SEED)`; per ciascuna si prende il minimo sulle tegole distinte.
6. **Firma**: concatenazione dei valori MinHash, ciascuno con zeri iniziali fino a `H_CIFRE` cifre (8 con `BIG_PRIME = 37⁵ + 22 = 69343979`). La stringa è usata come chiave primaria (SQLite non ammette interi oltre 64 bit).
7. **Bande**: la firma è divisa in `NUM_BANDS` sottostringhe consecutive da `ROWS_PER_BAND` valori; ogni sottostringa è l'identificatore della banda.
8. **Scrittura**: inserimenti in batch (`INSERT OR IGNORE` + `executemany`) in un'unica transazione, con controllo delle chiavi esterne sospeso durante la scrittura.

## Parametri (`FUNZIONI.py`)

| Parametro | Valore | Significato |
| --- | --- | --- |
| `K` | 5 | Lunghezza delle tegole |
| `NUM_HASHES` | 300 | Valori MinHash per firma |
| `ROWS_PER_BAND` | 20 | MinHash per banda (`r`) |
| `NUM_BANDS` | 15 | Bande per firma (`b = NUM_HASHES / r`) |
| `MIN_DIM` | 200 | Dimensione minima (byte) del documento |
| `SEED` | 1 | Seme delle funzioni hash |
| `MAX_WORKERS` | 5 | Processi paralleli |
| `MAX_DOCS_PER_BATCH` | 500 | Documenti validi massimi estratti da ciascun file WET |
| `WET_FOLDER`, `DB_PATH`, `SCHEMA_PATH`, `LINGUE_FILE` | vedi file | Percorsi di input/output |

Con `r = 20` e `b = 15` la soglia di similarità approssimata `(1/b)^(1/r)` è circa **0,87**: la configurazione rileva soprattutto similarità molto elevate. Diminuire `r` (e aumentare `b`) abbassa la soglia ma genera più coppie candidate.

Parametri del download, in `download_dati.py`: `CRAWL_ID` (default `CC-MAIN-2025-05`), `N_FILES` (default 5), `OUTPUT_DIR` (default `dati_2025`).

**Configurazione attuale:** 5 file WET × 500 documenti = **2.500 documenti**.

> `FUNZIONI.py`, `POPOLAMENTO.py` e `OPERAZIONI.py` devono trovarsi nella stessa cartella e vanno lanciati da lì, perché i percorsi dei file sono relativi. Cambiando `NUM_HASHES`, `ROWS_PER_BAND`, `K` o `SEED` occorre ricreare il database.

## Schema del database

| Tabella | Chiave primaria | Note |
| --- | --- | --- |
| `FIRMA(f)` | `f` | Stringa di `NUM_HASHES × H_CIFRE` cifre |
| `DOCUMENTO(id, f)` | `id` (URI) | `f` → `FIRMA`; più documenti possono avere la stessa firma |
| `TEGOLA(t)` | `t` | |
| `BANDA(b)` | `b` | |
| `COMPARE(id, pos, t)` | `(id, pos)` | Tegola `t` alla posizione `pos` del documento `id` |
| `PARTECIPA(f, p, b)` | `(f, p)` | Banda `b` in posizione `p` della firma `f` |
| `COPPIA(doc1, doc2, j)` | `(doc1, doc2)` | `CHECK (doc1 < doc2)`; `j` = Jaccard stimato |

Indici: `idx_partecipa_b_p_f` su `PARTECIPA(b, p, f)` (ricerca delle firme che condividono una banda), `idx_coppia_j` su `COPPIA(j)`, `idx_coppia_doc2` su `COPPIA(doc2)`.

## Operazioni (`OPERAZIONI.py`)

Tutte accettano un parametro opzionale `conn`: se omesso aprono e chiudono una connessione propria; se fornito, la riutilizzano (utile nei cicli).

| Funzione | Descrizione |
| --- | --- |
| `inserisci_documento((id, testo))` | Calcola tegole, firma e bande e popola le tabelle. Non calcola le coppie. |
| `calcola_coppie_documento(id)` | Trova i documenti che condividono almeno una banda (stessa posizione) con `id`, stima `j` come frazione di MinHash concordanti e salva le coppie in `COPPIA`. |
| `calcola_coppie_da_bande_frequenti(bande_freq)` | Seleziona le bande presenti in più di `bande_freq` firme distinte e applica `calcola_coppie_documento` ai documenti coinvolti. |
| `recupera_coppie_sopra_soglia(s)` | Coppie con `j >= s`, ordinate per `j` decrescente. |
| `dati_documento(id)` | Firma del documento e coppie in cui compare. |
| `coppie_di_confronto_documento(id)` | Coppie di `COPPIA` in cui compare il documento. |
| `ricostruisci_documento(id)` | Testo normalizzato approssimato, concatenando le tegole in posizione multipla di 5. |

Il blocco `__main__` inserisce tre documenti di esempio e poi usa due URI reali del campione scaricato: per questi due casi serve il database popolato dal passo 2 con la stessa configurazione. Termina con `calcola_coppie_da_bande_frequenti(3)` sull'intera collezione.

## Confronto con il file system

`CONFRONTO.py` riproduce le stesse fasi di calcolo (importate da `FUNZIONI.py`) ma salva ogni "tabella" in un file di testo senza indici, quindi ogni interrogazione è una scansione completa. `run_confronto.py` genera un corpus sintetico (default: 50 famiglie × 5 quasi-duplicati + 50 documenti indipendenti) e stampa tempi, numero di coppie e spazio su disco delle due implementazioni. Sono misurati: popolamento, ricerca delle coppie candidate, coppie sopra soglia (`j >= 0.5`), ricostruzione e ricerca dati di un documento.

Il confronto isola il solo effetto di persistenza e indicizzazione: i tempi sono indicativi dell'ordine di grandezza del vantaggio, non della scala del campione reale.

## Output generati

| Percorso | Prodotto da |
| --- | --- |
| `dati_2025/*.warc.wet.gz` | `download_dati.py` |
| `collezione.db` (più `-wal`, `-shm`) | `POPOLAMENTO.py` |
| `dati_fs/` | `CONFRONTO.py` / `run_confronto.py` |

## Documentazione

Descrizione dettagliata di progettazione, scelta dei parametri e risultati: tesi allegata al progetto (`documento.docx`).
