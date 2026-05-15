# KataSymbol E10 — client Python

Client Python autonomo per pilotare la stampante BLE per etichette termiche
**Katasymbol E10** (`printerType=15`, famiglia firmware T15) da Mac o Linux,
senza l'app ufficiale Android.

Il protocollo è stato ricavato per reverse engineering dell'app
`com.supvan.katasymbol` v1.4.21 e verificato byte-per-byte su hardware reale
(unit `T0131F2408286248`).

> Progetto non ufficiale. Nessuna affiliazione con Supvan / Katasymbol.

## Cosa fa

- Discovery BLE filtrato sui seriali E10 noti (allowlist di 75 nomi)
- Lettura registri stato `MSTA` / `FSTA` (busy, cover open, label end, …)
- Stampa di immagini PNG/JPEG o di testo renderizzato al volo
- Cornice opzionale intorno al testo (`--box`)
- Concentrazione 1–7 e copie multiple
- Pipeline raster → pre-LZMA buffer → compressione LZMA-Alone → trasferimento
  DMA in chunk da 506 byte con envelope a 4×128 byte

## Hardware supportato

- **Katasymbol E10** (etichette termiche dirette, BLE only)
- Testa 96 dot (203 dpi), 12 byte/colonna
- Concentrazione 1–7, copie 1–100
- Firmware T15 / Series 2

I 75 seriali noti sono nell'allowlist di `katasym/constants.py`. Se la tua
stampante ha un seriale fuori lista la scan non la mostrerà — passa
`--all` a `katasym scan` per vederla comunque e usa l'indirizzo manualmente.

## Installazione

### Con [uv](https://github.com/astral-sh/uv) (consigliato)

```bash
git clone https://github.com/Giorgiofox/KataSymbol_E10_Python.git
cd KataSymbol_E10_Python
uv sync
```

### Con pip

```bash
git clone https://github.com/Giorgiofox/KataSymbol_E10_Python.git
cd KataSymbol_E10_Python
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Dipendenze runtime: `bleak >= 0.22`, `pillow >= 10`. Python ≥ 3.10.

## Uso

### Discovery

```bash
uv run katasym scan
```

Mostra tutte le E10 raggiungibili con RSSI. Esempio output:

```
  6C5A5C1B-1B17-DB3B-626B-3ABAD6C3A5AB   -46 dBm  E10 T0131       raw='T0131F2408286248'
```

Su macOS l'indirizzo è uno UUID di CoreBluetooth, non un MAC reale.
Su Linux è un MAC standard.

### Stato stampante

```bash
uv run katasym status
```

L'indirizzo è opzionale: se omesso, viene fatto uno scan rapido e usata la
prima E10 trovata. Vale per tutti i comandi.

Per puntare a una stampante specifica:

```bash
uv run katasym status --address 6C5A5C1B-1B17-DB3B-626B-3ABAD6C3A5AB
```

### Stampa di testo

```bash
uv run katasym print --text "Ciao mondo"
uv run katasym print --text "Ciao mondo" --concentration 7 --copies 2
uv run katasym print --text "Ciao mondo" --box
```

Opzioni rilevanti:

| Flag | Default | Significato |
|---|---|---|
| `--text "..."` | — | testo da renderizzare (alternativo a `--image`) |
| `--image FILE` | — | percorso PNG / JPEG |
| `--font-size N` | 56 | dimensione font per `--text` |
| `--concentration N` | 4 | densità testa termica 1–7 (più alta = più scuro) |
| `--copies N` | 1 | numero di copie |
| `--threshold N` | 125 | soglia per binarizzare il bitmap (0–255) |
| `--box` | off | cornice rettangolare intorno al testo |
| `--address ADDR` | auto | indirizzo BLE; auto-scan se assente |

### Stampa di immagini

```bash
uv run katasym print --image label.png --concentration 6
```

L'immagine viene centrata su un canvas alto 96 dot (= altezza testa);
la larghezza del canvas determina la lunghezza dell'etichetta stampata.
Per risultati prevedibili, fornire un PNG già alto 96 px.

### Diagnostica BLE

```bash
uv run katasym diag
```

Esegue un dump completo di servizi e caratteristiche GATT, si iscrive a
tutte le caratteristiche notify e prova inquiry con vari opcode (`0x11`,
`0x13`, `0xC5`) su tutte le caratteristiche write. Utile se la stampante
non risponde: aiuta a capire dove il firmware ha cambiato qualcosa.

## Esempio programmatico

```python
import asyncio
from PIL import Image
from katasym.ble import E10Connection, discover
from katasym.protocol import E10Printer

