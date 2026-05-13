from __future__ import annotations
from dataclasses import dataclass

# 与 Neo4j TravelDetail / Price / Departure 及 Chroma 文档对齐的结构。
@dataclass
class TravelListing:
    source_id: str
    source_site: str
    detail: str
    departure: str
    price: int
    offer: str | None = None
    url: str | None = None
    raw_title: str = ""
    target_city: str | None = None
    departure_code: int | None = None

    def chroma_page_content(self) -> str:
        parts = [
            self.raw_title or self.detail[:120],
            f"出发地:{self.departure}",
        ]
        if self.target_city:
            parts.append(f"目的地:{self.target_city}")
        parts += [
            f"价格约:{self.price}元",
            f"来源:{self.source_site}",
        ]
        if self.offer:
            parts.append(f"优惠:{self.offer}")
        if self.url:
            parts.append(f"链接:{self.url}")
        parts.append(self.detail)
        return "\n".join(parts)
