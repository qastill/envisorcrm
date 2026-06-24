"""
============================================================
ENVISOR — WEB DATA EXPORT  (rolling latest 3 months)
============================================================
Tujuan : Baca folder "OLAP JABAR 2025" di Google Drive, hitung analisa
         CRM kVArh, lalu tulis 1 file kecil  ->  envisor_web_data.json
         (cuma pelanggan yang kena denda kVArh, 3 bulan TERBARU).

Output : <folder OLAP>/envisor_web_data.json   (± 1-2 MB)
         File ini yang dipublish ke web (index.html  ->  data.json).

Cara pakai (tiap bulan):
  1. Upload file OLAP bulan baru ke folder "OLAP JABAR 2025" di Drive.
  2. Buka notebook ini di Google Colab -> Runtime -> Run all.
  3. Setelah muncul "SAVED ... envisor_web_data.json", minta Claude
     untuk "publish dashboard" (Claude tarik file ini & update web).

Rumus sudah diverifikasi 1:1 dengan build CRM awal (Jan/Feb/Mar 2026).
============================================================
"""

import os, glob, re, json, gc
from collections import defaultdict
from datetime import date
import pandas as pd

# ── 0. Mount Drive (aman dipanggil ulang) ─────────────────────────────
try:
    from google.colab import drive
    if not os.path.exists('/content/drive/MyDrive'):
        drive.mount('/content/drive')
except Exception:
    pass  # bukan di Colab

def find_folder(base, name):
    for root, dirs, _ in os.walk(base):
        if name in dirs:
            return os.path.join(root, name)
    return None

FOLDER = (find_folder('/content/drive', 'OLAP JABAR 2025')
          or find_folder('/content/drive', 'olap 2025'))
assert FOLDER, "❌ Folder 'OLAP JABAR 2025' tidak ditemukan di Drive."
print("📂 Folder:", FOLDER)

# ── 1. Konstanta / mapping (terverifikasi dari data asli) ─────────────
TARIF_KVARH = {'B2':1000,'B3':1050,'C':1000,'I2':900,'I3':1114,'I3P':1114,
               'I4':1000,'LB3':1000,'P2':950,'S2':1000,'S2K':950}
HARGA_TR, HARGA_TM = 300_000, 550_000      # < / > 1 MVA
FIXED_INSTALL      = 10_000_000            # biaya pasang tetap (Rp)
KVAR_SAFETY        = 1.2                   # kvar_rec = 1.2 x kvar_min

MONTHS_SHORT = ['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des']
MONTHS_LONG  = ['Januari','Februari','Maret','April','Mei','Juni','Juli','Agustus',
                'September','Oktober','November','Desember']
BULAN_KEY = {'januari':1,'jan':1,'februari':2,'feb':2,'maret':3,'mar':3,'april':4,'apr':4,
             'mei':5,'may':5,'juni':6,'jun':6,'juli':7,'jul':7,'agustus':8,'agu':8,'agus':8,
             'agt':8,'aug':8,'september':9,'sept':9,'sep':9,'oktober':10,'okt':10,'oct':10,
             'november':11,'nov':11,'desember':12,'des':12,'dec':12}

def detect_month_year(stem):
    s = stem.lower()
    my = re.search(r'(20\d{2})', s)
    year = int(my.group(1)) if my else None
    mon = None
    for tok in sorted(BULAN_KEY, key=len, reverse=True):   # token terpanjang dulu
        if re.search(r'(?<![a-z])' + tok, s):
            mon = BULAN_KEY[tok]; break
    return year, mon

# ── 2. Peta ULP -> (kode UP3, nama UP3, nama ULP) dari "KODE UP.xlsx" ──
def load_ulpmap(folder):
    m = {}
    for f in glob.glob(os.path.join(folder, '*.xls*')):
        if 'KODE' not in os.path.basename(f).upper():
            continue
        try:
            raw = pd.read_excel(f, header=None, dtype=str)
            for _, r in raw.iterrows():
                up3c, ulpc, up3n, ulpn = r.get(5), r.get(6), r.get(7), r.get(8)
                if pd.isna(ulpc) or pd.isna(up3n):
                    continue
                if str(up3c).upper().startswith('KODE'):
                    continue
                try:
                    key = int(float(str(ulpc).strip()))
                except Exception:
                    continue
                m[key] = (str(up3c).strip(),
                          str(up3n).strip().title(),
                          '' if pd.isna(ulpn) else str(ulpn).strip().title())
        except Exception as e:
            print("  ⚠️ KODE UP:", e)
    print(f"🗺️  Peta ULP: {len(m)} entri")
    return m
