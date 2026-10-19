# backend/scripts/test_chat.py
import asyncio
import os
import sys
import uuid

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.db import AsyncSessionLocal
from app.orchestrator.router import get_orchestrator_graph, RunContext
from app.auth.deps import SessionContext
from sqlalchemy import text

async def test_chat():
    async with AsyncSessionLocal() as db:
        res = await db.execute(text("SELECT id, role, account_status FROM users WHERE email = 'member.alex@gympro.local'"))
        user = res.mappings().one()
        
        session_ctx = SessionContext(
            user_id=str(user['id']),
            account_email='member.alex@gympro.local',
            role='USER',
            account_status='ACTIVE',
            health_consent=True
        )
        
        run_ctx = RunContext(
            session=session_ctx,
            db=db,
            run_id=uuid.uuid4(),
            trace_id=str(uuid.uuid4()),
        )
        graph = get_orchestrator_graph()
        
        state = {
            'ctx': run_ctx,
            'query': 'What classes do you have tomorrow?',
            'outputs': {},
            'bundle': None,
            'reply': {},
        }
        
        try:
            tid = f"{user['id']}:{uuid.uuid4()}"
            res = await graph.ainvoke(
                state,
                config={'configurable': {'thread_id': tid}},
            )
            print('CHAT SUCCESS! Reply:', res.get('reply'))
        except Exception as e:
            import traceback
            traceback.print_exc()

if __name__ == '__main__':
    asyncio.run(test_chat())
