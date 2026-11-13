# Dati di mercato per TR-Companion

Ogni giorno di borsa GitHub Actions esegue `lavoro.py` e salva in `data/` (file pubblici, nessun dato personale):

- `titoli.json`: analisi tecnica dei titoli di FTSE MIB, Euro Stoxx 50 e S&P 500 e dei principali indici;
- `mercato.json`: previsioni del mattino, notizie, volumi anomali (oltre 5 volte la media di 60 giorni), calendario macro;
- `storico.json`: stime d'apertura passate e risultato reale.

Orari: verso le 6:20/7:20 (mattina) e dopo le 17:50/18:50 (sera), ora italiana.
Commento IA facoltativo: segreto `GEMINI_API_KEY` (Google AI Studio, gratuito) oppure `ANTHROPIC_API_KEY` nelle impostazioni del repository.
Fonti: Yahoo Finance (dati non ufficiali), feed RSS dei giornali, calendario macro pubblico. Informazioni generali, non consigli d'investimento.