ULPMAP = load_ulpmap(FOLDER)

# ── 3. Deteksi & pilih 3 bulan TERBARU ────────────────────────────────
cand = []
for f in glob.glob(os.path.join(FOLDER, '*.xlsx')) + glob.glob(os.path.join(FOLDER, '*.csv')):
    b = os.path.basename(f)
    if 'KODE' in b.upper():
        continue
    y, mo = detect_month_year(os.path.splitext(b)[0])
    if y and mo:
        cand.append((y, mo, f, b))
seen = {}
for y, mo, f, b in sorted(cand, key=lambda x: (x[0], x[1])):
    seen[(y, mo)] = (f, b)                 # dedup: file terakhir menang
latest3 = sorted(seen.items())[-3:]
assert latest3, "❌ Tidak ada file bulanan terdeteksi (cek nama file)."
print("🗓️  3 bulan terbaru:", [f"{MONTHS_LONG[mo-1]} {y}" for (y, mo), _ in latest3])

# ── 4. Baca kolom yang diperlukan saja ────────────────────────────────
NEED = ['IDPEL','NAMA','ALAMAT','TARIF','DAYA','UNITAP','UNITUP',
        'NAMAGARDU','PEMKWH','RPKVARH','RPTAG','JAMNYALA']
def norm(df):
    df.columns = [str(c).strip().upper().replace(' ', '_') for c in df.columns]
    return df

def _sniff_sep(path):
    """Tebak delimiter dari baris pertama (,/;/tab/|)."""
    try:
        with open(path, 'r', encoding='utf-8', errors='ignore') as fh:
            line = fh.readline()
        cand = {d: line.count(d) for d in [',', ';', '\t', '|']}
        best = max(cand, key=cand.get)
        return best if cand[best] > 0 else ','
    except Exception:
        return ','

def read_needed(path):
    """Baca file -> hanya kolom NEED. Robust terhadap delimiter, encoding,
    dan baris judul di atas header (coba header di baris 0/1/2)."""
    is_csv = path.lower().endswith('.csv')
    makers = []
    if is_csv:
        sep = _sniff_sep(path)
        for enc in ('utf-8', 'latin1'):
            makers.append(lambda hdr, enc=enc, sep=sep: pd.read_csv(
                path, dtype=str, low_memory=False, on_bad_lines='skip',
                sep=sep, encoding=enc, header=hdr))
        # fallback terakhir: biarkan pandas menebak delimiter sendiri
        makers.append(lambda hdr: pd.read_csv(
            path, dtype=str, sep=None, engine='python',
            on_bad_lines='skip', header=hdr))
    else:
        makers.append(lambda hdr: pd.read_excel(path, dtype=str, header=hdr))

    df = None
    for make in makers:
        for hdr in (0, 1, 2):
            try:
                cand = norm(make(hdr))
            except Exception:
                continue
            if 'IDPEL' in cand.columns:
                df = cand
                break
        if df is not None:
            break

    fname = os.path.basename(path)
    if df is None:
        raise ValueError(f"❌ Kolom IDPEL tak ditemukan di '{fname}'. "
                         f"Cek delimiter / format file.")
    if 'RPKVARH' not in df.columns:
        raise ValueError(f"❌ '{fname}' tidak punya kolom RPKVARH (denda kVArh). "
                         f"Kolom terbaca: {list(df.columns)[:20]}. "
                         f"Pastikan file OLAP lengkap (bukan ekspor 3-kolom).")
    keep = [c for c in NEED if c in df.columns]
    miss = [c for c in ('DAYA','TARIF','UNITUP','JAMNYALA') if c not in df.columns]
    if miss:
        print(f"   ⚠️ {fname}: kolom opsional hilang {miss}")
    return df[keep].copy()

