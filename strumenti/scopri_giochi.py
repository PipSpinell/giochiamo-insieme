"""Scopre in automatico i giochi co-op nuovi su Steam e li aggiunge alla libreria (auto.json).
Gira da solo su GitHub ogni 6 ore insieme ai prezzi. Usa solo la libreria standard di Python.

Regole per entrare (tutte obbligatorie):
- Steam dichiara "Schermo condiviso/diviso - Cooperativa" (categoria 39): si gioca nella stessa stanza, niente online;
- è un gioco (non un programma), non richiede la realtà virtuale, non ha contenuti sessuali;
- recensioni: almeno l'85% positive su almeno 500 recensioni, oppure (uscite negli ultimi 120 giorni) il 90% su almeno 150;
- non è già in libreria (stesso numero Steam o stesso titolo), e non è tra quelli già scartati.
Età, violenza e genere arrivano dai dati di Steam (PEGI e descrittori): per prudenza un gioco senza PEGI conta come 12+.
Le schede create così sono segnate "aggiunto in automatico" nell'app."""
import json, os, re, sys, time, html, datetime, unicodedata, urllib.request, urllib.parse
ROOT = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_NEW = int(os.environ.get('MAX_NUOVI', '40'))
H = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36',
     'Accept-Language': 'it-IT,it;q=0.9,en;q=0.8'}
def get(u, tries=3):
    for i in range(tries):
        try:
            d = urllib.request.urlopen(urllib.request.Request(u, headers=H), timeout=30).read().decode('utf-8', 'ignore'); time.sleep(1.3); return d
        except urllib.error.HTTPError as e:
            if e.code == 429: time.sleep(40 * (i + 1)); continue
            if e.code in (400, 403, 404): return None
            time.sleep(8)
        except Exception: time.sleep(5)
    return None
def norm(s):
    s = re.sub(r'[™®©]', '', s or '')
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()
    s = re.sub(r'\b(the|edition|remastered|deluxe|definitive|complete|hd|remake|anniversary|goty|game of the year)\b', ' ', s)
    return re.sub(r'[^a-z0-9]', '', s)
def slug(s): return re.sub(r'[^a-z0-9]+', '-', unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode().lower()).strip('-')[:60]

DATA = json.load(open(os.path.join(ROOT, 'data.json'), encoding='utf-8'))
AUTO_P = os.path.join(ROOT, 'auto.json')
AUTO = json.load(open(AUTO_P, encoding='utf-8')) if os.path.exists(AUTO_P) else {'games': [], 'imgs': {}, 'scartati': {}}
SRC = json.load(open(os.path.join(ROOT, 'strumenti', 'fonti_prezzi.json'), encoding='utf-8'))
NOTI = json.load(open(os.path.join(ROOT, 'strumenti', 'steam_noti.json'), encoding='utf-8')) if os.path.exists(os.path.join(ROOT, 'strumenti', 'steam_noti.json')) else []
known_ids = {int(x) for x in NOTI} | {int(s['steam']) for s in SRC.values() if s.get('steam')} | {g['appid'] for g in AUTO['games']}
known_titles = [norm(t) for g in DATA['games'] for t in (g['t'], g.get('en')) if t] + [norm(g['t']) for g in AUTO['games']]
scartati = AUTO.setdefault('scartati', {})
def already(name):
    n = norm(name)
    return any(n == k or (len(k) >= 8 and (n.startswith(k) or k.startswith(n))) for k in known_titles)

# 1) candidati: i più apprezzati e i più recenti con co-op sullo stesso schermo
cand = {}
for sort, pages in (('Reviews_DESC', 8), ('Released_DESC', 3)):
    for p in range(pages):
        r = get('https://store.steampowered.com/search/results/?query&start=%d&count=100&category3=39&category1=998&sort_by=%s&infinite=1&cc=it&l=english' % (p * 100, sort))
        try: h = json.loads(r)['results_html']
        except Exception: continue
        for row in re.split(r'<a href="https://store.steampowered.com/app/', h)[1:]:
            aid = int(row.split('/')[0])
            t = re.search(r'<span class="title">(.*?)</span>', row)
            rv = re.search(r'(\d+)% of the ([\d,]+) user reviews', html.unescape(row))
            dt = re.search(r'search_released[^>]*>\s*(.*?)\s*<', row, re.S)
            if t and rv: cand[aid] = dict(name=html.unescape(t.group(1)), pct=int(rv.group(1)), n=int(rv.group(2).replace(',', '')), date=dt.group(1).strip() if dt else '')

def recent(d):
    for fmt in ('%d %b, %Y', '%b %d, %Y', '%d %B, %Y'):
        try: return (datetime.date.today() - datetime.datetime.strptime(d, fmt).date()).days <= 120
        except Exception: pass
    return False

