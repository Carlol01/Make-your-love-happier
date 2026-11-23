# Scorciatoia iOS per inviare i dati di Salute

Questa guida descrive come costruire (a mano) una Scorciatoia che legge il flusso
mestruale da Apple Salute e lo invia al repository tramite l'API GitHub.
**Non è fornito un file `.shortcut` firmato**: le Scorciatoie cambiano con le versioni di iOS,
quindi la procedura è documentata passo per passo ed è da considerare *best-effort*.

## Come funziona

1. La Scorciatoia legge gli ultimi 90 giorni di dati "Mestruazioni" da Salute.
2. Costruisce un JSON e lo invia con `POST` a
   `https://api.github.com/repos/Carlol01/make-your-love-happier/dispatches`.
3. GitHub avvia il workflow `daily.yml` (evento `repository_dispatch`, tipo `cycle-data`).
4. Il workflow esegue `python -m cycle_notifier ingest-dispatch`, che salva il payload in
   `data/imports/shortcut-<data-ora-UTC>.json`, poi lo integra nello storico e calcola le previsioni.

## Token GitHub

Crea un **fine-grained personal access token** limitato **solo a questo repository** con il permesso
*Contents: Read and write* (serve per `repository_dispatch`). Salvalo soltanto nella Scorciatoia.
Se lo perdi o sospetti una fuga, revocalo da GitHub e creane uno nuovo.

## Passi nella Scorciatoia

1. **Trova campioni di Salute**: tipo *Mestruazioni*, ordinati per data di inizio, ultimi 90 giorni.
2. **Ripeti con ciascun elemento**: crea un *Dizionario* con
   - `start`: data di inizio in formato ISO 8601,
   - `end`: data di fine in formato ISO 8601,
   - `flow`: `light`, `medium`, `heavy` o `unspecified`;
   aggiungilo a una variabile (elenco `samples`).
3. **Ottieni contenuto da URL**
   - URL: `https://api.github.com/repos/Carlol01/make-your-love-happier/dispatches`
   - Metodo: `POST`
   - Intestazioni: `Authorization: Bearer <IL_TUO_TOKEN>`, `Accept: application/vnd.github+json`
   - Corpo della richiesta: JSON con `event_type` = `cycle-data` e `client_payload` contenente `samples`.
4. **Automazione**: in *Automazione* crea un'automazione personale giornaliera (per esempio alle 07:30)
   che esegue la Scorciatoia con **Esegui immediatamente** attivo (nessuna richiesta di conferma).

## Formato del payload

```json
{
  "event_type": "cycle-data",
  "client_payload": {
    "source": "ios_shortcut",
    "generated_at": "2026-11-01T08:00:00Z",
    "samples": [
      { "start": "2026-10-24", "end": "2026-10-28", "flow": "medium" }
    ]
  }
}
```

`source` e `generated_at` sono facoltativi. Date future o precedenti al 2000 vengono scartate.

## Limiti

- Le automazioni iOS non sono garantite: se il telefono non esegue l'automazione, i dati arrivano al
  primo avvio riuscito.
- Il token ha permessi di scrittura: tienilo nella Scorciatoia e non in file condivisi.
- Il repository è bersaglio di `repository_dispatch` solo per chi possiede un token valido.
