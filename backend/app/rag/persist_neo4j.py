from __future__ import annotations
from neo4j import GraphDatabase

from backend.app.config import settings
from backend.app.rag.models import TravelListing

driver = GraphDatabase.driver(
    settings.NEO4J_URI,
    auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
)

# 与 get_travel_details 中 Cypher 查询兼容：TravelDetail.detail / Departure / Price / Offer。
def upsert_listing(tx, item: TravelListing) -> None:
    tx.run(
        """
        MERGE (td:TravelDetail {source_id: $source_id})
        SET td.detail = $detail,
            td.source_site = $source_site,
            td.url = coalesce($url, ''),
            td.target_city = coalesce($target_city, ''),
            td.departure_code = $departure_code
        MERGE (dp:Departure {location: $departure})
        MERGE (td)-[:HAS_DEPARTURE]->(dp)
        WITH td
        OPTIONAL MATCH (td)-[rh:HAS_PRICE]->(oldp:Price)
        DELETE rh, oldp
        WITH td
        CREATE (pr:Price {amount: $price})
        CREATE (td)-[:HAS_PRICE]->(pr)
        """,
        source_id=item.source_id,
        detail=item.detail[:4000],
        source_site=item.source_site,
        url=item.url or "",
        departure=item.departure[:120],
        price=int(item.price),
        target_city=(item.target_city or "")[:80],
        departure_code=item.departure_code,
    )
    off = (item.offer or "").strip()
    if off:
        tx.run(
            """
            MATCH (td:TravelDetail {source_id: $source_id})
            OPTIONAL MATCH (td)-[ro:HAS_OFFER]->(oldo:Offer)
            DELETE ro, oldo
            WITH td
            CREATE (of:Offer {discount: $offer})
            CREATE (td)-[:HAS_OFFER]->(of)
            """,
            source_id=item.source_id,
            offer=off[:500],
        )

def write_listings_to_neo4j(items: list[TravelListing]) -> int:
    if not items:
        return 0
    with driver.session() as session:
        for it in items:
            session.execute_write(upsert_listing, it)
    return len(items)