# core.py
import asyncio
import json
import logging
import os
import time
import math

from VoiceAPI import KookVoiceClient, VoiceClientError
from client_manager import get_client, remove_client, clients


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

    # 转换channel_id为字符串，确保类型一致性
    channel_id_str = str(channel_id)

    for item in alive_data.get('items', []):
        if str(item['id']) == channel_id_str:
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

        # 关闭持久客户端连接（如果存在）
        if channel_id in clients:
            client = clients.pop(channel_id, None)
            if client:
                try:
                    await client.close()
                    print(f"已关闭频道 {channel_id} 的持久客户端")
                except Exception as e:
                    print(f"关闭持久客户端时发生错误: {e}")

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
        # 初始化连续失败计数器
        consecutive_failures = 0
        max_failures = 3  # 允许连续失败的最大次数

        while True:
            try:
                # 记录发送心跳前的时间
                before_time = time.time()

                # 发送心跳
                result = await client.keep_alive(channel_id)

                # 计算心跳响应时间
                response_time = time.time() - before_time

                # 重置失败计数
                consecutive_failures = 0

                # 记录心跳成功的详细信息
                print(f"保持频道 {channel_id} 活跃成功，响应时间: {response_time:.2f}秒，响应数据: {result}")

            except VoiceClientError as e:
                # 增加失败计数
                consecutive_failures += 1

                print(f"保持频道 {channel_id} 活跃时出错 (尝试 {consecutive_failures}/{max_failures}): {e}")

                # 如果连续失败次数超过阈值，重新创建客户端
                if consecutive_failures >= max_failures:
                    print(f"频道 {channel_id} 连续 {consecutive_failures} 次心跳失败，尝试重新创建客户端")
                    await remove_client(channel_id)
                    client = await get_client(channel_id, token)
                    consecutive_failures = 0

            except Exception as e:
                # 记录非预期的异常
                print(f"保持频道 {channel_id} 活跃时发生意外错误: {e}")
                consecutive_failures += 1

            # 等待时间可以根据KOOK的要求调整
            # KOOK的文档建议30-50秒发送一次心跳
            await asyncio.sleep(30)  # 减少到30秒，确保不会因为网络延迟等问题导致超时

    except asyncio.CancelledError:
        print(f"保持频道 {channel_id} 活动任务被取消")
    except Exception as e:
        print(f"保持频道 {channel_id} 活动任务发生异常: {e}")
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


