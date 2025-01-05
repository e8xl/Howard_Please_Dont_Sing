# core.py
import asyncio
import json
import logging
import os
import time

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
'''
多频道单文件推流
'''


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

    # noinspection PyMethodMayBeStatic
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

    # noinspection PyMethodMayBeStatic
    def _print_stdout(self, line):
        logger.info(f"[STDOUT] {line}")

    # noinspection PyMethodMayBeStatic
    def _print_stderr(self, line):
        logger.error(f"[STDERR] {line}")

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.stop()
# endregion
