# Sviluppo e test

## Ambiente

```bash
python3.12 -m venv .venv
. .venv/bin/activate
pip install -e ".[dev,crypto]"     # aggiungi ".[garmin]" solo se ti serve l'accesso Garmin
ruff check .
pytest -q
```

I test sono completamente offline e usano solo dati **sintetici** (`tests/fixtures/`); l'adattatore
Garmin usa un client finto, quindi `garminconnect` non è necessario. Gli archivi ZIP di Apple Salute
e Health Connect vengono costruiti in `conftest.py` a partire dall'XML e da `schema.sql`.

## Architettura

- Tutte le funzioni ricevono `today: date` (fuso Europe/Rome) per essere deterministiche.
- `models.py` dataclass immutabili; `config.py` (env > .env > config.toml > default);
  `storage.py` scrittura atomica e cifratura Fernet opzionale.
- `sources/` adattatori (mai eccezioni, errori in `SourceResult.error`) + registro con autorilevamento.
- `merge.py` unisce periodi e giorni di flusso; `predictor.py` calcola la previsione;
  `scheduler.py` decide gli invii; `messages.py`/`i18n.py` renderizzano IT/EN.
- `ics_feed.py` costruisce il feed; `publish.py` lo pubblica (gist/pages/none).
- `service.py` è condiviso da `cli.py` e `mcp_server.py`.

## Come aggiungere una sorgente

1. Crea `sources/nuova.py` con una classe che implementa `detect`, `parse` (e `fetch` se remota).
2. Registrala in `sources/registry.py`.
3. Aggiungi una fixture sintetica e `tests/test_sources_*.py`.
4. Documenta limiti e affidabilità in `docs/formati.md` e nelle guide del sito.

## Server MCP

```bash
python -m cycle_notifier.mcp_server        # stdio
```

Gli strumenti sono funzioni Python semplici (testate direttamente in `tests/test_mcp_server.py`).
Richiede `mcp>=1.2,<2` (il pacchetto 2.x ha rinominato `FastMCP`).

## Integrazione continua

`ci.yml` esegue `ruff check .` e `pytest -q` a ogni push (esclusi i commit che toccano solo `data/`).
Non usa segreti.
