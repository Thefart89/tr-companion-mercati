# Dati di mercato per TR-Companion

Ogni giorno di borsa GitHub Actions esegue `lavoro.py` e salva in `data/` (file pubblici, nessun dato personale):

- `titoli.json`: analisi tecnica dei titoli di FTSE MIB, Euro Stoxx 50 e S&P 500 e dei principali indici;
- `mercato.json`: previsioni del mattino, notizie, volumi anomali (oltre 5 volte la media di 60 giorni), calendario macro;
- `storico.json`: stime d'apertura passate e risultato reale.

Durante la seduta `volumi.py` (ogni 20 minuti) confronta il volume di ogni titolo con quello che scambia
di solito ENTRO la stessa ora (media di 60 giorni, barre da 15 minuti) e scrive:

- `volumi_oggi.json`: titoli oltre 5 volte il normale a quell'ora (+400%), segnalati una volta al giorno;
- `segnali_storico.json`: segnali passati con il movimento fino alla chiusura (le prime ~35 sedute sono simulate).

Avviso Telegram facoltativo: segreti `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.

Orari: verso le 6:20/7:20 (mattina) e dopo le 17:50/18:50 (sera), ora italiana.
Commento IA facoltativo: segreto `GEMINI_API_KEY` (Google AI Studio, gratuito) oppure `ANTHROPIC_API_KEY` nelle impostazioni del repository.
Fonti: Yahoo Finance (dati non ufficiali), feed RSS dei giornali, calendario macro pubblico. Informazioni generali, non consigli d'investimento.
