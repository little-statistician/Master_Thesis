# Master_Thesis: Gestione e confronto di documenti Common Crawl

Progettazione e implementazione di una base di dati per l'individuazione su larga scala di documenti duplicati, o quasi duplicati, tramite firme MinHash e Locality-Sensitive Hashing, con backend SQLite. Comprende il download dati da Common Crawl, l'implementazione del DB e il confronto prestazionale con l'implementazione su File System.

Per eseguire il funzionamento completo del progetto, i programmi devono essere eseguiti nel seguente ordine:

1. `dowload_dati.py`
2. `POPOLAMENTO.py`
3. `OPERAZIONI.py`

Il file `FUNZIONI.py` contiene i parametri di configurazione e le funzioni utilizzate dagli altri programmi.

---

## Struttura dei file

| File                   | Descrizione                                                                                                                         |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| `dowload_dati.py`      | Scarica i dati da Common Crawl e crea la cartella contenente i file compressi.                                                      |
| `POPOLAMENTO.py`       | Decomprime i file scaricati, estrae i documenti e popola la base di dati.                                                           |
| `OPERAZIONI.py`        | Implementa ed esegue le operazioni previste sulla base di dati.                                                                     |
| `FUNZIONI.py`          | Contiene i parametri di configurazione e le funzioni utilizzate dagli altri programmi.                                              |
| `CONFRONTO.py`         | Confronta le prestazioni dell'implementazione basata sulla base di dati con un'implementazione analoga basata sul solo file system. |
| `Guida_al_codice.docx` | Contiene una spiegazione dettagliata del funzionamento dei diversi file e delle funzioni implementate.                              |

---

## Requisiti

È necessario disporre di:

* Python 3
* una connessione a Internet, necessaria per il download dei dati da Common Crawl;
* spazio sufficiente sul disco per i file scaricati, i documenti estratti e la base di dati.

Le eventuali librerie Python necessarie devono essere installate prima dell'esecuzione dei programmi.

---

## Esecuzione

### 1. Download dei dati

Per prima cosa eseguire:

```bash
python dowload_dati.py
```

Il programma crea una cartella dedicata e scarica al suo interno i file compressi contenenti i dati provenienti da Common Crawl.

I parametri utilizzati per il download sono definiti in `FUNZIONI.py`.

### 2. Popolamento della base di dati

Al termine del download, eseguire:

```bash
python POPOLAMENTO.py
```

Il programma:

1. decomprime i file scaricati;
2. estrae i documenti;
3. elabora i documenti;
4. popola la base di dati.

**Nota:** con la configurazione attuale, l'esecuzione di `POPOLAMENTO.py` richiede circa **20 minuti** sulla macchina utilizzata per lo sviluppo. Il tempo effettivo può variare in funzione delle caratteristiche del computer.

### 3. Esecuzione delle operazioni

Una volta completato il popolamento della base di dati, eseguire:

```bash
python OPERAZIONI.py
```

Il programma implementa ed esegue le operazioni previste dalla base di dati.

---

## Confronto delle prestazioni

Il file `CONFRONTO.py` permette di confrontare le prestazioni dell'implementazione basata sulla base di dati con un'implementazione analoga che utilizza esclusivamente il file system.

Per eseguire il confronto:

```bash
python CONFRONTO.py
```

Il programma esegue le operazioni previste dalle due implementazioni e restituisce i risultati del confronto delle prestazioni.

---

## Configurazione attuale

I principali parametri del progetto sono definiti nel file `FUNZIONI.py`.

Nella configurazione attuale, il programma è impostato per scaricare automaticamente **5.000 documenti**, selezionati dai primi **5 file** caricati sul sito di Common Crawl a gennaio 2025:

* 500 documenti dal primo file;
* 500 documenti dal secondo file;
* 500 documenti dal terzo file;
* 500 documenti dal quarto file;
* 500 documenti dal quinto file.

È possibile modificare questi parametri direttamente in `FUNZIONI.py`.

### MinHash

Le firme utilizzate per rappresentare i documenti sono costituite da:

* **300 MinHash**;
* suddivisi in **15 bande**.

Questi parametri sono stati scelti per individuare principalmente **similarità molto elevate** tra i documenti.

Anche questi valori possono essere modificati nel file `FUNZIONI.py`.

---

## Ordine di esecuzione

Per una prima esecuzione completa del progetto, utilizzare il seguente ordine:

```text
dowload_dati.py
       ↓
POPOLAMENTO.py
       ↓
OPERAZIONI.py
```

`CONFRONTO.py` può essere eseguito separatamente per effettuare il confronto delle prestazioni tra la soluzione basata sulla base di dati e quella basata sul file system.

---

## Documentazione

Per una descrizione più dettagliata del codice, delle funzioni implementate e del loro funzionamento, consultare:

**`Guida_al_codice.docx`**

Il documento contiene una spiegazione dei diversi file presenti nel progetto e delle modalità con cui sono state implementate le principali funzioni.
