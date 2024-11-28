# core.py
import asyncio
import json
import logging
import os
import time

import aiohttp
from qrcode.main import QRCode

from VoiceAPI import KookVoiceClient, VoiceClientError
from client_manager import get_client, remove_client


# region 环境配置部分
def open_file(path: str):
    # 检查文件是否存在
    if not os.path.exists(path):
        print(f"错误: 文件 '{path}' 不存在。")
        return None

    try:
        with open(path, 'r', encoding='utf-8') as f:
            tmp = json.load(f)
        return tmp
    except FileNotFoundError:
        print(f"错误: 文件 '{path}' 找不到。")
        return None
    except json.JSONDecodeError:
        print(f"错误: 文件 '{path}' 包含无效的 JSON 格式。")
        return None
    except Exception as e:
        print(f"发生了一个意外错误: {e}")
        return None


# 打开config.json并进行检测
config = open_file('./config/config.json')
if config is None:
    # 文件不存在或加载出错时，停止程序
    print("加载配置文件失败，程序退出。")
    exit(1)  # 或者使用 break 来终止循环或程序

token = config['token']


# 设置 ffmpeg 路径
def set_ffmpeg_path():
    ffmpeg_path = os.path.join(os.path.dirname(__file__), 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')
    if not os.path.exists(ffmpeg_path):
        raise FileNotFoundError(f"未找到 ffmpeg.exe，请检查路径是否正确: {ffmpeg_path}")
    return ffmpeg_path


# endregion

# region 网易API部分
async def search_netease_music(keyword: str):
    # aiohttp调用网易云音乐API localhost:3000/search?keywords=keyword
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f'http://localhost:3000/search?keywords={keyword}') as resp:
                data = await resp.json()
                if data['code'] == 200:
                    songs = data['result']['songs']
                    if songs:
                        # 格式化为指定的字符串格式，每行一首歌曲
                        formatted_songs = "\n".join([
                            # f"歌曲ID:{song['id']} 歌名:{song['name']} 歌手:{song['artists'][0]['name']}"
                            f"{song['name']} - {song['artists'][0]['name']}"
                            for song in songs[:15]  # 限制为最多15条
                        ])
                        print(songs)
                        return formatted_songs
                    else:
                        return "未找到相关音乐"
                else:
                    raise Exception("调用 API 失败")
    except Exception as e:
        raise Exception(e)


# 检查登录状态/login/status
async def check_login_status():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:3000/login/status') as resp:
            data = await resp.json()
            # 访问 data['data']['code']，因为 'code' 键嵌套在 'data' 中
            if data['data']['code'] == 200:
                profile = data['data']['profile']
                # 需要确认 profile 是否为 None，避免 KeyError
                if profile is not None:
                    print(profile)
                    return
                else:
                    print("未登录")
                    return None
            else:
                print("未登录")
                return None


# 退出登录/logout
async def logout():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:3000/logout') as resp:
            data = await resp.json()
            if data['code'] == 200:
                return "已退出登录"
            else:
                return "退出登录失败"


# 游客登录/register/anonimous
async def register_anonimous():
    async with aiohttp.ClientSession() as session:
        async with session.get('http://localhost:3000/register/anonimous') as resp:
            data = await resp.json()
            if data['code'] == 200:
                return "已登录为游客"
            else:
                return None


# 获取登陆状态
async def get_login_status(session, cookie):
    try:
        status_response = await session.post(
            f'http://localhost:3000/login/status?timestamp={int(asyncio.get_event_loop().time() * 1000)}',
            json={"cookie": cookie})
        status_data = await status_response.json()
        print("登录状态：", status_data)
    except Exception as e:
        print(f"获取登录状态失败：{e}")


# 展示二维码
def render_qr_to_console(data):
    qr = QRCode()
    qr.add_data(data)
    qr.make(fit=True)
    qr_console = qr.make_image(fill_color="black", back_color="white")
    qr_console.show()


