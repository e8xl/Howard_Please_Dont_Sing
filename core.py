# core.py
import asyncio
import json
import os

from khl import Bot

from VoiceAPI import KookVoiceClient as Voice

lock = asyncio.Lock()
# 添加一个全局字典来存储客户端实例
clients = {}


def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


config = open_file('./config/config.json')
bot = Bot(token=config['token'])
# 指定 ffmpeg 路径
ffmpeg_path = os.path.join(os.path.dirname(__file__), 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')


async def join_voice_channel(channel_id: str):
    async with lock:
        token = config['token']

        # 检查是否已经有这个频道的客户端实例
        if channel_id not in clients:
            client = Voice(token, channel_id)
            clients[channel_id] = client
        else:
            client = clients[channel_id]

        # 加入语音频道
        await client.join_channel()

        # 构建推流地址
        stream_details = client.construct_stream_url()
        if stream_details:
            print("推流详情:")
            # for key, value in stream_details.items():
            #     print(f"{key}: {value}")
            print(stream_details)
            return stream_details

        # 获取频道列表
        channel_list = await client.get_channel_list()
        if channel_list:
            print("已加入的语音频道列表:")
            for channel in channel_list:
                print(channel)


async def leave_voice_channel(channel_id: str):
    async with lock:
        if channel_id in clients:
            client = clients[channel_id]
            # 离开语音频道
            await client.leave_channel()
            print("成功离开语音频道")
            # 移除客户端实例
            del clients[channel_id]
        else:
            print("没有找到对应的语音频道客户端实例")
