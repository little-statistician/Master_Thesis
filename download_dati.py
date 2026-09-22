#scarica dal web i file compressi dei dati veri e propri e li mette in wet_file.

import requests
import gzip
import os
import time

# ── CONFIGURAZIONE ──────────────────────────────────────────
CRAWL_ID  = "CC-MAIN-2025-05"   # cambia con il crawl che ti serve
N_FILES   = 5                   # quanti file WET scaricare
OUTPUT_DIR = "dati_2025"        # cartella di destinazione
BASE_URL  = "https://data.commoncrawl.org"
# ────────────────────────────────────────────────────────────

os.makedirs(OUTPUT_DIR, exist_ok=True)

# 1. Scaricamento dell'indice dei percorsi WET
paths_url = f"{BASE_URL}/crawl-data/{CRAWL_ID}/wet.paths.gz"
print(f"Scarico indice da: {paths_url}")

response = requests.get(paths_url, stream=True)
response.raise_for_status() #se diverso da 200 non fa nulla

# 2. Decompressione e lettura dei percorsi
with gzip.open(response.raw, "rt") as f:
    paths = [line.strip() for line in f]

print(f"Trovati {len(paths)} file WET. Scarico i primi {N_FILES}...")

start_time = time.perf_counter()

# 3. Scaricamento dei file WET
for i, path in enumerate(paths[:N_FILES]):
    url = f"{BASE_URL}/{path}"
    filename = os.path.join(OUTPUT_DIR, os.path.basename(path))

    print(f"[{i+1}/{N_FILES}] {os.path.basename(path)}")

    with requests.get(url, stream=True) as r:
        r.raise_for_status()
        with open(filename, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):  # 1MB chunk
                f.write(chunk)

end_time = time.perf_counter()
elapsed_time = end_time - start_time

print(f"\nTempo di esecuzione: {elapsed_time:.4f} secondi")
print("Download completato!")