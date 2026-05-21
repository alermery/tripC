from __future__ import annotations

import hashlib
import re
from functools import lru_cache
from pathlib import Path

import pandas as pd

from backend.app.rag.chroma_rag_kb import add_rag_text_chunks
from backend.app.rag.models import TravelListing
from backend.app.rag.persist_chroma import write_listings_to_chroma
from backend.app.rag.persist_neo4j import write_listings_to_neo4j

_MAX = 2400
_OVERLAP = 180
_SEPARATORS = ("\n\n", "\n", "。", "！", "？", "；", "; ", ". ", "! ", "? ", "，", ", ", "、", " ")
_HINT_CSV = Path(__file__).resolve().parent.parent / "data" / "dest_city_hints.csv"
_PKG_KEYS = frozenset({"departure", "detail", "price"})
_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("departure", ("departure", "出发地", "始发地", "起程城市", "出发城市")),
    ("detail", ("detail", "行程", "详情", "详情/行程", "行程/详情", "套餐描述", "标题", "描述", "套餐", "产品介绍", "content")),
    ("price", ("price", "价格", "金额", "现价", "费用")),
    ("target_city", ("target_city", "目的地", "到达城市", "目标城市", "城市")),
    ("offer", ("offer", "优惠", "折扣", "优惠活动", "促销", "优惠信息")),
    ("url", ("url", "链接", "地址", "产品链接")),
    ("raw_title", ("raw_title", "名称", "产品名", "标题名")),
)


def _fold(s: str) -> str:
    """规整表头或单元格文本中的空白和 BOM。"""
    return str(s).strip().replace("\ufeff", "").replace("\u3000", " ").strip()


def _pieces_with_separator(text: str, sep: str) -> list[str]:
    """按指定分隔符拆分文本，并保留中文句末标点。"""
    if sep in {"。", "！", "？", "；", "，", "、"}:
        return [p for p in re.split(f"(?<={re.escape(sep)})", text) if p.strip()]
    if sep in {". ", "! ", "? ", "; ", ", "}:
        mark = sep.strip()
        return [p for p in re.split(f"(?<={re.escape(mark)})\\s+", text) if p.strip()]
    return [p for p in text.split(sep) if p.strip()]


def _merge_semantic_units(units: list[str], max_len: int | None = None, overlap: int | None = None) -> list[str]:
    """把语义片段合并成长度受控、带重叠的文本块。"""
    max_len = _MAX if max_len is None else max_len
    overlap = _OVERLAP if overlap is None else overlap
    chunks: list[str] = []
    current = ""
    tail = ""
    for raw in units:
        unit = raw.strip()
        if not unit:
            continue
        if len(unit) > max_len:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(_semantic_split(unit, max_len=max_len, overlap=overlap))
            tail = chunks[-1][-overlap:] if chunks and overlap > 0 else ""
            continue
        if not current:
            current = unit
        elif len(current) + 1 + len(unit) <= max_len:
            current = f"{current}\n{unit}"
        else:
            chunks.append(current)
            prefix = tail if tail and len(tail) + 1 + len(unit) <= max_len else ""
            current = f"{prefix}\n{unit}".strip() if prefix else unit
        tail = current[-overlap:] if overlap > 0 else ""
    if current:
        chunks.append(current)
    return chunks


def _semantic_split(text: str, max_len: int | None = None, overlap: int | None = None) -> list[str]:
    """按优先级尝试语义切分，必要时退化为固定长度切片。"""
    max_len = _MAX if max_len is None else max_len
    overlap = _OVERLAP if overlap is None else overlap
    t = text.strip()
    if not t:
        return []
    if len(t) <= max_len:
        return [t]
    for sep in _SEPARATORS:
        if sep not in t:
            continue
        pieces = _pieces_with_separator(t, sep)
        if len(pieces) <= 1:
            continue
        chunks = _merge_semantic_units(pieces, max_len=max_len, overlap=overlap)
        if chunks and all(len(c) <= max_len for c in chunks):
            return chunks
    # 无可用语义分隔符时，退化为固定长度切片。
    chunks: list[str] = []
    step = max(1, max_len - max(0, overlap))
    for start in range(0, len(t), step):
        chunk = t[start : start + max_len].strip()
        if chunk:
            chunks.append(chunk)
    return chunks


def _chunk_txt(text: str) -> list[str]:
    """把纯文本文件切分为可入库的知识片段。"""
    t = text.strip()
    if not t:
        return []
    parts = [p.strip() for p in re.split(r"\n{2,}", t) if p.strip()]
    return _merge_semantic_units(parts)


