"""Evidence coverage audit for a user.

Usage:
    python scripts/audit_evidence.py qa@paperlens.ai
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.db import SessionLocal
from app.models import Conversation, Evidence, Message, ResearchAnalysis, User


def main() -> int:
    email = sys.argv[1] if len(sys.argv) > 1 else "qa@paperlens.ai"
    db = SessionLocal()
    try:
        user = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            print("user not found:", email)
            return 1

        messages = db.execute(
            select(Message)
            .join(Conversation, Conversation.id == Message.conversation_id)
            .where(Conversation.user_id == user.id, Message.role == "assistant")
        ).scalars().all()
        analyses = db.execute(
            select(ResearchAnalysis).where(ResearchAnalysis.user_id == user.id)
        ).scalars().all()
        evidence = db.execute(select(Evidence).where(Evidence.user_id == user.id)).scalars().all()

        by_source = {}
        for item in evidence:
            by_source[(item.source_type, item.source_id)] = by_source.get((item.source_type, item.source_id), 0) + 1

        cited_messages = [m for m in messages if m.citations]
        missing_messages = [m for m in cited_messages if by_source.get(("message", m.id), 0) == 0]
        cited_analyses = [a for a in analyses if a.citations]
        missing_analyses = [a for a in cited_analyses if by_source.get(("analysis", a.id), 0) == 0]

        verified = sum(1 for item in evidence if item.verified)
        types = {}
        for item in evidence:
            types[item.evidence_type] = types.get(item.evidence_type, 0) + 1

        print(f"user: {email}")
        print(f"evidence total: {len(evidence)} | verified: {verified} | unverified: {len(evidence) - verified}")
        print(f"types: {types}")
        print(f"assistant messages: {len(messages)} | with citations: {len(cited_messages)} | missing evidence: {len(missing_messages)}")
        print(f"analyses: {len(analyses)} | with citations: {len(cited_analyses)} | missing evidence: {len(missing_analyses)}")
        if missing_messages:
            print("missing message ids:", [m.id for m in missing_messages[:20]])
        if missing_analyses:
            print("missing analysis ids:", [a.id for a in missing_analyses[:20]])
        coverage = 1.0
        denominators = len(cited_messages) + len(cited_analyses)
        if denominators:
            coverage = (denominators - len(missing_messages) - len(missing_analyses)) / denominators
        print(f"citation coverage: {coverage:.1%}")
        return 0 if not missing_messages and not missing_analyses else 2
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