def fix_idpel(x):
    x = str(x).strip()
    if 'E+' in x.upper() or re.fullmatch(r'\d+\.\d+', x):
        try: return str(int(float(x)))
        except Exception: return x
    return x.split('.')[0]

def num(s): return pd.to_numeric(s, errors='coerce').fillna(0)

slots = []           # list of (year, mon, dataframe)
for (y, mo), (f, b) in latest3:
    df = read_needed(f)
    df['IDPEL'] = df['IDPEL'].map(fix_idpel)
    for c in ['PEMKWH','RPKVARH','RPTAG','DAYA','UNITUP','JAMNYALA']:
        if c in df.columns: df[c] = num(df[c])
    df = df[df['IDPEL'].str.len() >= 6]
    slots.append((y, mo, df))
    print(f"   ✅ {MONTHS_LONG[mo-1]} {y}: {len(df):,} baris  <- {b}")

m_short = [MONTHS_SHORT[mo-1] for (y, mo, _) in slots]
m_long  = [MONTHS_LONG[mo-1]  for (y, mo, _) in slots]
year_latest = slots[-1][0]

# info pelanggan diambil dari bulan terbaru
info = slots[-1][2].drop_duplicates('IDPEL').set_index('IDPEL')

# ── 5. Agregasi per pelanggan lintas 3 slot ───────────────────────────
denda, kwh, jamny, tag_latest = {}, {}, {}, {}
for i, (y, mo, df) in enumerate(slots):
    g = df.groupby('IDPEL').agg(rpkvarh=('RPKVARH','sum'),
                                pemkwh=('PEMKWH','sum'),
                                rptag=('RPTAG','sum'),
                                jam=('JAMNYALA','mean'))
    for idp, row in g.iterrows():
        denda.setdefault(idp, [0,0,0])[i] = float(row['rpkvarh'])
        kwh.setdefault(idp,   [0,0,0])[i] = float(row['pemkwh'])
        jamny.setdefault(idp, [0,0,0])[i] = float(row['jam'])
        if i == len(slots) - 1:
            tag_latest[idp] = float(row['rptag'])

def cell(row, col, default=''):
    if row is None or col not in row.index: return default
    v = row[col]
    return default if pd.isna(v) else v

leads = []
for idp, d in denda.items():
    pen = [x for x in d if x > 0]
    months = len(pen)
    if months == 0:                      # tanpa denda kVArh -> bukan lead
        continue
    avg = sum(pen) / months
    ks  = [x for x in kwh.get(idp, [0,0,0]) if x > 0]
    kwh_avg = round(sum(ks) / len(ks)) if ks else 0
    js  = [x for x in jamny.get(idp, [0,0,0]) if x > 0]
    jam = round(sum(js) / len(js), 1) if js else 0

    r = info.loc[idp] if idp in info.index else None
    daya  = float(cell(r, 'DAYA', 0) or 0)
    tarif = str(cell(r, 'TARIF', '') or '').strip()
    tk    = TARIF_KVARH.get(tarif, 1000)

    kvar_min = round((avg / tk) / jam) if jam > 0 else 0
    kvar_rec = round(KVAR_SAFETY * kvar_min)
    harga    = HARGA_TM if daya > 1_000_000 else HARGA_TR
    invest   = kvar_rec * harga + FIXED_INSTALL
    roi      = min(99, round(invest / avg, 1)) if avg > 0 else 99
    tag      = tag_latest.get(idp, 0)
    rasio    = round(avg / tag * 100, 1) if tag > 0 else 0

    ulp_num = int(cell(r, 'UNITUP', 0) or 0)
    unitap  = str(cell(r, 'UNITAP', '') or '').strip()
    up3c, up3n, ulpn = ULPMAP.get(ulp_num, (unitap, unitap, str(ulp_num)))

    is_c3, is_c2 = months == 3, months >= 2
    if months == 3:   freq = '🔴 3 Bulan'
    elif months == 2: freq = '🟡 2 Bulan'
    else:             freq = '⚪ ' + m_short[d.index(next(x for x in d if x > 0))]

    if months == 3:   pri = 'URGENT' if avg >= 30e6 else 'HIGH'
    elif months == 2: pri = 'HIGH'   if avg >= 50e6 else 'MEDIUM'
    else:             pri = 'MEDIUM' if avg >= 10e6 else 'LOW'

    leads.append({
        'id': idp, 'nama': str(cell(r,'NAMA','') or '').strip(),
        'alamat': str(cell(r,'ALAMAT','') or '').strip(), 'tarif': tarif,
        'daya_va': int(daya), 'denda_avg': round(avg),
        'denda_jan': round(d[0]), 'denda_feb': round(d[1]), 'denda_mar': round(d[2]),
        'tagihan': round(tag), 'rasio': rasio, 'jam_nyala': jam, 'kwh_avg': kwh_avg,
        'up3_code': up3c, 'up3': up3n, 'ulp_num': ulp_num, 'ulp': ulpn,
        'gardu': str(cell(r,'NAMAGARDU','') or '').strip(),
        'tarif_kvarh': tk, 'kvar_min': kvar_min, 'kvar_rec': kvar_rec, 'harga_kvar': harga,
        'invest_est': invest, 'roi_bulan': roi, 'freq': freq, 'months': months,
        'is_c3': is_c3, 'is_c2': is_c2, 'priority': pri,
        'stage': 'prospek', 'contact': '', 'next_action': '', 'notes': '',
    })

