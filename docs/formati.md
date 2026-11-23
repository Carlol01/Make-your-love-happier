# Formati di input supportati

Tutti i parser sono **tolleranti** e non lanciano mai eccezioni: gli errori finiscono in
`SourceResult.error` e un avviso nel report di sincronizzazione. Date nel futuro o precedenti al
2000 vengono scartate. Nessuna delle app elencate offre un'API pubblica: dove non esiste un formato
documentato, il supporto è *best-effort* e basato sul parser tollerante.

| Sorgente | Tipo | File / accesso | Affidabilità |
| --- | --- | --- | --- |
| Calendario ICS | remoto | secret `ICS_URLS` o file `.ics` | stabile (formato standard) |
| Apple Salute | file | `export.zip` / `export.xml` | stabile (formato Apple), manuale |
| Scorciatoia iOS | file | `data/imports/shortcut-*.json` | best-effort |
| Health Connect | file | export ZIP con database SQLite | non ufficiale (tabelle non documentate) |
| Garmin | remoto | `garminconnect` (extra), `GARMIN_TOKENS` | non ufficiale |
| Clue | file | `.cluedata` (JSON) | best-effort |
| Flo | file | export GDPR JSON | best-effort |
| Natural Cycles | file | CSV | best-effort |
| Stardust | file | qualsiasi JSON/CSV | best-effort (parser tollerante) |
| Period Tracker | file | CSV | best-effort (parser tollerante) |
| Generico | file | CSV / JSON | stabile (definito qui) |

## Autorilevamento

`sources/registry.py` legge i primi 64 KB (per gli ZIP, l'elenco dei file senza estrarli) e
l'estensione, chiede un punteggio 0-1 a ogni adattatore e sceglie il massimo. Sotto 0,5 si usa il
parser tollerante (`_tolerant.py`).

## Formato generico

CSV (date ISO o `gg/mm/aaaa`, secondo `date_order`):

```csv
start_date,end_date,note
2026-10-24,2026-10-28,
```

JSON (`end` può essere `null` se il periodo è in corso):

```json
{"periods": [{"start": "2026-10-24", "end": "2026-10-28"}]}
```

## Payload della Scorciatoia iOS

```json
{"source": "ios_shortcut", "generated_at": "2026-11-01T08:00:00Z",
 "samples": [{"start": "2026-10-24", "end": "2026-10-28", "flow": "medium"}]}
```

## Parser tollerante

- **JSON**: cammina ricorsivamente la struttura. Un oggetto con chiave di inizio
  (`start`, `start_date`, `startDate`, `period_start(_date)`, `begin`, ...) diventa un periodo, con
  fine opzionale. Un oggetto con una chiave giorno (`date`, `day`, ...) e un indicatore
  (chiave o tipo che corrisponde a `period|menstru|flow|bleed|ciclo`) diventa un giorno di flusso.
- **CSV**: delimitatore rilevato automaticamente, intestazioni normalizzate (minuscole, senza accenti)
  e tabella di alias (`inizio`, `fine`, `menstruation`, ...).
- **Date**: ISO, epoch (secondi o millisecondi), poi `dateutil` con `dayfirst` secondo `date_order`.

## Cosa NON è supportato

- Eventi ICS ricorrenti (RRULE): solo la prima occorrenza.
- File ZIP diversi da Apple Salute e Health Connect.
- Esportazioni cifrate o protette da password.

## Note sui singoli formati

- **Apple Salute**: si legge `HKCategoryTypeIdentifierMenstrualFlow`; i valori `None` sono saltati;
  `IntermenstrualBleeding` solo con `include_spotting`. L'XML è letto in streaming. File troppo grandi
  per essere committati: usa `sync --file` in locale o il convertitore del sito.
- **Health Connect**: il database viene aperto in sola lettura; le tabelle con `menstruation` nel nome
  sono scoperte a runtime e le colonne interpretate per nome (epoch in millisecondi, offset di fuso se
  presente). I nomi non sono ufficiali e possono cambiare.
- **Garmin**: usa la libreria non ufficiale `garminconnect`; può smettere di funzionare senza preavviso.
