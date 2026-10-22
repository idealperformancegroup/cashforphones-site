"""Build prices.js from the weekly buyer price sheets.

Usage: python3 tools/build_prices.py <device-buyers.txt> <bestdealphones.txt> [out=prices.js]

Inputs are the sheet text dumps (Google Drive "contentSnippet" of each sheet).
For every model / storage / lock / grade it keeps the HIGHER of the two buyers.
For add-on deductions (cracked back, lens) it keeps the LARGER of the two, so offers stay safe.
"""
import json, re, sys
from datetime import date

GRADES = ["S", "O", "A", "B", "BC", "C", "D", "DOA"]  # sealed, open, A, B, B-/C+, C, D, DOA
DB_ONLY = {}  # Device Buyers unlocked iPhone prices: the only buyer that takes blacklisted phones
TOO_OLD = {"iPhone 8", "iPhone 8 Plus", "iPhone X"}  # we buy iPhone XR and newer

def money(x):
    x = x.strip().replace("$", "").replace(",", "")
    return int(float(x)) if re.fullmatch(r"\d+(\.\d+)?", x) and float(x) > 0 else None

def sections(path):
    out, cur = {}, None
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("# "):
            cur = line[2:].strip().replace("\\", ""); out[cur] = []
        elif cur is not None:
            out[cur].append(line.rstrip())
    return out

def split_money(s):
    """Split '$1,005,$970,ask,$0' into cells, keeping thousands separators inside a value."""
    return [c.strip() for c in re.split(r",(?=\s*(?:\$|[A-Za-z]|-|$))", s)]

def put(table, model, storage, lock, grade, price):
    if price is None: return
    slot = table.setdefault(model, {"st": [], "P": {}, "back": None, "lens": None})
    if storage not in slot["st"]: slot["st"].append(storage)
    g = slot["P"].setdefault(storage, {}).setdefault(lock, {})
    if price > g.get(grade, 0): g[grade] = price

def ded(table, model, key, val):
    if val is None: return
    slot = table.setdefault(model, {"st": [], "P": {}, "back": None, "lens": None})
    slot[key] = max(slot[key] or 0, val)

# ---------- iPhone names ----------
def iphone_name(raw):
    s = raw.upper().replace("IPHONE", "").strip()
    s = re.sub(r"\s+", " ", s)
    if re.search(r"SE \(?(3RD|3)", s): return "iPhone SE (3rd gen)"
    if re.search(r"SE \(?(2020|2ND|2)\b", s) or s == "SE 2": return "iPhone SE (2nd gen)"
    s = s.title().replace("Xs", "XS").replace("Xr", "XR").replace("17E", "17e").replace("16E", "16e")
    return "iPhone " + s

def storage_norm(s):
    m = re.search(r"(\d+)\s*(GB|G|TB|T)\b", s, re.I)
    if not m: return None
    return m.group(1) + ("TB" if m.group(2).upper().startswith("T") else "GB")

def parse_db_iphones(secs, T):
    cols = ["S", "O", None, "A", "B", "BC", "C", "D", "DOA"]  # HSO column skipped
    pending = {}
    for line in secs.get("iPhones", []):
        m = re.match(r"Cracked Back = \$(\d+) off / Cracked Lens = \$(\d+)", line)
        if m: pending = {"back": int(m.group(1)), "lens": int(m.group(2))}; continue
        m = re.match(r"^((?:iPhone )?(?:\d+|XS Max|XS|XR|SE)[^,]*?)\s+(\d+\s*(?:GB|TB))\s+(Unlocked|Carrier Locked),(.*)$", line)
        if not m: continue
        model = iphone_name(m.group(1)); st = storage_norm(m.group(2)); lock = "U" if m.group(3) == "Unlocked" else "L"
        if pending:
            for k, v in pending.items(): ded(T, model, k, v)
            pending = {}
        cells = split_money(m.group(4))
        for c, g in zip(cells, cols):
            if g:
                put(T, model, st, lock, g, money(c))
                if lock == "U" and DB_ONLY is not None: put(DB_ONLY, model, st, "U", g, money(c))

