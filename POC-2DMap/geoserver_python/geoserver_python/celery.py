import os
from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoserver_python.settings')

app = Celery('geoserver_python')

app.config_from_object('django.conf:settings', namespace='CELERY')
app.conf.task_always_eager = True

app.autodiscover_tasks()