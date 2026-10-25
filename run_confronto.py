"""
run_confronto.py

Esegue due run sullo STESSO corpus sintetico:
  (A) con SGBD  -> popolamento tramite POPOLAMENTO.py, operazioni tramite run3_OPERAZIONI.py
  (B) senza SGBD -> popolamento e operazioni tramite CONFRONTO.py (solo file system)

e misura le differenze più importanti: tempo di popolamento, tempo delle
operazioni di interrogazione, spazio occupato su disco.

NOTA: in questo ambiente l'accesso a data.commoncrawl.org non è consentito
dalla rete sandbox, quindi al posto di download_dati.py + acquisizione da
file WET reali viene generato un corpus sintetico ma realistico (con
quasi-duplicati), passato direttamente a POPOLAMENTO.popola_database() e a
CONFRONTO.popola_filesystem(). Tutto il resto del codice (FUNZIONI.py,
POPOLAMENTO.py, run3_OPERAZIONI.py, CONFRONTO.py) è quello originale, non
modificato per il benchmark.
"""

import os
import random
import time
import sqlite3

import FUNZIONI as F
import POPOLAMENTO as P
import OPERAZIONI as O
import CONFRONTO as C


# ─────────────────────────────────────────────────────────────────────
# 1. GENERAZIONE DI UN CORPUS SINTETICO (sostituisce download + acquisizione)
# ─────────────────────────────────────────────────────────────────────

def genera_corpus(n_famiglie=80, copie_per_famiglia=5, n_singoli=100, seed=1):
    """
    Genera un corpus sintetico di documenti normalizzati (stesso alfabeto
    usato da normalizzazione_testo: a-z, 0-9, spazio), con alcune famiglie
    di quasi-duplicati (per generare coppie candidate reali) e alcuni
    documenti totalmente indipendenti.
    n_famiglie = numero di famiglie di quasi-duplicati
    copie_per_famiglia = numero di documenti per famiglia (almeno 2), dove i primo documento è l'oiginale e gli altri alcune sue varianti
    n_singoli = numero di documenti indipendenti (non duplicati)

    documenti totali = n_famiglie * copie_per_famiglia + n_singoli
    """
    rnd = random.Random(seed)
    vocabolario = [
        "".join(rnd.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(rnd.randint(3, 9)))
        for _ in range(800)
    ]

    def testo_casuale(n_parole):
        parole = [rnd.choice(vocabolario) for _ in range(n_parole)]
        return F.normalizzazione_testo(" ".join(parole))

    def variante(testo, intensita=0.12):
        parole = testo.split(" ")
        for i in range(len(parole)):
            if rnd.random() < intensita:
                parole[i] = rnd.choice(vocabolario)
        return " ".join(parole)

    documenti = []
    contatore = 0

    for fam in range(n_famiglie):
        base = testo_casuale(rnd.randint(60, 120))
        for copia in range(copie_per_famiglia):
            contatore += 1
            uri = f"http://esempio.test/fam{fam:03d}/doc{copia:02d}"
            testo = base if copia == 0 else variante(base)
            documenti.append((uri, testo))

    for i in range(n_singoli):
        contatore += 1
        uri = f"http://esempio.test/singolo/doc{i:03d}"
        documenti.append((uri, testo_casuale(rnd.randint(60, 120))))

    rnd.shuffle(documenti)
    return documenti


# ─────────────────────────────────────────────────────────────────────
# 2. UTILITA' DI SUPPORTO PER IL BENCHMARK
# ─────────────────────────────────────────────────────────────────────

def reset_ambiente():
    """Ripulisce database, file system e cartella di lavoro tra le run."""
    if os.path.exists(F.DB_PATH):
        os.remove(F.DB_PATH)
    for estensione in ("-wal", "-shm"):
        p = F.DB_PATH + estensione
        if os.path.exists(p):
            os.remove(p)
    if os.path.exists(C.FS_FOLDER):
        for nome in os.listdir(C.FS_FOLDER):
            os.remove(os.path.join(C.FS_FOLDER, nome))


def dimensione_db():
    totale = 0
    for estensione in ("", "-wal", "-shm"):
        p = F.DB_PATH + estensione
        if os.path.exists(p):
            totale += os.path.getsize(p)
    return totale


def cronometra(funzione, *args, **kwargs):
    inizio = time.perf_counter()
    risultato = funzione(*args, **kwargs)
    return risultato, time.perf_counter() - inizio


# ─────────────────────────────────────────────────────────────────────
# 3. RUN (A): CON SGBD -> POPOLAMENTO.py + run3_OPERAZIONI.py
# ─────────────────────────────────────────────────────────────────────