# region 新增推流功能类
class EnhancedAudioStreamer:
    """增强型音频流媒体类，支持播放列表管理"""

    def __init__(self, connection_info, message_obj=None, message_callback=None, channel_id=None):
        """
        初始化增强型音频推流
        
        :param connection_info: 从KOOK API获取的连接信息
        :param message_obj: 原始消息对象，用于回复
        :param message_callback: 消息回调函数，用于发送通知
        :param channel_id: 频道ID，用于创建唯一的管道名称
        """
        if not connection_info:
            raise ValueError("connection_info 不能为空")

        # 导入config以获取音量参数
        config = open_file('./config/config.json')
        volume_param = config.get('ffmpge_volume', '0.8')

        # 尝试转换音量为浮点数
        try:
            volume = float(volume_param)
            if volume > 2.0:  # 验证音量参数
                volume = 2.0
                print(f"警告：音量参数 {volume_param} 超过最大值 2.0，将使用 2.0")
                volume_param = '2.0'
        except ValueError:
            print(f"警告：音量参数 {volume_param} 不是有效的数值，将使用默认值 0.8")
            volume_param = '0.8'

        self.connection_info = connection_info
        self.message_obj = message_obj
        self.message_callback = message_callback
        self.channel_id = channel_id  # 保存频道ID
        self.rtp_url = self._build_rtp_url()
        self.streamer = None
        self.playlist_manager = None
        self.volume = volume_param  # 存储音量参数

    def _build_rtp_url(self):
        """根据连接信息构建RTP URL"""
        ip = self.connection_info['ip']
        port = self.connection_info['port']
        rtcp_port = self.connection_info['rtcp_port']
        audio_ssrc = self.connection_info['audio_ssrc']
        audio_pt = self.connection_info['audio_pt']

        # 构建适用于FFmpegPipeStreamer的RTP URL
        # 注意这里使用字符串格式化将参数添加到URL
        return f"rtp://{ip}:{port}?rtcpport={rtcp_port}&ssrc={audio_ssrc}&payload_type={audio_pt}"

    async def start(self):
        """启动音频推流服务"""
        try:
            from StreamTools.ffmpeg_stream_tool import FFmpegPipeStreamer
            import logging
            logger = logging.getLogger(__name__)

            # 从connection_info中获取bitrate，并进行处理
            bitrate = self.connection_info.get('bitrate', 32000)
            # 转换为kbps并增加15%的余量以确保音质
            bitrate_k = f"{int(bitrate) * 1.15 // 1000}k"

            # 创建FFmpegPipeStreamer实例，传入消息对象和回调函数
            self.streamer = FFmpegPipeStreamer(
                self.rtp_url,
                bitrate=bitrate_k,
                message_obj=self.message_obj,
                message_callback=self.message_callback,
                volume=self.volume,  # 传递音量参数
                channel_id=self.channel_id  # 传递频道ID给FFmpegPipeStreamer
            )

            # 获取播放列表管理器
            self.playlist_manager = self.streamer.playlist_manager

            # 启动推流
            await self.streamer.start()

            logger.info(f"增强型音频推流服务已启动，RTP地址: {self.rtp_url}，比特率: {bitrate_k}")
            return True
        except Exception as e:
            logger.error(f"启动增强型音频推流服务时出错: {e}")
            import traceback
            print(traceback.format_exc())
            return False

    async def add_song(self, audio_file_path, song_info=None):
        """
        添加歌曲到播放列表
        
        :param audio_file_path: 音频文件路径
        :param song_info: 包含歌曲名、艺术家等信息的字典
        :return: 是否成功添加
        """
        if not self.streamer or not self.playlist_manager:
            logger.error("推流服务未启动，无法添加歌曲")
            return False

        result = self.playlist_manager.add_song(audio_file_path, song_info)
        if result:
            logger.info(f"成功添加歌曲到播放列表: {os.path.basename(audio_file_path)}")
        else:
            logger.error(f"添加歌曲失败，文件不存在: {audio_file_path}")
        return result

    async def skip_current(self):
        """跳过当前歌曲"""
        if not self.streamer or not self.playlist_manager:
            logger.error("推流服务未启动，无法跳过歌曲")
            return None, None

        old, new = self.playlist_manager.skip_current()
        if old:
            logger.info(f"已跳过歌曲: {os.path.basename(old)}")

            # 获取真实的歌曲名称信息
            old_song_name = os.path.basename(old)
            new_song_name = None

            # 尝试获取歌曲的真实名称
            if old in self.playlist_manager.songs_info:
                old_info = self.playlist_manager.songs_info[old]
                old_song_name = f"{old_info.get('song_name', '')} - {old_info.get('artist_name', '')}"

            # 如果有下一首歌，获取其名称
            if new:
                if new in self.playlist_manager.songs_info:
                    new_info = self.playlist_manager.songs_info[new]
                    new_song_name = f"{new_info.get('song_name', '')} - {new_info.get('artist_name', '')}"
                else:
                    new_song_name = os.path.basename(new)

                # 已有下一首歌，但不是通过message_callback通知的（那个是在_audio_loop中），这里就不用通知了

        return old, new

    async def list_songs(self):
        """获取播放列表"""
        if not self.streamer or not self.playlist_manager:
            logger.error("推流服务未启动，无法获取播放列表")
            return []

        return self.playlist_manager.list_songs()

    async def stop(self):
        """停止音频推流服务"""
        exit_due_to_empty_playlist = False
        success = False
        try:
            if self.streamer:
                # 检查是否因为播放列表为空而停止
                exit_due_to_empty_playlist = getattr(self.streamer, 'exit_due_to_empty_playlist', False)
                
                # 在停止之前，先将running标志设为False，防止在停止过程中发送额外消息
                if hasattr(self.streamer, '_running'):
                    self.streamer._running = False
                    
                # 确保任何消息通知标志也被重置，防止发送额外消息
                if hasattr(self.streamer, 'playlist_manager'):
                    self.streamer.playlist_manager.current_song_notified = True
                
                await self.streamer.stop()
                self.streamer = None
                self.playlist_manager = None
                logger.info("增强型音频推流服务已停止")
                success = True
            return success, exit_due_to_empty_playlist
        except Exception as e:
            logger.error(f"停止音频推流时出错: {e}")
            # 添加更详细的错误信息
            import traceback
            logger.error(f"详细错误: {traceback.format_exc()}")
            return success, exit_due_to_empty_playlist

    async def update_volume(self, new_volume):
        """
        更新音量设置，并保存到配置文件
        
        :param new_volume: 新的音量值，字符串类型
        :return: 是否成功更新
        """
        try:
            # 确保有日志记录器
            import logging
            logger = logging.getLogger(__name__)

            # 如果streamer已经初始化，更新它的音量
            if self.streamer:
                success = await self.streamer.update_volume(new_volume)
                if not success:
                    return False

            # 更新自身存储的音量
            self.volume = new_volume

            # 更新配置文件
            config = open_file('./config/config.json')
            if config:
                config['ffmpge_volume'] = new_volume
                try:
                    with open('./config/config.json', 'w', encoding='utf-8') as f:
                        json.dump(config, f, ensure_ascii=False, indent=2)
                    logger.info(f"音量已更新为 {new_volume} 并保存到配置文件")
                except Exception as e:
                    logger.error(f"保存音量设置到配置文件时出错: {e}")
                    return False

            return True
        except Exception as e:
            logger.error(f"更新音量时出错: {e}")
            return False

    async def set_play_mode(self, mode):
        """
        设置播放模式
        
        :param mode: 播放模式，可选值：sequential(顺序播放), random(随机播放), single_loop(单曲循环), list_loop(列表循环)
        :return: 是否成功更新
        """
        try:
            # 确保有日志记录器
            import logging
            logger = logging.getLogger(__name__)

            # 如果streamer已经初始化，更新它的播放模式
            if not self.streamer or not self.playlist_manager:
                logger.error("推流服务未启动，无法设置播放模式")
                return False

            success = self.playlist_manager.set_play_mode(mode)
            if success:
                logger.info(f"播放模式已更新为: {mode}")
                return True
            else:
                logger.error(f"无效的播放模式: {mode}")
                return False

        except Exception as e:
            logger.error(f"设置播放模式时出错: {e}")
            return False

    async def get_play_mode(self):
        """
        获取当前播放模式
        
        :return: 当前播放模式名称和中文描述，若推流服务未启动则返回None
        """
        try:
            if not self.streamer or not self.playlist_manager:
                return None
                
            return self.playlist_manager.get_play_mode()
        except Exception as e:
            print(f"获取播放模式时出错: {e}")
            return None
            
    async def import_playlist(self, playlist_id, max_songs=20, channel_id: str = ""):
        """
        导入网易云音乐歌单
        
        :param playlist_id: 歌单ID
        :param max_songs: 最大导入歌曲数量，设为0表示导入全部
        :param channel_id: 频道ID，用于指定频道
        :return: 包含导入信息的字典
        """
        try:
            import logging
            logger = logging.getLogger(__name__)
            
            # 确定目标频道
            if not channel_id:
                if self.message_obj:
                    channel_id = getattr(self.message_obj, 'ctx', {}).get('channel_id', '')
                    
            if not channel_id:
                return {"error": "未指定频道ID"}
                
            # 获取对应频道的流媒体推送器
            if not self.streamer or not self.playlist_manager:
                logger.error("推流服务未启动，无法导入歌单")
                return {"error": "推流服务未启动，无法导入歌单"}
            
            # 设置导入标志，避免导入过程中因播放列表为空而退出
            self.streamer.is_importing = True
            logger.info("已设置导入标志，防止在导入过程中退出")
                
            # 导入NeteaseAPI
            import importlib
            NeteaseAPI = importlib.import_module("NeteaseAPI")
            
            try:
                # 获取歌单详情
                logger.info(f"正在获取歌单ID: {playlist_id} 的详情")
                playlist_detail = await NeteaseAPI.get_playlist_detail(playlist_id)
                
                if "error" in playlist_detail:
                    logger.error(f"获取歌单详情失败: {playlist_detail['error']}")
                    return {"error": f"获取歌单详情失败: {playlist_detail['error']}"}
                    
                # 保存歌单信息
                self.playlist_manager.set_playlist_info(playlist_detail)
                
                # 提取歌单基本信息
                playlist_info = self.playlist_manager.get_playlist_info()
                if not playlist_info:
                    logger.error("解析歌单信息失败")
                    return {"error": "解析歌单信息失败"}
                    
                # 获取歌单中的歌曲列表
                total_tracks = playlist_info['trackCount']
                
                # 确定要导入的歌曲数量
                to_import = total_tracks if max_songs == 0 else min(max_songs, total_tracks)
                
                logger.info(f"歌单 '{playlist_info['name']}' 共有 {total_tracks} 首歌曲，将导入 {to_import} 首")
                
                # 分页获取歌曲列表
                all_tracks = []
                page_size = 100  # 网易API每页最多返回100首歌曲
                
                # 循环获取歌曲直到达到指定数量或获取完所有歌曲
                for offset in range(0, to_import, page_size):
                    # 计算当前页需要获取的歌曲数量
                    current_limit = min(page_size, to_import - offset)
                    
                    logger.info(f"获取歌单歌曲列表，第 {offset//page_size + 1} 页，共 {math.ceil(to_import/page_size)} 页")
                    tracks_data = await NeteaseAPI.get_playlist_tracks(playlist_id, limit=current_limit, offset=offset)
                    
                    if "error" in tracks_data:
                        logger.error(f"获取歌单歌曲列表失败: {tracks_data['error']}")
                        # 如果已获取一些歌曲，继续处理
                        if all_tracks:
                            logger.info(f"已获取 {len(all_tracks)} 首歌曲，将继续处理")
                            break
                        return {"error": f"获取歌单歌曲列表失败: {tracks_data['error']}"}
                    
                    # 提取歌曲信息并添加到总列表
                    tracks = tracks_data.get('songs', [])
                    all_tracks.extend(tracks)
                    
                    # 每次获取后等待一小段时间，避免过于频繁的API调用
                    await asyncio.sleep(0.5)
                    
                    # 如果获取的数量不足，表示已经到达歌单末尾
                    if len(tracks) < current_limit:
                        logger.info(f"已到达歌单末尾，实际获取 {len(all_tracks)} 首歌曲")
                        break
                
                logger.info(f"共获取 {len(all_tracks)} 首歌曲信息")
                
                # 保存歌曲列表到播放列表管理器
                self.playlist_manager.set_playlist_tracks(all_tracks)
                
                # 重置播放列表管理器的状态，确保新歌单可以正确应用
                # 清空当前播放列表，避免混合播放不同歌单的歌曲
                self.playlist_manager.clear_playlist()
                
                # 将歌曲添加到播放系统
                added_count = self.playlist_manager.add_playlist_batch(all_tracks)
                
                logger.info(f"已将 {added_count} 首歌曲添加到播放系统")
                
                # 导入完成，重置导入标志
                self.streamer.is_importing = False
                logger.info("导入完成，已重置导入标志")
                
                return {
                    "name": playlist_info['name'],
                    "id": playlist_info['id'],
                    "creator": playlist_info['creator'],
                    "description": playlist_info['description'],
                    "total_tracks": total_tracks,
                    "imported_tracks": len(all_tracks)
                }
            except Exception as e:
                # 发生异常时也要重置导入标志
                self.streamer.is_importing = False
                logger.error(f"导入过程中发生异常，已重置导入标志: {e}")
                raise
            
        except Exception as e:
            logger.error(f"导入歌单时出错: {e}")
            import traceback
            logger.error(traceback.format_exc())
            # 确保在任何情况下都重置导入标志
            if hasattr(self, 'streamer') and self.streamer:
                self.streamer.is_importing = False
                logger.info("异常处理：已重置导入标志")
            return {"error": f"导入歌单时出错: {e}"}
            
    async def remove_song(self, index):
        """
        从播放列表中删除指定索引的歌曲
        
        :param index: 歌曲索引（从1开始）
        :return: 是否成功删除
        """
        try:
            if not self.streamer or not self.playlist_manager:
                return False
                
            return self.playlist_manager.remove_song_by_index(index)
        except Exception as e:
            print(f"删除歌曲时出错: {e}")
            return False
            
    async def clear_playlist(self):
        """
        清空播放列表（不包括当前正在播放的歌曲）
        
        :return: 清除的歌曲数量
        """
        try:
            if not self.streamer or not self.playlist_manager:
                return 0
                
            return self.playlist_manager.clear_playlist()
        except Exception as e:
            print(f"清空播放列表时出错: {e}")
            return 0