# 二维码登录
async def qrcode_login():
    """通过二维码登录并保存有效的 Cookie"""
    async with aiohttp.ClientSession() as session:
        try:
            # 获取二维码唯一标识 key
            key_response = await session.get(
                f'http://localhost:3000/login/qr/key?timestamp={int(asyncio.get_event_loop().time() * 1000)}')
            key_data = await key_response.json()
            key = key_data.get('data', {}).get('unikey')
            if not key:
                return "获取二维码 key 失败"

            # 生成二维码
            qr_response = await session.get(
                f'http://localhost:3000/login/qr/create?key={key}&qrimg=true&timestamp={int(asyncio.get_event_loop().time() * 1000)}')
            qr_data = await qr_response.json()
            qr_url = qr_data.get('data', {}).get('qrurl')
            if not qr_url:
                return "生成二维码失败"

            # 渲染二维码到控制台
            render_qr_to_console(qr_url)

            # 轮询二维码登录状态
            while True:
                await asyncio.sleep(3)
                status_response = await session.get(
                    f'http://localhost:3000/login/qr/check?key={key}&timestamp={int(asyncio.get_event_loop().time() * 1000)}')
                status_data = await status_response.json()

                if status_data.get('code') == 800:
                    return "二维码已过期，请重新生成"
                elif status_data.get('code') == 803:
                    # 登录成功，提取 Cookie
                    cookie_header = status_data.get('cookie')
                    cookies = parse_cookie_header(cookie_header)
                    await save_cookies(cookies)
                    return "登录成功"
                elif status_data.get('code') == 801:
                    print("等待用户扫描二维码...")
        except Exception as e:
            return f"发生错误：{e}"


# 解析 Cookie 字段
def parse_cookie_header(cookie_header: str) -> dict:
    """解析并仅保留指定的 Cookie 字段"""
    allowed_keys = {"MUSIC_A_T", "MUSIC_R_T", "__csrf", "NMTID", "MUSIC_SNS", "MUSIC_U"}
    cookies = {}
    for item in cookie_header.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            key = key.strip()
            value = value.strip()
            if key in allowed_keys:  # 只保留指定的字段
                cookies[key] = value
    return cookies


# 保存 Cookie 到文件
async def save_cookies(cookies: dict):
    """保存 Cookie 到文件"""
    with open("cookie.json", "w") as f:
        json.dump(cookies, f)  # type: ignore