def parse_bdp_iphones(secs, T):
    cur, lock = None, "U"
    for line in secs.get("-USED iPhone-", []):
        m = re.match(r"USED IPHONE ([^,]+),", line)
        if m:
            cur = None if "DUO" in m.group(1) else iphone_name(m.group(1)); lock = None; continue
        if not cur: continue
        mb = re.search(r"Crack Back -\s?\$?(\d+)", line); ml = re.search(r"Crack Cam lens -\s?\$?(\d+)", line)
        if mb and (lock in (None, "U")): ded(T, cur, "back", int(mb.group(1)))
        if ml and (lock in (None, "U")): ded(T, cur, "lens", int(ml.group(1)))
        if re.match(r"^[^,]+,HSO / SWAP", line):
            lock = "U" if lock is None else "L"; continue
        cells = [c.strip() for c in line.split(",")]
        i = next((k for k, c in enumerate(cells) if re.fullmatch(r"\d+(GB|TB)", c)), None)
        if i is None or lock is None: continue
        st = cells[i]; vals = split_money(",".join(cells[i + 1:]))
        for v, g in zip(vals, ["A", "B", "C", "D", "DOA"]):
            put(T, cur, st, lock, g, money(v))
    cur, lock = None, "U"
    for line in secs.get("-NEW iPhone-", []):
        m = re.match(r"NEW IPHONE ([^,]+),", line)
        if m: cur = None if "DUO" in m.group(1) else iphone_name(m.group(1)); lock = "U"; continue
        if not cur: continue
        if line.startswith("LOCK CARRIER"): lock = "L"
        cells = [c.strip() for c in line.split(",")]
        i = next((k for k, c in enumerate(cells) if re.fullmatch(r"\d+(GB|TB)", c)), None)
        if i is None: continue
        rest = re.sub(r",\s*\d+(GB|TB)\s*$", "", ",".join(cells[i + 1:]))  # rows repeat the storage at the end
        vals = split_money(rest)
        for v, g in zip(vals, ["S", "O"]): put(T, cur, cells[i], lock, g, money(v))

def parse_db_icloud(secs):
    out = {}
    for line in secs.get("iCloud/Parts Only", []):
        m = re.match(r"^((?:iPhone|IPhone|i)\s?[^,(]+?)\s*\(Cracked Back -\s?\$?(\d+)[^)]*\),(.*)$", line)
        if not m or "Duo" in m.group(1): continue
        name = m.group(1).replace("IPhone", "iPhone")
        name = re.sub(r"^i(\d)", r"iPhone \1", name)
        model = iphone_name(name); vals = split_money(m.group(3))
        out[model] = {"back": int(m.group(2))}
        for v, g in zip(vals, ["AB", "C", "D", "DOA"]):
            p = money(v)
            if p: out[model][g] = p
    return out

