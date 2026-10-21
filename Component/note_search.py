"""ค้นโน้ตส่วนตัวของผู้ใช้ให้ราฟาเอล (RAG แบบเบา)

- ไม่ใช้ embedding / ไม่ต้องลงไลบรารีเพิ่ม / ทำดัชนีในเครื่อง ข้อมูลไม่ถูกส่งออกไปตอนทำดัชนี
  (เฉพาะชิ้นที่ค้นเจอและถูกส่งเป็น context ให้ LLM ตอนตอบเท่านั้น)
- ใช้ TF-IDF ของ "ตัวอักษรติดกัน 2-3 ตัว" จึงไม่ต้องตัดคำไทย
- โยนไฟล์ .txt / .md ลงโฟลเดอร์ knowledge/ ได้เลย (โฟลเดอร์ย่อยก็ได้) และอ่าน my_notes.txt ที่คำสั่ง
  "จดโน้ต" สร้างไว้ให้ด้วย ไฟล์ใหม่หรือไฟล์ที่แก้ไขจะถูกทำดัชนีใหม่อัตโนมัติ ไม่ต้องสั่งอัปเดต
- ไฟล์/โฟลเดอร์ที่ขึ้นต้นด้วย "_" หรือ "." จะถูกข้าม ใช้กับโน้ตที่ไม่อยากให้ถูกส่งไปให้ LLM
  (เช่น _private/รหัสผ่าน.txt)

ใช้งาน:
    import note_search
    chunks = note_search.search("ผมจดเรื่อง git ไว้ว่าอะไร")   # -> list[str] ส่งเข้า llm.ask(context=chunks)

ทดสอบจากบรรทัดคำสั่ง:
    python note_search.py "คำถามที่อยากลอง"
"""
import math
import os
import re
import time
import unicodedata
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
# ถ้าไฟล์นี้อยู่ในโฟลเดอร์ Component/ ให้ชี้ไปที่โฟลเดอร์โปรเจกต์
ROOT = os.path.dirname(_HERE) if os.path.basename(_HERE).lower() == "component" else _HERE

NOTES_DIR = os.path.join(ROOT, "knowledge")
EXTRA_FILES = [os.path.join(ROOT, "my_notes.txt")]
EXTS = (".txt", ".md")

CHUNK_MAX = 800            # ความยาวชิ้นสูงสุด (ตัวอักษร)
LINE_GROUP = 300           # เวลาหั่นย่อหน้าที่ยาวตามบรรทัด จะรวมบรรทัดจนยาวราวนี้
NGRAMS = (2, 3)
MIN_SCORE = 0.12           # ต่ำกว่านี้ถือว่าไม่เกี่ยวข้อง (ปรับด้วยคำสั่งทดสอบ)
MAX_CONTEXT_CHARS = 1500   # รวมทุกชิ้นที่ส่งให้ LLM ไม่เกินนี้ (ให้ prompt สั้นและตอบเร็ว)
RECHECK_SEC = 2.0          # เช็กว่าไฟล์เปลี่ยนไหมไม่ถี่เกินไป

# คำที่ไม่ช่วยค้นหา ตัดออกจากคำถามก่อนค้น
_QUERY_NOISE = ["ราฟาเอล", "raphael", "ช่วย", "หน่อย", "ไหม", "หรือเปล่า", "ค่ะ", "ครับ", "คะ", "จำได้", "ผมจด", "ฉันจด"]

_index = {"sig": None, "checked": 0.0, "chunks": [], "vecs": [], "norms": [], "idf": {}, "n": 0}


# ---------------------------------------------------------------------
# เตรียมข้อความ -> n-gram
# ---------------------------------------------------------------------
def _normalize(s):
    s = s.lower()
    s = "".join(" " if unicodedata.category(c)[0] in "PSC" else c for c in s)
    return re.sub(r"\s+", " ", s).strip()


def _ngrams(s):
    s = _normalize(s)
    grams = Counter()
    for n in NGRAMS:
        for i in range(len(s) - n + 1):
            g = s[i:i + n]
            if g.strip():
                grams[g] += 1
    return grams


# ---------------------------------------------------------------------
# อ่านไฟล์ + หั่นเป็นชิ้น
# ---------------------------------------------------------------------
def _list_files():
    files = []
    if os.path.isdir(NOTES_DIR):
        for dirpath, dirnames, filenames in os.walk(NOTES_DIR):
            dirnames[:] = [d for d in dirnames if not d.startswith(("_", "."))]
            for name in filenames:
                if name.lower().endswith(EXTS) and not name.startswith(("_", ".")):
                    files.append(os.path.join(dirpath, name))
    for p in EXTRA_FILES:
        if os.path.isfile(p) and p not in files:
            files.append(p)
    return sorted(files)


