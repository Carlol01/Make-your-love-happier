# cycle-notifier — implementation plan (by Opus)

## 1. Tech
- Python 3.12, pyproject.toml (hatchling), package `cycle_notifier`.
- Deps: icalendar, requests, python-dateutil, mcp (FastMCP), tzdata (win). Config TOML via tomllib, zoneinfo, sqlite3 stdlib.
- Extras: [garmin]=garminconnect, [crypto]=cryptography (Fernet), [dev]=pytest, ruff.
- Email: smtplib or Resend HTTP via requests. Own tiny .env parser in config.py.
- Site: plain HTML/CSS/vanilla JS, no build, deployed via actions/deploy-pages.
- All functions take injected `today: date` (Europe/Rome).
- README caveats: Pages on private repo needs Pro/Team/Enterprise and the site is PUBLIC (no personal data in it). Free plan: second public repo or read guides locally.
- ICS feed protected only by unguessable URL. FEED_MODE: `gist` (default, Free-plan OK, workflow PATCHes a secret gist, subscribe to gist raw URL) | `pages` (`/f/<FEED_TOKEN>/cycle.ics`, robots Disallow /f/) | `none`.
- Mitigations: neutral configurable event titles, minimal descriptions, only next 1–3 predicted events, token rotation `ics --new-token`.

## 2. File tree
```
cycle-notifier/
  pyproject.toml README.md(IT) LICENSE .gitignore .env.example
  config/config.toml config/contacts.example.json config/templates/README.md ({lang}/{name}.txt overrides)
  data/cycles.json data/state.json data/imports/.gitkeep
  cycle_notifier/
    __init__.py __main__.py cli.py config.py models.py storage.py merge.py predictor.py
    scheduler.py i18n.py messages.py ics_feed.py publish.py service.py mcp_server.py
    notify/{__init__,base,smtp,resend}.py
    sources/{__init__,base,registry,_tolerant,ics,apple_health,ios_shortcut,health_connect,garmin,clue,flo,natural_cycles,stardust,period_tracker_gp,generic}.py
  site/ index.html contatti.html privacy.html converti.html dashboard.html
        guide/{google-ics,apple-health,scorciatoia-ios,health-connect,garmin,flo,clue,natural-cycles,stardust,period-tracker,csv-generico}.html
        assets/{style.css,parsers.js,converter.js,dashboard.js} robots.txt .nojekyll
  shortcuts/README.md  docs/formati.md docs/sviluppo.md
  tests/ conftest.py fixtures/(ics, apple_health xml (zip built in conftest), shortcut, health_connect (db built in conftest from SQL) + csv, garmin json, clue new/old, flo json, nc csv, stardust csv, period_tracker csv, generic csv/json)
         test_predictor test_merge test_scheduler test_messages test_i18n test_ics_feed test_storage test_config test_notify test_publish test_sources_* test_tolerant test_registry test_cli test_service test_mcp_server
  .github/workflows/daily.yml pages.yml ci.yml
```
All fixtures synthetic.

## 3. Schemas
### config/config.toml
```toml
[user]
display_name = "Giulia"
timezone = "Europe/Rome"
default_lang = "it"
[prediction]
history_cycles = 6
min_cycle_days = 21
max_cycle_days = 45
min_period_days = 2
max_period_days = 10
default_cycle_days = 28
default_period_days = 5
stale_after_factor = 2.0
include_spotting = false
weighted = false
[notifications]
offsets_days = [3, 2]
channels = ["email"]
catch_up = false
min_days_between_same_offset = 15
email_provider = "smtp"   # smtp | resend
attach_ics = true
[feed]
mode = "gist"             # gist | pages | none (env FEED_MODE overrides)
event_title = "🌸 Ciclo previsto – {user}"
events_ahead = 2
reminder_events = true
alarm_time = "09:00"
[sources]
enabled = ["ics", "imports", "garmin"]
ics_keywords = ["ciclo", "mestruazioni", "period", "periodo", "🩸"]
date_order = "DMY"
delete_imports_after_ingest = false
```
### Contacts: secret CONTACTS_JSON (locally config/contacts.local.json, gitignored)
```json
[{"id":"marco","name":"Marco","email":"marco@example.com","lang":"it","channels":["email"],"offsets_days":[3,2],
  "consent":{"given":true,"date":"2026-11-20","method":"email reply"},"active":true}]
```
Never send unless consent.given && active (except invite/test to that single contact, labelled).
### data/cycles.json
```json
{"schema_version":1,"updated_at":"...","periods":[{"start":"2026-10-03","end":"2026-10-07","end_estimated":false,"sources":["clue","ics"],"manual":false,"note":null}],
 "excluded_days":[],"source_status":{"ics":{"last_sync":"...","periods":14,"error":null}},"ingested_imports":{"data/imports/x.cluedata":"sha256:..."}}
```
end inclusive, may be null if ongoing; sorted ascending.
### data/state.json
```json
{"schema_version":1,"last_run":"...","last_prediction":{"anchor":"2026-10-28","start":"2026-11-25","end":"2026-11-29","confidence":"high","computed_at":"..."},
 "feed":{"sequence":7,"last_hash":"sha256:...","published_at":"..."},
 "sent":{"2026-10-28|marco|3|email":{"sent_at":"...","predicted_start":"2026-11-25","contact":"marco","offset":3}}}
```
Contact ids only, never emails. Prune >180 days.
### Encryption (optional): if CYCLES_KEY (Fernet) set, use cycles.json.enc/state.json.enc; storage.migrate(); refuse plaintext save when key set.
### Generic import: CSV `start_date,end_date[,note]` (ISO or dd/mm/yyyy); JSON `{"periods":[{"start":..,"end":..|null}]}`; Shortcut payload `{"source":"ios_shortcut","generated_at":"…","samples":[{"start":"ISO","end":"ISO","flow":"medium"}]}`.

