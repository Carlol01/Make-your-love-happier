# Make-your-love-happier

> Notifiche sul ciclo della tua ragazza... meno litigi, più cioccolato 🍫

_(pacchetto Python: `cycle_notifier`)_

Promemoria gentili per il ciclo mestruale: legge i tuoi dati da calendario o app, **calcola in locale** la prossima data prevista e avvisa, **solo con il loro consenso**, le persone che hai scelto (per esempio il partner) qualche giorno prima, via email e con un calendario in abbonamento. Gira gratis su GitHub Actions, senza server.

## Cos'è

- Un workflow giornaliero (GitHub Actions) legge le fonti, aggiorna lo storico in `data/` e calcola la previsione.
- Invia email di preavviso (di norma 3 e 2 giorni prima) ai contatti che hanno dato il consenso.
- Pubblica un feed calendario `.ics` in abbonamento (iPhone, Android, Google Calendar).
- Offre una CLI, un server MCP per Claude (Desktop e Code) e un piccolo sito statico in italiano con guide e strumenti locali.
- I dati restano tuoi: nessun servizio terzo, a parte GitHub e il provider email che scegli.

## ⚠️ Avvertenze

- **Non è un dispositivo medico** né un metodo contraccettivo. Le previsioni sono stime statistiche e possono sbagliare di diversi giorni, soprattutto con cicli irregolari.
- **Consenso**: non inviare mai nulla a qualcuno che non l'ha chiesto o accettato. Il programma invia solo a contatti con `consent.given = true` e `active = true`. Ogni email spiega come smettere di riceverla.
- **Dati sensibili**: lo storico del ciclo è un dato sanitario. Tieni il repository **privato** e valuta la cifratura (`CYCLES_KEY`).

## Requisiti