def _signature(files):
    sig = []
    for p in files:
        try:
            st = os.stat(p)
            sig.append((p, st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    return tuple(sig)


def _read(path):
    for enc in ("utf-8-sig", "utf-8", "cp874"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
        except OSError:
            return ""
    return ""


def _pack(lines, limit):
    """รวมบรรทัดติดกันเป็นชิ้นละไม่เกิน limit ตัวอักษร"""
    out, cur = [], ""
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if cur and len(cur) + len(line) + 1 > limit:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


_ENTRY = re.compile(r"^\s*(\[\d|[-*•]\s|\d{4}-\d{2}-\d{2}|\d+[.)]\s)")


def _is_entry_list(lines):
    """True ถ้าเป็นรายการที่แต่ละบรรทัดคือโน้ตหนึ่งอัน (มีเวลานำหน้า เช่น my_notes.txt หรือขึ้นต้นด้วย - / 1.)"""
    lines = [l for l in lines if l.strip()]
    return len(lines) > 1 and sum(bool(_ENTRY.match(l)) for l in lines) >= 0.6 * len(lines)


def _split_text(text):
    """คืน [(หัวข้อ, ข้อความ)] หั่นตามหัวข้อ markdown และย่อหน้า"""
    out, heading = [], ""
    for para in re.split(r"\n\s*\n", text.replace("\r\n", "\n")):
        para = para.strip()
        if not para:
            continue
        lines = para.split("\n")
        if lines[0].lstrip().startswith("#"):
            heading = lines[0].lstrip("# ").strip()
            para = "\n".join(lines[1:]).strip()
            if not para:
                continue
        if len(lines) > 1 and _is_entry_list(lines):
            out.extend((heading, ln.strip()) for ln in lines if ln.strip())
            continue
        if len(para) <= CHUNK_MAX:
            out.append((heading, para))
            continue
        pieces = _pack(para.split("\n"), LINE_GROUP)
        for piece in pieces:
            while len(piece) > CHUNK_MAX:          # บรรทัดเดียวยาวมาก ตัดตรง ๆ
                out.append((heading, piece[:CHUNK_MAX]))
                piece = piece[CHUNK_MAX:]
            if piece.strip():
                out.append((heading, piece))
    return out


# ---------------------------------------------------------------------
# สร้างดัชนี
# ---------------------------------------------------------------------
def _build(files):
    chunks = []
    for path in files:
        name = os.path.basename(path)
        for heading, body in _split_text(_read(path)):
            chunks.append({"source": name, "text": f"{heading}: {body}" if heading else body})

    tfs = [_ngrams(c["text"]) for c in chunks]
    df = Counter()
    for tf in tfs:
        df.update(tf.keys())
    n = len(chunks)
    idf = {g: math.log((n + 1) / (d + 1)) + 1 for g, d in df.items()}

    vecs, norms = [], []
    for tf in tfs:
        v = {g: (1 + math.log(c)) * idf[g] for g, c in tf.items()}
        vecs.append(v)
        norms.append(math.sqrt(sum(x * x for x in v.values())) or 1.0)

    _index.update(chunks=chunks, vecs=vecs, norms=norms, idf=idf, n=n)


def reindex(force=True):
    """สร้างดัชนีใหม่ (ปกติไม่ต้องเรียกเอง เพราะ search() เช็กไฟล์เปลี่ยนให้)"""
    files = _list_files()
    _build(files)
    _index["sig"] = _signature(files)
    _index["checked"] = time.time()
    return len(_index["chunks"])


def _ensure_index():
    now = time.time()
    if _index["sig"] is not None and now - _index["checked"] < RECHECK_SEC:
        return
    files = _list_files()
    sig = _signature(files)
    if sig != _index["sig"]:
        _build(files)
        _index["sig"] = sig
    _index["checked"] = now


# ---------------------------------------------------------------------
# ค้นหา
# ---------------------------------------------------------------------
def search_scored(query, top_k=3, min_score=MIN_SCORE):
    """คืน [(คะแนน, ชื่อไฟล์, ข้อความ)] เรียงจากใกล้สุด (ใช้ดีบัก/ปรับ MIN_SCORE)"""
    _ensure_index()
    if not _index["chunks"]:
        return []
    q = query.lower()
    for w in _QUERY_NOISE:
        q = q.replace(w, " ")
    tf = _ngrams(q)
    idf = _index["idf"]
    default_idf = math.log(_index["n"] + 1) + 1          # n-gram ที่ไม่เคยเจอในโน้ต
    qv = {g: (1 + math.log(c)) * idf.get(g, default_idf) for g, c in tf.items()}
    qnorm = math.sqrt(sum(x * x for x in qv.values()))
    if not qnorm:
        return []

    scored = []
    for i, v in enumerate(_index["vecs"]):
        dot = sum(w * v[g] for g, w in qv.items() if g in v)
        if dot:
            scored.append((dot / (qnorm * _index["norms"][i]), i))
    scored.sort(reverse=True)

    results = []
    best = scored[0][0] if scored else 0.0
    for score, i in scored[:top_k]:
        if score < min_score or score < best * 0.5:     # ไม่เกี่ยว หรือห่างจากอันดับ 1 มาก
            break
        c = _index["chunks"][i]
        results.append((score, c["source"], c["text"]))
    return results


def search(query, top_k=3, min_score=MIN_SCORE):
    """คืน list ข้อความอ้างอิงสำหรับ llm.ask(context=...) ว่างถ้าไม่มีอะไรเกี่ยวข้อง"""
    out, used = [], 0
    for _score, source, text in search_scored(query, top_k, min_score):
        item = f"(จากโน้ต {source}) {text}"
        if used + len(item) > MAX_CONTEXT_CHARS and out:
            break
        out.append(item)
        used += len(item)
    return out


def stats():
    _ensure_index()
    return {"files": len({c["source"] for c in _index["chunks"]}), "chunks": _index["n"]}


if __name__ == "__main__":
    import sys
    reindex()
    print("ดัชนี:", stats(), "| โฟลเดอร์:", NOTES_DIR)
    q = " ".join(sys.argv[1:]) or input("คำถาม: ")
    hits = search_scored(q, top_k=5, min_score=0.0)
    for score, source, text in hits:
        mark = "✅" if score >= MIN_SCORE else "  "
        print(f"{mark} {score:.2f} [{source}] {text[:90]!r}")
    if not hits:
        print("ไม่พบอะไรเลย")