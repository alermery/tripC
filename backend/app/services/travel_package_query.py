"""
Neo4j 旅游套餐图谱查询（单一实现，仅供 LangChain 工具调用）。
"""

from __future__ import annotations

import re
from typing import Any, Optional

from neo4j import GraphDatabase

from backend.app.config import settings

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)


def _normalize_departure_token(departure: str) -> str:
    raw = (departure or "").strip()
    if not raw:
        return raw
    s = raw
    m = re.match(r"^从\s*([\u4e00-\u9fff]{2,12}?)\s*出发", s)
    if m:
        s = m.group(1).strip()
    else:
        m2 = re.match(r"^在\s*([\u4e00-\u9fff]{2,12}?)\s*出发", s)
        if m2:
            s = m2.group(1).strip()
        else:
            s = re.sub(r"出发\s*$", "", s)
    s = re.sub(
        r"(市辖区|壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市|县|区)\s*$",
        "",
        s,
    )
    return (s.strip() or raw)[:60]


def _strip_city_noise(name: str) -> str:
    n = (name or "").strip()
    for suf in (
        "市辖区",
        "壮族自治区",
        "回族自治区",
        "维吾尔自治区",
        "特别行政区",
        "自治区",
        "省",
        "市",
        "县",
        "区",
    ):
        if len(n) > 2 and n.endswith(suf):
            n = n[: -len(suf)].strip()
    return n


def _departure_graph_stem_cypher() -> str:
    return "replace(replace(coalesce(dp.location, ''), '出发', ''), ' ', '')"


def _departure_match_any_clause() -> str:
    stem = _departure_graph_stem_cypher()
    return (
        "ANY(d IN $dep_terms WHERE size(d) >= 2 AND ("
        "dp.location CONTAINS d OR "
        f"(size({stem}) >= 2 AND d CONTAINS {stem})"
        "))"
    )


def _departure_search_terms(departure: str) -> list[str]:
    raw0 = (departure or "").strip()
    if not raw0:
        return []
    raw = _strip_city_noise(raw0) or raw0
    norm = _normalize_departure_token(raw)
    terms: list[str] = []
    for t in (
        norm,
        raw,
        raw0,
        (norm + "出发") if norm else "",
        (raw + "出发") if raw and not raw.endswith("出发") else "",
        (raw0 + "出发") if raw0 and not raw0.endswith("出发") else "",
    ):
        t = (t or "").strip()
        if len(t) >= 2 and t not in terms:
            terms.append(t)
    return terms[:10] or [raw0[:60]]


def _strip_travel_planning_noise_from_dest(text: str) -> str:
    t = str(text or "").strip()
    if not t:
        return t
    t = re.sub(
        r"(?:\d{1,3}|[一二三四五六七八九十百千万两]{1,5})\s*(?:晚\s*)?(?:日|天|夜|晚)(?:游|行程)?",
        " ",
        t,
    )
    t = re.sub(
        r"(?:^|[\s、，,/|+])(?:[一二三四五六七八九十两]+|\d+)\s*[天日月晚](?:游)?(?=[\s、，,/|+]|$)",
        " ",
        t,
    )
    t = re.sub(
        r"(?:跟团|自由行|半自助|私家团|包车游|纯玩|深度游|经典游)(?:\s|的|$)",
        " ",
        t,
    )
    return re.sub(r"\s+", " ", t).strip()


def _is_destination_noise_token(p: str) -> bool:
    x = (p or "").strip()
    if len(x) < 2:
        return True
    if re.fullmatch(r"(?:[一二三四五六七八九十两]+|\d+)\s*[天日月晚]", x):
        return True
    if x in ("跟团", "自由行", "半自助", "攻略", "规划", "预算", "左右", "大概", "日游", "晚"):
        return True
    return False


def _keyword_search_terms(keywords: str | None) -> list[str]:
    if not keywords or not str(keywords).strip():
        return []
    raw0 = str(keywords).strip()
    s0 = _strip_travel_planning_noise_from_dest(raw0) or raw0
    parts = re.split(r"[\s、，,/|+]+", s0)
    terms: list[str] = []
    for p in parts:
        p = p.strip()
        if len(p) < 2 or _is_destination_noise_token(p):
            continue
        if p not in terms:
            terms.append(p)
        bare = re.sub(
            r"(市辖区|壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市|县|区|州)\s*$",
            "",
            p,
        ).strip()
        if len(bare) >= 2 and bare not in terms and not _is_destination_noise_token(bare):
            terms.append(bare)
    if len(s0) >= 2 and s0 not in terms and not _is_destination_noise_token(s0):
        terms.insert(0, s0)
    bare0 = re.sub(
        r"(市辖区|壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市|县|区|州)\s*$",
        "",
        s0,
    ).strip()
    if len(bare0) >= 2 and bare0 not in terms and not _is_destination_noise_token(bare0):
        terms.append(bare0)
    for bridge in (s0, raw0):
        if not bridge:
            continue
        for seg in re.split(r"[到往至去]", bridge):
            seg = (_strip_travel_planning_noise_from_dest(seg.strip()) or seg.strip()).strip()
            if len(seg) < 2 or _is_destination_noise_token(seg):
                continue
            bare_seg = re.sub(
                r"(市辖区|壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市|县|区|州)\s*$",
                "",
                seg,
            ).strip()
            for cand in (seg, bare_seg):
                if len(cand) >= 2 and cand not in terms and not _is_destination_noise_token(cand):
                    terms.append(cand)
    if not terms and raw0:
        for chunk in re.findall(r"[\u4e00-\u9fff]{2,8}", raw0):
            c = _strip_travel_planning_noise_from_dest(chunk) or chunk
            if len(c) >= 2 and not _is_destination_noise_token(c) and c not in terms:
                terms.append(c)
    return terms[:12]