# Genere dalle etichette degli utenti Steam (la prima che corrisponde): (etichette, genere IT, genere EN, categorie dell'app)
GENRE = [(('Puzzle Platformer',), 'Puzzle/piattaforme', 'Puzzle platformer', ['puzzle', 'platform']),
         (('Racing', 'Driving'), 'Corse', 'Racing', ['racing']), (('Sports', 'Football (Soccer)', 'Golf', 'Basketball'), 'Sport', 'Sports', ['sports']),
         (('Party Game', 'Party'), 'Party', 'Party', ['party']), (('Rhythm', 'Music'), 'Ritmo', 'Rhythm', ['party']), (("Beat 'em up",), "Beat 'em up", "Beat 'em up", ['fight']),
         (('Farming Sim', 'Life Sim', 'Cozy', 'Relaxing'), 'Rilassante', 'Relaxing', ['sandbox']),
         (('Twin Stick Shooter', 'Top-Down Shooter', 'Shoot \'Em Up', 'FPS', 'Shooter', 'Run and Gun', 'Bullet Hell'), 'Sparatutto', 'Shooter', ['action']),
         (('Roguelike', 'Roguelite', 'Action Roguelike'), 'Azione roguelike', 'Roguelike action', ['action']),
         (('RPG', 'Action RPG', 'JRPG', 'CRPG'), 'Gioco di ruolo', 'RPG', ['rpg']),
         (('Tower Defense', 'Strategy', 'Management', 'Base Building', 'Board Game', 'Card Game'), 'Strategia', 'Strategy', ['strategy']),
         (('Platformer', '2D Platformer', '3D Platformer', 'Precision Platformer'), 'Piattaforme', 'Platformer', ['platform']),
         (('Puzzle',), 'Puzzle co-op', 'Co-op puzzle', ['puzzle']),
         (('Survival', 'Sandbox', 'Crafting', 'Open World Survival Craft'), 'Sandbox/avventura', 'Sandbox/adventure', ['sandbox', 'adventure']),
         (('Adventure', 'Action-Adventure', 'Exploration'), 'Avventura', 'Adventure', ['adventure'])]
CK = {'birthtime': '283993201', 'lastagecheckage': '1-0-1979', 'wants_mature_content': '1'}
def user_tags(aid):
    req = urllib.request.Request('https://store.steampowered.com/app/%d/?l=english' % aid, headers=dict(H, Cookie='; '.join('%s=%s' % kv for kv in CK.items())))
    try: p = urllib.request.urlopen(req, timeout=30).read().decode('utf-8', 'ignore'); time.sleep(1.3)
    except Exception: return None
    return [html.unescape(t) for t in re.findall(r'class="app_tag"[^>]*>\s*([^<]+?)\s*<', p)]