def run_con_sgbd(documenti):
    reset_ambiente()

    # popolamento: stesso identico codice di POPOLAMENTO.py.
    # Sostituiamo solo l'origine dei documenti (corpus sintetico invece
    # che file WET), lasciando invariata ogni altra fase.
    F.acquisisci_documenti = lambda folder, lingue_file: documenti
    _, t_popolamento = cronometra(P.popola_database)

    conn = sqlite3.connect(F.DB_PATH)

    # operazione 1: individuazione di TUTTE le coppie candidate a partire
    # dalle bande condivise da almeno una firma (equivalente a "tutte le
    # coppie con almeno una banda in comune")
    (_, coppie_trovate), t_coppie = cronometra(O.calcola_coppie_da_bande_frequenti, 0, conn)

    # operazione 2: recupero delle coppie sopra una soglia di similarita'
    (_, t_soglia_dummy) = (None, 0)
    risultati_soglia, t_soglia = cronometra(O.recupera_coppie_sopra_soglia, 0.5, conn)

    # operazione 3: ricostruzione del contenuto di un documento campione
    id_campione = documenti[0][0]
    testo_ricostruito, t_ricostruzione = cronometra(O.ricostruisci_documento, id_campione, conn)

    # operazione 4: ricerca dati di un documento (firma + coppie)
    _, t_dati_doc = cronometra(O.dati_documento, id_campione, conn)

    conn.close()

    return {
        "t_popolamento": t_popolamento,
        "t_coppie": t_coppie,
        "n_coppie": len(coppie_trovate),
        "t_soglia": t_soglia,
        "n_soglia": len(risultati_soglia),
        "t_ricostruzione": t_ricostruzione,
        "t_dati_doc": t_dati_doc,
        "dimensione_disco": dimensione_db(),
    }


# ─────────────────────────────────────────────────────────────────────
# 4. RUN (B): SENZA SGBD -> CONFRONTO.py (solo file system)
# ─────────────────────────────────────────────────────────────────────

def run_senza_sgbd(documenti):
    reset_ambiente()

    t_popolamento = C.popola_filesystem(documenti)

    (_, coppie_trovate), t_coppie = cronometra(C.calcola_coppie_da_bande_frequenti, 0)

    risultati_soglia, t_soglia = cronometra(C.recupera_coppie_sopra_soglia, 0.5)

    id_campione = documenti[0][0]
    testo_ricostruito, t_ricostruzione = cronometra(C.ricostruisci_documento, id_campione)

    _, t_dati_doc = cronometra(C.dati_documento, id_campione)

    return {
        "t_popolamento": t_popolamento,
        "t_coppie": t_coppie,
        "n_coppie": len(coppie_trovate),
        "t_soglia": t_soglia,
        "n_soglia": len(risultati_soglia),
        "t_ricostruzione": t_ricostruzione,
        "t_dati_doc": t_dati_doc,
        "dimensione_disco": C.dimensione_totale_fs(),
    }


# ─────────────────────────────────────────────────────────────────────
# 5. ESECUZIONE E CONFRONTO
# ─────────────────────────────────────────────────────────────────────

def stampa_confronto(sgbd, fs):
    def riga(etichetta, chiave, unita="s", fmt="{:.4f}"):
        v1 = sgbd[chiave]
        v2 = fs[chiave]
        rapporto = (v2 / v1) if v1 > 0 else float("inf")
        print(f"{etichetta:38s} | {fmt.format(v1):>12s} {unita} | {fmt.format(v2):>12s} {unita} | "
              f"x{rapporto:6.1f}")

    print("\n" + "=" * 95)
    print(f"{'OPERAZIONE':38s} | {'CON SGBD':>14s} | {'SENZA SGBD (FS)':>14s} | FS/SGBD")
    print("=" * 95)
    riga("Popolamento (creazione+scrittura)", "t_popolamento")
    riga("Ricerca coppie candidate (LSH)", "t_coppie")
    riga("Coppie sopra soglia j>=0.5", "t_soglia")
    riga("Ricostruzione di un documento", "t_ricostruzione")
    riga("Ricerca dati di un documento", "t_dati_doc")
    print("-" * 95)
    print(f"{'Coppie candidate individuate':38s} | {sgbd['n_coppie']:>12d}   | {fs['n_coppie']:>12d}   |")
    print(f"{'Coppie con j>=0.5':38s} | {sgbd['n_soglia']:>12d}   | {fs['n_soglia']:>12d}   |")
    dim_sgbd_kb = sgbd["dimensione_disco"] / 1024
    dim_fs_kb = fs["dimensione_disco"] / 1024
    rapporto_dim = dim_fs_kb / dim_sgbd_kb if dim_sgbd_kb > 0 else float("inf")
    print(f"{'Spazio su disco (KB)':38s} | {dim_sgbd_kb:>12.1f}   | {dim_fs_kb:>12.1f}   | x{rapporto_dim:6.1f}")
    print("=" * 95)


if __name__ == "__main__":
    print("Generazione corpus sintetico...")
    documenti = genera_corpus(n_famiglie=80, copie_per_famiglia=5, n_singoli=100)
    print(f"Corpus generato: {len(documenti)} documenti "
          f"({80} famiglie di quasi-duplicati x 5 copie + {100} documenti singoli)\n")

    print(">>> RUN (A) - CON SGBD (POPOLAMENTO.py + run3_OPERAZIONI.py)")
    risultati_sgbd = run_con_sgbd(documenti)

    print("\n>>> RUN (B) - SENZA SGBD (CONFRONTO.py, solo file system)")
    risultati_fs = run_senza_sgbd(documenti)

    stampa_confronto(risultati_sgbd, risultati_fs)