def _rows_to_dicts(rows: list[Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(dict(r))
    return out


def query_search_travel_deals(
    departure: str,
    max_price: Optional[int] = None,
    keywords: Optional[str] = None,
) -> list[dict[str, Any]]:
    dep_terms = _departure_search_terms(departure)
    kw_terms = _keyword_search_terms(keywords) if keywords else []

    def cypher_query(tx):
        q = f"""
        MATCH (td:TravelDetail)-[:HAS_DEPARTURE]->(dp:Departure)
        WHERE {_departure_match_any_clause()}
        """
        params: dict = {"dep_terms": dep_terms}
        if kw_terms:
            q += """AND ANY(k IN $kw_terms WHERE size(k) >= 2 AND (
                td.detail CONTAINS k
                OR coalesce(td.target_city, '') CONTAINS k
                OR coalesce(td.url, '') CONTAINS k
                OR toLower(td.detail) CONTAINS toLower(k)
                OR toLower(coalesce(td.target_city, '')) CONTAINS toLower(k)
            ))
            """
            params["kw_terms"] = kw_terms
        if max_price:
            q += "MATCH (td)-[:HAS_PRICE]->(pr:Price)\nWHERE pr.amount <= $max_price\n"
            params["max_price"] = max_price
        q += """
        OPTIONAL MATCH (td)-[:HAS_OFFER]->(of:Offer)
        OPTIONAL MATCH (td)-[:HAS_PRICE]->(pr:Price)
        RETURN td.detail AS itinerary,
               pr.amount AS price,
               of.discount AS offer,
               dp.location AS departure
        ORDER BY coalesce(pr.amount, 999999) ASC
        LIMIT 10
        """
        return list(tx.run(q, **params))

    with driver.session() as session:
        return _rows_to_dicts(session.execute_read(cypher_query))


def query_find_best_offers(
    departure: str,
    destination_keywords: str,
    max_price: int = 200_000,
) -> list[dict[str, Any]]:
    dep_terms = _departure_search_terms(departure)
    kw_terms = _keyword_search_terms(destination_keywords)

    def cypher_query(tx):
        q = f"""
        MATCH (td:TravelDetail)-[:HAS_DEPARTURE]->(dp:Departure)
        WHERE {_departure_match_any_clause()}
        AND (
            size($kw_terms) = 0
            OR ANY(k IN $kw_terms WHERE size(k) >= 2 AND (
                td.detail CONTAINS k
                OR coalesce(td.target_city, '') CONTAINS k
                OR coalesce(td.url, '') CONTAINS k
                OR toLower(td.detail) CONTAINS toLower(k)
                OR toLower(coalesce(td.target_city, '')) CONTAINS toLower(k)
            ))
        )
        MATCH (td)-[:HAS_PRICE]->(pr:Price)
        WHERE pr.amount <= $max_price
        OPTIONAL MATCH (td)-[:HAS_OFFER]->(of:Offer)
        RETURN td.detail AS itinerary,
               pr.amount AS price,
               of.discount AS offer,
               (pr.amount * 0.9) AS score
        ORDER BY score ASC, pr.amount ASC
        LIMIT 5
        """
        return list(tx.run(q, dep_terms=dep_terms, kw_terms=kw_terms, max_price=max_price))

    with driver.session() as session:
        return _rows_to_dicts(session.execute_read(cypher_query))


def query_travel_by_price_range(
    departure: str,
    min_price: int,
    max_price: int,
) -> list[dict[str, Any]]:
    dep_terms = _departure_search_terms(departure)

    def cypher_query(tx):
        q = f"""
        MATCH (td:TravelDetail)-[:HAS_DEPARTURE]->(dp:Departure)
        MATCH (td)-[:HAS_PRICE]->(pr:Price)
        WHERE {_departure_match_any_clause()}
        AND pr.amount >= $min_price AND pr.amount <= $max_price
        OPTIONAL MATCH (td)-[:HAS_OFFER]->(of:Offer)
        RETURN td.detail AS itinerary,
               pr.amount AS price,
               of.discount AS offer
        ORDER BY pr.amount ASC
        LIMIT 15
        """
        return list(tx.run(q, dep_terms=dep_terms, min_price=min_price, max_price=max_price))

    with driver.session() as session:
        return _rows_to_dicts(session.execute_read(cypher_query))
