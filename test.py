"""
Address parser: tach (street, ward, province) tu dia chi tieng Viet.
Khong dung ML. Ky thuat:
  1. Chuan hoa: bo dau, bo khoang trang/dau cau  -> chuoi lien "nospace" + bang anh xa vi tri ve chuoi goc
  2. Reverse Trie (duyet tu cuoi chuoi) de khop province, roi ward (trong tap ward cua province do)
  3. Cat tien to (Tinh/TP/Phuong/Xa/P/T...) khi dinh lien hoac viet tat
  4. DP (edit distance, khop hau to) khi go sai chinh ta
  5. Regex lam sach street (ngo/hem/ngach/kiet, so nha, duong/pho)
"""
import json
import re
import sys
import time
import unicodedata
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


# ---------------------------------------------------------------- trie
class RTrie:
    """Trie tren chuoi dao nguoc -> khop hau to cua chuoi nhap."""

    def __init__(self):
        self.root = {}

    def add(self, word, val):
        n = self.root
        for ch in reversed(word):
            n = n.setdefault(ch, {})
        n.setdefault("$", []).append(val)

    def longest_suffix(self, s, end):
        """Khop dai nhat s[i:end] la mot tu trong trie. Tra ve (do_dai, [val]) hoac None."""
        n, best, i = self.root, None, end - 1
        while i >= 0 and s[i] in n:
            n = n[s[i]]
            if "$" in n:
                best = (end - i, n["$"])
            i -= 1
        return best


# ---------------------------------------------------------------- DP fuzzy
def fuzzy_suffix(k, end, cands):
    """
    Tim ung vien c trong cands (dict key->val) sao cho hau to cua k[:end] gan giong c nhat
    (edit distance <= nguong). DP tren chuoi dao: D[i][j] = ed(rc[:i], rs[:j]), lay min theo j.
    Tra ve (val, do_dai_khop) hoac None.
    """
    tail = k[max(0, end - 40):end][::-1]
    best = None
    for ck, val in cands.items():
        m = len(ck)
        mx = 0 if m <= 5 else 1          # chat: tranh khop nham phuong gan giong (Nam/Bac, 1/2)
        if mx == 0:
            continue
        rs = tail[: m + mx]
        rc = ck[::-1]
        prev = list(range(len(rs) + 1))
        for i, a in enumerate(rc, 1):
            cur = [i]
            for j, b in enumerate(rs, 1):
                cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a != b)))
            prev = cur
        d = min(prev)
        if d <= mx and (best is None or d < best[0]):
            j = prev.index(d)
            digits = lambda x: "".join(c for c in x if c.isdigit())
            if digits(ck) != digits(rs[:j]):   # khong sua chu so
                continue
            best = (d, val, j)
    return (best[1], best[2]) if best else None


# ---------------------------------------------------------------- street cleaning
ALLEY = re.compile(r"^(?:hẻm|ngõ|ngách|kiệt|hem|ngo|ngach|kiet)\s+\d[\w/]*\s*", re.I)
HOUSE = re.compile(r"^\d+[A-Za-z]?(?:/\d+[A-Za-z]?)*(?:\s+[A-Z](?=\s))?\s+")
ROAD = re.compile(r"^(?:đường|phố|duong|pho)\s+", re.I)


def clean_street(s):
    s = " ".join(s.replace(".", ". ").split()).replace(". ", ".") if False else " ".join(s.split())
    s = s.strip(" ,.-")
    while True:
        n = ALLEY.sub("", s, 1)
        h = HOUSE.sub("", n, 1)
        if h:
            n = h
        if n == s:
            break
        s = n
    s = ROAD.sub("", s, 1).strip(" ,.-")
    return s[:1].upper() + s[1:]


# du lieu nhieu: mat chu "Đ" dau tu (Đoàn -> oàn, Đặng -> ặng, Đại -> ại...)
LOST_D = {"oàn", "ặng", "ại", "ường", "ặc", "ạo"}


def fix_lost_d(s):
    first, sp, rest = s.partition(" ")
    if first.lower() in LOST_D:
        return "Đ" + first.lower() + sp + rest
    return s


def pick_street(raw):
    """raw co the chua dau phay (vd 'So 5, Ngo 20, Duong X'): lay doan cuoi co chu."""
    segs = [x for x in raw.split(",") if x.strip()]
    for seg in reversed(segs):
        c = fix_lost_d(clean_street(seg))
        if re.search(r"[^\W\d_]|\d", c):
            return c
    return ""


# ---------------------------------------------------------------- parser
PROV_PFX = ("thanhpho", "tinh", "tp", "t")
WARD_PFX = ("phuong", "dackhu", "thitran", "xa", "p", "x")
SUFFIX_JUNK = ("vietnam",)


