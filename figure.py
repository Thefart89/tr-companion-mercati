"""Figure grafiche dell'analisi tecnica su grafici GIORNALIERI (solo libreria standard).

Figure riconosciute (le stesse dei manuali, regole scritte qui sotto in modo esplicito):
  doppio minimo / doppio massimo, triplo minimo / triplo massimo,
  testa e spalle / testa e spalle rovesciato, rettangolo, triangolo ascendente / discendente,
  bandiera rialzista / ribassista.

Come funziona:
  1. "punti di svolta": un massimo (minimo) e' tale se e' il piu' alto (basso) delle W sedute prima e dopo.
     Si conosce quindi solo W sedute dopo: nelle prove storiche non si usa mai un dato futuro.
  2. le figure sono sequenze di punti di svolta alternati (minimo, massimo, minimo...) con livelli simili
     (tolleranza in ATR, cioe' in "movimenti normali di un giorno" del titolo).
  3. la figura e' CONFERMATA quando una chiusura supera la linea chiave (neckline / resistenza / supporto)
     entro MAX_ATTESA sedute; e' FALLITA se prima della rottura il prezzo chiude oltre il livello di invalidazione.
  Obiettivo = altezza della figura proiettata dalla rottura (regola classica). Invalidazione = livello oltre il
  quale la figura non vale piu' (utile come riferimento per lo stop).

Nessun consiglio di acquisto/vendita: descrive la figura e i suoi livelli.
"""
from __future__ import annotations

W = 4              # sedute prima e dopo per un punto di svolta
TOL = 0.8          # livelli "uguali" se distano meno di TOL x ATR
MIN_H = 2.0        # altezza minima della figura in ATR
MAX_ATTESA = 30    # sedute dopo la conferma dell'ultimo punto per la rottura
LARGH = (12, 130)  # durata della figura (sedute dal primo all'ultimo punto)

NOMI = {
    'doppio_minimo': 'Doppio minimo', 'doppio_massimo': 'Doppio massimo',
    'triplo_minimo': 'Triplo minimo', 'triplo_massimo': 'Triplo massimo',
    'ts_rovesciato': 'Testa e spalle rovesciato', 'ts': 'Testa e spalle',
    'rettangolo_su': 'Rettangolo (rottura in alto)', 'rettangolo_giu': 'Rettangolo (rottura in basso)',
    'triangolo_asc': 'Triangolo ascendente', 'triangolo_disc': 'Triangolo discendente',
    'bandiera_su': 'Bandiera rialzista', 'bandiera_giu': 'Bandiera ribassista',
}
INVERSIONE = {'doppio_minimo', 'doppio_massimo', 'triplo_minimo', 'triplo_massimo', 'ts_rovesciato', 'ts'}


def atr_serie(h, l, c, n=14):
    out = [None] * len(c)
    if len(c) <= n:
        return out
    tr = [h[0] - l[0]] + [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(1, len(c))]
    a = sum(tr[1:n + 1]) / n
    out[n] = a
    for i in range(n + 1, len(c)):
        a = (a * (n - 1) + tr[i]) / n
        out[i] = a
    return out


def punti_svolta(h, l):
    """Punti alternati [(i, prezzo, 'H'|'L')]: si tiene il piu' estremo se due dello stesso tipo sono di fila."""
    n = len(h)
    raw = []
    for i in range(W, n - W):
        if h[i] == max(h[i - W:i + W + 1]):
            raw.append((i, h[i], 'H'))
        if l[i] == min(l[i - W:i + W + 1]):
            raw.append((i, l[i], 'L'))
    raw.sort(key=lambda x: (x[0], x[2] == 'H'))
    alt = []
    for p in raw:
        if alt and alt[-1][2] == p[2]:
            if (p[2] == 'H' and p[1] >= alt[-1][1]) or (p[2] == 'L' and p[1] <= alt[-1][1]):
                alt[-1] = p
        else:
            alt.append(p)
    return alt


def _linea(p1, p2, j):
    (i1, y1), (i2, y2) = p1, p2
    return y1 + (y2 - y1) * (j - i1) / (i2 - i1) if i2 != i1 else y1


