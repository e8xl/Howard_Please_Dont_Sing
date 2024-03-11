import asyncio
import json
import random
import time
from typing import List
import subprocess

import aiohttp
from aiohttp import ClientWebSocketResponse


def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


config = open_file('./config/config.json')

token = config['token']
bot_id = config['botid']
channel_id = config['channel_id']

ws_clients: List[ClientWebSocketResponse] = []
wait_handler_msgs = []
with open('1.json', 'r') as f:
    a = json.loads(f.read())


async def get_gateway(channel_id: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(f'https://www.kaiheila.cn/api/v3/gateway/voice?channel_id={channel_id}',
                               headers={'Authorization': f'Bot {token}'}) as res:
            return (await res.json())['data']['gateway_url']


async def connect_ws():
    global ws_clients
    gateway = await get_gateway(channel_id)
    print(gateway)
    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(gateway) as ws:
            ws_clients.append(ws)
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    wait_handler_msgs.append(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    break
                else:
                    return


async def ws_msg():
    while True:
        if len(ws_clients) != 0:
            break
        await asyncio.sleep(0.1)
    a['1']['id'] = random.randint(1000000, 9999999)
    print('1:', a['1'])
    await ws_clients[0].send_json(a['1'])
    now = 1
    ip = ''
    port = 0
    rtcp_port = 0
    while True:
        if len(wait_handler_msgs) != 0:
            data = json.loads(wait_handler_msgs.pop(0))
            if now == 1:
                print('1:', data)
                a['2']['id'] = random.randint(1000000, 9999999)
                print('2:', a['2'])
                await ws_clients[0].send_json(a['2'])
                now = 2
            elif now == 2:
                print('2:', data)
                a['3']['id'] = random.randint(1000000, 9999999)
                print('3:', a['3'])
                await ws_clients[0].send_json(a['3'])
                now = 3
            elif now == 3:
                print('3:', data)
                transport_id = data['data']['id']
                ip = data['data']['ip']
                port = data['data']['port']
                rtcp_port = data['data']['rtcpPort']
                a['4']['data']['transportId'] = transport_id
                a['4']['id'] = random.randint(1000000, 9999999)
                print('4:', a['4'])
                await ws_clients[0].send_json(a['4'])
                now = 4
            elif now == 4:
                print('4:', data)
                print(f'ssrc=1357 ffmpeg rtp url: rtp://{ip}:{port}?rtcpport={rtcp_port}')
                audio_file_path = config["testMusic"]  # 替换为你的音频文件路径
                rtp_url = f"rtp://{ip}:{port}?rtcpport={rtcp_port}&ssrc=1357"  # 使用从 WebSocket 消息中获取的实际值
                ffmpeg_command = (f'ffmpeg -re -loglevel level+info -nostats -i "{audio_file_path}" '
                                  f'-map 0:a:0 -acodec libopus -ab 128k -filter:a volume=0.8 -ac 2 -ar 48000 '
                                  f'-f tee [select=a:f=rtp:ssrc=1357:payload_type=100]{rtp_url}')
                subprocess.run(ffmpeg_command, shell=True)
                now = 5
            else:
                if 'notification' in data and 'method' in data and data['method'] == 'disconnect':
                    print('The connection had been disconnected', data)
                elif 'notification' in data and 'method' in data and data['method'] == 'networkStat' and bot_id in \
                        data['data']['stat']:
                    # await (ws_clients.pop(0)).close()
                    # return
                    pass
                else:
                    print(data)
            continue
        await asyncio.sleep(0.1)


async def ws_ping():
    while True:
        if len(ws_clients) != 0:
            break
        await asyncio.sleep(0.1)
    ping_time = 0.0
    while True:
        await asyncio.sleep(0.1)
        if len(ws_clients) == 0:
            return
        now_time = time.time()
        if now_time - ping_time >= 30:
            await ws_clients[0].ping()
            ping_time = now_time


async def main():
    while True:
        await asyncio.gather(
            connect_ws(),
            ws_msg(),
            ws_ping()
        )


if __name__ == '__main__':
    asyncio.run(main())
