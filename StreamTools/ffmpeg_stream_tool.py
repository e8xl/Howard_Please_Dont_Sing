#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import json
import os
import platform
import shlex
import subprocess
from collections import deque

# 可以修改的RTP推流地址
RTP_URL = "rtp://127.0.0.1:7890"
SAMPLE_RATE = 48000
CHANNELS = 2
BITRATE = "128k"
PAYLOAD_TYPE = 111
SSRC = 1111


# 设置 ffmpeg 路径
def set_ffmpeg_path():
    ffmpeg_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Tools', 'ffmpeg', 'bin', 'ffmpeg.exe')
    if not os.path.exists(ffmpeg_path):
        raise FileNotFoundError(f"未找到 ffmpeg.exe，请检查路径是否正确: {ffmpeg_path}")
    return ffmpeg_path


# 设置 ffprobe 路径
def set_ffprobe_path():
    ffprobe_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'Tools', 'ffmpeg', 'bin', 'ffprobe.exe')
    if not os.path.exists(ffprobe_path):
        raise FileNotFoundError(f"未找到 ffprobe.exe，请检查路径是否正确: {ffprobe_path}")
    return ffprobe_path


# 仅在Windows上导入需要的模块
if platform.system() == 'Windows':
    import win32pipe
    import win32file
else:
    pass