@lru_cache
def _hints_longest() -> tuple[str, ...]:
    """读取目的地提示词，并按长度倒序缓存。"""
    if not _HINT_CSV.is_file():
        raise FileNotFoundError(f"missing {_HINT_CSV}")
    df = pd.read_csv(_HINT_CSV, encoding="utf-8-sig")
    df.columns = [_fold(str(c)) for c in df.columns]
    if df.empty or not len(df.columns):
        raise ValueError(f"{_HINT_CSV.name} invalid")
    col = next((c for c in df.columns if _fold(c).lower() in {"city", "name", "hint"} or c in ("城市", "目的地")), None)
    col = col or df.columns[0]
    names = [n for n in df[col].dropna().astype(str).str.strip() if len(n) >= 2]
    if not names:
        raise ValueError(f"{_HINT_CSV.name} has no usable rows")
    return tuple(sorted(set(names), key=len, reverse=True))


def _infer_city(detail: str) -> str | None:
    """根据行程详情推断目的地城市。"""
    d = (detail or "").strip()
    if len(d) < 2:
        return None
    hints = _hints_longest()
    for name in hints:
        if d.startswith(name) or name in d:
            return name[:80]
    return None


def _strip_junk(df: pd.DataFrame) -> pd.DataFrame:
    """删除表格最左侧的空列或 Unnamed 列。"""
    out = df.copy()
    while len(out.columns):
        raw, name = out.columns[0], _fold(str(out.columns[0]))
        if name == "" or re.match(r"^Unnamed:\s*\d+$", name, re.I):
            out = out.drop(columns=[raw], axis=1)
        else:
            break
    return out


def _hdr_tokens(col: str) -> set[str]:
    """把表头拆成可匹配的候选词。"""
    h = _fold(col).lower()
    if not h:
        return set()
    return {p.strip() for p in re.split(r"[/\\|、，,\s]+", h) if p.strip()} | {h}


def _canon_map(cols: list[str]) -> dict[str, str]:
    """把上传表格列名映射到标准套餐字段。"""
    lm = {_fold(c).lower(): c for c in cols}
    m: dict[str, str] = {}
    for canon, alist in _ALIASES:
        found = lm.get(canon) or next((lm[_fold(a).lower()] for a in alist if _fold(a).lower() in lm), None)
        if not found:
            for col in cols:
                tok = _hdr_tokens(col)
                if any(_fold(a).lower() in tok for a in alist):
                    found = col
                    break
        if found:
            m[canon] = found
    return m


def _tabular(path: Path) -> pd.DataFrame:
    """按文件后缀读取 CSV 或 Excel 表格。"""
    return pd.read_csv(path, encoding="utf-8-sig") if path.suffix.lower() == ".csv" else pd.read_excel(path, engine="openpyxl")


def _prep(df: pd.DataFrame) -> tuple[pd.DataFrame, list[str], dict[str, str]]:
    """清洗表头并生成标准字段映射。"""
    df = _strip_junk(df)
    df.columns = [_fold(c) for c in df.columns]
    cols = list(df.columns)
    return df, cols, _canon_map(cols)


def _price_int(raw) -> int | None:
    """从价格单元格中提取整数金额。"""
    if pd.isna(raw):
        return None
    s = re.search(r"(\d+(?:\.\d+)?)", str(raw).replace(",", "").replace("元", ""))
    return int(float(s.group(1))) if s else None


def _cell(row, key: str | None) -> str:
    """安全读取表格单元格并转成字符串。"""
    if not key or key not in row or pd.isna(row[key]):
        return ""
    return str(row[key]).strip()


def _rows_to_listings(df: pd.DataFrame, cm: dict[str, str], src: str) -> tuple[list[TravelListing], dict]:
    """把标准字段表格行转换成 TravelListing 列表和统计信息。"""
    dep, det, pr = cm["departure"], cm["detail"], cm["price"]
    tc, off, url, tit = cm.get("target_city"), cm.get("offer"), cm.get("url"), cm.get("raw_title")
    items: list[TravelListing] = []
    bad_p, bad_m = 0, 0
    for idx, row in df.iterrows():
        price = _price_int(row[pr])
        if price is None:
            bad_p += 1
            continue
        departure, detail = _cell(row, dep), _cell(row, det)
        if not departure or not detail:
            bad_m += 1
            continue
        sid = hashlib.sha256(f"{src}:{idx}:{departure}:{detail}:{price}".encode()).hexdigest()[:40]
        target_city = _cell(row, tc) or _infer_city(detail) or None
        offer_text = _cell(row, off) if off else ""
        offer = offer_text if offer_text else "无优惠"
        items.append(
            TravelListing(
                source_id=sid,
                source_site="rag_upload",
                detail=detail[:4000],
                departure=departure[:120],
                price=price,
                offer=offer[:500],
                url=_cell(row, url) or None,
                raw_title=_cell(row, tit)[:200],
                target_city=target_city,
                departure_code=None,
            )
        )
    stats = {
        "total_rows": len(df),
        "processed": len(items),
        "skipped_price": bad_p,
        "skipped_missing": bad_m,
        "mapped_columns": dict(cm),
        "offer_column_missing": "offer" not in cm,
    }
    return items, stats


