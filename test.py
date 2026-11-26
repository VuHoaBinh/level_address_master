import json
import random
import re
import sys
import time
import unicodedata
from bisect import bisect_left
from collections import Counter
from functools import lru_cache
from pathlib import Path


# ---------------------------------------------------------------- normalize
@lru_cache(maxsize=None)
def _base(ch):
    if ch in "đĐ":
        return "d"
    d = unicodedata.normalize("NFD", ch)
    return "".join(x for x in d if unicodedata.category(x) != "Mn").lower()


def norm_map(s):
    """Tra ve (s_NFC, chuoi_lien_khong_dau, pos) voi pos[i] = vi tri trong s_NFC cua ky tu i."""
    s = unicodedata.normalize("NFC", s)
    out, pos = [], []
    for i, ch in enumerate(s):
        for b in _base(ch):
            if b.isalnum():
                out.append(b)
                pos.append(i)
    return s, "".join(out), pos


def nk(s):
    return norm_map(s)[1]


EMPTY = ""      # gia tri tra ve khi thieu thanh phan (thay giao noi ""; doi thanh None neu public.json dung null)


# ---------------------------------------------------------------- tien to / alias
PROV_NAME_PFX = {"thanhpho", "tp", "tinh", "thudo"}
WARD_NAME_PFX = {"phuong", "xa", "thitran", "dackhu"}
STREET_NAME_PFX = {"duong", "pho"}

PROV_PFX = ("thanhpho", "tinh", "tp", "t")                       # tien to co the dinh truoc ten tinh trong input
WARD_PFX = ("phuong", "dackhu", "thitran", "xa", "p", "x")
WARD_EXPLICIT = ("phuong", "thitran", "dackhu", "xa")
SUFFIX_JUNK = ("vietnam",)

# Viet tat chu cai dau (hn, dn, hcm, dnai, tpdn...) duoc SINH TU DONG tu ten tinh trong DB (xem gen_abbrevs).
# Day chi la alias KHONG suy ra duoc tu ten (key = ten tinh khong dau, khong tien to). Co the bo trong.
PROV_ALIAS_EXTRA = {
    "hochiminh": ("sg", "saigon", "hcmc"),
    "bariavungtau": ("brvt", "vungtau"),
    "thuathienhue": ("tth",),
}


def gen_abbrevs(words):
    """Ten tinh (da bo tien to) -> cac viet tat sinh tu dong. 'Dong Nai' -> {dn, dnai}; 'Ho Chi Minh' -> {hcm, hcminh}."""
    ws = [w for w in (nk(x) for x in words) if w]
    if len(ws) < 2:
        return set()
    ini = "".join(w[0] for w in ws)
    return {ini, ini[:-1] + ws[-1]}                      # chu cai dau; chu cai dau + nguyen tu cuoi (dnai, qninh)


def strip_name_prefix(name, pfxs):
    parts = name.split()
    for n in (2, 1):
        if len(parts) > n and nk("".join(parts[:n])) in pfxs:
            return " ".join(parts[n:])
    return name


# ---------------------------------------------------------------- trie
class RTrie:
    """Trie tren chuoi dao nguoc -> khop hau to cua chuoi nhap."""

    def __init__(self):
        self.root = {}

    def add(self, word, val):
        n = self.root
        for ch in reversed(word):
            n = n.setdefault(ch, {})
        lst = n.setdefault("$", [])
        if val not in lst:
            lst.append(val)

    def suffixes(self, s, end):
        """Moi khop s[i:end] la mot tu trong trie, tu DAI den NGAN: [(do_dai, [val])]."""
        n, out, i = self.root, [], end - 1
        while i >= 0 and s[i] in n:
            n = n[s[i]]
            if "$" in n:
                out.append((end - i, n["$"]))
            i -= 1
        out.reverse()
        return out