class AddressParser:
    def __init__(self, ref):
        """ref = {"Đà Nẵng": ["Hải Châu", ...], ...}"""
        self.prov_trie = RTrie()
        self.prov_keys = {}
        self.ward_trie = {}
        self.ward_keys = {}
        self.global_ward = RTrie()
        for p, ws in ref.items():
            pk = nk(p)
            self.prov_trie.add(pk, p)
            self.prov_keys[pk] = p
            t, wk = RTrie(), {}
            for w in ws:
                k = nk(w)
                t.add(k, w)
                wk[k] = w
                self.global_ward.add(k, (p, w))
            self.ward_trie[p] = t
            self.ward_keys[p] = wk

    # cat tien to ngay truoc ten (ket thuc tai k[:name_start]); tra ve vi tri bat dau tien to hoac name_start
    @staticmethod
    def _strip_prefix(s, k, pos, name_start, pfxs):
        if name_start <= 0 or name_start >= len(pos):
            return name_start
        for p in pfxs:
            st = name_start - len(p)
            if st < 0 or k[st:name_start] != p:
                continue
            o0 = pos[st]
            if o0 > 0 and s[o0 - 1].isalpha():          # tien to phai bat dau o ranh gioi tu
                continue
            if "," in s[pos[name_start - 1] + 1: pos[name_start]]:  # khong vuot qua dau phay
                continue
            if len(p) == 1 and not s[o0].isupper():       # tien to 1 chu cai (P, T) phai viet hoa
                continue
            return st
        return name_start

    def parse(self, addr):
        s, k, pos = norm_map(addr)
        end = len(k)
        for j in SUFFIX_JUNK:
            if k.endswith(j):
                end -= len(j)

        # ---- province
        province, pstart = None, end
        m = self.prov_trie.longest_suffix(k, end)
        if m:
            province, pstart = m[1][0], end - m[0]
        else:
            f = fuzzy_suffix(k, end, self.prov_keys)
            if f:
                province, pstart = f[0], end - f[1]
        if province:
            end = self._strip_prefix(s, k, pos, pstart, PROV_PFX)

        # ---- ward
        ward, wstart = None, end
        if province:
            m = self.ward_trie[province].longest_suffix(k, end)
            if m and "," not in s[pos[end - m[0]]: pos[end - 1]]:
                ward, wstart = m[1][0], end - m[0]
            else:
                f = fuzzy_suffix(k, end, self.ward_keys[province])
                if f:
                    ward, wstart = f[0], end - f[1]
        else:  # khong thay province: suy ra tu ward (neu ward duy nhat)
            m = self.global_ward.longest_suffix(k, end)
            if m and len({p for p, _ in m[1]}) == 1:
                province, ward = m[1][0]
                wstart = end - m[0]

        if ward:
            cut_k = self._strip_prefix(s, k, pos, wstart, WARD_PFX)
            cut = pos[cut_k] if cut_k < len(pos) else len(s)
            lastc = s.rfind(",", 0, cut)
            if lastc != -1 and s[lastc + 1: cut].strip(" ."):
                ward = None            # khop "nuot" mot phan ten duong -> khong tin
        if ward:
            raw = s[:cut]
        else:
            # ward la tu ngoai tu dien: dung cau truc dau phay lam du phong
            cut = pos[end] if end < len(pos) else len(s)
            head = s[:cut].rstrip(" ,.")
            if "," in head:
                raw, _, seg = head.rpartition(",")
                seg = seg.strip()
                seg = re.sub(r"^(?:phường|xã|đặc khu|thị trấn)\s*", "", seg, flags=re.I)
                seg = re.sub(r"^[PX]\.?\s*(?=[A-ZÀ-Ỹ])", "", seg)   # P, P., PLào, X. Bình Lư
                ward = seg or None
            else:
                raw = head
        return {"street": pick_street(raw), "ward": ward, "province": province}


# ---------------------------------------------------------------- CLI / eval
def build_ref_from_public(data):
    ref = {}
    for d in data:
        r = d["result"]
        ref.setdefault(r["province"], set()).add(r["ward"])
    return {p: sorted(w) for p, w in ref.items()}


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
    print(f"max={tmax*1000:.3f} ms  avg={tsum/n*1000:.3f} ms")
    for b in bad[:show]:
        print("X", b[0], "\n   got:", b[1], "\n   exp:", b[2])


if __name__ == "__main__":
    # python test.py [public.json]                   -> danh gia
    # python test.py ref.json "dia chi ..."           -> parse 1 dia chi (ref.json = {tinh: [phuong,...]})
    if len(sys.argv) == 3:
        ref = json.load(open(sys.argv[1], encoding="utf-8"))
        print(json.dumps(AddressParser(ref).parse(sys.argv[2]), ensure_ascii=False))
    elif len(sys.argv) <= 2:
        data_path = sys.argv[1] if len(sys.argv) == 2 else Path(__file__).resolve().with_name("public.json")
        data = json.load(open(data_path, encoding="utf-8"))
        evaluate(AddressParser(build_ref_from_public(data)), data)
    else:
        sys.exit('Cách dùng: python3 test.py [public.json] hoặc python3 test.py ref.json "địa chỉ"')