- Un account GitHub e un repository (copia o fork di questo, **privato**).
- Python 3.12 per l'uso locale e i test.
- Un provider email: SMTP (qualsiasi) oppure [Resend](https://resend.com).
- **Attenzione a GitHub Pages**: sui repository privati Pages richiede un piano GitHub Pro, Team o Enterprise, e **il sito pubblicato è PUBBLICO** anche se il repository è privato. Per questo il sito (`site/`) non contiene alcun dato personale. Con il piano Free puoi: usare il feed in modalità `gist` (predefinita, non serve Pages), tenere un secondo repository pubblico solo per il sito, oppure leggere le guide in locale aprendo `site/index.html`.

## Setup

1. **Repository**: crea il tuo repository privato con questo codice (ad esempio `Carlol01/make-your-love-happier`) e abilita Actions.
2. **Configurazione**: modifica `config/config.toml` (nome mostrato, preavvisi, titolo neutro degli eventi, fonti attive).
3. **Contatti**: copia `config/contacts.example.json` in `config/contacts.local.json` (ignorato da git), inserisci i tuoi contatti e carica il secret:
   ```bash
   gh secret set CONTACTS_JSON < config/contacts.local.json
   ```
   Senza `consent.given: true` nessun promemoria viene inviato.
4. **Provider email**: per SMTP imposta `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` (e facoltativamente `SMTP_REPLY_TO`); per Resend imposta `RESEND_API_KEY`, `RESEND_FROM` e la variabile `EMAIL_PROVIDER=resend` (o `email_provider = "resend"` in `config.toml`).
5. **Feed calendario** (`FEED_MODE`):
   - `gist` (predefinito, va bene col piano Free): crea un **gist segreto** con un file `cycle.ics`, un token con permesso *gist* e imposta i secret `GIST_TOKEN` e `GIST_ID`. Gli iscritti si abbonano all'indirizzo *raw* del gist.
   - `pages`: il feed è pubblicato su `/f/<FEED_TOKEN>/cycle.ics` (imposta il secret `FEED_TOKEN`, genera un valore con `python -m cycle_notifier ics --new-token`). Vedi l'avvertenza su Pages.
   - `none`: nessuna pubblicazione (file locale in `build/cycle.ics`).
6. **Fonti**: configura almeno una fonte (vedi sotto), per esempio il secret `ICS_URLS` del tuo Google Calendar.
7. **Prima prova**: da *Actions → Promemoria giornaliero → Run workflow* con **dry_run** attivo. Controlla il riepilogo del job (solo conteggi e stato).
8. **Inviti**: per ogni contatto, `python -m cycle_notifier invite <id>` invia la richiesta di consenso (risponde "sì"). Poi imposta `consent.given` a `true`, aggiorna `CONTACTS_JSON` e, se vuoi, `python -m cycle_notifier test-email <id>` per un messaggio di prova.

## Secret e variabili

| Nome | Tipo | Scopo |
| --- | --- | --- |
| `ICS_URLS` | secret | URL iCal segreti dei calendari (uno per riga; `webcal://` ok) |
| `CONTACTS_JSON` | secret | contatti con consenso (vedi `config/contacts.example.json`) |
| `SMTP_HOST` `SMTP_PORT` `SMTP_USER` `SMTP_PASSWORD` `SMTP_FROM` | secret | email via SMTP (465 SSL, 587 STARTTLS) |
| `SMTP_REPLY_TO` | secret (opz.) | indirizzo per le risposte e la disiscrizione |
| `RESEND_API_KEY` `RESEND_FROM` | secret | alternativa a SMTP |
| `GARMIN_TOKENS` | secret (opz.) | token Garmin (da `garmin-login`) |
| `GARMIN_EMAIL` `GARMIN_PASSWORD` | secret (opz.) | alternativa ai token (niente MFA) |
| `GIST_TOKEN` `GIST_ID` | secret | pubblicazione del feed in modalità `gist` |
| `FEED_TOKEN` | secret | percorso segreto del feed in modalità `pages` |
| `CYCLES_KEY` | secret (opz.) | chiave Fernet per cifrare `data/*.json` |
| `FEED_MODE` | variabile | `gist` (default), `pages` o `none` |
| `EMAIL_PROVIDER` | variabile (opz.) | `smtp` (default) o `resend` |
| `NOTIFY_DRY_RUN` | variabile (opz.) | `1` per non inviare nulla |
| `FEED_URL`, `SITE_URL` | variabile (opz.) | link da includere negli inviti |

In locale puoi mettere gli stessi nomi in un file `.env` (vedi `.env.example`, ignorato da git). Precedenza: variabili d'ambiente > `.env` > `config.toml` > valori predefiniti.

## Fonti e affidabilità

Nessuna app (Flo, Clue, Natural Cycles, Stardust, Period Tracker) offre un'API pubblica. Dove manca un'esportazione ufficiale il supporto è *best-effort*.

| Fonte | Come | Affidabilità |
| --- | --- | --- |
| Google Calendar / ICS | secret `ICS_URLS` | stabile |
| Apple Salute | `export.zip` manuale, oppure Scorciatoia iOS | stabile (manuale) |
| Scorciatoia iOS | automazione giornaliera → `repository_dispatch` | best-effort |
| Android Health Connect | solo esportazione manuale (nessuna API cloud) | non ufficiale |
| Garmin | libreria non ufficiale `garminconnect` | non ufficiale, può rompersi |
| Clue, Flo, Natural Cycles | esportazione dati | best-effort |
| Stardust, Period Tracker | parser tollerante | best-effort |
| CSV / JSON generico | formato semplice | stabile |

Le guide passo-passo sono nel sito (`site/guide/`) e i formati in [docs/formati.md](docs/formati.md). Per importare un file: `python -m cycle_notifier sync --file export.zip` oppure copialo in `data/imports/` (viene letto una sola volta).

## Notifiche e calendario

- **Email**: preavviso a 3 e 2 giorni (configurabile per contatto), con file `ciclo.ics` allegato.
- **iPhone**: *Impostazioni → Calendario → Account → Aggiungi account → Altro → Aggiungi calendario sottoscritto*. Disattiva **"Rimuovi avvisi"**, altrimenti gli allarmi del feed vengono ignorati.
- **Android**: usa **ICSx⁵**, che rispetta gli allarmi (VALARM).
- **Google Calendar** ("Da URL") ignora gli avvisi del feed e si aggiorna ogni 12-24 ore: per questo il feed contiene anche eventi "Promemoria: tra 3 giorni…" e c'è sempre l'email.
- Titolo evento neutro e configurabile (`feed.event_title`), solo le prossime 1-3 date, descrizioni minime.

## CLI

```bash
python -m cycle_notifier run [--dry-run] [--today AAAA-MM-GG] [--no-publish]
python -m cycle_notifier sync [--source ics|imports|garmin] [--file PERCORSO] [--dry-run]
python -m cycle_notifier predict [--count 3] [--today ...] [--json]
python -m cycle_notifier preview [--contact ID] [--offset 3] [--lang it|en] [--today ...]
python -m cycle_notifier ics [--out FILE] [--publish] [--new-token]
python -m cycle_notifier add-period 2026-10-24 [2026-10-28]
python -m cycle_notifier exclude 2026-10-25 2026-10-26
python -m cycle_notifier invite ID        # richiesta di consenso
python -m cycle_notifier test-email ID    # messaggio [TEST]
python -m cycle_notifier ingest-dispatch  # usato dal workflow
python -m cycle_notifier garmin-login     # token Garmin (gestisce MFA)
python -m cycle_notifier encrypt [--generate-key] | decrypt
```

Codici di uscita: `0` ok, `1` invio/pubblicazione parzialmente fallito, `2` errore di configurazione o di utilizzo, `3` tutte le fonti hanno fallito e non ci sono dati salvati.

## Server MCP (Claude)

Strumenti: `get_cycle_status`, `predict_next_period`, `list_cycles`, `add_period`, `sync_sources`, `list_contacts` (email mascherate), `add_contact`, `send_test_notification`, `preview_message`, più la risorsa `cycle://status`.

**Claude Desktop** (`claude_desktop_config.json`):

```json
{"mcpServers":{"cycle-notifier":{"command":"uv","args":["run","--directory","/percorso/cycle-notifier","--extra","garmin","python","-m","cycle_notifier.mcp_server"],"env":{"CYCLE_NOTIFIER_HOME":"/percorso/cycle-notifier"}}}}
```

**Claude Code**:

```bash
claude mcp add cycle-notifier -- uv run --directory /percorso/cycle-notifier python -m cycle_notifier.mcp_server
```

`add_contact` scrive in `config/contacts.local.json` e ti ricorda di aggiornare il secret con `gh secret set CONTACTS_JSON < config/contacts.local.json`. `add_period(commit=True)` esegue commit e push solo se esiste un remote.

## Privacy e sicurezza

- Il sito è statico e **pubblico**, con `noindex`, nessuno script o font esterno e una CSP restrittiva; non contiene dati personali. Convertitore e dashboard lavorano nel browser, senza upload.
- Lo storico (`data/cycles.json`) sta nel repository: tienilo **privato**. Con `CYCLES_KEY` (Fernet) i file diventano `*.json.enc` e il programma rifiuta di scrivere in chiaro se la chiave è impostata.
- Gli indirizzi email sono solo nel secret `CONTACTS_JSON` (o in `contacts.local.json`, ignorato da git). `state.json` salva solo gli identificativi dei contatti. Il riepilogo del job riporta solo conteggi e stato, mai date o email.
- Gli export grezzi (`export.zip`, `*.cluedata`, ...) sono ignorati da git: non committarli.
- **L'URL del feed è l'unica protezione**: chi lo possiede può leggerlo. Non pubblicarlo, non incollarlo in chat pubbliche; se circola, ruotalo (`ics --new-token` per `pages`, nuovo gist per `gist`).
- Mitigazioni: titoli neutri e configurabili, descrizioni minime, solo le prossime 1-3 previsioni.

## Limitazioni oneste

- **Nessuna API pubblica** per Flo, Clue, Natural Cycles, Stardust, Period Tracker: si importano esportazioni manuali e i formati non sono documentati, quindi il supporto è *best-effort* e può smettere di funzionare.
- **Garmin non è ufficiale**: la libreria imita l'app, può rompersi o violare i termini del servizio; i token scadono.
- **Health Connect**: solo esportazione manuale; i nomi delle tabelle del database non sono ufficiali.
- **Apple Salute** richiede una Scorciatoia (automatica ma da costruire a mano) o l'esportazione manuale.
- **GitHub Actions**: gli orari `cron` sono in UTC e possono slittare; dopo 60 giorni di inattività GitHub disattiva i workflow pianificati (i commit automatici dei dati aiutano, ma controlla). Un secondo orario di recupero evita invii mancati, senza duplicati.
- **Calendari**: l'aggiornamento dei feed in abbonamento non è istantaneo e non tutti i client rispettano gli avvisi (Google li ignora).
- **Precisione**: con cicli irregolari o pochi dati l'errore può essere di molti giorni; la confidenza (alta/media/bassa) è indicata nei messaggi.
- **Eventi ICS ricorrenti** non sono espansi.
- Il feed è protetto solo dal suo indirizzo segreto; GitHub Pages su repository privato richiede un piano a pagamento e il sito resta pubblico.

## Sviluppo e test

```bash
python3.12 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,crypto]"
ruff check .
pytest -q
```

I test sono offline e usano solo fixture sintetiche. Dettagli in [docs/sviluppo.md](docs/sviluppo.md); piano di implementazione in [docs/PLAN.md](docs/PLAN.md).

## Licenza

MIT, vedi [LICENSE](LICENSE).