def _generic_chunks(df: pd.DataFrame, name: str) -> list[str]:
    """把非套餐表格按行转换为通用 RAG 文本片段。"""
    chunks: list[str] = []
    for idx, row in df.iterrows():
        line = "\n".join(f"{_fold(str(col))}: {row[col]}" for col in df.columns if not pd.isna(row[col]))
        if not line.strip():
            continue
        prefix = f"[{name}#row{idx}]\n"
        available = max(400, _MAX - len(prefix))
        chunks.extend(prefix + chunk for chunk in _semantic_split(line, max_len=available))
    return chunks


def _ret(ts: list[str], cr: int, ct: int, neo: int, notes: list[str], **kw) -> dict:
    """统一组织上传入库返回结构。"""
    return {"targets": ts, "chroma_rag_kb_docs": cr, "chroma_travel_deals_docs": ct, "neo4j_upserts": neo, "notes": notes, **kw}


def ingest_file(path: Path) -> dict:
    """根据文件类型把上传内容写入 RAG、套餐向量库或 Neo4j。"""
    ext, name = path.suffix.lower(), path.name
    targets: list[str] = []
    notes: list[str] = []
    chroma_rag = chroma_travel = neo4j = 0

    if ext == ".txt":
        n = add_rag_text_chunks(_chunk_txt(path.read_text(encoding="utf-8", errors="replace")), source_file=name, extra_meta={"kind": "txt"})
        chroma_rag = max(n, 0)
        targets.append("chroma:rag_kb")
        if n < 0:
            notes.append("Chroma 写入失败")
            return _ret(targets, chroma_rag, chroma_travel, neo4j, notes, message="知识库写入失败")
        if chroma_rag <= 0:
            return _ret(targets, chroma_rag, chroma_travel, neo4j, notes, message="未写入：文本为空")
        return _ret(targets, chroma_rag, chroma_travel, neo4j, notes, message=f"成功写入 {chroma_rag} 条知识库文档")

    if ext not in (".csv", ".xlsx"):
        raise ValueError(f"不支持的文件类型: {ext}")

    df, cols, cm = _prep(_tabular(path))
    if ext == ".xlsx" and not _PKG_KEYS.issubset(cm):
        df2, _, cm2 = _prep(pd.read_excel(path, engine="openpyxl", header=1))
        if _PKG_KEYS.issubset(cm2):
            df, cols, cm = df2, list(df2.columns), cm2

    if _PKG_KEYS.issubset(cm):
        listings, stats = _rows_to_listings(df, cm, name)
        neo4j = write_listings_to_neo4j(listings)
        chroma_write = write_listings_to_chroma(listings)
        chroma_travel = max(chroma_write, 0)
        targets += ["neo4j:TravelDetail", "chroma:travel_deals"]
        if chroma_write < 0:
            notes.append("travel_deals 向量写入失败")
        notes.append(f"套餐 {stats['processed']}/{stats['total_rows']} 条")
        return _ret(
            targets,
            chroma_rag,
            chroma_travel,
            neo4j,
            notes,
            stats=stats,
            filename=name,
            message=(f"已处理 {stats['processed']} 条旅行详情" if stats["processed"] else "无有效套餐行"),
        )

    n = add_rag_text_chunks(_generic_chunks(df, name), source_file=name, extra_meta={"kind": "tabular_generic"})
    chroma_rag = max(n, 0)
    targets.append("chroma:rag_kb")
    if n < 0:
        notes.append("Chroma 写入失败")
        msg = "知识库写入失败"
    elif chroma_rag > 0:
        msg = f"成功写入 {chroma_rag} 条知识库文档"
    else:
        msg = "未写入任何片段"
    notes.append(f"非套餐表 -> rag_kb；表头 {', '.join(str(c) for c in cols[:6])}；{len(df)} 行")
    return _ret(targets, chroma_rag, chroma_travel, neo4j, notes, message=msg)


def ingest_file_safe(path: Path) -> dict:
    """安全执行文件入库，异常时返回结构化错误信息。"""
    try:
        return ingest_file(path)
    except Exception as exc:
        return {"message": f"处理失败: {exc}", "targets": [], "notes": [str(exc)]}
