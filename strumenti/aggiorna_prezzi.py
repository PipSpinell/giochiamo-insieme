"""Aggiorna prices.json leggendo i prezzi attuali da DekuDeals (eShop e negozi), Steam e PriceCharting (usato).
Gira da solo ogni settimana su GitHub (vedi .github/workflows/aggiorna.yml). Usa solo la libreria standard di Python.
Se una fonte non risponde, tiene il prezzo della settimana prima: non cancella mai nulla per un errore di rete."""
import json, os, re, sys, time, datetime, urllib.request
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
     'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8'}
SRC = json.load(open(os.path.join(ROOT, 'strumenti', 'fonti_prezzi.json'), encoding='utf-8'))
AJ = os.path.join(ROOT, 'auto.json')   # i giochi aggiunti in automatico da Steam
if os.path.exists(AJ):
    for g in json.load(open(AJ, encoding='utf-8')).get('games', []): SRC.setdefault(g['id'], {'steam': g['appid']})
PJ = os.path.join(ROOT, 'prices.json')
old = json.load(open(PJ, encoding='utf-8')) if os.path.exists(PJ) else {'p': {}}

def get(u):
    for i in range(3):
        try:
            d = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30).read().decode('utf-8', 'ignore'); time.sleep(1.2); return d
        except urllib.error.HTTPError as e:
            if e.code in (400, 403, 404): return None
            time.sleep(10 * (i + 1))
        except Exception: time.sleep(5)
    return None

def deku(url):
    page = get(url)
    if not page or 'outAnalytics' not in page: return None
    dig = phy = None
    for m in re.finditer(r"outAnalytics\['([a-z_]+):[^']*'\] = (\{.*?\})\n", page):
        d = json.loads(m.group(2)); v = d['value'] / 100
        if m.group(1).startswith('eshop') and (dig is None or v < dig): dig = v
        if d['items'][0].get('item_variant') == 'physical' and v > 0 and (phy is None or v < phy): phy = v
    um = [float(x.replace('.', '').replace(',', '.')) for x in re.findall(r'Used: €([\d.,]+)', page)]
    return dict(dig=dig, phy=phy, used=min(um) if um else None)

def pricecharting(url, ps):
    page = get(url)
    if not page: return None
    f = lambda k: (lambda m: round(float(m.group(1).replace(',', '')) * 0.88, 2) if m else None)(
        re.search(r'id="%s_price"[^>]*>\s*<span class="price js-price">\s*\$([\d,.]+)' % k, page))
    return dict(used=f('used'), phy=f('new') if ps else None)

def steam(appids):
    res = {}
    for i in range(0, len(appids), 40):
        chunk = appids[i:i + 40]
        r = get('https://store.steampowered.com/api/appdetails?cc=it&filters=price_overview&appids=' + ','.join(map(str, chunk)))
        try: d = json.loads(r or '{}') or {}
        except Exception: continue
        for a in chunk:
            v = d.get(str(a)) or {}
            if not v.get('success'): continue
            data = v.get('data') or {}
            if isinstance(data, list): res[a] = 0.0; continue          # gratis: nessun prezzo
            po = data.get('price_overview')
            if po: res[a] = po['final'] / 100
    return res

def sane(new, prev):
    """Scarta valori assurdi (errori di lettura): prezzi negativi, sopra i 150 € o crolli sospetti rispetto a prima."""
    if new is None: return prev
    if new < 0 or new > 150: return prev
    return round(new, 2)

p = {k: dict(v) for k, v in old.get('p', {}).items()}
st = steam(sorted({s['steam'] for s in SRC.values() if s.get('steam')}))
changed = ok = fail = 0
for gid, s in SRC.items():
    cur = p.setdefault(gid, {}); before = dict(cur)
    if s.get('deku'):
        r = deku(s['deku'])
        if r: ok += 1; [cur.__setitem__(k, sane(r[k], cur.get(k))) for k in ('dig', 'phy', 'used') if r[k] is not None]
        else: fail += 1
    if s.get('pc'):
        r = pricecharting(s['pc'], s.get('ps'))
        if r: ok += 1; [cur.__setitem__(k, sane(r[k], cur.get(k))) for k in ('used', 'phy') if r[k] is not None]
        else: fail += 1
    if s.get('steam') in st: cur['steam'] = sane(st[s['steam']], cur.get('steam')); ok += 1
    if cur != before: changed += 1
today = datetime.date.today()
MESI = ['gennaio', 'febbraio', 'marzo', 'aprile', 'maggio', 'giugno', 'luglio', 'agosto', 'settembre', 'ottobre', 'novembre', 'dicembre']
out = dict(version=int(datetime.datetime.now().strftime('%Y%m%d%H%M')),
           date=dict(it='%d %s %d' % (today.day, MESI[today.month - 1], today.year), en=today.strftime('%B ') + str(today.day) + today.strftime(', %Y')),
           p=p, stats=dict(ok=ok, fail=fail, changed=changed))
if ok == 0:
    print('Nessuna fonte ha risposto: prices.json non viene toccato'); sys.exit(0)
json.dump(out, open(PJ, 'w', encoding='utf-8'), separators=(',', ':'))
print('fonti lette:', ok, '| non raggiunte:', fail, '| giochi con prezzo cambiato:', changed)