## 4. Modules
### models.py
Period(start, end|None, sources: frozenset, manual=False, end_estimated=False, note=None) frozen;
FlowDay(day, source, flow: light/medium/heavy/unspecified/spotting|None);
SourceResult(source, periods, flow_days, warnings, error=None);
Prediction(anchor, start, end, avg_cycle, avg_duration, sd_cycle, n_cycles, confidence high|medium|low|default, status upcoming|in_period|late|stale|no_data, days_until, window);
Contact(id,name,email,lang,channels,offsets_days,consent_given,active); Notification(contact, offset, channel, key, prediction).
### sources/base.py
SourceAdapter protocol: name, kind remote|file, detect(path, head)->0..1, parse(path, ctx)->SourceResult, fetch(ctx)->SourceResult. SourceContext(settings, today, tz, http session, since).
registry.autodetect: first 64KB + extension (list zip contents), highest score; <0.5 -> _tolerant. Adapters never raise; errors in SourceResult.error. Run fails only if all sources fail and no stored data.
### Adapters
- ics: secret ICS_URLS newline-separated; webcal:// -> https://; local files ok. SUMMARY keyword match case-insensitive, accent-stripped, word boundary. All-day DTEND exclusive -> -1 day. Timed -> local dates. Single-day events -> FlowDays. Skip UIDs ending `@cycle-notifier` (feedback loop). No RRULE expansion (warn).
- apple_health: export.zip (stream apple_health_export/export.xml) or export.xml; iterparse + elem.clear(); Record type HKCategoryTypeIdentifierMenstrualFlow, value HKCategoryValueMenstrualFlow{Unspecified|Light|Medium|Heavy|None}; skip None; startDate fmt "%Y-%m-%d %H:%M:%S %z" -> local date -> FlowDay. Ignore IntermenstrualBleeding unless include_spotting. Too big to commit: run sync --file locally or use converti.html.
- ios_shortcut: data/imports/shortcut-*.json; `ingest-dispatch` reads $GITHUB_EVENT_PATH client_payload and writes data/imports/shortcut-<utc-ts>.json.
- health_connect: Android 14+ export zip containing SQLite db; open read-only (uri mode=ro); discover tables matching /menstruation/ via sqlite_master + PRAGMA table_info regex (e.g. menstruation_period_record_table(start_time,end_time), menstruation_flow_record_table(time, flow)); epoch ms; zone offset cols if present. Names unofficial. CSVs via _tolerant. Docs: no cloud API.
- garmin (extra): garminconnect.Garmin(); prefer GARMIN_TOKENS secret (base64 of garth token dir from `garmin-login` locally, handles MFA); fallback GARMIN_EMAIL/PASSWORD. get_menstrual_calendar_data(start,end) last 365d, else get_menstrual_data_for_date. Tolerant mapping (start date keys + periodLength). Risks documented. Injectable client for tests.
- clue: .cluedata JSON; new format list of {"type":"period","date":..,"value":{"option":..}}; old {"data":[{"day":..,"period":..}]}; fallback _tolerant.
- flo: GDPR JSON, operationalData.cycles[*].period_start_date/period_end_date; fallback _tolerant.
- natural_cycles: CSV date column + Menstruation column (MENSTRUATION/SPOTTING/true) via aliases.
- stardust / period_tracker_gp: thin, delegate to _tolerant, detect by filename/headers; best-effort.
- generic: formats from section 3.
- _tolerant: JSON recursive walker (start keys start/start_date/startDate/period_start(_date)/begin, optional end keys, or date/day + flow/period indicator matching period|menstru|flow|bleed|ciclo); CSV Sniffer + normalized headers + alias table; dates ISO, epoch, then dateutil dayfirst per date_order; drop future or <2000.
### merge.py
1 expand periods to days (missing end -> start+default-1, end_estimated, unless ongoing current cycle); 2 add FlowDays (filter spotting); 3 subtract excluded_days; 4 cluster with gap_tolerance=1, sources union; 5 manual periods win over overlapping clusters; 6 drop clusters > max_period_days*1.5 w/ warning; 7 merge with stored history (union, never delete except via exclusions).
### predictor.py
```
starts sorted; lengths consecutive diffs; valid 21..45; recent last 6
avg_cycle = mean(recent) or 28; sd = pstdev if >=2 else None
durations of real-end periods 2..10, last 6; avg_dur round(mean) or 5
anchor = last start; no periods -> no_data (no alerts)
next_start = anchor + round(avg_cycle)
status: in_period if anchor<=today<=anchor+avg_dur-1 (or last.end>=today); late if next_start<today; stale if today-anchor > factor*avg; else upcoming
confidence: high n>=6&sd<=2; medium n>=3&sd<=4; low n>=1; default n==0
window = next_start ± ceil(sd or 3); predict_many(k)
```
Optional weighted mean (weights 1..n) behind prediction.weighted.
### scheduler.py
due(prediction, contacts, state, settings, today): only status upcoming; for active+consented contacts, each offset (contact or default), each channel: hit if days_until==off; catch_up option (smallest unsent offset with 0<=days_until<off); key f"{anchor}|{id}|{off}|{ch}" skip if sent; skip if same (id,off,ch) sent within min_days_between_same_offset. mark_sent. Save state after each successful send. Dry-run via --dry-run or NOTIFY_DRY_RUN=1.
### i18n.py / messages.py
Built-in IT/EN weekday+month names; fmt_date -> "giovedì 25 novembre"; plural_days "1 giorno"/"N giorni". Templates: config/templates/{lang}/{name}.txt override else built-in; string.Template.safe_substitute. Output subject, text, simple inline HTML.
IT subject: `Promemoria: il ciclo di $user è previsto tra $n_days`
IT body:
```
Ciao $contact,
tra $n_days ($start_date) è previsto l'inizio del ciclo di $user: di solito dura circa $duration_days (fino a $end_date circa).
$confidence_line

Un piccolo gesto di attenzione fa sempre piacere 💛

—
Ricevi questo promemoria perché hai accettato di riceverlo da $user.
È una stima automatica e può variare di qualche giorno.
Per non riceverlo più, rispondi a questa email o scrivilo a $user.
```
confidence_line: high "La previsione è piuttosto affidabile."; medium "La data può variare di circa ±$sd giorni."; low/default "Ci sono pochi dati: la data è indicativa."
EN equivalents ("Reminder: $user's period is expected in $n_days", ...). Templates `invite` (asks reply sì/yes, includes feed link and contatti.html guide) and `test` ([TEST] prefix).
### ics_feed.py
build_feed(predictions, settings, state)->bytes: VCALENDAR PRODID -//cycle-notifier//IT, VERSION 2.0, CALSCALE GREGORIAN, METHOD PUBLISH, X-WR-CALNAME "Promemoria $user", X-WR-TIMEZONE Europe/Rome, REFRESH-INTERVAL;VALUE=DURATION:PT6H, X-PUBLISHED-TTL PT6H. One all-day VEVENT per predicted period (events_ahead): DTSTART;VALUE=DATE, DTEND end+1, UID sha256(f"{anchor}+{i}")[:16]@cycle-notifier (stable), SEQUENCE from state.feed.sequence bumped only on content hash change, DTSTAMP, TRANSP TRANSPARENT, SUMMARY event_title, DESCRIPTION "Stima automatica, durata ~N giorni. Affidabilità: …", CLASS PRIVATE, two VALARM DISPLAY: TRIGGER;RELATED=START:-P2DT15H (3 days before at 09:00) and -P1DT15H (2 days before), computed from alarm_time. reminder_events: extra all-day "Promemoria: tra 3 giorni…" on day -3 and -2 with stable UIDs. late/stale: last prediction, no reminder events. no data: empty valid calendar.
build_invite(prediction, contact): single event, same UID, METHOD PUBLISH, attached as text/calendar; method=PUBLISH; name=ciclo.ics.
Client notes: iPhone Settings→Calendar→Accounts→Add Subscribed Calendar, turn OFF "Rimuovi avvisi"; Android use ICSx⁵ (honours VALARM); Google "From URL" ignores VALARM and refreshes 12–24h → reminder events/email.
### publish.py
gist: PATCH https://api.github.com/gists/{GIST_ID} {"files":{"cycle.ics":{"content":ics}}} with GIST_TOKEN; skip if hash unchanged. pages: write build/site/f/{FEED_TOKEN}/cycle.ics. none: build/cycle.ics.
### notify/
Notifier.send(to, subject, text, html, attachments)->id. smtp: SMTP_HOST, SMTP_PORT (465 SSL / 587 STARTTLS), SMTP_USER, SMTP_PASSWORD, SMTP_FROM, Reply-To SMTP_REPLY_TO, List-Unsubscribe mailto. resend: POST https://api.resend.com/emails with RESEND_API_KEY, RESEND_FROM, base64 attachments.
### service.py (shared CLI+MCP)
sync(sources, files, dry_run) (skip imports whose sha256 already ingested); status; predict; list_cycles; add_period; exclude_days; run(today, dry_run): sync→predict→due→send→save state→publish feed; writes $GITHUB_STEP_SUMMARY with counts/status only (no dates/emails). preview; contacts_list; contacts_add (writes contacts.local.json, returns `gh secret set CONTACTS_JSON < config/contacts.local.json` hint); send_test; invite.
### config.py
Precedence env > .env > config.toml > defaults. CYCLE_NOTIFIER_HOME or walk up to pyproject.toml. Contacts from CONTACTS_JSON env else contacts.local.json. Frozen Settings.