# ---------- Samsung ----------
def sam_name(raw):
    s = raw.upper().replace("GALAZY", "GALAXY").replace("GALAXY", "").strip()
    s = s.replace("PLUS", "+").replace(" +", "+")
    s = re.sub(r"^(FOLD|FLIP)", r"Z \1", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.title().replace("Fe", "FE").replace("S10E", "S10e")
    return "Galaxy " + s

def sam_ok(name):
    m = re.search(r"(S|Note )(\d+)", name)
    if "Fold" in name or "Flip" in name: return True
    return bool(m) and int(m.group(2)) >= 10

def parse_db_samsung(secs, T):
    cols = ["S", "A", "B", "C", "D", "DOA"]; cur = None; back = None
    for line in secs.get("Samsung", []):
        mb = re.match(r"Cracked Back - \$(\d+) off", line)
        if mb: back = int(mb.group(1))
        m = re.match(r"^([^,]+),(Unlocked),(.*)$", line)
        if m:
            cur = sam_name(m.group(1))
            if not sam_ok(cur): cur = None; continue
            if back: ded(T, cur, "back", back)
            back = None
            for v, g in zip(split_money(m.group(3)), cols): put(T, cur, "*", "U", g, money(v))
            continue
        if cur and re.match(r"^(Carrier Locked|AT&T|ATT|TM|SP|VZ|T-Mobile)[^,]*,", line):
            vals = split_money(line.split(",", 1)[1])
            for v, g in zip(vals, cols):
                p = money(v)
                if p is None: continue
                slot = T[cur]["P"].setdefault("*", {}).setdefault("L", {})
                slot[g] = min(slot.get(g, p), p)  # carriers differ: keep the lowest, we don't ask which carrier
                if "*" not in T[cur]["st"]: T[cur]["st"].append("*")
        elif line and not line.startswith(("Cracked", "C/D", "DEDUCTION", "NEW", "Must", "NOT", "**")) and "," not in line:
            cur = None

def parse_bdp_samsung(secs, T):
    cur = None
    for line in secs.get("Samsung", []):
        m = re.match(r"^((?:GALAXY |Z )[^,]+),NEW", line)  # some headers drop "GALAXY" (Z FOLD 6)
        if m:
            cur = sam_name(m.group(1)); cur = cur if sam_ok(cur) else None; continue
        if not cur: continue
        if line.startswith("UNLOCKED,"): lock, cols = "U", ["S", "A", "B", "BC", "C", "D"]
        elif line.startswith("LOCK CARRIER,"): lock, cols = "L", ["S", "A", "B", "BC", "C", "D"]
        else: continue
        for v, g in zip(split_money(line.split(",", 1)[1]), cols): put(T, cur, "*", lock, g, money(v))

# ---------- iPad ----------
def ipad_key(raw):
    s = raw.upper().replace('"', " ").replace("INCH", " ")
    line = "Pro" if "PRO" in s and "A17" not in s else "Air" if "AIR" in s else "mini" if "MINI" in s else "iPad"
    size = next((z for z in ["12.9", "13", "11", "10.5", "9.7"] if re.search(r"(?<![\d.])" + re.escape(z) + r"(?![\d])", s)), "")
    chip = re.search(r"\b(M[2-5]|A16|A17)\b", s)
    gen = re.search(r"\(?(\d+)(?:ST|ND|RD|TH)? GEN\)?|GEN (\d)|(?:AIR|MINI) (\d)\b|IPAD (\d+)(?:TH)?\b", s)
    year = re.search(r"\b(2024|2025)\b", s)
    c = chip.group(1) if chip else None
    if line == "Air" and year: c = {"2024": "M2", "2025": "M3"}[year.group(1)]
    if line == "Air" and c is None and re.search(r"AIR (7|8)\b", s): c = {"7": "M3", "8": "M4"}[re.search(r"AIR (7|8)\b", s).group(1)]
    g = next((x for x in (gen.groups() if gen else []) if x), None)
    if line == "iPad" and c == "A16": g = None
    if line == "iPad" and size == "11" and c == "A16": size = ""
    if line in ("Air", "iPad", "mini") and size in ("11", "13") and not c and line != "Air": size = ""
    if line == "mini": size = ""
    if line == "iPad" and g and int(g) == 11: g = None
    name = {"Pro": "iPad Pro", "Air": "iPad Air", "mini": "iPad mini", "iPad": "iPad"}[line]
    if size: name += f' {size}"'
    if c: name += f" ({'A17 Pro' if c == 'A17' else c})"
    elif g: name += f" ({g}{'st' if g == '1' else 'nd' if g == '2' else 'rd' if g == '3' else 'th'} gen)"
    return name

def ipad_ok(name):
    if "mini" in name: m = re.search(r"\((\d)", name); return "A17" in name or (m and int(m.group(1)) >= 5)
    if name.startswith("iPad (") and "A16" not in name: return int(re.search(r"\((\d+)", name).group(1)) >= 9
    return not any(x in name for x in ['9.7"', '10.5"', '12.9" (1st', '12.9" (2nd'])

def parse_db_ipads(secs, T):
    cols = ["S", "O", "A", "B", "BC", "C", "D"]
    for line in secs.get("iPads", []):
        m = re.match(r"^([^,]*?)\s*(\d+\s*(?:GB|G|TB|T))\s+(WiFi|Wifi|WIfi|WIFI|Cellular|CELL|4G)[^,]*,(.*)$", line, re.I)
        if not m or not re.search(r"wi", m.group(3), re.I): continue
        name = ipad_key(m.group(1) if re.search(r"ipad|mini", m.group(1), re.I) else "iPad " + m.group(1))
        if not ipad_ok(name): continue
        for v, g in zip(split_money(m.group(4)), cols): put(T, name, storage_norm(m.group(2)), "U", g, money(v))

def parse_bdp_ipads(secs, T):
    cur = None
    for line in secs.get("USED IPAD", []):
        m = re.match(r"^(IPAD [^,]+),A,B,", line)
        if m: cur = ipad_key(m.group(1)); cur = cur if ipad_ok(cur) else None; continue
        m = re.match(r"^WIFI\s*-\s*(\d+\s*(?:GB|TB)),(.*)$", line)
        if cur and m:
            for v, g in zip(split_money(m.group(2)), ["A", "B", "BC", "C", "D", "DOA"]):
                put(T, cur, storage_norm(m.group(1)), "U", g, money(v))

def st_key(s):
    if s == "*": return 0
    n = int(re.match(r"\d+", s).group()); return n * (1024 if s.endswith("TB") else 1)

def consistent(P, sts):
    """Sheets sometimes pay more for a worse answer (C over B-/C+, locked over unlocked, 512GB over 1TB).
    Lower the odd value so a worse answer never quotes higher. Only ever lowers, so the margin stays safe."""
    fixes = 0
    for _ in range(3):
        for i, st in enumerate(sts):
            locks = P[st]
            for lock, g in locks.items():
                best = None
                for gr in GRADES:  # a worse grade never pays more than a better one
                    if gr not in g: continue
                    if best is not None and g[gr] > best: g[gr] = best; fixes += 1
                    best = g[gr]
                for gr, p in g.items():
                    if lock == "L" and gr in locks.get("U", {}) and p > locks["U"][gr]:  # locked never beats unlocked
                        g[gr] = locks["U"][gr]; fixes += 1
                    if i + 1 < len(sts):  # a smaller storage never beats a bigger one
                        up = P[sts[i + 1]].get(lock, {}).get(gr)
                        if up is not None and g[gr] > up: g[gr] = up; fixes += 1
    return fixes

FIXES = []

def finish(T):
    out = {}
    for model, d in T.items():
        P = {st: locks for st, locks in d["P"].items() if any(len(g) for g in locks.values())}
        if not P: continue
        sts = sorted(P, key=st_key)
        n = consistent(P, sts)
        if n: FIXES.append(f"{model} ({n})")
        out[model] = {"st": sts, "P": {st: P[st] for st in sts}}
        if d["back"]: out[model]["back"] = d["back"]
        if d["lens"]: out[model]["lens"] = d["lens"]
    return out

def model_sort(name):
    nums = [int(x) for x in re.findall(r"\d+", name)] or [0]
    rank = 3 if "Ultra" in name or "Pro Max" in name else 2 if "Pro" in name or "+" in name else 1
    return (-nums[0], -rank, name)

if __name__ == "__main__":
    db, bdp = sections(sys.argv[1]), sections(sys.argv[2])
    out_path = sys.argv[3] if len(sys.argv) > 3 else "prices.js"
    iph, sam, ipd = {}, {}, {}
    parse_db_iphones(db, iph); parse_bdp_iphones(bdp, iph)
    parse_db_samsung(db, sam); parse_bdp_samsung(bdp, sam)
    parse_db_ipads(db, ipd); parse_bdp_ipads(bdp, ipd)
    data = {
        "updated": date.today().isoformat(),
        "iphone": dict(sorted(((k, v) for k, v in finish(iph).items() if k not in TOO_OLD), key=lambda kv: model_sort(kv[0]))),
        "samsung": dict(sorted(finish(sam).items(), key=lambda kv: model_sort(kv[0]))),
        "ipad": dict(sorted(finish(ipd).items(), key=lambda kv: (kv[0].split(" (")[0].split('"')[0], model_sort(kv[0])))),
        "icloud": parse_db_icloud(db),
        "iphone_db": {k: {st: v["P"][st]["U"] for st in v["st"] if "U" in v["P"][st]} for k, v in finish(DB_ONLY).items() if k not in TOO_OLD},
    }
    open(out_path, "w").write("/* Generated by tools/build_prices.py from the weekly buyer sheets. Do not edit by hand. */\nwindow.PRICES = " + json.dumps(data, separators=(",", ":")) + ";\n")
    for k in ("iphone", "samsung", "ipad"):
        print(k, len(data[k]), "models:", ", ".join(data[k]))
    print("icloud", len(data["icloud"]))
    print("evened out:", ", ".join(FIXES) or "nothing")