added = []
today = datetime.date.today()
for aid, c in sorted(cand.items(), key=lambda x: -x[1]['n']):
    if len(added) >= MAX_NEW: break
    sc = scartati.get(str(aid))
    if aid in known_ids or (sc and (today - datetime.date.fromisoformat(sc.get('d', '2000-01-01'))).days < 30): continue   # gli scartati si ricontrollano dopo un mese
    ok_reviews = (c['pct'] >= 85 and c['n'] >= 500) or (recent(c['date']) and c['pct'] >= 90 and c['n'] >= 150)
    if not ok_reviews: continue
    def skip(r): scartati[str(aid)] = dict(r=r + ': ' + c['name'], d=today.isoformat())
    if already(c['name']): skip('già in libreria'); continue
    if re.search(r'jackbox|sunderfolk|\bvr\b|soundtrack|demo\b|playtest', c['name'], re.I): skip('escluso (serve internet, il telefono o altro)'); continue
    tags = user_tags(aid)
    if tags is None: continue
    top = tags[:20]
    rank = lambda names: min([top.index(t) for t in names if t in top] or [99])
    if rank(('Local Co-Op', 'Split Screen')) == 99: skip('per gli utenti non è co-op in locale'); continue
    VERSUS = ('Fighting', '2D Fighter', '3D Fighter', 'Wrestling', 'PvP', 'Competitive', 'Arena Shooter', 'eSports', 'Battle Royale')
    coop_rank = rank(('Local Co-Op', 'Split Screen', 'Co-op', 'Co-op Campaign'))
    if rank(VERSUS) < coop_rank or (rank(VERSUS) < 8 and rank(('Co-op', 'Co-op Campaign', 'Local Co-Op')) >= 8): skip('più sfida che co-op'); continue
    if set(top) & {'Software', 'Utilities', 'Sexual Content', 'Nudity', 'NSFW', 'Hentai', 'Dating Sim', 'Massively Multiplayer', 'VR'}: skip('escluso per etichette'); continue
    raw = get('https://store.steampowered.com/api/appdetails?cc=it&l=italian&appids=%d' % aid)
    try: d = (json.loads(raw) or {}).get(str(aid)) or {}
    except Exception: continue
    if not d.get('success'): continue
    it = d['data']
    raw_en = get('https://store.steampowered.com/api/appdetails?cc=it&l=english&appids=%d' % aid)
    try: en = ((json.loads(raw_en) or {}).get(str(aid)) or {}).get('data') or {}
    except Exception: en = {}
    cats = {x['id'] for x in it.get('categories', [])}
    desc = set((it.get('content_descriptors') or {}).get('ids') or [])
    genres_en = [g['description'] for g in en.get('genres', [])]
    why = None
    if it.get('type') != 'game': why = 'non è un gioco'
    elif 39 not in cats: why = 'niente co-op sullo stesso schermo'
    elif 54 in cats: why = 'solo VR'
    elif desc & {1, 3, 4}: why = 'contenuti sessuali'
    elif any(g in genres_en for g in ('Utilities', 'Software', 'Design & Illustration', 'Animation & Modeling', 'Video Production', 'Audio Production')): why = 'non è un gioco'
    if why: skip(why); continue
    pegi = None
    try: pegi = int(((it.get('ratings') or {}).get('pegi') or {}).get('rating'))
    except Exception: pass
    T = set(top)
    rough = bool(T & {'Gore', 'Blood', 'Violent', 'Horror', 'Survival Horror', 'Psychological Horror', 'Mature', 'Zombies'})
    family = bool(T & {'Family Friendly', 'Cute', 'Wholesome'}) and not rough
    age = pegi if pegi else (8 if family else 16 if rough else 12)   # senza PEGI non entra tra i giochi "con i bambini" (fino a 7 anni)
    if rough: age = max(age, 10)                                     # etichette "violento/horror": mai tra i giochi per bambini
    if 2 in desc or (pegi and pegi >= 16) or (rough and not pegi): v = 'Realistica'; age = max(age, pegi or 16)
    elif 5 in desc or age >= 12: v = 'Lieve'
    elif T & {'Action', 'Shooter', "Beat 'em up", 'Combat'}: v = 'Cartoon'
    else: v = 'Nessuna'
    age = max(age, 5)
    # genere = quello dell'etichetta più votata; categorie = quelle delle prime 10 etichette
    gi = min(GENRE, key=lambda g: rank(g[0])) if any(rank(g[0]) < 99 for g in GENRE) else (None, 'Co-op', 'Co-op', ['party'])
    t10 = set(top[:10])
    catl = sorted({x for g in GENRE if t10 & set(g[0]) for x in g[3]} | set(gi[3]) | ({'chaos'} if t10 & {'Physics', 'Funny'} else set()))[:4] or ['party']
    pl, pmax = ('1-4', 4) if '4 Player Local' in T else ('2', 2) if 'Local Co-Op' in T and 'Singleplayer' not in T else ('1-2', 2)
    e = 3 if T & {'Difficult', 'Souls-like', 'Precision Platformer'} else 1 if T & {'Casual', 'Relaxing', 'Family Friendly', 'Cozy'} else 2
    price = 0.0 if it.get('is_free') else ((it.get('price_overview') or {}).get('final', 0) / 100 or None)
    name = it.get('name') or c['name']
    gid = 'steam-' + slug(name)
    shots = [s['path_full'] for s in it.get('screenshots', [])][:3]
    thumbs = [s['path_thumbnail'] for s in it.get('screenshots', [])][:3]
    cover = 'https://shared.akamai.steamstatic.com/store_item_assets/steam/apps/%d/library_600x900.jpg' % aid
    if not get(cover, 1): cover = it.get('header_image')
    s = 5 if c['pct'] >= 95 and c['n'] >= 2000 else 4 if c['pct'] >= 88 else 3
    strip = lambda x: re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', x or ''))).strip()
    g = dict(id=gid, appid=aid, auto=True, t=name, en=en.get('name') if en.get('name') != name else None, sw=False, s2=False, ps=False, pc=True,
             mini=None, orig=None, ge=gi[1], ge_en=gi[2], pl=pl, pmax=pmax,
             k=('Co-op a schermo diviso' if 'Split Screen' in T else 'Co-op sullo stesso schermo') + ', un controller a testa',
             k_en=('Split-screen co-op' if 'Split Screen' in T else 'Same-screen co-op') + ', one controller each',
             no=strip(it.get('short_description'))[:300], no_en=strip(en.get('short_description'))[:300], kw=' '.join(top),
             e=e, a=0 if age >= 8 else 2, age=age, ad=3, cp=0, v=v, s=s, h=None, th=None, cats=catl, tags=['animals'] if T & {'Cats', 'Dog', 'Animals'} else [],
             pr=dict(steam=price, steamUrl='https://store.steampowered.com/app/%d/' % aid) if price is not None else dict(steamUrl='https://store.steampowered.com/app/%d/' % aid),
             ch=[], rv=dict(pct=c['pct'], n=c['n']), added=datetime.date.today().isoformat())
    AUTO['games'].append(g); AUTO['imgs'][gid] = dict(c=cover, s=shots, t=thumbs)
    known_titles.append(norm(name)); known_ids.add(aid); added.append(name)
    print('AGGIUNTO', name, c['pct'], c['n'], '| PEGI', pegi, '| età', age, v, '|', gi[1], catl, pl, '| tag:', ', '.join(top[:8]), flush=True)

AUTO['version'] = int(datetime.datetime.now().strftime('%Y%m%d%H%M'))
json.dump(AUTO, open(AUTO_P, 'w', encoding='utf-8'), ensure_ascii=False, separators=(',', ':'))
print('nuovi giochi:', len(added), '| totale automatici:', len(AUTO['games']), '| candidati visti:', len(cand), '| scartati:', len(scartati))
