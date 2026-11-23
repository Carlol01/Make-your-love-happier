# Template personalizzati

Per cambiare i testi dei messaggi crea file `config/templates/{lingua}/{nome}.txt`
(es. `config/templates/it/reminder_body.txt`). Se il file esiste sostituisce il
testo predefinito; altrimenti vengono usati i testi integrati.

Nomi disponibili: `reminder_subject`, `reminder_body`, `invite_subject`, `invite_body`,
`test_subject`, `test_banner`, `confidence_high`, `confidence_medium`, `confidence_low`.

I segnaposto usano la sintassi `$nome` di `string.Template` (sostituzione "sicura":
i segnaposto sconosciuti restano com'erano). Segnaposto disponibili:
`$user`, `$contact`, `$n_days`, `$start_date`, `$end_date`, `$duration_days`,
`$confidence_line`, e nell'invito `$feed_line`, `$guide_url`.

Lascia sempre nel messaggio il modo di non riceverlo più: il consenso è un requisito.