async def main():
    devs = await discover(timeout=6.0)
    addr = devs[0].address
    img = Image.open("label.png")
    async with E10Connection(addr) as conn:
        printer = E10Printer(conn)
        await printer.print_image(img, concentration=6, copies=1)

asyncio.run(main())
```

Vedi `examples/print_text.py` per uno script completo.

## Architettura del client

```
katasym/
  constants.py   Opcode, UUID GATT, parametri E10, lista seriali
  frame.py       Builder dei frame comando (16 byte) + chunk DMA (506 byte)
                 + envelope outer 512 byte + split BLE 4×128
  raster.py      PIL bitmap → stream 1bpp column-major (LSB = top)
  page.py        Pre-LZMA buffer header + PAGE_REG_BITS encoding
  compress.py    Wrapper LZMA-Alone con parametri (dict 8192, lc=3, pb=2, …)
  status.py      Decoder MSTA / FSTA
  ble.py         Trasporto bleak (scan, connect, write, notify queue)
  protocol.py    Macchina a stati di stampa end-to-end
  cli.py         CLI argparse (scan / status / diag / print)
```

## Note di protocollo

- **Servizio GATT**: `0000e0ff-3c17-d293-8e48-14fe2e4da212`
- **Write char**: `0000ffe9-…` (write + write-without-response)
- **Notify char**: `0000ffe1-…` (notify + write)
- **MTU**: 240 (negoziato; macOS può andare più basso)
- **Frame comando**: 16 byte fissi, `7E 5A LL 00 10 01 AA OP CS_LE16 [param 6B]`
- **Densità**: opcode `0xC9`, valore = `int(((conc-1)/10 + 0.8) * 100)` →
  80/90/100/110/120/130/140 per concentrazione 1–7
- **Start print**: opcode `0x13`
- **Bulk transfer**: opcode `0x5C` con `[page_size LE16][num_chunks LE16]`,
  seguito da N chunk DMA di 506 byte ciascuno (header `AA BB cs idx tot` +
  500 byte LZMA)
- **Envelope chunk per BLE**: ogni chunk DMA viene incapsulato in 512 byte
  `7E 5A FC 01 10 02 + 506B` e splittato in 4 BLE write da 128 byte con
  50 ms di delay
- **Buf full**: opcode `0x10` dopo l'ultimo chunk

LZMA stream è in formato `.lzma` (LZMA-Alone): 5 byte properties header +
8 byte LE64 size + payload. Parametri: `dict_size=8192`, `lc=3`, `lp=0`,
`pb=2`, `nice_len=128`.

## Limiti noti

- Testato solo su `T0131F2408286248` (firmware Series 2). Altri sub-modelli
  potrebbero richiedere tuning di `dict_size`, `mat_shift` o opcode.
- Su macOS gli indirizzi sono UUID CoreBluetooth — rotano nel tempo; basta
  ri-scannerizzare.
- Stampa di immagini molto larghe (> 332 colonne) non testata: il codice
  segue un path single-frame e dovrebbe funzionare, ma manca conferma.
- Auth challenge opzionali (`CMD_READ_RANDOM = 0xD5`,
  `CMD_VERIFY_RANDOM = 0xD6`) non implementati — non sono necessari sulla
  unit di test, ma esistono in altre revisioni firmware.

## Reverse engineering — credits

Il protocollo è stato ricavato decompilando con
[jadx](https://github.com/skylot/jadx) l'app Android `com.supvan.katasymbol`
v1.4.21 estratta da APKPure. Il riferimento Java principale è
`com/fhit/app_iprinter/communication/print/T15Print.java`.

Tutte le scelte di byte ordering, lunghezza frame, checksum e parametri LZMA
nel codice riportano il riferimento alla riga Java corrispondente nei
commenti.

## Licenza

MIT — vedi [`LICENSE`](LICENSE).

Questo client è materiale di reverse engineering a scopo di interoperabilità
con hardware acquistato legalmente. Non sono inclusi né binari, né asset, né
codice originale dell'app o del firmware.