def _candidati(P, h, l, c, A):
    """Figure possibili (non ancora rotte) dalle sequenze di punti di svolta."""
    out = []
    for k in range(len(P)):
        for m in (3, 4, 5):
            if k + m > len(P):
                continue
            q = P[k:k + m]
            i0, iN = q[0][0], q[-1][0]
            a = A[iN]
            if not a or not (LARGH[0] <= iN - i0 <= LARGH[1]):
                continue
            tol = TOL * a
            low = [x for x in q if x[2] == 'L']
            hig = [x for x in q if x[2] == 'H']
            first = q[0][2]
            prima = c[max(0, i0 - 30):i0]
            # --- inversioni: servono un movimento precedente da invertire ---
            if m == 3 and first == 'L':                       # L H L: doppio minimo
                L1, H1, L2 = q
                alt = H1[1] - min(L1[1], L2[1])
                if abs(L1[1] - L2[1]) <= tol and alt >= MIN_H * a and prima and max(prima) >= L1[1] + alt:
                    out.append(dict(tipo='doppio_minimo', dir=1, punti=q, collo=lambda j, v=H1[1]: v,
                                    inval=min(L1[1], L2[1]), alt=alt))
            if m == 3 and first == 'H':                       # H L H: doppio massimo
                H1, L1, H2 = q
                alt = max(H1[1], H2[1]) - L1[1]
                if abs(H1[1] - H2[1]) <= tol and alt >= MIN_H * a and prima and min(prima) <= H1[1] - alt:
                    out.append(dict(tipo='doppio_massimo', dir=-1, punti=q, collo=lambda j, v=L1[1]: v,
                                    inval=max(H1[1], H2[1]), alt=alt))
            if m == 5 and first == 'L':                       # L H L H L
                L1, H1, L2, H2, L3 = q
                if L2[1] < min(L1[1], L3[1]) - 0.5 * a and abs(L1[1] - L3[1]) <= 1.5 * tol:   # testa piu' bassa
                    neck = lambda j, p1=(H1[0], H1[1]), p2=(H2[0], H2[1]): _linea(p1, p2, j)
                    alt = neck(L2[0]) - L2[1]
                    if alt >= MIN_H * a and prima and max(prima) >= L2[1] + alt:
                        out.append(dict(tipo='ts_rovesciato', dir=1, punti=q, collo=neck, inval=L3[1], alt=alt))
                elif max(x[1] for x in low) - min(x[1] for x in low) <= tol:
                    alt = max(H1[1], H2[1]) - min(x[1] for x in low)
                    if alt >= MIN_H * a and prima and max(prima) >= min(x[1] for x in low) + alt:
                        out.append(dict(tipo='triplo_minimo', dir=1, punti=q, collo=lambda j, v=max(H1[1], H2[1]): v,
                                        inval=min(x[1] for x in low), alt=alt))
            if m == 5 and first == 'H':                       # H L H L H
                H1, L1, H2, L2, H3 = q
                if H2[1] > max(H1[1], H3[1]) + 0.5 * a and abs(H1[1] - H3[1]) <= 1.5 * tol:
                    neck = lambda j, p1=(L1[0], L1[1]), p2=(L2[0], L2[1]): _linea(p1, p2, j)
                    alt = H2[1] - neck(H2[0])
                    if alt >= MIN_H * a and prima and min(prima) <= H2[1] - alt:
                        out.append(dict(tipo='ts', dir=-1, punti=q, collo=neck, inval=H3[1], alt=alt))
                elif max(x[1] for x in hig) - min(x[1] for x in hig) <= tol:
                    alt = max(x[1] for x in hig) - min(L1[1], L2[1])
                    if alt >= MIN_H * a and prima and min(prima) <= max(x[1] for x in hig) - alt:
                        out.append(dict(tipo='triplo_massimo', dir=-1, punti=q, collo=lambda j, v=min(L1[1], L2[1]): v,
                                        inval=max(x[1] for x in hig), alt=alt))
            # --- rettangoli e triangoli (4-5 punti) ---
            if m >= 4 and len(low) >= 2 and len(hig) >= 2:
                top, bot = max(x[1] for x in hig), min(x[1] for x in low)
                alt = top - bot
                piatto_h = top - min(x[1] for x in hig) <= tol
                piatto_l = max(x[1] for x in low) - bot <= tol
                sal_l = all(low[i + 1][1] >= low[i][1] + 0.5 * tol for i in range(len(low) - 1))
                sce_h = all(hig[i + 1][1] <= hig[i][1] - 0.5 * tol for i in range(len(hig) - 1))
                if alt < MIN_H * a:
                    continue
                mid = (top + bot) / 2
                if piatto_h and piatto_l:
                    out.append(dict(tipo='rettangolo_su', dir=1, punti=q, collo=lambda j, v=top: v, inval_pre=bot - 0.25 * a, inval=mid, alt=alt))
                    out.append(dict(tipo='rettangolo_giu', dir=-1, punti=q, collo=lambda j, v=bot: v, inval_pre=top + 0.25 * a, inval=mid, alt=alt))
                elif piatto_h and sal_l:
                    out.append(dict(tipo='triangolo_asc', dir=1, punti=q, collo=lambda j, v=top: v, inval=low[-1][1], alt=alt))
                elif piatto_l and sce_h:
                    out.append(dict(tipo='triangolo_disc', dir=-1, punti=q, collo=lambda j, v=bot: v, inval=hig[-1][1], alt=alt))
    return out


