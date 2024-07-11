from celery import shared_task
from . import views
import time
import pandas as pd
@shared_task(bind=True)
def my_task(celery_task, file_data, files=None):
    print('\n\n**********\nstartttttttttttttt...\n**********\n\n')
    start = time.time()


    task_results = views.concurrency_logic(file_data, task=celery_task)

    end = time.time()
    print('\n\n**********\n endddddddddddddddd--> {:0.1f} seconds\n**********\n\n'.format(
        (end - start)))

    print('Hello from Celery!')
    return task_results

def chunkify(df, chunk_size):
    for start in range(0, len(df), chunk_size):
        yield df[start:start + chunk_size]

@shared_task(bind=True)
def create_point_shape_file_task(celery_task, file_data, files=None):
    print('\n\n**********\nstartttttttttttttt...\n**********\n\n')
    start = time.time()

    chunk_size = 1000
    is_first_chunk = True
    all_results = []

    for idx, chunk in enumerate(chunkify(pd.DataFrame(file_data), chunk_size)):
        chunk_dict = chunk.to_dict(orient='records')
        task_results = views.create_point_shape_file(chunk_dict,is_first_chunk, task=celery_task)
        all_results.append(task_results)
        is_first_chunk = False

    end = time.time()
    print('\n\n**********\n endddddddddddddddd--> {:0.1f} seconds\n**********\n\n'.format(
        (end - start)))

    print('Hello from Celery!')
    return all_results

@shared_task(bind=True)
def create_polygon_shape_file_task(celery_task, file_data, files=None):
    print('\n\n**********\nstartttttttttttttt...\n**********\n\n')
    start = time.time()

    chunk_size = 1000
    is_first_chunk = True
    all_results = []

    for idx, chunk in enumerate(chunkify(pd.DataFrame(file_data), chunk_size)):
        chunk_dict = chunk.to_dict(orient='records')
        task_results = views.create_polygon_shape_file(chunk_dict,is_first_chunk, task=celery_task)
        all_results.append(task_results)
        is_first_chunk = False

    end = time.time()
    print('\n\n**********\n endddddddddddddddd--> {:0.1f} seconds\n**********\n\n'.format(
        (end - start)))

    print('Hello from Celery!')
    return all_results

@shared_task(bind=True)
def create_geo_tiff_for_contour_data_task(celery_task, file_data, files=None):
    print('\n\n**********\nstartttttttttttttt...\n**********\n\n')
    start = time.time()


    task_results = views.create_geo_tiff_for_contour_data(file_data, task=celery_task)

    end = time.time()
    print('\n\n**********\n endddddddddddddddd--> {:0.1f} seconds\n**********\n\n'.format(
        (end - start)))

    print('Hello from Celery!')
    return task_results

@shared_task(bind=True)
def create_geo_tiff_for_heatmap_data_task(celery_task, file_data, files=None):
    print('\n\n**********\nstartttttttttttttt...\n**********\n\n')
    start = time.time()


    task_results = views.create_geo_tiff_for_heatmap_data(file_data, task=celery_task)

    end = time.time()
    print('\n\n**********\n endddddddddddddddd--> {:0.1f} seconds\n**********\n\n'.format(
        (end - start)))

    print('Hello from Celery!')
    return task_results
