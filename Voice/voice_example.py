import asyncio
import json
import os
import random
import subprocess
import sys
import io
import time
import logging
from typing import List

import aiohttp
from aiohttp import ClientWebSocketResponse
from khl import Message, Bot

# Set the encoding to UTF-8 for console output
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

ffmpeg_path = os.path.join(os.path.dirname(__file__), '..', 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')


def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


config = open_file('../config/config.json')
bot = Bot(token=config['token'])

token = config['token']

ws_clients: List[ClientWebSocketResponse] = []
wait_handler_msgs = []
is_playing = False  # 添加播放状态标志
with open('../1.json', 'r') as f:
    a = json.loads(f.read())


async def get_gateway(channel_id: str) -> str:
    async with aiohttp.ClientSession() as session:
        async with session.get(f'https://www.kaiheila.cn/api/v3/gateway/voice?channel_id={channel_id}',
                               headers={'Authorization': f'Bot {token}'}) as res:
            return (await res.json())['data']['gateway_url']


@bot.command(name='play')
async def connect_ws(msg: Message):
    global ws_clients, is_playing, wait_handler_msgs

    # 重置状态
    wait_handler_msgs = []
    if is_playing:  # 检查是否正在播放
        await msg.reply("暂不可使用，请等待当前播放完毕")
        logging.info("Play command received but already playing. User notified.")
        return

    logging.info("Play command received. Connecting to channel.")
    channel = await msg.ctx.guild.fetch_joined_channel(msg.author)
    channel_id = channel[0].id
    gateway = await get_gateway(channel_id)
    logging.info(f"Gateway URL: {gateway}")

    # Close previous WebSocket connection if exists
    if ws_clients:
        await ws_clients[0].close()
        ws_clients.clear()

    async with aiohttp.ClientSession() as session:
        async with session.ws_connect(gateway) as ws:
            ws_clients.append(ws)
            # 处理任务的异常
            task1 = asyncio.create_task(ws_msg())
            task2 = asyncio.create_task(ws_ping())
            task1.add_done_callback(task_exception_handler)
            task2.add_done_callback(task_exception_handler)
            async for msg in ws:  # type: aiohttp.WSMessage
                if msg.type == aiohttp.WSMsgType.TEXT:
                    wait_handler_msgs.append(msg.data)
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    logging.error("WebSocket encountered an error")
                    break
                else:
                    logging.warning("Received unknown WebSocket message type")
                    return


@bot.command(name="状态")
async def menu(msg: Message):
    await msg.reply("正在运行")
    logging.info("Status command received. Bot is running.")


async def ws_msg():
    global is_playing
    is_playing = True  # 设置播放状态为 True
    logging.info("WebSocket message handling started. Setting is_playing to True.")
    while True:
        if len(ws_clients) != 0:
            break
        await asyncio.sleep(0.1)
    a['1']['id'] = random.randint(1000000, 9999999)
    logging.info(f"Sending initial message: {a['1']}")
    await ws_clients[0].send_json(a['1'])
    now = 1
    ip = ''
    port = 0
    rtcp_port = 0
    while True:
        if len(wait_handler_msgs) != 0:
            data = json.loads(wait_handler_msgs.pop(0))
            logging.info(f"Received message: {data}")
            if now == 1:
                a['2']['id'] = random.randint(1000000, 9999999)
                logging.info(f"Sending second message: {a['2']}")
                await ws_clients[0].send_json(a['2'])
                now = 2
            elif now == 2:
                a['3']['id'] = random.randint(1000000, 9999999)
                logging.info(f"Sending third message: {a['3']}")
                await ws_clients[0].send_json(a['3'])
                now = 3
            elif now == 3:
                transport_id = data['data']['id']
                ip = data['data']['ip']
                port = data['data']['port']
                rtcp_port = data['data']['rtcpPort']
                a['4']['data']['transportId'] = transport_id
                a['4']['id'] = random.randint(1000000, 9999999)
                logging.info(f"Sending fourth message: {a['4']}")
                await ws_clients[0].send_json(a['4'])
                now = 4
            elif now == 4:
                logging.info(f"Received final response: {data}")
                audio_file_path = config["testMusic"]  # 替换为你的音频文件路径
                rtp_url = f"rtp://{ip}:{port}?rtcpport={rtcp_port}&ssrc=1357"  # 使用从 WebSocket 消息中获取的实际值
                ffmpeg_command = (f'{ffmpeg_path} -re -loglevel level+info -nostats -i "{audio_file_path}" '
                                  f'-map 0:a:0 -acodec libopus -ab 128k -filter:a volume=0.6 -ac 2 -ar 48000 '
                                  f'-f tee [select=a:f=rtp:ssrc=1357:payload_type=100]{rtp_url}')
                logging.info(f"Starting ffmpeg with command: {ffmpeg_command}")
                task = asyncio.create_task(run_ffmpeg(ffmpeg_command))
                task.add_done_callback(task_exception_handler)  # 添加任务完成回调函数
                now = 5
            else:
                if 'notification' in data and 'method' in data and data['method'] == 'disconnect':
                    logging.info(f"The connection had been disconnected: {data}")
                elif 'notification' in data and 'method' in data and data['method'] == 'networkStat':
                    pass
                else:
                    logging.info(f"Unhandled message: {data}")
            continue
        await asyncio.sleep(0.1)


async def run_ffmpeg(command):
    logging.info(f"Running ffmpeg command: {command}")
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    stdout, stderr = await process.communicate()

    logging.info(f'[ffmpeg stdout]\n{stdout.decode("utf-8", errors="replace")}')
    logging.info(f'[ffmpeg stderr]\n{stderr.decode("utf-8", errors="replace")}')

    await monitor_ffmpeg()


async def monitor_ffmpeg():
    global is_playing
    logging.info("ffmpeg process finished. Waiting 10 seconds before disconnecting.")
    await asyncio.sleep(10)  # 播放完毕后等待 10 秒再退出频道
    if ws_clients:
        await ws_clients[0].close()
        ws_clients.clear()
    logging.info("Disconnected from channel")
    is_playing = False  # 播放结束后重置播放状态


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
            logging.info("Sent ping to keep WebSocket connection alive.")


def task_exception_handler(task):
    try:
        task.result()
    except Exception as e:
        logging.error(f'Task raised an exception: {e}')


if __name__ == '__main__':
    logging.info("Starting bot.")
    bot.run()
