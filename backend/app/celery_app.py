from .config import settings
from celery import Celery

celery = Celery("deep_agents", broker=settings.redis_url, backend=settings.redis_url)
celery.conf.update(
    task_always_eager=settings.celery_task_always_eager,
    task_eager_propagates=True,
)
celery.conf.beat_schedule = {}