class PlaylistManager:
    """播放列表管理器"""

    def __init__(self):
        self.playlist = deque()
        self.songs_info = {}  # 存储歌曲信息的字典，键为歌曲路径
        self.current_song = None
        self.current_song_info = None
        self.ffprobe_path = set_ffprobe_path() if platform.system() == 'Windows' else 'ffprobe'
        # 添加当前歌曲已通知标志
        self.current_song_notified = False
        # 添加用于跟踪刚添加的歌曲的集合
        self.recently_added_songs = set()

    def add_song(self, song_path, song_info=None):
        """
        添加歌曲到播放列表
        
        :param song_path: 歌曲文件路径
        :param song_info: 可选的歌曲信息字典，包含song_name, artist_name, album_name等
        :return: 是否成功添加
        """
        if os.path.exists(song_path):
            self.playlist.append(song_path)

            # 保存歌曲信息（如果提供）
            if song_info:
                self.songs_info[song_path] = song_info

            # 将歌曲添加到最近添加集合中
            self.recently_added_songs.add(song_path)

            return True
        return False

    def get_current_audio(self):
        """获取当前正在播放的音频路径"""
        if self.current_song:
            return self.current_song

        # 如果没有当前歌曲，尝试获取下一首
        if not self.playlist:
            return None

        self.current_song = self.get_next_song()
        # 重置通知标志
        self.current_song_notified = False
        return self.current_song

    def get_next_song(self):
        """获取下一首歌"""
        if not self.playlist:
            return None
        self.current_song = self.playlist.popleft()

        # 首先检查是否有预先存储的信息，否则使用ffprobe获取
        if self.current_song in self.songs_info:
            # 构建类似ffprobe返回的格式
            song_info = self.songs_info[self.current_song]
            title = f"{song_info.get('song_name', '')} - {song_info.get('artist_name', '')}"

            self.current_song_info = {
                'title': title,
                'duration': 0,  # 没有精确时长，可能需要从ffprobe获取
                'path': self.current_song,
                'full_info': song_info
            }

            # 使用ffprobe补充获取时长信息
            probe_info = self.get_song_info(self.current_song)
            if probe_info:
                self.current_song_info['duration'] = probe_info.get('duration', 0)
        else:
            # 没有预存信息，使用ffprobe获取
            self.current_song_info = self.get_song_info(self.current_song)

        # 重置通知标志
        self.current_song_notified = False

        # 如果这是最后一首歌，清空recently_added_songs
        if not self.playlist:
            self.recently_added_songs.clear()

        return self.current_song

    def skip_current(self):
        """跳过当前歌曲"""
        old_song = self.current_song
        self.current_song = None if not self.playlist else self.get_next_song()
        return old_song, self.current_song

    def get_song_info(self, song_path):
        """使用ffprobe获取歌曲信息"""
        try:
            cmd = [
                self.ffprobe_path,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                song_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            info = json.loads(result.stdout)

            # 提取关键信息
            duration = float(info.get('format', {}).get('duration', 0))

            # 首先检查是否有预先存储的信息
            if song_path in self.songs_info:
                song_info = self.songs_info[song_path]
                title = f"{song_info.get('song_name', '')} - {song_info.get('artist_name', '')}"
            else:
                # 尝试获取媒体标签中的标题
                tags = info.get('format', {}).get('tags', {})
                if 'title' in tags and 'artist' in tags:
                    title = f"{tags['title']} - {tags['artist']}"
                elif 'title' in tags:
                    title = tags['title']
                else:
                    title = os.path.basename(song_path)

            return {
                'title': title,
                'duration': duration,
                'path': song_path
            }
        except Exception as e:
            print(f"获取歌曲信息出错: {e}")

            # 如果ffprobe失败但有预存信息
            if song_path in self.songs_info:
                song_info = self.songs_info[song_path]
                title = f"{song_info.get('song_name', '')} - {song_info.get('artist_name', '')}"
                return {
                    'title': title,
                    'duration': 0,
                    'path': song_path
                }

            # 完全回退到使用文件名
            return {
                'title': os.path.basename(song_path),
                'duration': 0,
                'path': song_path
            }

    def list_songs(self):
        """列出播放列表中的所有歌曲"""
        songs = []
        if self.current_song:
            songs.append(f"当前播放: {self.current_song_info['title']} "
                         f"({int(self.current_song_info['duration'] // 60)}:"
                         f"{int(self.current_song_info['duration'] % 60):02d})")

        for i, song_path in enumerate(self.playlist, 1):
            # 首先检查是否有预先存储的信息
            if song_path in self.songs_info:
                song_info = self.songs_info[song_path]
                title = f"{song_info.get('song_name', '')} - {song_info.get('artist_name', '')}"
            else:
                # 使用ffprobe获取信息
                info = self.get_song_info(song_path)
                title = info['title']

            # 仅添加歌曲标题，不显示时长
            songs.append(f"{i}. {title}")

        return songs

    def has_songs(self):
        """检查是否还有歌曲"""
        return len(self.playlist) > 0 or self.current_song is not None


class FFmpegPipeStreamer:
    """FFmpeg管道流媒体播放器"""

    def __init__(self, rtp_url, bitrate=None, message_obj=None, message_callback=None, volume="0.8"):
        self.rtp_url = rtp_url
        # 使用传入的bitrate或默认值
        self.bitrate = bitrate if bitrate else BITRATE
        self.playlist_manager = PlaylistManager()
        self.pipe_path = self._get_pipe_path()
        self.ffmpeg_process_player = None
        self.ffmpeg_process_streamer = None
        self._running = False
        self._pipe = None
        self.ffmpeg_path = set_ffmpeg_path() if platform.system() == 'Windows' else 'ffmpeg'
        # 修改参数
        self.message_obj = message_obj
        self.message_callback = message_callback
        # 添加音量参数
        self.volume = volume
        # 添加空列表退出标志
        self.exit_due_to_empty_playlist = False
        # 添加初始化标志，防止首次启动时立即判断为空播放列表
        self.initialization_grace_period = True
        # 添加当前歌曲通知标志
        self.current_song_notified = False
        # 添加第一首歌标志，避免第一首歌被重复通知
        self.is_first_song = True
        print(f"初始化FFmpegPipeStreamer，推流地址: {rtp_url}，比特率: {self.bitrate}，音量: {self.volume}")

    @staticmethod
    def _get_pipe_path():
        """获取管道路径"""
        if platform.system() == 'Windows':
            return r'\\.\pipe\audio_pipe'
        else:
            return '/tmp/audio_pipe'

    async def start(self):
        """启动FFmpeg进程"""
        self._running = True

        # 创建管道
        if platform.system() == 'Windows':
            self._pipe = win32pipe.CreateNamedPipe(
                self.pipe_path,
                win32pipe.PIPE_ACCESS_OUTBOUND,
                win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
                1, 65536, 65536, 0, None
            )
        else:
            # 在Unix系统上创建FIFO
            if os.path.exists(self.pipe_path):
                os.unlink(self.pipe_path)
            os.mkfifo(self.pipe_path)

        # 启动推流FFmpeg进程
        streamer_cmd = [
            self.ffmpeg_path,
            "-re",
            "-f", "s16le",  # 从管道读取原始PCM数据
            "-ar", str(SAMPLE_RATE),
            "-ac", str(CHANNELS),
            "-i", self.pipe_path,
            "-acodec", "libopus",
            "-b:a", self.bitrate,  # 使用实例变量bitrate
            "-ac", str(CHANNELS),
            "-ar", str(SAMPLE_RATE),
            "-af", f"volume={self.volume}",  # 添加音量控制
            "-ssrc", str(SSRC),
            "-payload_type", str(PAYLOAD_TYPE),
            "-f", "rtp",
            self.rtp_url
        ]

        print("启动RTP推流进程...")
        print(" ".join(streamer_cmd))

        if platform.system() == 'Windows':
            # Windows上需要使用CREATE_NO_WINDOW标志来避免显示黑窗口
            self.ffmpeg_process_streamer = subprocess.Popen(
                streamer_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=subprocess.CREATE_NO_WINDOW
            )
        else:
            self.ffmpeg_process_streamer = subprocess.Popen(
                streamer_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )

        # Windows上连接管道
        if platform.system() == 'Windows':
            win32pipe.ConnectNamedPipe(self._pipe, None)

        # 启动音频播放循环
        asyncio.create_task(self._audio_loop())

    async def _audio_loop(self):
        """音频播放循环"""
        try:
            # 设置初始化宽限期
            self.initialization_grace_period = True
            await asyncio.sleep(3)  # 等待3秒初始化
            self.initialization_grace_period = False

            # 检查播放列表是否为空的计时器
            empty_playlist_timer = 0
            # 将自动退出标志重置为False
            self.exit_due_to_empty_playlist = False

            while self._running:
                # 检查播放列表是否为空
                current_audio_path = self.playlist_manager.get_current_audio()

                if current_audio_path is None:
                    empty_playlist_timer += 1
                    if empty_playlist_timer >= 5:  # 连续5次检查播放列表为空
                        print("播放列表为空，将退出音频循环")
                        # 设置标志，指示由于播放列表为空而退出
                        self.exit_due_to_empty_playlist = True
                        # 标记音频循环已停止
                        self._running = False
                        print(f"已设置exit_due_to_empty_playlist为True（频道将自动退出），音频循环已标记为停止")
                        break
                    await asyncio.sleep(1)  # 等待1秒再检查
                    continue
                else:
                    # 重置计时器
                    empty_playlist_timer = 0
                    self.exit_due_to_empty_playlist = False

                try:
                    # 获取当前播放的歌曲信息
                    song_info = None
                    if current_audio_path in self.playlist_manager.songs_info:
                        song_info = self.playlist_manager.songs_info[current_audio_path]

                    # 通知用户正在播放的歌曲
                    if self.message_callback and self.message_obj and not self.playlist_manager.current_song_notified:
                        song_name = "未知歌曲"
                        artist_name = "未知艺术家"

                        if song_info:
                            song_name = song_info.get('song_name', os.path.basename(current_audio_path))
                            artist_name = song_info.get('artist_name', "未知艺术家")

                        try:
                            # 彻底移除这段通知逻辑，防止重复通知
                            # 只标记为已通知，无需发送任何消息
                            self.playlist_manager.current_song_notified = True
                            # 移除歌曲从recently_added_songs集合中
                            if current_audio_path in self.playlist_manager.recently_added_songs:
                                self.playlist_manager.recently_added_songs.remove(current_audio_path)
                            # 重置第一首歌标志
                            self.is_first_song = False
                        except Exception as e:
                            print(f"处理播放通知时出错: {e}")

                    # 播放当前歌曲
                    print(f"播放: {os.path.basename(current_audio_path)}")

                    # 启动播放器FFmpeg进程
                    player_cmd = [
                        self.ffmpeg_path,
                        "-v", "quiet",
                        "-i", current_audio_path,
                        "-af", f"volume={self.volume}",  # 添加音量控制
                        "-f", "s16le",  # 输出为原始PCM数据
                        "-ar", str(SAMPLE_RATE),
                        "-ac", str(CHANNELS),
                        "-"  # 输出到stdout
                    ]

                    self.ffmpeg_process_player = subprocess.Popen(
                        player_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )

                    # 从播放器读取数据并写入管道
                    while self._running and self.playlist_manager.current_song == current_audio_path:
                        try:
                            # 非阻塞读取，每次读取8KB数据
                            data = self.ffmpeg_process_player.stdout.read(8192)
                            if not data:
                                # 文件播放完毕
                                break

                            # 写入管道
                            if platform.system() == 'Windows':
                                win32file.WriteFile(self._pipe, data)
                            else:
                                with open(self.pipe_path, 'wb') as pipe:
                                    pipe.write(data)

                        except Exception as e:
                            print(f"播放出错: {e}")
                            break

                        # 让出控制权给其他任务
                        await asyncio.sleep(0.01)

                    # 清理播放器进程
                    if self.ffmpeg_process_player:
                        self.ffmpeg_process_player.terminate()
                        self.ffmpeg_process_player = None

                    # 如果是自然播放完毕（没有被跳过），设置当前歌曲为None
                    if self.playlist_manager.current_song == current_audio_path:
                        self.playlist_manager.current_song = None
                        self.playlist_manager.current_song_notified = False
                        
                        # 检查是否有下一首歌，如果有，通知用户
                        if self.playlist_manager.playlist and self.message_callback and self.message_obj:
                            # 获取下一首歌的信息
                            next_song_path = self.playlist_manager.playlist[0]
                            next_song_info = None
                            next_song_title = "未知歌曲"
                            
                            if next_song_path in self.playlist_manager.songs_info:
                                next_song_info = self.playlist_manager.songs_info[next_song_path]
                                song_name = next_song_info.get('song_name', os.path.basename(next_song_path))
                                artist_name = next_song_info.get('artist_name', "未知艺术家")
                                next_song_title = f"{song_name} - {artist_name}"
                            else:
                                # 尝试使用ffprobe获取信息
                                info = self.playlist_manager.get_song_info(next_song_path)
                                next_song_title = info['title']
                            
                            try:
                                # 通知用户下一首歌曲
                                await self.message_callback(self.message_obj, f"即将播放: {next_song_title}")
                            except Exception as e:
                                print(f"发送下一首歌曲通知时出错: {e}")

                except Exception as e:
                    print(f"音频流处理错误: {e}")
                    await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("音频循环被取消")
            raise
        except Exception as e:
            print(f"音频循环出现异常: {e}")
            import traceback
            print(traceback.format_exc())

    async def stop(self):
        """停止所有FFmpeg进程"""
        self._running = False

        # 停止播放器进程
        if self.ffmpeg_process_player:
            self.ffmpeg_process_player.terminate()
            self.ffmpeg_process_player = None

        # 停止推流进程
        if self.ffmpeg_process_streamer:
            self.ffmpeg_process_streamer.terminate()
            self.ffmpeg_process_streamer = None

        # 清理管道
        if platform.system() == 'Windows' and self._pipe:
            win32file.CloseHandle(self._pipe)
        elif os.path.exists(self.pipe_path):
            os.unlink(self.pipe_path)

    async def add_song(self, file_path, song_info=None):
        """
        添加歌曲到播放列表
        
        :param file_path: 音频文件路径
        :param song_info: 歌曲信息字典
        :return: True表示添加成功，False表示添加失败
        """
        # 检查播放列表是否为空（用于确定是否是第一首歌）
        playlist_empty = not self.playlist_manager.has_songs()
        
        # 添加歌曲到播放列表
        success = self.playlist_manager.add_song(file_path, song_info)
        if not success:
            return False
            
        # 如果歌曲添加成功，重置退出标志（避免自动退出）
        self.exit_due_to_empty_playlist = False
        
        # 如果音频循环已经中断（退出标志被设置为True），重新启动音频循环
        if not self._running:
            self._running = True
            asyncio.create_task(self._audio_loop())
            print("播放列表更新，已重新启动音频循环")
        
        return playlist_empty  # 返回是否是播放列表中的第一首歌

    async def update_volume(self, new_volume):
        """更新音量设置
        
        :param new_volume: 新的音量值，字符串类型
        :return: 是否成功更新
        """
        try:
            # 验证音量是否有效
            volume = float(new_volume)
            if volume <= 0:
                print(f"音量必须大于0，收到的值: {volume}")
                return False
                
            if volume > 2.0:
                print(f"音量不能超过2.0，收到的值: {volume}，将使用最大值2.0")
                volume = 2.0
                new_volume = "2.0"
                
            # 更新音量参数
            self.volume = new_volume
            print(f"音量已更新为: {self.volume}")
            return True
        except ValueError:
            print(f"无效的音量值: {new_volume}")
            return False


async def command_interface(streamer):
    """命令行界面"""
    print("音频推流工具已启动")
    print("可用命令:")
    print("  add <文件路径> - 添加歌曲到播放列表")
    print("  list - 显示播放列表")
    print("  skip - 跳过当前歌曲")
    print("  now - 显示正在播放的歌曲")
    print("  quit - 退出程序")

    while True:
        print("\n> ", end="", flush=True)

        # 异步非阻塞读取
        # 使用lambda包装input函数，避免args参数未填的问题
        line = await asyncio.get_event_loop().run_in_executor(None, lambda: input())
        cmd_parts = shlex.split(line)

        if not cmd_parts:
            continue

        cmd = cmd_parts[0].lower()

        if cmd == "quit":
            print("停止服务...")
            await streamer.stop()
            break

        elif cmd == "add" and len(cmd_parts) > 1:
            filepath = " ".join(cmd_parts[1:])
            if streamer.playlist_manager.add_song(filepath):
                print(f"已添加: {os.path.basename(filepath)}")
            else:
                print(f"文件不存在: {filepath}")

        elif cmd == "list":
            songs = streamer.playlist_manager.list_songs()
            if songs:
                print("播放列表:")
                for song in songs:
                    print(song)
            else:
                print("播放列表为空")

        elif cmd == "skip":
            old, new = streamer.playlist_manager.skip_current()
            if old:
                print(f"已跳过: {os.path.basename(old)}")
                if new:
                    print(f"即将播放: {os.path.basename(new)}")
            else:
                print("没有正在播放的歌曲")

        elif cmd == "now":
            if streamer.playlist_manager.current_song:
                info = streamer.playlist_manager.current_song_info
                print(f"正在播放: {info['title']} "
                      f"({int(info['duration'] // 60)}:"
                      f"{int(info['duration'] % 60):02d})")
            else:
                print("没有正在播放的歌曲")

        else:
            print("未知命令，可用命令: add, list, skip, now, quit")


async def main():
    """主函数"""
    streamer = FFmpegPipeStreamer(RTP_URL)
    await streamer.start()

    try:
        await command_interface(streamer)
    except KeyboardInterrupt:
        print("\n接收到中断信号，正在退出...")
    finally:
        await streamer.stop()


if __name__ == "__main__":
    asyncio.run(main())
