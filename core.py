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


def update_ffmpeg_config(stream_url: str, bitrate: str):
    config_path = './config/ffmpeg_config.json'
    config_data = open_file(config_path)
    config_data['rtp_url'] = stream_url
    config_data['bitrate'] = bitrate

    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(config_data, f, ensure_ascii=False, indent=4)


async def join_voice_channel(channel_id: str):
    async with lock:
        token = config['token']

        if channel_id not in clients:
            client = Voice(token, channel_id)
            clients[channel_id] = client
        else:
            client = clients[channel_id]

        await client.join_channel()
        stream_details = client.construct_stream_url()
        if stream_details:
            print("推流详情:")
            print(stream_details)
            # Update the rtp_url in ffmpeg_config.json
            update_ffmpeg_config(stream_details['stream_url'], stream_details['bitrate'])
            return stream_details

        channel_list = await client.get_channel_list()
        if channel_list:
            print("已加入的语音频道列表:")
            for channel in channel_list:
                print(channel)


async def leave_voice_channel(channel_id: str):
    async with lock:
        if channel_id in clients:
            client = clients[channel_id]
            await client.leave_channel()
            print("成功离开语音频道")
            del clients[channel_id]
            # Clear the rtp_url in ffmpeg_config.json
            update_ffmpeg_config('', '')
        else:
            print("没有找到对应的语音频道客户端实例")
