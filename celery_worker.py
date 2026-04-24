# celery_worker.py
from app.services.celery_tasks import celery_app

if __name__ == "__main__":
    celery_app.start()