import json
from channels.generic.websocket import WebsocketConsumer

from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import async_to_sync

class UploadProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):  # Replace with your channel name logic
        await self.channel_layer.group_add(
            'progress_group',
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            'progress_group',
            self.channel_name
        )

    async def send_progress(self, event):
        progress = event['progress']
        await self.send(text_data=str(progress))