# 从文件加载 Cookie
async def load_cookies() -> dict:
    """从文件加载 Cookie"""
    try:
        with open("cookie.json", "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


# 检查当前保存的 Cookie 是否有效
async def session_is_valid() -> bool:
    """检查当前保存的 Cookie 是否有效"""
    cookies = await load_cookies()
    if not cookies:
        return False

    async with aiohttp.ClientSession(cookies=cookies) as session:
        try:
            # 使用 /login/status 检查登录状态
            async with session.get("http://localhost:3000/login/status") as resp:
                data = await resp.json()
                if data.get("data", {}).get("code") == 200:
                    return True
        except Exception as e:
            print(e)
            pass
    return False


# 确保用户已登录
async def ensure_logged_in():
    """确保用户已登录"""
    if not await session_is_valid():
        print("Cookie 无效或已过期")
        return "Cookie不存在或过期，请通知开发者重新登录"
    else:
        status = "网易API Cookie有效"
        return status


# 下载音乐
async def download_music(keyword: str):
    try:
        # 确保已登录
        await ensure_logged_in()

        # 加载 Cookie
        cookies = await load_cookies()
        if not cookies:
            return {"error": "未登录，请通知开发者完成登录操作"}

        async with aiohttp.ClientSession(cookies=cookies) as session:
            # 搜索歌曲
            async with session.get(f"http://localhost:3000/search?keywords={keyword}") as resp:
                data = await resp.json()
                if data['code'] != 200:
                    raise Exception("调用搜索 API 失败")

                # 检查搜索结果
                songs = data.get('result', {}).get('songs', [])
                if not songs:
                    return {"error": "未找到相关歌曲"}

                # 下载逻辑
                first_song = songs[0]
                song_id = first_song['id']
                song_name = first_song['name']
                artist_name = ", ".join(artist['name'] for artist in first_song['artists'])
                album_name = first_song['album']['name']
                relative_path = "./AudioLib"
                absolute_path = os.path.abspath(relative_path)

                async with session.get(
                        f"http://localhost:3000/song/download/url/v1?id={song_id}&level=higher") as download_resp:
                    download_data = await download_resp.json()
                    if download_data['code'] != 200 or not download_data['data']['url']:
                        return {"error": "无法获取下载链接，可能需要 VIP 权限"}

                    download_url = download_data['data']['url']
                    file_name = os.path.join(absolute_path, f"{song_id}.mp3")
                    os.makedirs(os.path.dirname(file_name), exist_ok=True)

                    # 下载文件
                    file_name = os.path.normpath(file_name)
                    async with session.get(download_url) as music_resp:
                        with open(file_name, 'wb') as f:
                            f.write(await music_resp.read())

                    return {
                        "file_name": file_name,
                        "download_url": download_url,
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "album_name": album_name
                    }
    except Exception as e:
        return {"error": str(e)}


# endregion

# region VoiceAPI调用配置（加入频道退出频道等）


async def get_alive_channel_list():
    client = KookVoiceClient(token)
    try:
        # 获取频道列表示例
        list_data = await client.list_channels()
        return list_data  # Return the actual data for processing
    except VoiceClientError as e:
        return {"error": str(e)}
    finally:
        await client.close()


cooldown_tracker = {}
cooldown_seconds = 0  # 冷却时间（秒）


# 全局CD检查
def check_cooldown(channel_id):
    """
    检查指定 channel_id 是否处于冷却中。
    如果在冷却中，返回剩余时间；否则记录当前时间并返回 None。
    """
    current_time = time.time()
    if channel_id in cooldown_tracker:
        elapsed_time = current_time - cooldown_tracker[channel_id]
        if elapsed_time < cooldown_seconds:
            wait_cd = cooldown_seconds - elapsed_time
            return wait_cd  # 返回剩余冷却时间
    # 更新冷却时间戳
    cooldown_tracker[channel_id] = current_time
    return None  # 没有冷却限制


def is_bot_in_channel(alive_data, channel_id):
    """
    判断机器人是否在指定的频道中。
    """
    if 'error' in alive_data:
        return False, alive_data['error']
    for item in alive_data.get('items', []):
        if item['id'] == channel_id:
            return True, None
    return False, None


async def join_channel(channel_id):
    """
    加入指定的语音频道。
    """
    wait_cd = check_cooldown(channel_id)
    if wait_cd is not None:
        return {"error": f"请等待 {wait_cd:.2f} 秒后使用"}

    client = await get_client(channel_id, token)
    try:
        join_data = await client.join_channel(rtcp_mux=False)  # 将rtcp_mux设置为False 防止推流失败
        return join_data
    except VoiceClientError as e:
        return {"error": str(e)}
    # 不在这里关闭客户端，因为可能还需要保持活跃状态


async def leave_channel(channel_id):
    """
    离开指定的语音频道。
    """
    wait_cd = check_cooldown(channel_id)
    if wait_cd is not None:
        return {"error": f"请等待 {wait_cd:.2f} 秒后使用"}

    # 通过获取活跃频道列表来判断机器人是否在频道中
    alive_data = await get_alive_channel_list()
    is_in_channel, error = is_bot_in_channel(alive_data, channel_id)
    if error:
        return {"error": error}
    if not is_in_channel:
        return {"error": "机器人未在该频道"}

    # 使用临时客户端来离开频道，不依赖于 client_manager 的客户端实例
    temp_client = KookVoiceClient(token)
    try:
        leave_data = await temp_client.leave_channel(channel_id)
        return {"success": leave_data}
    except VoiceClientError as e:
        return {"error": str(e)}
    finally:
        await temp_client.close()


async def keep_channel_alive(channel_id):
    """
    保持指定频道的活跃状态。
    """
    client = await get_client(channel_id, token)
    try:
        while True:
            try:
                await client.keep_alive(channel_id)
                print(f"保持频道 {channel_id} 活跃成功")
            except VoiceClientError as e:
                print(f"保持频道 {channel_id} 活跃时出错: {e}")
            await asyncio.sleep(40)  # 等待40秒后再次调用
    except asyncio.CancelledError:
        print(f"保持频道 {channel_id} 活动任务被取消")
    finally:
        await remove_client(channel_id)
        print(f"已关闭频道 {channel_id} 的客户端会话")


# endregion

# region 推流搜索功能(Test)
async def search_files(folder_path="AudioLib", search_keyword=""):
    """
    搜索指定文件夹中符合关键字和文件后缀的文件。

    :param folder_path: 要搜索的文件夹路径
    :param search_keyword: 文件名中包含的关键字（部分匹配）
    :return: 符合条件的文件路径列表
    """
    result_files = []  # 用于存储符合条件的文件路径
    file_extensions = [".flac", ".mp3", ".wav"]
    # 遍历文件夹及其子文件夹中的所有文件
    for root, dirs, files in os.walk(folder_path):
        # 遍历当前目录下的文件
        for music_name in files:
            # 检查文件名是否包含指定的关键字
            if search_keyword in music_name:
                # 检查文件后缀是否符合要求
                if any(music_name.endswith(extension) for extension in file_extensions):
                    # 将符合条件的文件完整路径添加到结果列表
                    result_files.append(os.path.join(root, music_name))

    return result_files  # 返回符合条件的文件列表
# endregion

# region 推流功能类
logger = logging.getLogger(__name__)


# noinspection PyMethodMayBeStatic,PyAsyncCall
class AudioStreamer:
    def __init__(self, audio_file_path, connection_info):
        self.audio_file_path = audio_file_path
        self.connection_info = connection_info
        self.process = None
        self.stdout_task = None
        self.stderr_task = None
        self._stopped = asyncio.Event()
        self._stopping = False  # 标记是否正在停止

    async def start(self):
        if self.process:
            raise RuntimeError("AudioStreamer 已经在运行。")

        try:
            bitrate = self.connection_info.get('bitrate', 32000)
            bitrate_k = f"{int(bitrate) * 1.15 // 1000}k"  # 乘以1.15是为了避免音频质量损失

            ip = self.connection_info['ip']
            port = self.connection_info['port']
            ffmpeg_path = set_ffmpeg_path()  # 确保这个函数已定义

            command = [
                ffmpeg_path,
                '-loglevel', 'info',
                '-re',
                '-i', self.audio_file_path,
                '-map', '0:a:0',
                '-acodec', 'libopus',
                '-b:a', bitrate_k,
                '-ac', '2',
                '-ar', '48000',
                '-filter:a', 'volume=0.5',
                '-f', 'tee',
                f"[select=a:f=rtp:ssrc={self.connection_info['audio_ssrc']}:payload_type={self.connection_info['audio_pt']}]rtp://{ip}:{port}?rtcpport={self.connection_info['rtcp_port']}"
            ]

            logger.info(f"FFmpeg command: {' '.join(command)}")
            await asyncio.sleep(3)

            self.process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )

            self.stdout_task = asyncio.create_task(self._read_stream(self.process.stdout, self._print_stdout))
            self.stderr_task = asyncio.create_task(self._read_stream(self.process.stderr, self._print_stderr))

            asyncio.create_task(self._wait_process())

        except Exception as e:
            logger.error(f"启动音频流时发生错误: {e}")
            await self.stop()
            raise

    async def _wait_process(self):
        try:
            returncode = await self.process.wait()
            await asyncio.gather(self.stdout_task, self.stderr_task)
            if returncode != 0 and not self._stopping:
                logger.error(f"FFmpeg 进程以错误码 {returncode} 结束。")
                raise RuntimeError(f"FFmpeg 错误 {returncode}")
            else:
                logger.info(f"FFmpeg 成功完成，返回码 {returncode}")
        except asyncio.CancelledError:
            logger.info("等待 FFmpeg 进程结束的任务被取消。")
        except Exception as e:
            logger.error(f"等待 FFmpeg 进程结束时发生错误: {e}")

    async def stop(self):
        if self.process and self.process.returncode is None:
            logger.info("正在终止 FFmpeg 进程。")
            self._stopping = True
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5)
                logger.info("FFmpeg 进程已终止。")
            except asyncio.TimeoutError:
                logger.warning("FFmpeg 进程未能及时终止，强制杀死进程。")
                self.process.kill()
                await self.process.wait()
            finally:
                self.process = None

        if self.stdout_task:
            self.stdout_task.cancel()
            try:
                await self.stdout_task
            except asyncio.CancelledError:
                pass

        if self.stderr_task:
            self.stderr_task.cancel()
            try:
                await self.stderr_task
            except asyncio.CancelledError:
                pass

        self._stopped.set()

    async def _read_stream(self, stream, callback):
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                callback(line.decode().rstrip())
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"读取流时发生错误: {e}")

    def _print_stdout(self, line):
        logger.info(f"[STDOUT] {line}")

    def _print_stderr(self, line):
        logger.error(f"[STDERR] {line}")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()
# endregion