## 5. CLI `python -m cycle_notifier`
run [--dry-run] [--today] [--no-publish]; sync [--source ...] [--file ...] [--dry-run]; predict [--count 3] [--today] [--json]; preview [--contact] [--offset 3] [--lang] [--today]; ics [--out] [--publish] [--new-token]; add-period START [END]; exclude DAY...; ingest-dispatch; invite ID; test-email ID; garmin-login; encrypt/decrypt. Exit 0 ok, 2 config error, 3 all sources failed & no data.

## 6. MCP server (FastMCP("cycle-notifier"), stdio)
get_cycle_status(today=None)->dict; predict_next_period(count=3,today=None)->list; list_cycles(limit=12); add_period(start,end=None,note=None,commit=False) (commit → git add/commit/push only if remote); sync_sources(sources=None,files=None,dry_run=False); list_contacts() (masked emails m***@gmail.com); add_contact(name,email,lang="it",offsets_days=None,consent=False); send_test_notification(contact_id,dry_run=True); preview_message(contact_id=None,offset=3,lang=None,today=None)->{subject,body,ics}. Optional resource cycle://status. Script `cycle-notifier-mcp`.
Claude Desktop snippet:
```json
{"mcpServers":{"cycle-notifier":{"command":"uv","args":["run","--directory","/percorso/cycle-notifier","--extra","garmin","python","-m","cycle_notifier.mcp_server"],"env":{"CYCLE_NOTIFIER_HOME":"/percorso/cycle-notifier"}}}}
```
Claude Code: `claude mcp add cycle-notifier -- uv run --directory /percorso/cycle-notifier python -m cycle_notifier.mcp_server`.