def _bandiere(P, h, l, c, A):
    """Asta (forte movimento in <=12 sedute, >=5 ATR) e poi pausa stretta di 4-20 sedute che non ritraccia oltre meta'."""
    out = []
    for (b, v, t) in P:
        a = A[b]
        if not a or b < 12:
            continue
        if t == 'H':
            a0 = min(range(b - 12, b - 2), key=lambda i: l[i])
            asta = v - l[a0]
            if asta >= 5 * a:
                out.append(dict(tipo='bandiera_su', dir=1, punti=[(a0, l[a0], 'L'), (b, v, 'H')], collo=lambda j, x=v: x,
                                inval=v - 0.5 * asta, alt=asta, bandiera=True))
        else:
            a0 = max(range(b - 12, b - 2), key=lambda i: h[i])
            asta = h[a0] - v
            if asta >= 5 * a:
                out.append(dict(tipo='bandiera_giu', dir=-1, punti=[(a0, h[a0], 'H'), (b, v, 'L')], collo=lambda j, x=v: x,
                                inval=v + 0.5 * asta, alt=asta, bandiera=True))
    return out


def trova(d: dict) -> list[dict]:
    """Tutte le figure della serie, con l'esito della rottura (senza usare dati successivi alla rottura per decidere)."""
    h, l, c = d['h'], d['l'], d['c']
    v = d.get('v') or [0] * len(c)
    n = len(c)
    A = atr_serie(h, l, c)
    P = punti_svolta(h, l)
    res = []
    for f in _candidati(P, h, l, c, A) + _bandiere(P, h, l, c, A):
        ultimo = f['punti'][-1][0]
        da = ultimo + W                                  # da qui il punto e' conosciuto
        if da >= n:
            continue
        min_band = ultimo + 4 if f.get('bandiera') else da
        fine = min(n, da + (20 if f.get('bandiera') else MAX_ATTESA))
        f['nota_da'] = da
        f['stato'] = 'in formazione'
        f['rottura'] = None
        for j in range(da, fine):
            neck = f['collo'](j)
            # fallita prima della rottura
            pre = f.get('inval_pre', f['inval'])
            if (f['dir'] > 0 and c[j] < pre) or (f['dir'] < 0 and c[j] > pre):
                f['stato'] = 'fallita'; f['fine'] = j
                break
            if j < min_band:
                continue
            if (f['dir'] > 0 and c[j] > neck) or (f['dir'] < 0 and c[j] < neck):
                f['stato'] = 'confermata'; f['rottura'] = j; f['livello'] = neck
                f['obiettivo'] = neck + f['dir'] * f['alt']
                if f.get('bandiera'):                    # invalidazione dopo la rottura = estremo della bandiera
                    seg = range(ultimo + 1, j)
                    if seg:
                        f['inval'] = min(l[i] for i in seg) if f['dir'] > 0 else max(h[i] for i in seg)
                vm = sum(v[max(0, j - 50):j]) / max(1, len(v[max(0, j - 50):j]))
                f['vol_x'] = round(v[j] / vm, 2) if vm else None
                break
        else:
            if fine < n:
                f['stato'] = 'scaduta'
        res.append(f)
    # una sola figura per rottura (stesso giorno e direzione): vince la piu' "classica"
    ordine = ['ts_rovesciato', 'ts', 'triplo_minimo', 'triplo_massimo', 'doppio_minimo', 'doppio_massimo',
              'triangolo_asc', 'triangolo_disc', 'bandiera_su', 'bandiera_giu', 'rettangolo_su', 'rettangolo_giu']
    res.sort(key=lambda f: ordine.index(f['tipo']))
    visti, out = set(), []
    for f in res:
        k = (f['rottura'], f['dir']) if f['rottura'] is not None else (f['tipo'], f['punti'][-1][0])
        if k in visti:
            continue
        visti.add(k)
        out.append(f)
    return out


