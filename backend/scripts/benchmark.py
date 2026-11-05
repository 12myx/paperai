"""P9 synthetic retrieval benchmark.

Run: python scripts/benchmark.py
This measures the offline lexical/trigram index, not model latency or PDF parsing.
"""
from __future__ import annotations

import json
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import Paper
from app.services.retrieval import Document, HybridIndex

WORDS = "retrieval augmentation citation faithfulness section chunking contrastive low-resource evaluation dataset metric method limitation evidence".split()


def main() -> None:
    documents = [
        Document(
            chunk_id=f"c{index}",
            paper_id=f"p{index // 40}",
            paper_title=f"Paper {index // 40} on retrieval",
            page_start=index % 20 + 1,
            page_end=index % 20 + 1,
            section="Method" if index % 3 else "Results",
            text=" ".join(WORDS[(index + step) % len(WORDS)] for step in range(60)),
            tags=["method"],
        )
        for index in range(5000)
    ]
    started = time.perf_counter()
    index = HybridIndex(documents)
    build_ms = (time.perf_counter() - started) * 1000
    timings = []
    for query in ["retrieval citation faithfulness", "low resource contrastive evaluation", "section chunking evidence", "dataset metric limitation"] * 8:
        start = time.perf_counter()
        index.search(query, top_k=8)
        timings.append((time.perf_counter() - start) * 1000)
    timings.sort()
    p95 = timings[int(len(timings) * 0.95) - 1]
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    with Session() as db:
        db.add_all([
            Paper(user_id="bench", title=f"Benchmark paper {index}", filename=f"p{index}.pdf", stored_path=f"p{index}.pdf", sha256=f"bench-{index}", status="ready")
            for index in range(50)
        ])
        db.commit()
        start = time.perf_counter()
        db.execute(select(Paper).where(Paper.user_id == "bench", Paper.status == "ready").order_by(Paper.created_at.desc()).limit(60)).scalars().all()
        paper_list_ms = (time.perf_counter() - start) * 1000
    print(json.dumps({
        "documents": len(documents),
        "build_ms": round(build_ms, 2),
        "queries": len(timings),
        "p50_ms": round(statistics.median(timings), 2),
        "p95_ms": round(p95, 2),
        "max_ms": round(max(timings), 2),
        "paper_list_50_ms": round(paper_list_ms, 2),
        "target_p95_ms": 300,
        "target_list_50_ms": 500,
        "pass": p95 < 300 and paper_list_ms < 500,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()