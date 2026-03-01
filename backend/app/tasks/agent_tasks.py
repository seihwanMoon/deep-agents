from ..celery_app import celery


@celery.task(name="agent.execute")
def execute_agent(agent_id: int, message: str):
    return {"agent_id": agent_id, "result": f"executed: {message}"}