# ---------------------------------------------------------------- DP fuzzy
class Fuzzy:
    """Khop mo hau to: edit distance <= nguong (theo do dai key). Dung som khi vuot nguong."""

    def __init__(self, items):
        self.items = []
        for ck, val in items:
            m = len(ck)
            mx = 0 if m <= 5 else (1 if m <= 9 else 2)       # ten ngan: khong sua (tranh nham Nam/Bac, 1/2)
            if mx:
                rc = ck[::-1]                                   # so sanh chu so tren chuoi dao nguoc de cung thu tu voi rs
                self.items.append((rc, mx, val, "".join(c for c in rc if c.isdigit())))

    def search(self, k, end):
        """Tra ve (val, do_dai_khop_tren_k) hoac None."""
        tail = k[max(0, end - 48):end][::-1]
        best = None
        for rc, mx, val, dg in self.items:
            rs = tail[: len(rc) + mx]
            prev = list(range(len(rs) + 1))
            prev2 = None
            dead = False
            for i, a in enumerate(rc, 1):
                cur = [i]
                lo = i
                for j, b in enumerate(rs, 1):
                    v = prev[j - 1] + (a != b)
                    t = prev[j] + 1
                    if t < v:
                        v = t
                    t = cur[j - 1] + 1
                    if t < v:
                        v = t
                    if prev2 is not None and j > 1 and a == rs[j - 2] and rc[i - 2] == b:   # hoan vi 2 ky tu ke nhau
                        t = prev2[j - 2] + 1
                        if t < v:
                            v = t
                    cur.append(v)
                    if v < lo:
                        lo = v
                if lo > mx:                                   # khong con hy vong
                    dead = True
                    break
                prev2, prev = prev, cur
            if dead:
                continue
            d = min(prev)
            if d > mx:
                continue
            j = prev.index(d)
            if dg != "".join(c for c in rs[:j] if c.isdigit()):   # khong sua chu so
                continue
            if best is None or (d, -j) < (best[0], -best[2]):
                best = (d, val, j)
        return (best[1], best[2]) if best else None


class Index:
    """Mot tap key -> val, co trie (khop chinh xac) va fuzzy (khop gan dung)."""

    def __init__(self):
        self.trie = RTrie()
        self._items = []
        self.fuzzy = None

    def add(self, key, val, fuzzy=True):
        if key:
            self.trie.add(key, val)
            if fuzzy:
                self._items.append((key, val))

    def done(self):
        self.fuzzy = Fuzzy(self._items) if self._items else None
        self._items = []
        return self