# urutkan: prioritas -> denda terbesar (rank kartu)
po = {'URGENT':0,'HIGH':1,'MEDIUM':2,'LOW':3}
leads.sort(key=lambda l: (po.get(l['priority'], 3), -l['denda_avg']))
print(f"\n👥 Lead (kena denda kVArh): {len(leads):,}")

# ── 6. Hierarki UP3 -> ULP (untuk filter & treemap) ───────────────────
H = {}
for l in leads:
    h = H.setdefault(l['up3_code'], {'code': l['up3_code'], 'name': l['up3'],
                                     'leads': 0, 'denda': 0, 'ulps': {}})
    h['leads'] += 1; h['denda'] += l['denda_avg']
    u = h['ulps'].setdefault(l['ulp_num'], {'num': l['ulp_num'], 'name': l['ulp'],
                                            'leads': 0, 'denda': 0})
    u['leads'] += 1; u['denda'] += l['denda_avg']
hierarchy = []
for h in H.values():
    ulps = sorted(h['ulps'].values(), key=lambda u: -u['denda'])
    hierarchy.append({'code': h['code'], 'name': h['name'], 'leads': h['leads'],
                      'denda': round(h['denda']),
                      'ulps': [{'num': u['num'], 'name': u['name'], 'leads': u['leads'],
                                'denda': round(u['denda'])} for u in ulps]})
hierarchy.sort(key=lambda x: -x['denda'])

# ── 7. Tulis JSON ─────────────────────────────────────────────────────
meta = {
    'schema_version': 1,
    'period_label': '·'.join(m_short) + f' {year_latest}',
    'months_short': m_short, 'months_long': m_long, 'year': year_latest,
    'n_up3': len(hierarchy), 'n_ulp': len({l['ulp_num'] for l in leads}),
    'generated': str(date.today()),
    'source': 'OLAP JABAR 2025 (auto-generated by Colab)',
}
out = {'meta': meta, 'leads': leads, 'hierarchy': hierarchy}

out_path = os.path.join(FOLDER, 'envisor_web_data.json')
with open(out_path, 'w', encoding='utf-8') as fp:
    json.dump(out, fp, ensure_ascii=False, separators=(',', ':'))

size_mb = os.path.getsize(out_path) / 1024 / 1024
print(f"\n💾 SAVED: {out_path}  ({size_mb:.2f} MB)")
print(f"   Periode : {meta['period_label']}")
print(f"   UP3/ULP : {meta['n_up3']} / {meta['n_ulp']}")
print(f"   URGENT  : {sum(1 for l in leads if l['priority']=='URGENT')}")
print("\n✅ Selesai. Minta Claude untuk 'publish dashboard'.")