# ---------------------------------------------------------------- figure di adesso (per l'app)
def _r(x):
    """4 cifre significative."""
    if x is None:
        return None
    from math import floor, log10
    return round(x, max(0, 3 - int(floor(log10(abs(x))))) if x else 0)


def attuali(d: dict, giorni: int = 10, data=None) -> list[dict]:
    """Figure in formazione o confermate nelle ultime `giorni` sedute. d = serie COMPLETE (senza la seduta in corso).
    data(i) -> 'AAAA-MM-GG' della seduta i."""
    h, l, c = d['h'], d['l'], d['c']
    n = len(c)
    data = data or (lambda i: str(i))
    figs = trova(d)
    forma, conf = [], []
    for f in figs:
        if f['stato'] == 'in formazione':
            forma.append(f)
        elif f['stato'] == 'confermata' and n - 1 - f['rottura'] <= giorni:
            j, di = f['rottura'], f['dir']
            f['esito'] = None
            for i in range(j + 1, n):
                if (di > 0 and c[i] < f['inval']) or (di < 0 and c[i] > f['inval']):
                    f['esito'] = 'annullata'; break
                if (di > 0 and h[i] >= f['obiettivo']) or (di < 0 and l[i] <= f['obiettivo']):
                    f['esito'] = 'obiettivo'; break
            conf.append(f)
    conf.sort(key=lambda f: -f['rottura'])
    forma.sort(key=lambda f: -f['punti'][-1][0])
    # rettangolo in formazione: le due versioni (su/giu) diventano una sola
    scelte, visti = [], set()
    for f in conf[:2] + forma:
        k = tuple(p[0] for p in f['punti'])
        if k in visti:
            continue
        visti.add(k)
        scelte.append(f)
        if len(scelte) >= 2:
            break
    out = []
    for f in scelte:
        i0 = max(0, f['punti'][0][0] - 5)
        conf_ = f['stato'] == 'confermata'
        tipo = f['tipo']
        x = dict(tipo=tipo, nome=NOMI[tipo], dir=f['dir'], inversione=tipo in INVERSIONE,
                 stato=f.get('esito') or ('confermata' if conf_ else 'in formazione'),
                 punti=[[data(i), _r(p), t, i - i0] for i, p, t in f['punti']],
                 d0=data(i0), serie=[_r(v) for v in c[i0:]], alt=_r(f['alt']))
        if conf_:
            x.update(rottura=data(f['rottura']), rk=f['rottura'] - i0, sedute=n - 1 - f['rottura'], livello=_r(f['livello']),
                     obiettivo=_r(f['obiettivo']), inval=_r(f['inval']), vol_x=f.get('vol_x'))
        else:
            liv = f['collo'](n - 1)
            x.update(livello=_r(liv), obiettivo=_r(liv + f['dir'] * f['alt']), inval=_r(f.get('inval_pre', f['inval'])))
            if tipo.startswith('rettangolo'):
                top = max(p for _, p, t in f['punti'] if t == 'H'); bot = min(p for _, p, t in f['punti'] if t == 'L')
                x.update(tipo='rettangolo', nome='Rettangolo', dir=0, sopra=_r(top), sotto=_r(bot), livello=None,
                         obiettivo=None, inval=None, obiettivo_su=_r(top + f['alt']), obiettivo_giu=_r(bot - f['alt']))
        out.append(x)
    return out


