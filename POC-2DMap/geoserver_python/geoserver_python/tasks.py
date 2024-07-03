from celery import shared_task
from . import views
import time
@shared_task(bind=True, queue='poc_tasks')
def my_task(celery_task, file_data, files=None):
    print('\n\n**********\nstartttttttttttttt...\n**********\n\n')
    start = time.time()


    task_results = views.concurrency_logic(file_data, task=celery_task)

    end = time.time()
    print('\n\n**********\n endddddddddddddddd--> {:0.1f} seconds\n**********\n\n'.format(
        (end - start)))

    print('Hello from Celery!')
    return task_results
