import asyncio

from VoiceAPI import KookVoiceClient

# 全局字典来管理客户端实例
clients = {}
clients_lock = asyncio.Lock()

# 全局字典来管理保持活跃的任务
keep_alive_tasks = {}

# 全局字典来管理推流任务
stream_tasks = {}


async def get_client(channel_id, token):
    async with clients_lock:
        if channel_id in clients:
            return clients[channel_id]
        else:
            client = KookVoiceClient(token, channel_id)
            clients[channel_id] = client
            return client


async def remove_client(channel_id):
    async with clients_lock:
        client = clients.pop(channel_id, None)
        if client:
            await client.close()