def _near_prefix(w):
    """w (khong dau) la tien to ward bi go sai (<=2 loi)? Dung de nhan ra 'phuono', 'pưhờng'..."""
    for p in ("phuong", "thitran", "dackhu"):
        if abs(len(w) - len(p)) > 2:
            continue
        prev = list(range(len(p) + 1))
        for i, a in enumerate(w, 1):
            cur = [i]
            for j, b in enumerate(p, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
            prev = cur
        if prev[-1] <= (1 if len(p) <= 6 else 2) + (1 if sorted(w) == sorted(p) else 0):
            return True
    return False


# ---------------------------------------------------------------- street cleaning (du phong khi khong co street DB)
ALLEY = re.compile(r"^(?:hẻm|ngõ|ngách|kiệt|hem|ngo|ngach|kiet)\s+\d[\w/]*\s*", re.I)
HOUSE = re.compile(r"^\d+[A-Za-z]?(?:/\d+[A-Za-z]?)*\s+(?!(?:tháng|thang)\b)", re.I)   # khong cat "3 Thang 2"
ROAD = re.compile(r"^(?:đường|phố|duong|pho)\s+", re.I)


def clean_street(s):
    s = " ".join(s.split()).strip(" ,.-")
    for _ in range(3):
        n = HOUSE.sub("", ALLEY.sub("", s, 1), 1)
        if n == s:
            break
        s = n
    s = ROAD.sub("", s, 1).strip(" ,.-")
    return s[:1].upper() + s[1:]


def pick_street(raw):
    """raw co the chua dau phay (vd 'So 5, Ngo 20, Duong X'): lay doan cuoi co chu."""
    for seg in reversed([x for x in raw.split(",") if x.strip()]):
        c = clean_street(seg)
        if re.search(r"[^\W\d_]|\d", c):
            return c
    return None


# ---------------------------------------------------------------- database
def normalize_db(obj):
    """-> {province: {ward: [street, ...]}}"""
    db = {}

    def add(p, w=None, st=None):
        ws = db.setdefault(p, {})
        if w:
            sl = ws.setdefault(w, [])
            if st and st not in sl:
                sl.append(st)

    if isinstance(obj, dict):
        for p, v in obj.items():
            add(p)
            if isinstance(v, dict):
                for w, sts in v.items():
                    add(p, w)
                    for st in sts or []:
                        add(p, w, st)
            else:
                for w in v:
                    add(p, w)
    else:
        for r in obj:
            r = r.get("result", r)
            r = {str(k).lower(): v for k, v in r.items()}
            if r.get("province"):
                add(r["province"], r.get("ward"), r.get("street"))
    return db


def load_db(path):
    with open(path, encoding="utf-8") as f:
        return normalize_db(json.load(f))


# ---------------------------------------------------------------- parser
class AddressParser:
    def __init__(self, db, raw_ward_fallback=False):
        """
        db: xem normalize_db.
        raw_ward_fallback: True -> neu ward khong co trong DB thi tra ve doan chu giua cac dau phay
                           (mac dinh False: theo slide de, ward ngoai DB -> None).
        """
        db = normalize_db(db)
        self.raw_ward_fallback = raw_ward_fallback
        self.has_streets = any(sts for ws in db.values() for sts in ws.values())

        self.prov = Index()
        self.ward, self.street, self.pstreet = {}, {}, {}
        self.gward = RTrie()                                   # ward toan quoc (suy ra province khi input thieu)
        self.ptype = {}                                        # loai: "city" (Thanh pho) / "prov" (Tinh) / None

        for p, ws in db.items():
            np_ = nk(p)
            self.ptype[p] = "city" if np_.startswith(("thanhpho", "tp")) else "prov" if np_.startswith("tinh") else None
            base = strip_name_prefix(p, PROV_NAME_PFX)
            for key in {np_, nk(base)}:
                self.prov.add(key, p)                          # ten day du: cho phep sua loi
            abbr = gen_abbrevs(base.split()) | set(PROV_ALIAS_EXTRA.get(nk(base), ()))
            for a_ in abbr:                                    # viet tat: chi khop chinh xac, CHO PHEP trung (dn -> Da Nang/Dong Nai)
                self.prov.add(a_, p, fuzzy=False)
                self.prov.add("tp" + a_, p, fuzzy=False)

            widx, psidx = Index(), Index()
            for w, sts in ws.items():
                bk = nk(strip_name_prefix(w, WARD_NAME_PFX))
                wk = {nk(w), "p" + bk if bk.isdigit() else bk}     # ward chi la so: "Phuong 1" -> p1, khong dung key "1"
                for key in wk:
                    if key:
                        widx.add(key, w)
                        self.gward.add(key, (p, w))
                if sts:
                    sidx = Index()
                    for st in sts:
                        for key in {nk(st), nk(strip_name_prefix(st, STREET_NAME_PFX))}:
                            sidx.add(key, st)
                            psidx.add(key, (w, st))
                    self.street[(p, w)] = sidx.done()
            self.ward[p] = widx.done()
            if psidx._items:
                self.pstreet[p] = psidx.done()
        self.prov.done()

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _boundary(s, pos, st):
        if st <= 0:
            return True
        p = pos[st]
        return p == 0 or not s[p - 1].isalnum()

    def _match(self, idx, k, s, pos, end):
        """Tim khop hau to cua k[:end] trong idx. Tra ve ([val], vi_tri_bat_dau) hoac None."""
        if end <= 0:
            return None
        for L, vals in idx.trie.suffixes(k, end):
            if L > 4 or self._boundary(s, pos, end - L):      # key ngan phai bat dau o ranh gioi tu
                return vals, end - L
        if idx.fuzzy:
            f = idx.fuzzy.search(k, end)
            if f:
                return [f[0]], end - f[1]
        return None

    # cat tien to ngay truoc ten; tra ve vi tri bat dau tien to hoac name_start
    @staticmethod
    def _strip_prefix(s, k, pos, name_start, pfxs):
        if name_start <= 0 or name_start >= len(pos):
            return name_start
        for p in pfxs:
            st = name_start - len(p)
            if st < 0 or k[st:name_start] != p:
                continue
            o0 = pos[st]
            if o0 > 0 and s[o0 - 1].isalpha():                   # tien to phai bat dau o ranh gioi tu
                continue
            if "," in s[pos[name_start - 1] + 1: pos[name_start]]:   # khong vuot qua dau phay
                continue
            if len(p) == 1 and not (s[o0].isupper() or (o0 + 1 < len(s) and s[o0 + 1] in ". ")):
                continue                                         # tien to 1 chu cai: viet hoa, hoac la tu roi ("p. x", "p x")
            return st
        return name_start

    @staticmethod
    def _prev_token(s, pos, name_start):
        """Vi tri k cua tu ngay truoc name_start (cung doan, khong qua dau phay); khong co -> name_start."""
        if name_start <= 0 or name_start >= len(pos):
            return name_start
        i = pos[name_start] - 1
        while i >= 0 and s[i] in " .":
            i -= 1
        if i < 0 or not s[i].isalnum():
            return name_start
        j = i
        while j >= 0 and s[j].isalnum():
            j -= 1
        return bisect_left(pos, j + 1)

    def _street(self, province, ward, k, s, pos, end):
        """Khop street theo DB. Tra ve (street_chuan | None, ward_suy_ra | None)."""
        if not self.has_streets or not province:
            return None, None
        if ward:
            idx = self.street.get((province, ward))
            if idx:
                m = self._match(idx, k, s, pos, end)
                if m:
                    return m[0][0], None
        idx = self.pstreet.get(province)                         # khong thay trong ward -> thu ca province
        if idx:
            m = self._match(idx, k, s, pos, end)
            if m:
                vals = m[0]
                if ward:
                    for w, st in vals:
                        if w == ward:
                            return st, None
                    return vals[0][1], None
                if len({w for w, _ in vals}) == 1:               # street nam sat province, ward bi thieu -> suy ra
                    return vals[0][1], vals[0][0]
                return vals[0][1], None
        return None, None

    # ------------------------------------------------------------ parse
    def parse(self, addr):
        out, cands, hint = self._parse(addr)
        if len(cands) > 1:                                       # viet tat nhap nhang (TPDN, QN, LC...): chon theo ward/street/loai
            def score(ic):
                i, c = ic
                o = self._parse(addr, force=c)[0]
                sc = 2 * (o["ward"] is not None)
                if self.has_streets:
                    sc += o["street"] is not None
                if hint and self.ptype.get(c) == hint:
                    sc += 0.5
                return (sc, -i)
            _, c = max(enumerate(cands), key=score)
            out = self._parse(addr, force=c)[0]
        return {f: (EMPTY if v is None else v) for f, v in out.items()}

    def _parse(self, addr, force=None):
        s, k, pos = norm_map(addr)
        end = len(k)
        for j in SUFFIX_JUNK:
            if k.endswith(j):
                end -= len(j)
        out = {"street": None, "ward": None, "province": None}
        if end <= 0:
            return out, [], None

        # ---- province
        province, cands, hint = None, [], None
        m = self._match(self.prov, k, s, pos, end)
        if m:
            cands = list(m[0])
            province = force if force in cands else cands[0]
            pstart, raw_end = m[1], end
            end = self._strip_prefix(s, k, pos, pstart, PROV_PFX)
            pre = k[end:pstart]
            if pre in ("tp", "thanhpho", "thudo") or k[pstart:raw_end].startswith(("tp", "thanhpho")):
                hint = "city"
            elif pre in ("tinh", "t"):
                hint = "prov"

        # ---- ward
        ward, wstart = None, end
        if province:
            # thu lan luot: sat province, roi bo qua toi da 2 tu (tien to tinh/TP bi go sai: "Thanh thuo", "Tin")
            e = end
            for _ in range(3):
                m = self._match(self.ward[province], k, s, pos, e)
                if m and "," not in s[pos[m[1]]: pos[e - 1]]:
                    ward, wstart, end = m[0][0], m[1], e
                    break
                if e != pstart and _ == 0:                       # da cat duoc tien to dung -> khong bo qua them
                    break
                e2 = self._prev_token(s, pos, e)
                if e2 == e:
                    break
                e = e2
        else:                                                    # khong thay province: suy ra tu ward (neu duy nhat)
            for L, vals in self.gward.suffixes(k, end):
                if (L > 4 or self._boundary(s, pos, end - L)) and len({p for p, _ in vals}) == 1:
                    province, ward = vals[0]
                    wstart = end - L
                    break

        cut_k = end
        if ward:
            cut_k = self._strip_prefix(s, k, pos, wstart, WARD_PFX)
            explicit = cut_k < wstart or k.startswith(WARD_EXPLICIT, wstart)
            cut = pos[cut_k] if cut_k < len(pos) else len(s)
            lastc = s.rfind(",", 0, cut)
            # khop "nuot" mot phan ten duong (khong co tien to ro rang, khong sat dau phay) -> khong tin
            left = s[lastc + 1: cut].strip(" .") if lastc != -1 else ""
            if not explicit and left:
                if not _near_prefix(nk(left)):
                    ward, cut_k = None, end
                else:
                    cut_k = bisect_left(pos, lastc + 1)          # bo luon tien to ward go sai

        # ---- street
        street = None
        if ward:
            street, _ = self._street(province, ward, k, s, pos, cut_k)
        elif province:
            street, inferred = self._street(province, None, k, s, pos, end)     # ward bi thieu hoan toan
            if street:
                ward = inferred
            else:                                                # co the con mot doan ward la (ngoai DB) truoc province
                cut = pos[end] if end < len(pos) else len(s)
                lastc = s.rfind(",", 0, cut)
                if lastc != -1:
                    street, _ = self._street(province, None, k, s, pos, bisect_left(pos, lastc))

        # ---- du phong khi DB khong co street
        raw_ward = None
        if street is None and not self.has_streets:
            if ward:
                raw = s[: pos[cut_k] if cut_k < len(pos) else len(s)]
            else:
                head = s[: pos[end] if end < len(pos) else len(s)].rstrip(" ,.")
                if "," in head:
                    raw, _, seg = head.rpartition(",")
                    seg = re.sub(r"^(?:phường|xã|đặc khu|thị trấn)\s*", "", seg.strip(), flags=re.I)
                    seg = re.sub(r"^[PX]\.?\s*(?=[A-ZÀ-Ỹ])", "", seg)
                    raw_ward = seg or None
                else:
                    raw = head
            street = pick_street(raw)
        if not ward and self.raw_ward_fallback:
            ward = raw_ward
        out.update(street=street, ward=ward, province=province)
        return out, cands, hint


# ---------------------------------------------------------------- du lieu nhieu tu db (de tu kiem tra)
def synth_tests(db, n=2000, seed=0):
    db = normalize_db(db)
    rnd = random.Random(seed)
    triples = [(p, w, st) for p, ws in db.items() for w, sts in ws.items() for st in sts]
    if not triples:
        return []

    def typo(x):
        if len(x) < 8:
            return x
        i = rnd.randrange(1, len(x) - 1)
        op = rnd.random()
        if op < 0.33:
            return x[:i] + x[i + 1:]
        if op < 0.66:
            return x[:i] + x[i + 1] + x[i] + x[i + 2:]
        return x[:i] + rnd.choice("abcdeghilmnoprstu") + x[i + 1:]

    out = []
    for _ in range(n):
        p, w, st = rnd.choice(triples)
        st_t, w_t, p_t = st, w, p
        if rnd.random() < 0.25:
            st_t = typo(st_t)
        if rnd.random() < 0.20:
            w_t = typo(w_t)
        if rnd.random() < 0.20:
            p_t = typo(p_t)
        if rnd.random() < 0.25:
            p_t = re.sub(r"^Thành phố ", "TP. ", p_t)
        if rnd.random() < 0.25:
            p_t = re.sub(r"^(?:Thành phố|Tỉnh) ", "", p_t)
        if rnd.random() < 0.25:
            w_t = re.sub(r"^Phường ", "P. ", w_t)
        house = rnd.choice(["", str(rnd.randint(1, 300)), f"{rnd.randint(1, 300)}/{rnd.randint(1, 50)}",
                            f"Hẻm {rnd.randint(1, 30)}/{rnd.randint(1, 20)} {rnd.randint(1, 99)}"])
        parts = [(house + " " + st_t).strip(), w_t, p_t]
        if rnd.random() < 0.2:
            parts.pop(rnd.choice([1, 1, 2]))                       # bo thieu ward/province
        addr = (" " if rnd.random() < 0.15 else ", ").join(parts)
        if rnd.random() < 0.3:
            addr = "".join(_base(c) for c in addr)                 # bo dau + viet thuong
        out.append({"address": addr, "result": {"street": st, "ward": w, "province": p}, "_cut": len(parts) < 3})
    return out


# ---------------------------------------------------------------- CLI / eval
def evaluate(parser, data, show=15):
    ok = {"street": 0, "ward": 0, "province": 0}
    full = tmax = tsum = 0
    bad = []
    for d in data:
        t = time.perf_counter()
        out = parser.parse(d["address"])
        dt = time.perf_counter() - t
        tmax, tsum = max(tmax, dt), tsum + dt
        good = True
        for f in ok:
            if out[f] == d["result"][f]:
                ok[f] += 1
            else:
                good = False
        full += good
        if not good:
            bad.append((d["address"], out, d["result"]))
    n = len(data)
    print({f: round(v / n, 4) for f, v in ok.items()}, "exact:", round(full / n, 4))
    print(f"max={tmax * 1000:.3f} ms  avg={tsum / n * 1000:.3f} ms  (n={n})")
    for b in bad[:show]:
        print("X", b[0], "\n   got:", b[1], "\n   exp:", b[2])


def _read(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def interactive(parser):
    for stream in (sys.stdin, sys.stdout):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    while True:
        try:
            address = input("Nhập địa chỉ (Enter để thoát): ").strip()
        except EOFError:
            break
        if not address:
            break
        print(json.dumps(parser.parse(address), ensure_ascii=False))


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--interactive":
        db_path = a[1] if len(a) > 1 else str(Path(__file__).resolve().with_name("public.json"))
        interactive(AddressParser(load_db(db_path)))
    else:
        if not a:
            a = [str(Path(__file__).resolve().with_name("public.json"))]
        if len(a) == 1:                                           # dev: db = public (CANH BAO: thoi phong diem)
            data = _read(a[0])
            print("CANH BAO: db dung tu dap an cua public -> diem khong phan anh private.")
            evaluate(AddressParser(data), data)
        elif a[1] == "--synth":
            n = int(a[2]) if len(a) > 2 else 2000
            db = load_db(a[0])
            evaluate(AddressParser(db), synth_tests(db, n))
        elif a[1].lower().endswith(".json"):
            evaluate(AddressParser(load_db(a[0])), _read(a[1]))
        else:
            print(json.dumps(AddressParser(load_db(a[0])).parse(a[1]), ensure_ascii=False))