# core.py

import asyncio
import json
import os
from VoiceAPI import KookVoiceClient as Voice
from khl import Bot, Message
import aiofiles
import logging

# 配置日志记录器
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
formatter = logging.Formatter('[%(asctime)s][%(levelname)s]: %(message)s')
handler.setFormatter(formatter)
logger.addHandler(handler)

# 加载配置
def load_config(path='./config/config.json'):
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()

# 初始化Bot
bot = Bot(token=config['token'])

# 指定ffmpeg路径
ffmpeg_path = os.path.join(os.path.dirname(__file__), 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')


def construct_ffmpeg_command(song_file, stream_details):
    # 提取推流参数
    audio_ssrc = stream_details.get('audio_ssrc')
    audio_pt = stream_details.get('audio_pt')
    ip = stream_details.get('ip')
    port = stream_details.get('port')
    rtcp_mux = stream_details.get('rtcp_mux', True)
    rtcp_port = stream_details.get('rtcp_port') if not rtcp_mux else None

    # 构建推流URL
    if rtcp_mux:
        stream_url = f"rtp://{ip}:{port}?ssrc={audio_ssrc}&payload_type={audio_pt}"
    else:
        stream_url = f"rtp://{ip}:{port}?ssrc={audio_ssrc}&payload_type={audio_pt}&rtcpport={rtcp_port}"

    # 构造ffmpeg命令
    ffmpeg_cmd = [
        '-i', song_file,
        '-map', '0:a:0',
        '-acodec', 'libopus',
        '-b:a', '48k',        # 码率48k
        '-ac', '2',
        '-ar', '48000',
        '-filter:a', 'volume=0.8',
        '-f', 'rtp',
        stream_url
    ]

    return ffmpeg_cmd


class VoiceManager:
    def __init__(self, config, ffmpeg_path, bot):
        self.config = config
        self.ffmpeg_path = ffmpeg_path
        self.bot = bot
        self.voice_clients = {}  # channel_id: Voice实例
        self.playlists = {}       # channel_id: 播放列表
        self.current_processes = {}  # channel_id: ffmpeg进程
        self.locks = {}           # channel_id: asyncio.Lock()
        self.playlist_file = './PlayList.json'
        self.audio_lib = os.path.join(os.path.dirname(__file__), 'AudioLib')
        self.text_channels = {}   # channel_id: 用于发送消息的文本频道ID

        # 如果存在，加载现有的播放列表
        if os.path.exists(self.playlist_file):
            with open(self.playlist_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                self.playlists = data.get("PlayList", {})
                logger.info("已加载现有的播放列表。")
        else:
            self.playlists = {}
            logger.info("未找到现有的播放列表，初始化为空。")

    async def join_channel(self, channel_id, text_channel_id=None):
        if channel_id in self.voice_clients:
            logger.info(f"已加入频道 {channel_id}")
            return

        token = self.config['token']
        client = Voice(token, channel_id)
        await client.join_channel()
        stream_details = client.construct_stream_url()

        if not stream_details:
            logger.error("获取推流信息失败。")
            return

        self.voice_clients[channel_id] = client
        self.playlists[channel_id] = []
        self.locks[channel_id] = asyncio.Lock()
        self.text_channels[channel_id] = text_channel_id

        logger.info(f"成功加入语音频道 {channel_id}。")

        # 启动播放循环任务
        asyncio.create_task(self.playback_loop(channel_id))

    async def leave_channel(self, channel_id):
        if channel_id not in self.voice_clients:
            logger.info(f"未加入频道 {channel_id}")
            return

        client = self.voice_clients[channel_id]
        await client.leave_channel()

        # 终止正在运行的ffmpeg进程
        if channel_id in self.current_processes:
            process = self.current_processes[channel_id]
            process.terminate()
            await process.wait()
            del self.current_processes[channel_id]
            logger.info(f"已终止频道 {channel_id} 的ffmpeg进程。")

        # 移除相关数据
        del self.voice_clients[channel_id]
        del self.playlists[channel_id]
        del self.locks[channel_id]
        if channel_id in self.text_channels:
            del self.text_channels[channel_id]

        logger.info(f"已离开语音频道 {channel_id}。")

    async def add_song_to_playlist(self, channel_id, song_name, singer, msg: Message):
        async with self.locks[channel_id]:
            playlist = self.playlists.get(channel_id, [])
            song_id = len(playlist)
            playlist.append({
                "id": str(song_id),
                "SongName": song_name,
                "Singer": singer
            })

            # 保存到PlayList.json
            await self.save_playlist()

            logger.info(f"已将歌曲 {song_name}-{singer} 添加到频道 {channel_id} 的播放列表。")

            await msg.reply(f"已将 **{song_name} - {singer}** 添加到播放列表。")

    async def save_playlist(self):
        data = {
            "PlayList": self.playlists
        }
        async with aiofiles.open(self.playlist_file, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(data, ensure_ascii=False, indent=4))
        logger.info("已保存播放列表到 PlayList.json。")

    async def load_playlist(self):
        if os.path.exists(self.playlist_file):
            async with aiofiles.open(self.playlist_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                data = json.loads(content)
                self.playlists = data.get("PlayList", {})
                logger.info("已从 PlayList.json 加载播放列表。")
        else:
            self.playlists = {}
            logger.info("未找到 PlayList.json，初始化为空播放列表。")

    async def playback_loop(self, channel_id):
        client = self.voice_clients[channel_id]
        while True:
            async with self.locks[channel_id]:
                if not self.playlists[channel_id]:
                    # 播放列表为空，等待后续添加
                    await asyncio.sleep(1)
                    continue

                # 获取播放列表中的第一首歌曲
                current_song = self.playlists[channel_id][0]
                song_file = self.find_song_file(current_song['SongName'], current_song.get('Singer', ''))

                if not song_file:
                    logger.error(f"在AudioLib中未找到歌曲 {current_song['SongName']}-{current_song.get('Singer', '')}。")
                    # 从播放列表中移除该歌曲
                    self.playlists[channel_id].pop(0)
                    await self.save_playlist()
                    continue

                # 获取推流信息
                stream_details = client.construct_stream_url()
                if not stream_details:
                    logger.error("获取推流信息失败。")
                    await asyncio.sleep(1)
                    continue

                # 构造ffmpeg命令
                ffmpeg_cmd = construct_ffmpeg_command(song_file, stream_details)

                logger.info(f"开始推流歌曲 {current_song['SongName']}-{current_song.get('Singer', '')}。")

                # 启动ffmpeg进程
                process = await asyncio.create_subprocess_exec(
                    self.ffmpeg_path,
                    *ffmpeg_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )

                self.current_processes[channel_id] = process

                # 发送正在播放的消息
                await self.send_playing_message(channel_id, current_song)

                # 等待ffmpeg进程结束
                stdout, stderr = await process.communicate()

                if process.returncode != 0:
                    logger.error(f"频道 {channel_id} 的ffmpeg错误: {stderr.decode()}")

                # 从播放列表中移除已播放的歌曲
                async with self.locks[channel_id]:
                    self.playlists[channel_id].pop(0)
                    await self.save_playlist()
                    logger.info(f"已从频道 {channel_id} 的播放列表中移除歌曲 {current_song['SongName']}-{current_song.get('Singer', '')}。")

                # 移除进程记录
                del self.current_processes[channel_id]

    def find_song_file(self, song_name, singer):
        # 在AudioLib中查找匹配的音频文件
        extensions = ['mp3', 'flac', 'wav']
        search_patterns = [
            f"{song_name}-{singer}",
            f"{song_name}"  # 如果不提供歌手名
        ]

        for pattern in search_patterns:
            for ext in extensions:
                filepath = os.path.join(self.audio_lib, f"{pattern}.{ext}")
                if os.path.exists(filepath):
                    logger.info(f"找到歌曲文件: {filepath}")
                    return filepath

        logger.warning(f"未在AudioLib中找到歌曲 {song_name}-{singer}。")
        return None

    async def send_playing_message(self, channel_id, song):
        text_channel_id = self.text_channels.get(channel_id)
        if not text_channel_id:
            logger.warning(f"未为语音频道 {channel_id} 指定文本频道，无法发送播放消息。")
            return

        # 构建消息内容
        message_content = f"🎶 正在播放 **{song['SongName']} - {song.get('Singer', '')}**"

        try:
            await self.bot.api.message.create(
                channel_id=text_channel_id,
                content=message_content
            )
            logger.info(f"已在文本频道 {text_channel_id} 发送播放消息。")
        except Exception as e:
            logger.error(f"发送播放消息失败: {e}")

# 实例化VoiceManager
voice_manager = VoiceManager(config, ffmpeg_path, bot)

# 核心函数，供index.py调用
async def join_voice_channel(channel_id: str, text_channel_id: str, msg: Message):
    await voice_manager.join_channel(channel_id, text_channel_id)
    await msg.reply(f"已加入语音频道 {channel_id}。")

async def leave_voice_channel(channel_id: str, msg: Message):
    await voice_manager.leave_channel(channel_id)
    await msg.reply(f"已离开语音频道 {channel_id}。")

async def play_song(channel_id: str, song_name: str, singer: str, msg: Message):
    if channel_id not in voice_manager.voice_clients:
        await msg.reply("机器人未加入任何语音频道。请先使用 `play` 命令加入语音频道。")
        return

    await voice_manager.add_song_to_playlist(channel_id, song_name, singer, msg)

# 请确保在index.py中启动bot的事件循环，例如：
# bot.run()

