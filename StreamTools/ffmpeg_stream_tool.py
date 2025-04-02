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
        # 添加播放模式
        self.play_mode = "sequential"  # 播放模式: sequential(顺序播放), random(随机播放), single_loop(单曲循环), list_loop(列表循环)
        # 保存已播放过的歌曲，用于列表循环
        self.played_songs = []
        # 添加歌单相关属性
        self.playlist_info = None  # 当前加载的歌单信息
        self.playlist_tracks = []  # 歌单中的所有歌曲信息
        self.playlist_track_index = 0  # 当前处理到的歌曲索引
        self.download_queue = deque()  # 待下载歌曲队列
        self.is_downloading = False  # 是否正在下载歌曲
        self.download_task = None  # 下载任务

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
            # 处理列表循环模式
            if self.play_mode == "list_loop" and self.played_songs:
                # 将已播放列表重新加入播放队列
                self.playlist.extend(self.played_songs)
                self.played_songs = []

            # 尝试获取下一首歌
            if not self.playlist:
                return None

        # 如果是单曲循环模式，并且当前有歌曲正在播放，则重复播放当前歌曲
        if self.play_mode == "single_loop" and self.current_song:
            # 将当前歌曲标记为未通知，这样会重新显示当前歌曲信息
            self.current_song_notified = False
            return self.current_song

        # 如果是随机播放模式，随机选择播放列表中的一首歌
        if self.play_mode == "random" and self.playlist:
            import random
            random_index = random.randrange(len(self.playlist))
            self.current_song = self.playlist[random_index]
            del self.playlist[random_index]
        else:
            # 顺序播放模式或其他模式，从队列头部获取歌曲
            self.current_song = self.playlist.popleft()

        # 记录已播放歌曲用于列表循环
        if self.play_mode == "list_loop":
            self.played_songs.append(self.current_song)

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
        if not self.playlist and self.play_mode != "list_loop":
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

    def set_play_mode(self, mode):
        """
        设置播放模式
        
        :param mode: 播放模式，可选值：sequential(顺序播放), random(随机播放), single_loop(单曲循环), list_loop(列表循环)
        :return: 设置是否成功
        """
        valid_modes = ["sequential", "random", "single_loop", "list_loop"]
        if mode not in valid_modes:
            return False
        
        self.play_mode = mode
        # 如果切换到列表循环模式，确保played_songs为空，避免历史播放记录影响
        if mode == "list_loop":
            self.played_songs = []
        
        return True
    
    def get_play_mode(self):
        """
        获取当前播放模式
        
        :return: 当前播放模式名称和中文描述
        """
        mode_names = {
            "sequential": "顺序播放",
            "random": "随机播放",
            "single_loop": "单曲循环",
            "list_loop": "列表循环"
        }
        return self.play_mode, mode_names.get(self.play_mode, "未知模式")

    def add_playlist_batch(self, tracks_info):
        """
        批量添加歌单中的歌曲信息到下载队列（不立即下载）
        
        :param tracks_info: 歌曲信息列表
        :return: 添加的歌曲数量
        """
        count = 0
        for track in tracks_info:
            # 从track提取必要信息
            song_id = str(track.get('id'))
            
            # 检查歌曲是否已存在本地，避免重复下载
            from os.path import join, exists, abspath
            
            # 检查缓存文件是否已存在
            relative_path = "./AudioLib"
            absolute_path = abspath(relative_path)
            file_path = join(absolute_path, f"{song_id}.mp3")
            
            # 准备歌曲信息
            song_info = {
                'id': song_id,
                'song_name': track.get('name', '未知歌曲'),
                'artist_name': ", ".join(ar.get('name', '未知艺术家') for ar in track.get('ar', [])),
                'album_name': track.get('al', {}).get('name', '未知专辑'),
                'file_path': file_path if exists(file_path) else None
            }
            
            # 添加到下载队列，已存在的歌曲也添加（但不会再次下载）
            self.download_queue.append(song_info)
            count += 1
            
        return count

    def remove_song_by_index(self, index):
        """
        从播放列表中删除指定索引的歌曲
        
        :param index: 歌曲索引（从1开始）
        :return: 是否成功删除
        """
        if not self.playlist or index <= 0 or index > len(self.playlist):
            return False
            
        # 将索引转换为0-based
        index = index - 1
        
        # 获取要删除的歌曲路径
        song_path = list(self.playlist)[index]
        
        # 如果是第一首歌曲（当前播放列表的头部），需要特殊处理
        if index == 0:
            self.playlist.popleft()
        else:
            # 创建一个新的队列，排除要删除的歌曲
            temp_queue = deque()
            for i, song in enumerate(self.playlist):
                if i != index:
                    temp_queue.append(song)
            self.playlist = temp_queue
            
        # 从recently_added_songs中移除，如果存在
        if song_path in self.recently_added_songs:
            self.recently_added_songs.remove(song_path)
            
        return True

    def clear_playlist(self):
        """
        清空播放列表（不包括当前正在播放的歌曲）
        
        :return: 清除的歌曲数量
        """
        count = len(self.playlist)
        self.playlist.clear()
        self.recently_added_songs.clear()
        return count

    def set_playlist_info(self, playlist_info):
        """
        设置当前加载的歌单信息
        
        :param playlist_info: 歌单详情信息
        """
        self.playlist_info = playlist_info
        
    def set_playlist_tracks(self, tracks):
        """
        设置歌单中的所有歌曲信息
        
        :param tracks: 歌曲信息列表
        """
        self.playlist_tracks = tracks
        self.playlist_track_index = 0
        
    def get_playlist_info(self):
        """
        获取当前加载的歌单信息
        
        :return: 歌单信息字典
        """
        if not self.playlist_info:
            return None
            
        # 提取有用的歌单信息
        try:
            playlist = self.playlist_info.get('playlist', {})
            return {
                'id': playlist.get('id', ''),
                'name': playlist.get('name', '未知歌单'),
                'description': playlist.get('description', ''),
                'creator': playlist.get('creator', {}).get('nickname', '未知用户'),
                'trackCount': playlist.get('trackCount', 0),
                'playCount': playlist.get('playCount', 0),
                'coverImgUrl': playlist.get('coverImgUrl', ''),
                'createTime': playlist.get('createTime', 0)
            }
        except Exception as e:
            print(f"解析歌单信息出错: {e}")
            return None


