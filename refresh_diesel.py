"""Crude-to-Pump Monitor - refresh.

Downloads the latest public data, rebuilds data.json and diesel.html.
  MBIE weekly fuel price monitoring, via data.govt.nz (mbie.govt.nz blocks scripted downloads)
  FRED DCOILBRENTEU (Brent spot, USD/bbl) and DEXUSNZ (US$ per NZ$)
No login or API key. Standard library only.

Run:  python refresh_diesel.py          (the Thursday scheduled task runs this)
Output: data.json and diesel.html in this folder. The previous data.json is kept in backup/.
"""
import csv, datetime as dt, io, json, os, shutil, sys, urllib.request
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
START = "2025-02"          # base month; the page shows changes from the month after
MBIE = ("https://catalogue.data.govt.nz/dataset/f4ac4dad-6e52-4100-bbb6-00e132935cfa/resource/"
        "9b8bba4c-0ac4-4116-97ab-2a75415da233/download/weekly-table.csv")
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s"
LITRES_PER_BBL = 158.987


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (EA diesel monitor)"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read().decode("utf-8-sig")


def fred(series):
    out = {}
    for row in csv.DictReader(io.StringIO(get(FRED % series))):
        v = row.get(series)
        if v not in (None, "", "."):
            out[dt.date.fromisoformat(row["observation_date"])] = float(v)
    if not out:
        raise RuntimeError("FRED %s returned no data" % series)
    return out


def mbie():
    w = defaultdict(dict)
    text = get(MBIE)
    if not text.startswith('"Week"'):
        raise RuntimeError("MBIE file did not come back as the expected CSV")
    for row in csv.DictReader(io.StringIO(text)):
        if row["Fuel"] != "Diesel" or row["Unit"] != "NZD c/L":
            continue
        k = {"Board price": "diesel", "Adjusted retail price": "adj", "Importer cost": "importer"}.get(row["Variable"])
        if k:
            d = dt.date.fromisoformat(row["Date"])
            w[d][k] = float(row["Value"])
            w[d]["prov"] = row["Status"] != "Final"
    return {d: v for d, v in w.items() if "diesel" in v and "adj" in v}


def ym(d):
    return "%04d-%02d" % (d.year, d.month)


def month_days(m):
    y, mo = map(int, m.split("-"))
    d = dt.date(y, mo, 1)
    while d.month == mo:
        yield d
        d += dt.timedelta(days=1)


def interpolate(weekly, key):
    """Weekly values to daily by straight-line interpolation between observations."""
    ds = sorted(weekly)
    daily = {}
    for a, b in zip(ds, ds[1:]):
        va, vb, n = weekly[a][key], weekly[b][key], (b - a).days
        for i in range(n):
            daily[a + dt.timedelta(days=i)] = va + (vb - va) * i / n
    daily[ds[-1]] = weekly[ds[-1]][key]
    return daily


def build():
    W = mbie()
    B, F = fred("DCOILBRENTEU"), fred("DEXUSNZ")
    last_w, last_b, last_f = max(W), max(B), max(F)
    today = dt.date.today()
    months = sorted({ym(d) for d in W if ym(d) >= START})
    dd, da = interpolate(W, "diesel"), interpolate(W, "adj")
    mean = lambda xs: sum(xs) / len(xs) if xs else None
    rnd = lambda v, n=4: None if v is None else round(v, n)
    rows = []
    for m in months:
        wk = [d for d in W if ym(d) == m]
        b = [v for d, v in B.items() if ym(d) == m]
        f = [v for d, v in F.items() if ym(d) == m]
        if not (b and f):
            continue
        brent, fx = mean(b), mean(f)
        # NZD Brent: mean of daily Brent / USD-NZD, on days both series have a value
        bn = mean([v / F[d] for d, v in B.items() if ym(d) == m and d in F])
        r = dict(month=m, brent=rnd(brent), brent_n=len(b), usdnzd=rnd(fx), brent_nzd=rnd(bn),
                 brent_cpl=rnd(bn / LITRES_PER_BBL * 100),
                 diesel=rnd(mean([W[d]["diesel"] for d in wk])), diesel_adj=rnd(mean([W[d]["adj"] for d in wk])),
                 importer=rnd(mean([W[d]["importer"] for d in wk if "importer" in W[d]])), weeks=len(wk),
                 mtd=m == ym(today),
                 provisional=any(W[d]["prov"] for d in wk))
        days = list(month_days(m))
        for lag in (0, 30, 60):
            shifted = [d + dt.timedelta(days=lag) for d in days]
            have = [d for d in shifted if d in dd]
            r["d%d" % lag] = rnd(mean([dd[d] for d in have])) if have else None
            r["da%d" % lag] = rnd(mean([da[d] for d in have])) if have else None
            r["cov%d" % lag] = round(len(have) / len(days), 4)
        rows.append(r)
    weekly = [dict(date=d.isoformat(), diesel=round(W[d]["diesel"], 2), adj=round(W[d]["adj"], 2))
              for d in sorted(W) if ym(d) > START]
    return dict(monthly=rows, weekly=weekly,
                meta=dict(mbie_last=last_w.isoformat(), brent_last=last_b.isoformat(), nzd_last=last_f.isoformat(),
                          refreshed=dt.datetime.now().strftime("%Y-%m-%d %H:%M")))


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.replace(tmp, path)


def main():
    data = build()
    if len(data["monthly"]) < 12:
        raise RuntimeError("Only %d months built - not overwriting" % len(data["monthly"]))
    js = os.path.join(HERE, "data.json")
    if os.path.exists(js):
        os.makedirs(os.path.join(HERE, "backup"), exist_ok=True)
        shutil.copy2(js, os.path.join(HERE, "backup", "data_%s.json" % dt.date.today().isoformat()))
    payload = json.dumps(data, separators=(",", ":"))
    write_atomic(js, payload)
    tpl = open(os.path.join(HERE, "template.html"), encoding="utf-8").read()
    if "/*DATA*/null" not in tpl:
        raise RuntimeError("template.html is missing the /*DATA*/null placeholder")
    write_atomic(os.path.join(HERE, "diesel.html"), tpl.replace("/*DATA*/null", payload))
    last = data["monthly"][-1]
    print("Refreshed %s: MBIE to %s, Brent to %s, %d months, latest %s diesel %.1f c/L, Brent $%.2f"
          % (data["meta"]["refreshed"], data["meta"]["mbie_last"], data["meta"]["brent_last"],
             len(data["monthly"]), last["month"], last["diesel"], last["brent"]))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("Diesel refresh FAILED: %s" % e, file=sys.stderr)
        sys.exit(1)