## 7. Workflows
daily.yml: cron "40 6 * * *" and "40 12 * * *" (catch-up, dedup protects), workflow_dispatch input dry_run, repository_dispatch types [cycle-data]; permissions contents: write; concurrency cycle-notifier-data; checkout, setup-python 3.12 pip cache, pip install ".[garmin,crypto]", ingest-dispatch if repository_dispatch, `run` with all secrets as env (ICS_URLS, CONTACTS_JSON, SMTP_*, RESEND_*, GARMIN_*, CYCLES_KEY, FEED_MODE var default gist, GIST_TOKEN, GIST_ID, NOTIFY_DRY_RUN var); commit step if: always() with github-actions[bot], `git add data/`, commit "chore(data): aggiornamento automatico [skip ci]", pull --rebase, push. Job pages calls pages.yml via workflow_call when vars.FEED_MODE=='pages'. Note cron UTC/delays/60-day inactivity disable. Shortcut needs fine-grained PAT, this repo only, Contents RW.
pages.yml: push main paths site/**, workflow_dispatch, workflow_call; copy site to build/site; if pages mode build feed to build/site/f/$FEED_TOKEN/cycle.ics; configure-pages@v5, upload-pages-artifact@v3, deploy-pages@v4; permissions pages write, id-token write, contents read. Never commit feed.
ci.yml: push/PR paths-ignore data/**; pip install ".[dev,crypto]"; ruff check .; pytest -q. No secrets; garmin via importorskip/fake.
Secrets: ICS_URLS, CONTACTS_JSON, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM, SMTP_REPLY_TO(opt), RESEND_API_KEY/RESEND_FROM (alt), GARMIN_TOKENS (or GARMIN_EMAIL+GARMIN_PASSWORD), GIST_TOKEN+GIST_ID, FEED_TOKEN (pages), CYCLES_KEY(opt). Variables: FEED_MODE, NOTIFY_DRY_RUN.

## 8. Site (Italian, noindex meta, no external scripts/fonts, CSP default-src 'self')
index (what, diagram sources→Actions→email+calendar, guide links, privacy box); guides with numbered steps, which file, where to put it, reliability badge (stabile/best-effort/non ufficiale): Google iCal secret address → ICS_URLS, event title "Ciclo"; Apple Health export; iOS Shortcut (Find Health Samples Mestruazioni 90d → Repeat → Dictionary → Get Contents of URL POST https://api.github.com/repos/Carlol01/make-your-love-happier/dispatches, headers Authorization Bearer PAT + Accept application/vnd.github+json, body {"event_type":"cycle-data","client_payload":{"samples":[…]}}, daily personal Automation "Esegui immediatamente"); Health Connect; Garmin; Flo; Clue; Natural Cycles; Stardust; Period Tracker; CSV generico. contatti.html (what they receive, consent/withdraw, subscribe iPhone webcal + Rimuovi avvisi OFF, Android ICSx⁵, Google From URL limits, email-only; URL never printed on site). privacy.html. converti.html + parsers.js (local only, Clue/Flo JSON tolerant walker port, CSV aliases, Apple export.xml streamed via File.stream() regex, no zip; outputs generic JSON download/copy). dashboard.html (open local cycles.json, stats + SVG timeline).

## 9. README (Italian)
Cos'è; ⚠️ Avvertenze (not medical, estimates, consent); Requisiti (Pages/private caveat); Setup steps (repo, config.toml, contacts + gh secret set, email provider, feed mode + secret gist, sources, first dry-run dispatch, invite contacts); secrets/variables table; sources summary w/ reliability; notifications (iOS Rimuovi avvisi, Google VALARM); CLI; MCP (Desktop + Code); Privacy & security; Limitazioni oneste (no public APIs, formats best-effort, Garmin unofficial, Health Connect export only, Apple needs Shortcut/export, cron delays & 60-day disable, calendar refresh/alarms, irregular cycles accuracy, feed URL public to holders); Sviluppo e test.

## 10. Tests (pytest, offline) — predictor (regular/irregular/outliers/defaults/last 6/statuses/tz), merge (dedup, gap 1 vs 3, estimated end, exclusions, manual, history survives, spotting), scheduler (3 and 2 due; not 4/1/0; dedup key & window; catch_up; consent/inactive; late/stale; per-contact offsets), messages/i18n (IT/EN, singular/plural, names, footer, override, safe), ics_feed (parse back, exclusive DTEND, stable UIDs, SEQUENCE, 2 VALARMs -P2DT15H/-P1DT15H, reminder toggle, empty valid, invite PUBLISH), sources (each fixture; ics keywords/accents/own UID/webcal/HTTP error; apple zip+xml, None skip, tz midnight; clue both; HC renamed columns; garmin fake client; registry autodetect; date_order; future dropped), storage (atomic, Fernet roundtrip, refuse plaintext, schema_version), notify (fake SMTP_SSL, resend payload, dry-run), publish (gist payload, hash skip, pages path), service/cli (e2e run --today --dry-run no state write; real run fake notifier writes state, second run sends nothing; ingest-dispatch), mcp (call tools directly, masked contacts, add_contact writes file).

## 11. Order
scaffold+ci → models/config/storage → predictor → merge → i18n/messages → scheduler → ics_feed → notify → sources base/registry/_tolerant/generic → adapters (ics, apple_health, ios_shortcut, clue, flo, natural_cycles, health_connect, stardust, period_tracker_gp, garmin) → service/publish → cli → mcp_server → workflows + initial data/config → site → docs/README → final: ruff+pytest green, run --dry-run on fixtures, grep no personal data/secrets.