class FFmpegPipeStreamer:
    """FFmpeg管道流媒体播放器"""

    def __init__(self, rtp_url, bitrate=None, message_obj=None, message_callback=None, volume="0.8", channel_id=None):
        self.rtp_url = rtp_url
        # 使用传入的bitrate或默认值
        self.bitrate = bitrate if bitrate else BITRATE
        self.playlist_manager = PlaylistManager()
        self.channel_id = channel_id or "default"  # 使用提供的channel_id或默认值
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

    def _get_pipe_path(self):
        """获取管道路径，使用channel_id确保唯一性"""
        if platform.system() == 'Windows':
            return fr'\\.\pipe\audio_pipe_{self.channel_id}'
        else:
            return f'/tmp/audio_pipe_{self.channel_id}'

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
            
            # 启动下载管理任务
            self._download_task = asyncio.create_task(self._manage_downloads())

            while self._running:
                # 检查播放列表是否为空
                current_audio_path = self.playlist_manager.get_current_audio()

                if current_audio_path is None:
                    # 如果播放列表为空但下载队列不为空，等待下载完成
                    if len(self.playlist_manager.download_queue) > 0:
                        print(f"播放列表为空，但还有 {len(self.playlist_manager.download_queue)} 首歌曲在下载队列")
                        await asyncio.sleep(1)  # 等待下载任务完成
                        continue
                        
                    empty_playlist_timer += 1
                    if empty_playlist_timer >= 5:  # 连续5次检查播放列表为空
                        # 仅在非循环模式下退出，循环模式应该会一直有歌曲
                        if self.playlist_manager.play_mode not in ["list_loop", "single_loop"]:
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

                    # 如果是自然播放完毕（没有被跳过），根据播放模式处理
                    if self.playlist_manager.current_song == current_audio_path:
                        if self.playlist_manager.play_mode == "single_loop":
                            # 单曲循环模式，不需要重置current_song
                            print(f"单曲循环模式：重新播放 {os.path.basename(current_audio_path)}")
                            self.playlist_manager.current_song_notified = False
                            continue
                        elif self.playlist_manager.play_mode == "list_loop" and not self.playlist_manager.playlist:
                            # 列表循环模式，如果播放列表为空，且是最后一首歌，通知将重新开始播放列表
                            if self.message_callback and self.message_obj:
                                try:
                                    await self.message_callback(self.message_obj, "列表播放完毕，将重新开始播放")
                                except Exception as e:
                                    print(f"发送列表循环通知时出错: {e}")
                        
                        # 正常处理下一首歌
                        self.playlist_manager.current_song = None
                        self.playlist_manager.current_song_notified = False
                        
                        # 获取下一首歌，即将播放的信息
                        if self.playlist_manager.playlist and self.message_callback and self.message_obj:
                            # 获取下一首歌的信息
                            next_song_path = None
                            next_song_title = "未知歌曲"
                            
                            # 对于随机播放，无法确定下一首是哪一首
                            if self.playlist_manager.play_mode != "random":
                                next_song_path = self.playlist_manager.playlist[0]
                                
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
        
        # 取消下载任务
        if hasattr(self, '_download_task') and self._download_task:
            self._download_task.cancel()
            try:
                await self._download_task
            except asyncio.CancelledError:
                pass

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

    async def _manage_downloads(self):
        """管理下载队列，按需下载歌曲"""
        try:
            print("启动下载管理任务")
            while self._running:
                # 如果队列为空，等待
                if not self.playlist_manager.download_queue:
                    await asyncio.sleep(1)
                    continue
                
                # 获取下载队列长度和播放列表长度
                queue_len = len(self.playlist_manager.download_queue)
                playlist_len = len(self.playlist_manager.playlist)
                
                # 判断是否需要下载更多歌曲
                # 策略：如果播放列表中的歌曲少于3首，从下载队列中取出歌曲下载
                if playlist_len < 3 and queue_len > 0 and not self.playlist_manager.is_downloading:
                    self.playlist_manager.is_downloading = True
                    
                    try:
                        # 从队列中取出歌曲信息
                        song_info = self.playlist_manager.download_queue.popleft()
                        song_id = song_info.get('id')
                        
                        # 检查文件是否已经存在
                        if song_info.get('file_path') and os.path.exists(song_info.get('file_path')):
                            print(f"歌曲已存在本地，无需下载: {song_info.get('song_name')}")
                            # 添加到播放列表
                            self.playlist_manager.add_song(song_info.get('file_path'), song_info)
                        else:
                            print(f"下载歌曲: {song_info.get('song_name')} (ID: {song_id})")
                            
                            # 动态导入NeteaseAPI，避免循环导入
                            import importlib
                            NeteaseAPI = importlib.import_module("NeteaseAPI")
                            
                            # 下载歌曲
                            result = await NeteaseAPI.download_music_by_id(song_id)
                            
                            if "error" in result:
                                print(f"下载歌曲出错: {result['error']}")
                            else:
                                # 添加到播放列表
                                self.playlist_manager.add_song(result['file_name'], result)
                                print(f"下载完成: {result['song_name']}")
                    except Exception as e:
                        print(f"下载歌曲时出错: {e}")
                    finally:
                        self.playlist_manager.is_downloading = False
                
                await asyncio.sleep(1)  # 避免CPU占用过高
                
        except asyncio.CancelledError:
            print("下载管理任务被取消")
        except Exception as e:
            print(f"下载管理任务异常: {e}")
            import traceback
            print(traceback.format_exc())
        finally:
            self.playlist_manager.is_downloading = False
            print("下载管理任务结束")


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
