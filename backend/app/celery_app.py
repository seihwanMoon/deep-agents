from celery import Celery

celery = Celery("deep_agents", broker="redis://redis:6379/0", backend="redis://redis:6379/0")
celery.conf.beat_schedule = {}