def per_simbolo(d: dict, now: float) -> list[dict]:
    """Figure di adesso da una serie di Yahoo (fonti.chart): toglie la seduta in corso e le barre incomplete."""
    from fonti import rome
    from tecnica import session_complete
    t = d.get('t') or []
    keep = [i for i in range(len(t)) if None not in (d['h'][i], d['l'][i], d['c'][i])]
    if len(keep) < 60:
        return []
    if not session_complete(t[keep[-1]], d.get('meta') or {}, now):
        keep = keep[:-1]
    s = {k: [d[k][i] for i in keep] for k in ('h', 'l', 'c')}
    s['v'] = [(d.get('v') or [0] * len(t))[i] or 0 for i in keep]
    tt = [t[i] for i in keep]
    return attuali(s, data=lambda i: rome(tt[i]))


# ---------------------------------------------------------------- prova storica (per statistiche.json)
def misura(D: dict, gruppo: dict) -> dict:
    """Per ogni figura: quante volte dopo la rottura il prezzo e' andato nel verso previsto (20 sedute), contro il caso;
    obiettivo toccato prima dell'invalidazione; confronto con la mediana del suo indice nello stesso periodo."""
    import statistics as stt
    from collections import defaultdict
    per = defaultdict(dict)
    for s, d in D.items():
        c = d['c']
        if not c or any(x is None for x in c):
            continue
        for i in range(len(c) - 20):
            per[(gruppo.get(s), d['t'][i] // 86400)][s] = c[i + 20] / c[i] - 1
    med = {k: stt.median(v.values()) for k, v in per.items() if len(v) >= 10}
    R = defaultdict(list)
    for s, d in D.items():
        c, h, l = d['c'], d['h'], d['l']
        if not c or len(c) < 300 or any(x is None for x in c + h + l):
            continue
        n = len(c)
        pu = sum(c[i + 20] > c[i] for i in range(n - 20)) / (n - 20)
        for f in trova(d):
            j = f['rottura']
            if j is None or j + 20 >= n or j < 60:
                continue
            e, di = c[j], f['dir']
            esito = 'nessuno'
            for i in range(j + 1, min(n, j + 61)):
                if (di > 0 and l[i] <= f['inval']) or (di < 0 and h[i] >= f['inval']):
                    esito = 'stop'; break
                if (di > 0 and h[i] >= f['obiettivo']) or (di < 0 and l[i] <= f['obiettivo']):
                    esito = 'obiettivo'; break
            ds, dt_ = abs(e - f['inval']), abs(f['obiettivo'] - e)
            k = (gruppo.get(s), d['t'][j] // 86400)
            R[f['tipo']].append(dict(ok=(c[j + 20] / e - 1) * di > 0, base=pu if di > 0 else 1 - pu, r=(c[j + 20] / e - 1) * di * 100,
                                     esito=esito, caso=ds / (ds + dt_) if ds + dt_ else .5,
                                     ecc=((c[j + 20] / e - 1) - med[k]) * di * 100 if k in med else None))

    def sintesi(L):
        if not L:
            return None
        E = [x['ecc'] for x in L if x['ecc'] is not None]
        p = lambda q: round(q * 100, 1)
        return dict(n=len(L), giusta=p(sum(x['ok'] for x in L) / len(L)), caso=p(stt.mean(x['base'] for x in L)),
                    media=round(stt.mean(x['r'] for x in L), 2), obiettivo=p(sum(x['esito'] == 'obiettivo' for x in L) / len(L)),
                    caso_obiettivo=p(stt.mean(x['caso'] for x in L)), stop=p(sum(x['esito'] == 'stop' for x in L) / len(L)),
                    batte_indice=p(sum(e > 0 for e in E) / len(E)) if E else None)
    out = {t: sintesi(L) for t, L in R.items()}
    out['tutte'] = sintesi([x for L in R.values() for x in L])
    return out
