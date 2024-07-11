#      -*- coding: utf-8 -*-
#
# ----------   info     ---------- #
#
# (c) 2020-2021 Terabase Energy#  Allan Daly, adaly@terabase.energy
#
# ----------   file     ---------- #
#
#  /terabase/utilities.py
#  Created by allan on 1/5/21 6:27 PM
#
# --------  description  --------- #
"""


"""
# ----------  imports   ---------- #

# python imports
import datetime as dt
from redis import Redis
import json

class RedisDBConnector(object):
    """encapsulates redis database backend functions"""

    def __init__(self, host, port, password):
        self.redisdb_client = Redis(
            host=host,
            port=port,
            password=password,
            db=0
        )

    def add(self, data):
        """
        add key-value pair to redis database

        :params data: dict of key-value pairs to be added
        :return True
        """
        for k in data.keys():
            if isinstance(data[k], dict):
                data[k] = json.dumps(data[k])

            self.redisdb_client.set(k, data[k])

        return True
    def add_df(self,key, data,timeout=None):
        """
        add key-value pair to redis database

        :params data: dict of key-value pairs to be added
        :return True
        """

        data = json.dumps(data)

        self.redisdb_client.set(key, data)
        if timeout is not None:
            self.redisdb_client.expire(key, timeout)

        return True

    def get_df(self, key):
        """
        get key value from redis database

        :params keys: list of keys
        :return rtype -> dict, values from redis database
        """

        data = self.redisdb_client.get(key)

        return data
    def get(self, keys):
        """
        get key value from redis database

        :params keys: list of keys
        :return rtype -> dict, values from redis database
        """
        if not isinstance(keys, list):
            raise Exception("expected list of keys")

        data = dict()
        for k in keys:
            data[k] = self.redisdb_client.get(k)

        return data

    def expire(self, key, timeout):
        self.redisdb_client.expire(key, timeout)
        return True
    def remove(self, keys):
        """
        delete key-value pair from redis database

        :params keys: list of keys
        :return None
        """
        if not isinstance(keys, list):
            raise Exception("expected list of keys")

        for k in keys:
            print(self.redisdb_client.delete(k))

        return True

    def add_update_tb_task(self, celery_task_id, task_data):
        """
        add terabase task data to redis database

        :params celery_task_id: dict of key-value pairs to be added
        :params task_data: dict of key-value pairs to be added
        :return True
        """
        tb_task_id = f'tb-task-{celery_task_id}'
        if not isinstance(task_data, dict):
            raise Exception("Task data must be a python dict object")

        tb_task_data = {
            tb_task_id: task_data
        }
        self.add(tb_task_data)

        return True

    def get_tb_task_data(self, tb_task_id):
        """
        get key value from redis database

        :params tb_task_id: terabase task id
        :return rtype -> dict, values from redis database
        """
        if not isinstance(tb_task_id, str):
            raise Exception("tb_task_id must be a string")

        task_data = self.get([tb_task_id])
        for d in task_data:
            task_data[d] = json.loads(task_data[d])

        return task_data

    def remove(self, keys):
        """
        delete key-value pair from redis database

        :params keys: list of keys
        :return None
        """
        if not isinstance(keys, list):
            raise Exception("expected list of keys")

        for k in keys:
            print(self.redisdb_client.delete(k))