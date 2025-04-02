#!/usr/bin/env python
# -*- coding: utf-8 -*-

import asyncio
import json
import os
import platform
import random
import shlex
import subprocess
from collections import deque
import time

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
        """初始化播放列表管理器"""
        self.playlist = deque()  # 当前播放列表
        self.temp_playlist = deque()  # 临时播放列表，用于填充主播放列表
        self.full_playlist = []  # 完整播放列表，用于重新创建临时列表
        self.played_songs = []  # 已播放歌曲列表，用于列表循环模式
        self.current_song = None  # 当前播放的歌曲
        self.current_song_info = None  # 当前歌曲的信息
        self.current_song_notified = False  # 当前歌曲是否已通知
        self.songs_info = {}  # 歌曲信息缓存
        self.download_queue = deque()  # 下载队列 - 修改为deque
        self.is_downloading = False  # 是否正在下载
        self.recently_added_songs = deque(maxlen=5)  # 最近添加的歌曲，最多保存5首
        self.buffer_size = 3  # 播放列表缓冲大小
        self.play_mode = "sequential"  # 播放模式：sequential（顺序）, random（随机）, list_loop（列表循环）, single_loop（单曲循环）
        self.temp_playlist_mode = "sequential"  # 临时播放列表的播放模式
        self.download_callback = None  # 下载回调函数
        self.ffprobe_path = set_ffprobe_path() if platform.system() == 'Windows' else 'ffprobe'

        # 用于存储从网易云音乐获取的完整歌单
        self.playlist_info = {
            'id': None,
            'name': '',
            'description': '',
            'image_url': '',
            'track_count': 0
        }

        # 下载相关
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
            self.recently_added_songs.append(song_path)

            return True
        return False

    def get_current_audio(self):
        """获取当前正在播放的音频路径"""
        if self.current_song:
            return self.current_song

        # 如果没有当前歌曲，尝试获取下一首
        if not self.playlist:
            # 处理临时播放列表和播放模式变化
            if self.temp_playlist and self.play_mode != self.temp_playlist_mode:
                print(f"播放模式已从 {self.temp_playlist_mode} 变为 {self.play_mode}，重新创建临时播放列表")
                self._recreate_temp_playlist()
                self._refill_playlist_from_temp()

            # 再次检查播放列表是否为空
            if not self.playlist:
                # 处理列表循环模式
                if self.play_mode == "list_loop":
                    # 检查是否有已播放歌曲
                    if self.played_songs:
                        print(f"列表循环模式：重新使用已播放的 {len(self.played_songs)} 首歌曲")
                        # 将已播放列表重新加入播放队列
                        self.playlist.extend(self.played_songs)
                        self.played_songs = []
                    # 如果仍然没有歌曲，但有完整歌单，重新创建临时列表
                    elif self.full_playlist:
                        print("列表循环模式：从完整歌单重新创建临时列表")
                        self._recreate_temp_playlist()
                        self._refill_playlist_from_temp()

                # 最终检查播放列表
                if not self.playlist:
                    # 尝试从临时播放列表获取更多歌曲
                    if self.temp_playlist:
                        print(f"从临时播放列表中填充歌曲，临时列表中有 {len(self.temp_playlist)} 首歌曲")
                        self._refill_playlist_from_temp()

                    # 最终检查
                    if not self.playlist:
                        return None

        self.current_song = self.get_next_song()
        # 重置通知标志
        self.current_song_notified = False
        return self.current_song

    def get_next_song(self):
        """获取下一首歌"""
        if not self.playlist:
            # 再次尝试填充播放列表
            if self.temp_playlist:
                print(f"播放列表为空，从临时列表填充，临时列表中有 {len(self.temp_playlist)} 首歌曲")
                self._refill_playlist_from_temp()

            # 处理列表循环模式
            if self.play_mode == "list_loop":
                # 先检查是否有已播放歌曲
                if self.played_songs:
                    print(f"列表循环模式：重新使用已播放的 {len(self.played_songs)} 首歌曲")
                    # 将已播放列表重新加入播放队列
                    for song in self.played_songs:
                        self.playlist.append(song)

                    # 在随机模式下，打乱新添加的歌曲
                    if self.play_mode == "random":
                        print("随机模式下的列表循环：随机打乱已播放的歌曲")
                        temp_list = list(self.playlist)
                        random.shuffle(temp_list)
                        self.playlist = deque(temp_list)

                    self.played_songs.clear()
                # 如果仍然没有歌曲，但有完整歌单，重新创建临时列表
                elif self.full_playlist and not self.temp_playlist:
                    print("列表循环模式：从完整歌单重新创建临时列表")
                    self._recreate_temp_playlist()
                    self._refill_playlist_from_temp()

            # 最终检查播放列表
            if not self.playlist:
                print("所有列表均为空，无法获取下一首歌曲")
                return None

        # 如果是单曲循环模式，并且当前有歌曲正在播放，则重复播放当前歌曲
        if self.play_mode == "single_loop" and self.current_song:
            # 将当前歌曲标记为未通知，这样会重新显示当前歌曲信息
            self.current_song_notified = False
            print(f"单曲循环模式：重复播放 {os.path.basename(self.current_song)}")
            return self.current_song

        # 在随机模式下，如果current_song在播放列表中的第一位，随机重排
        if self.play_mode == "random" and self.playlist and self.current_song and self.playlist[0] == self.current_song:
            print("随机模式：检测到下一首歌与当前歌曲相同，重新随机化")
            temp_list = list(self.playlist)
            random.shuffle(temp_list)
            self.playlist = deque(temp_list)

            # 如果重排后第一首仍然是当前歌曲，再尝试几次
            attempts = 0
            while attempts < 3 and self.playlist and self.playlist[0] == self.current_song:
                print(f"随机模式：第{attempts + 1}次尝试避免重复歌曲")
                temp_list = list(self.playlist)
                random.shuffle(temp_list)
                self.playlist = deque(temp_list)
                attempts += 1

        # 获取下一首歌曲
        next_song = self.playlist.popleft()

        # 记录已播放歌曲用于列表循环
        if self.play_mode == "list_loop":
            self.played_songs.append(next_song)
            print(
                f"将歌曲 {os.path.basename(next_song)} 添加到已播放列表，已播放列表当前有 {len(self.played_songs)} 首歌曲")

        # 更新当前歌曲和歌曲信息
        self.current_song = next_song
        # 记录歌曲开始播放的时间
        self.current_song_start_time = time.time()

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

        # 检查是否需要填充更多歌曲到播放列表
        if len(self.playlist) < self.buffer_size:
            if self.temp_playlist:
                print(f"播放列表中只有 {len(self.playlist)} 首歌曲，将从临时列表填充更多歌曲")
                self._refill_playlist_from_temp(count=self.buffer_size - len(self.playlist))
            elif not self.temp_playlist and self.play_mode == "list_loop" and self.full_playlist:
                # 在列表循环模式下，如果临时列表为空但有完整歌单，重新创建临时列表
                print("列表循环模式：临时列表为空，从完整歌单重新创建")
                self._recreate_temp_playlist()
                self._refill_playlist_from_temp(count=self.buffer_size - len(self.playlist))

        return self.current_song

    def skip_current(self):
        """
        跳过当前歌曲
        
        :return: (旧歌曲路径, 新歌曲路径)
        """
        old_song = self.current_song

        # 如果没有正在播放的歌曲，无法跳过
        if not old_song:
            print("没有正在播放的歌曲，无法跳过")
            return None, None

        # 重置已通知标记
        self.current_song_notified = False

        # 保存原始的播放列表，以便在日志中显示有意义的信息
        if self.playlist:
            next_song_in_queue = self.playlist[0]
        else:
            next_song_in_queue = None

        # 如果是单曲循环模式，跳过后应该不再循环当前歌曲
        if self.play_mode == "single_loop":
            # 将当前歌曲添加到已播放列表（如果处于列表循环模式）
            if self.play_mode == "list_loop":
                self.played_songs.append(old_song)

            # 重置当前歌曲，这样get_next_song不会重复播放
            self.current_song = None
            # 重置开始时间
            self.current_song_start_time = 0
        else:
            # 非单曲循环模式，直接重置当前歌曲
            self.current_song = None
            # 重置开始时间
            self.current_song_start_time = 0

            # 将跳过的歌曲添加到已播放列表（如果处于列表循环模式）
            if self.play_mode == "list_loop":
                self.played_songs.append(old_song)

        # 检查播放列表是否太短，可能需要从临时列表填充
        if (not self.playlist or len(self.playlist) < self.buffer_size) and self.temp_playlist:
            fill_result = self._refill_playlist_from_temp(count=max(1, self.buffer_size - len(self.playlist)))

            # 如果我们在随机模式下并且有新歌填充，队列已经被重新随机排序，不需要在下面再次随机排序
            if self.play_mode == "random" and fill_result:
                return old_song, self.get_next_song()

        # 随机模式下，如果下一首和当前歌曲相同，则随机重排队列
        if self.play_mode == "random" and self.playlist:
            if next_song_in_queue == self.playlist[0]:
                print("随机模式：重新随机化播放队列以避免播放相同的歌曲")
                current_playlist = list(self.playlist)
                random.shuffle(current_playlist)
                self.playlist = deque(current_playlist)

            # 确保当前队列中的第一首歌曲不是刚刚播放过的歌曲
            attempts = 0
            while self.playlist and self.playlist[0] == old_song and attempts < 3:
                print("随机模式：重新随机化播放队列以避免播放相同的歌曲")
                current_playlist = list(self.playlist)
                random.shuffle(current_playlist)
                self.playlist = deque(current_playlist)
                attempts += 1

        # 获取下一首歌
        next_song = self.get_next_song()

        # 如果没有下一首歌，但有临时播放列表和完整歌单，尝试重新填充
        if not next_song and (self.temp_playlist or (self.full_playlist and self.play_mode == "list_loop")):
            print("当前播放列表已空，但还有歌曲在临时列表中，将尝试填充")

            # 如果临时列表为空但是列表循环模式，重新创建临时列表
            if not self.temp_playlist and self.play_mode == "list_loop" and self.full_playlist:
                print("列表循环模式：重新创建临时列表")
                self._recreate_temp_playlist()

            # 尝试从临时列表填充
            if self.temp_playlist:
                self._refill_playlist_from_temp(count=min(self.buffer_size, len(self.temp_playlist)))
                # 再次尝试获取下一首歌
                next_song = self.get_next_song()

        if not next_song:
            print("播放列表已播放完毕")

        return old_song, next_song

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

    def set_play_mode(self, mode):
        """设置播放模式
        
        Args:
            mode: 播放模式，可以是 "sequential", "random", "single_loop", "list_loop"
        
        Returns:
            bool: 是否成功设置了播放模式
        """
        valid_modes = ["sequential", "random", "single_loop", "list_loop"]
        if mode not in valid_modes:
            print(f"无效的播放模式: {mode}, 有效模式: {', '.join(valid_modes)}")
            return False

        # 如果模式没有变化，不做任何操作
        if self.play_mode == mode:
            print(f"播放模式已经是 {mode}")
            return True

        old_mode = self.play_mode
        self.play_mode = mode
        print(f"播放模式从 {old_mode} 更改为 {mode}")

        # 保存当前播放的歌曲，以便模式变化时不中断
        current_song = self.current_song

        # 根据播放模式变化处理当前播放列表和临时播放列表
        if self.play_mode != self.temp_playlist_mode:
            # 对于随机模式，需要将当前播放列表也随机化
            if self.play_mode == "random" and self.playlist:
                # 将当前播放列表转换为列表，随机化，再转回双端队列
                current_playlist = list(self.playlist)
                random.shuffle(current_playlist)
                self.playlist = deque(current_playlist)
                print(f"已将当前播放列表({len(self.playlist)}首歌曲)随机排序")

            # 重新创建临时播放列表
            if self.full_playlist:
                print("播放模式变化，重新创建临时播放列表")
                self._recreate_temp_playlist()

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

    def _recreate_temp_playlist(self):
        """根据当前播放模式重新创建临时播放列表"""
        if not self.full_playlist:
            print("没有完整播放列表，无法重新创建临时播放列表")
            return

        # 清空现有临时列表
        self.temp_playlist = deque()

        # 基于播放模式决定如何填充临时列表
        if self.play_mode == "random":
            # 随机模式: 随机打乱完整播放列表复制后填入临时列表
            temp_list = list(self.full_playlist)
            random.shuffle(temp_list)
            self.temp_playlist = deque(temp_list)
            print(f"随机模式：已创建包含 {len(self.temp_playlist)} 首随机排序歌曲的临时列表")
        elif self.play_mode == "list_loop":
            # 列表循环模式: 按顺序复制完整播放列表
            self.temp_playlist = deque(self.full_playlist)
            print(f"列表循环模式：已创建包含 {len(self.temp_playlist)} 首顺序排列歌曲的临时列表")
        elif self.play_mode == "single_loop":
            # 单曲循环模式: 主要依赖于get_next_song的逻辑，但也创建顺序列表以备需要
            self.temp_playlist = deque(self.full_playlist)
            print(f"单曲循环模式：已创建包含 {len(self.temp_playlist)} 首顺序排列歌曲的临时列表(仅作为备用)")
        else:  # 默认和顺序模式
            # 顺序模式: 按顺序复制完整播放列表
            self.temp_playlist = deque(self.full_playlist)
            print(f"顺序模式：已创建包含 {len(self.temp_playlist)} 首顺序排列歌曲的临时列表")

        # 更新临时列表模式
        self.temp_playlist_mode = self.play_mode

    def _refill_playlist_from_temp(self, count=None):
        """从临时播放列表中填充歌曲到主播放列表
        
        Args:
            count: 指定要添加的歌曲数量，如果为None则添加至buffer_size或全部添加
        """
        if not self.temp_playlist:
            print("临时播放列表为空，无法填充")
            return False

        # 确定要填充的数量
        to_fill = count if count is not None else self.buffer_size
        to_fill = min(to_fill, len(self.temp_playlist))

        # 如果to_fill为0，表示不需要添加
        if to_fill <= 0:
            return False

        print(f"从临时播放列表填充 {to_fill} 首歌曲到下载队列")

        # 临时存储将要处理的歌曲
        tracks_to_process = []

        # 从临时列表取出指定数量的歌曲
        for _ in range(to_fill):
            if not self.temp_playlist:
                break
            tracks_to_process.append(self.temp_playlist.popleft())

        # 确保播放列表有足够的歌曲
        added_count = 0
        downloaded_count = 0

        for track in tracks_to_process:
            # 处理歌曲
            if isinstance(track, dict):
                # 如果是字典，包含歌曲信息
                song_id = str(track.get('id', ''))
                if song_id:
                    # 检查文件是否已经存在，如果存在则直接加入播放列表
                    from os.path import join, exists, abspath
                    relative_path = "./AudioLib"
                    absolute_path = abspath(relative_path)
                    file_path = join(absolute_path, f"{song_id}.mp3")

                    if exists(file_path):
                        # 文件已存在，直接加入播放列表
                        track["file_path"] = file_path
                        self.add_song(file_path, track)
                        print(f"歌曲已存在，直接加入播放列表: {track.get('song_name', song_id)}")
                        added_count += 1
                    else:
                        # 文件不存在，加入下载队列
                        added = self._add_to_download_queue(track)
                        if added:
                            print(f"加入下载队列: {track.get('song_name', song_id)}")
                            downloaded_count += 1
                else:
                    print(f"歌曲信息缺少ID: {track}")
            else:
                # 如果是字符串，可能是歌曲ID或文件路径
                if os.path.exists(track):
                    # 是文件路径，直接加入播放列表
                    self.add_song(track)
                    print(f"直接加入播放列表: {os.path.basename(track)}")
                    added_count += 1
                else:
                    # 可能是歌曲ID
                    song_id = track
                    # 构建简单的歌曲信息
                    track_info = {'id': song_id}
                    added = self._add_to_download_queue(track_info)
                    if added:
                        print(f"加入下载队列: {song_id}")
                        downloaded_count += 1

        print(
            f"已从临时播放列表处理 {len(tracks_to_process)} 首歌曲，直接添加到播放列表 {added_count} 首，加入下载队列 {downloaded_count} 首")

        # 如果当前是随机模式，并且有新添加的歌曲，重新随机排序播放列表
        if self.play_mode == "random" and added_count > 0 and len(self.playlist) > 1:
            current_playlist = list(self.playlist)
            random.shuffle(current_playlist)
            self.playlist = deque(current_playlist)
            print(f"随机模式：重新随机排序播放列表({len(self.playlist)}首歌曲)")

        return added_count > 0

    def _add_to_download_queue(self, track_info):
        """添加歌曲到下载队列
        
        :param track_info: 歌曲信息字典
        :return: 是否成功添加（True表示添加成功）
        """
        # 检查是否已在下载队列中
        song_id = str(track_info.get('id', ''))
        if not song_id:
            print("歌曲信息缺少ID，无法添加到下载队列")
            return False

        # 检查是否已在下载队列中
        for item in self.download_queue:
            if str(item.get('id', '')) == song_id:
                print(f"歌曲 {song_id} 已在下载队列中")
                return False

        # 检查歌曲是否已经在播放列表中（通过检查songs_info）
        for song_path, info in self.songs_info.items():
            if str(info.get('id', '')) == song_id:
                print(f"歌曲 {song_id} 已在播放列表中")
                return False

        # 检查歌曲文件是否已存在（但尚未加入播放列表）
        from os.path import join, exists, abspath
        relative_path = "./AudioLib"
        absolute_path = abspath(relative_path)
        file_path = join(absolute_path, f"{song_id}.mp3")

        if exists(file_path):
            # 文件已存在，直接加入播放列表
            track_info["file_path"] = file_path
            self.add_song(file_path, track_info)
            print(f"歌曲文件已存在，直接加入播放列表: {track_info.get('song_name', song_id)}")
            return True

        # 添加到下载队列
        self.download_queue.append(track_info)
        return True

    def add_playlist_batch(self, tracks_info):
        """
        批量添加歌单中的歌曲信息到系统
        
        :param tracks_info: 歌曲信息列表
        :return: 添加的歌曲数量
        """
        count = 0

        # 保存完整歌单信息
        self.full_playlist = []
        for track in tracks_info:
            # 提取必要信息
            song_id = str(track.get('id'))

            # 构建歌曲信息 - 修复处理艺术家名称的方法，避免None值导致join失败
            artists = []
            for ar in track.get('ar', []):
                name = ar.get('name')
                if name is not None:  # 确保不是None
                    artists.append(name)
                else:
                    artists.append('未知艺术家')

            # 使用安全处理后的艺术家列表
            artist_name = ", ".join(artists) if artists else "未知艺术家"

            song_info = {
                'id': song_id,
                'song_name': track.get('name', '未知歌曲'),
                'artist_name': artist_name,
                'album_name': track.get('al', {}).get('name', '未知专辑')
            }

            # 添加到完整歌单
            self.full_playlist.append(song_info)
            count += 1

        # 创建临时播放列表
        self._recreate_temp_playlist()

        # 填充播放列表
        self._refill_playlist_from_temp()

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

        # 如果播放列表变得太短，从临时列表填充
        if len(self.playlist) < self.buffer_size and self.temp_playlist:
            self._refill_playlist_from_temp()

        return True

    def clear_playlist(self):
        """
        清空播放列表（不包括当前正在播放的歌曲）
        
        :return: 清除的歌曲数量
        """
        count = len(self.playlist)
        self.playlist.clear()
        self.recently_added_songs.clear()

        # 如果有完整歌单，也清空临时播放列表
        if self.full_playlist:
            self.temp_playlist.clear()

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

    def list_songs(self, max_items=20):
        """
        列出播放列表中的所有歌曲
        
        :param max_items: 最多显示的歌曲数量
        :return: 格式化的歌曲列表
        """
        songs = []

        # 显示当前播放的歌曲
        if self.current_song and self.current_song_info:
            songs.append(f"当前播放: {self.current_song_info['title']} "
                         f"({int(self.current_song_info['duration'] // 60)}:"
                         f"{int(self.current_song_info['duration'] % 60):02d})")

        # 显示接下来要播放的歌曲
        for i, song_path in enumerate(self.playlist, 1):
            if i > max_items:
                songs.append(f"... 还有 {len(self.playlist) - max_items} 首歌曲")
                break

            # 获取歌曲标题
            if song_path in self.songs_info:
                song_info = self.songs_info[song_path]
                title = f"{song_info.get('song_name', '')} - {song_info.get('artist_name', '')}"
            else:
                # 使用ffprobe获取信息
                info = self.get_song_info(song_path)
                title = info['title']

            songs.append(f"{i}. {title}")

        # 显示下载队列中的歌曲
        if self.download_queue:
            pending_count = len(self.download_queue)
            if pending_count > 0:
                songs.append(f"下载队列: {pending_count} 首歌曲等待下载")

        # 显示歌单信息
        if self.playlist_info:
            playlist_info = self.get_playlist_info()
            if playlist_info:
                songs.append(f"当前歌单: {playlist_info['name']} (共 {playlist_info['trackCount']} 首歌曲)")

        # 显示播放模式
        _, mode_name = self.get_play_mode()
        songs.append(f"播放模式: {mode_name}")

        return songs

    def has_songs(self):
        """检查是否还有歌曲"""
        # 检查当前播放列表、当前歌曲、下载队列和临时播放列表
        has_current = self.current_song is not None
        has_in_playlist = len(self.playlist) > 0
        has_in_download_queue = len(self.download_queue) > 0
        has_in_temp_playlist = len(self.temp_playlist) > 0

        # 如果任何一个队列中有歌曲，返回True
        return has_current or has_in_playlist or has_in_download_queue or has_in_temp_playlist

    def check_song_end(self, force_next=False):
        """检查当前歌曲是否已结束，如果是则自动切换到下一首
        
        Args:
            force_next: 是否强制切换到下一首歌曲
            
        Returns:
            bool: 如果已切换到下一首返回True，否则返回False
        """
        if not self.current_song:
            # 没有当前播放的歌曲，尝试获取一首
            next_audio = self.get_current_audio()
            if next_audio:
                print(f"开始播放首首歌曲: {os.path.basename(next_audio)}")
                return True
            return False

        # 检查是否需要强制切换
        if force_next:
            print("强制切换到下一首歌曲")
            self.skip_current()
            return True

        # 获取当前歌曲时长和播放位置
        try:
            duration = float(self.get_song_duration(self.current_song))
            position = float(self.get_play_position())

            # 如果位置为0且之前已经播放过，可能是因为歌曲结束循环
            if position == 0 and duration > 0 and hasattr(self, 'last_position') and self.last_position > 0:
                # 判断为歌曲已结束
                print(f"当前歌曲 {os.path.basename(self.current_song)} 已结束，切换到下一首")

                # 单曲循环模式下，直接重新开始当前歌曲
                if self.play_mode == "single_loop":
                    print("单曲循环模式：重新播放当前歌曲")
                    self.current_song_notified = False  # 重置通知状态，会重新显示歌曲信息
                    return True

                # 其他模式，切换到下一首
                return self.skip_current()

            # 更新上一次位置
            self.last_position = position

            # 检查是否接近结束（剩余不到2秒）
            if duration > 0 and (duration - position) < 2:
                print(f"当前歌曲 {os.path.basename(self.current_song)} 即将结束，准备切换到下一首")

                # 如果是单曲循环，不执行切换
                if self.play_mode == "single_loop":
                    return False

                # 提前加载下一首歌准备切换
                if len(self.playlist) < 1 and self.temp_playlist:
                    print("预加载下一首歌曲")
                    self._refill_playlist_from_temp(count=1)

                # 判断列表循环模式是否需要重新加载列表
                if len(self.playlist) == 0 and self.play_mode == "list_loop":
                    if not self.temp_playlist and self.played_songs:
                        print(f"列表循环模式：即将用 {len(self.played_songs)} 首已播放歌曲重新填充播放列表")

        except Exception as e:
            print(f"检查歌曲结束状态时出错: {e}")

        return False

    def get_play_position(self):
        """获取当前播放位置（秒）
        
        Returns:
            float: 当前播放位置，如果无法获取则返回0
        """
        # 如果没有当前播放的歌曲，返回0
        if not self.current_song:
            return 0
            
        # 如果播放时间尚未记录，返回0
        if not hasattr(self, 'current_song_start_time'):
            return 0
            
        # 计算已播放时间
        elapsed_time = time.time() - self.current_song_start_time
        
        # 对时间进行合理性检查和限制
        if elapsed_time < 0:
            elapsed_time = 0
            
        # 获取歌曲总时长，确保不超过总时长
        total_duration = self.get_song_duration(self.current_song)
        if total_duration > 0 and elapsed_time > total_duration:
            elapsed_time = total_duration
            
        return elapsed_time

    def get_song_duration(self, file_path):
        """获取歌曲时长
        
        Args:
            file_path: 歌曲文件路径
            
        Returns:
            float: 歌曲时长（秒），如果无法获取则返回0
        """
        # 首先检查是否有预存的歌曲信息
        if file_path in self.songs_info:
            info = self.songs_info[file_path]
            if 'duration' in info:
                return float(info['duration'])

        # 使用ffprobe获取时长
        try:
            # 使用ffprobe获取音频时长
            cmd = [
                self.ffprobe_path,
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if result.returncode == 0:
                duration = result.stdout.strip()
                if duration:
                    # 缓存结果
                    if file_path in self.songs_info:
                        self.songs_info[file_path]['duration'] = float(duration)
                    return float(duration)
        except Exception as e:
            print(f"获取歌曲时长时出错: {e}")

        return 0


class FFmpegPipeStreamer:
    """基于FFmpeg和命名管道的音频流传输器，提供更多高级功能，如播放列表管理、音量控制等"""

    def __init__(self, rtp_url, bitrate='36k', volume=0.8, message_obj=None, message_callback=None, channel_id=None):
        """
        初始化流传输器
        
        :param rtp_url: RTP目标地址
        :param bitrate: 音频比特率
        :param volume: 音频音量（0.0-1.0）
        :param message_obj: 消息对象，用于发送通知
        :param message_callback: 消息回调函数，用于发送通知
        :param channel_id: 频道ID，用于创建唯一管道
        """
        self.rtp_address = rtp_url
        self.bitrate = bitrate
        self.volume = volume
        self.message_obj = message_obj
        self.message_callback = message_callback
        self.channel_id = channel_id or "default"

        # 获取管道路径
        self.pipe_path = self._get_pipe_path()

        # 初始化FFmpeg路径
        self._init_ffmpeg_paths()

        # 初始化管道
        self._pipe = None

        # 控制标志
        self._running = False
        self.exit_due_to_empty_playlist = False
        self.is_importing = False  # 表示是否正在导入播放列表
        self.initialization_grace_period = True  # 初始化宽限期标志

        # 播放列表管理器
        self.playlist_manager = PlaylistManager()

        # 播放器进程
        self.ffmpeg_process = None
        self.ffmpeg_process_player = None
        self.ffmpeg_process_streamer = None

        # 任务
        self.audio_loop_task = None
        self.download_task = None

        # 第一首歌标志
        self.is_first_song = True

        print(f"初始化FFmpegPipeStreamer，推流地址: {rtp_url}，比特率: {self.bitrate}，音量: {self.volume}")

    def _get_pipe_path(self):
        """获取管道路径，使用channel_id确保唯一性"""
        if platform.system() == 'Windows':
            return fr'\\.\pipe\audio_pipe_{self.channel_id}'
        else:
            return f'/tmp/audio_pipe_{self.channel_id}'

    def _init_ffmpeg_paths(self):
        self.ffmpeg_path = set_ffmpeg_path() if platform.system() == 'Windows' else 'ffmpeg'
        self.ffprobe_path = set_ffprobe_path() if platform.system() == 'Windows' else 'ffprobe'

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
            self.rtp_address
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

        # 启动音频播放循环和下载管理
        self.audio_loop_task = asyncio.create_task(self._audio_loop())
        return True

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
                    # 播放列表为空，检查是否有下载队列或临时列表
                    has_pending_songs = (
                            len(self.playlist_manager.download_queue) > 0 or
                            len(self.playlist_manager.temp_playlist) > 0
                    )

                    if has_pending_songs:
                        # 如果有待下载或待处理的歌曲，等待下载完成
                        print(
                            f"播放列表为空，但还有待处理的歌曲：下载队列({len(self.playlist_manager.download_queue)})，临时列表({len(self.playlist_manager.temp_playlist)})")

                        # 尝试从临时列表填充更多歌曲
                        if self.playlist_manager.temp_playlist:
                            self.playlist_manager._refill_playlist_from_temp()

                        # 等待下载完成
                        await asyncio.sleep(1)
                        continue
                    else:
                        # 没有待处理的歌曲，计时器增加
                        empty_playlist_timer += 1
                        print(f"播放列表为空 ({empty_playlist_timer}/5)，无待处理歌曲")

                        if empty_playlist_timer >= 5:  # 连续5次检查播放列表为空
                            # 如果正在导入歌曲，不要退出
                            if self.is_importing:
                                print("正在导入歌曲，不设置退出标志")
                                empty_playlist_timer = 0  # 重置计时器
                                await asyncio.sleep(2)  # 多等待一会
                                continue

                            # 进行全面检查，确保真的没有任何歌曲
                            has_current = self.playlist_manager.current_song is not None
                            has_playlist = len(self.playlist_manager.playlist) > 0
                            has_queue = len(self.playlist_manager.download_queue) > 0
                            has_temp = len(self.playlist_manager.temp_playlist) > 0

                            if has_current or has_playlist or has_queue or has_temp:
                                print(
                                    f"检测到仍有歌曲: 当前歌曲({has_current}), 播放列表({has_playlist}), 下载队列({has_queue}), 临时列表({has_temp})")
                                empty_playlist_timer = 0  # 重置计时器
                                await asyncio.sleep(1)
                                continue

                            # 如果完整歌单也为空，则表示确实没有歌曲了
                            if not self.playlist_manager.full_playlist:
                                print("完整歌单也为空，将退出音频循环")
                                # 确保之前的退出标志被清除
                                self.exit_due_to_empty_playlist = True
                                self._running = False
                                print(f"已设置exit_due_to_empty_playlist为True（频道将自动退出），音频循环已标记为停止")

                                # 确保播放列表和下载队列已清空
                                self.playlist_manager.playlist.clear()
                                self.playlist_manager.download_queue.clear()
                                self.playlist_manager.temp_playlist.clear()

                                # 终止循环，避免重置标志
                                break

                            # 尝试从完整歌单重新创建临时列表（如果列表循环模式）
                            if self.playlist_manager.play_mode == "list_loop":
                                print("列表循环模式：重新创建临时列表")
                                self.playlist_manager._recreate_temp_playlist()
                                self.playlist_manager._refill_playlist_from_temp()
                                # 重置计时器
                                empty_playlist_timer = 0
                                continue
                            else:
                                # 非循环模式且播放列表为空，自动退出
                                print("非循环模式且播放列表为空，将退出音频循环")

                                # 最后一次全面检查，确保确实没有任何歌曲
                                has_current = self.playlist_manager.current_song is not None
                                has_playlist = len(self.playlist_manager.playlist) > 0
                                has_queue = len(self.playlist_manager.download_queue) > 0
                                has_temp = len(self.playlist_manager.temp_playlist) > 0

                                if has_current or has_playlist or has_queue or has_temp:
                                    print(
                                        f"最后检测到仍有歌曲: 当前歌曲({has_current}), 播放列表({has_playlist}), 下载队列({has_queue}), 临时列表({has_temp})")
                                    empty_playlist_timer = 0  # 重置计时器
                                    await asyncio.sleep(1)
                                    continue

                                self.exit_due_to_empty_playlist = True
                                self._running = False

                                # 确保播放列表和下载队列已清空
                                self.playlist_manager.playlist.clear()
                                self.playlist_manager.download_queue.clear()
                                self.playlist_manager.temp_playlist.clear()

                                print(f"已设置exit_due_to_empty_playlist为True（频道将自动退出），音频循环已标记为停止")
                                # 终止循环，避免重置标志
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
                            # 标记为已通知
                            self.playlist_manager.current_song_notified = True
                            # 移除歌曲从recently_added_songs集合中
                            if current_audio_path in self.playlist_manager.recently_added_songs:
                                self.playlist_manager.recently_added_songs.remove(current_audio_path)
                            # 重置第一首歌标志
                            self.is_first_song = False

                            # 发送播放通知
                            await self.message_callback(self.message_obj, f"正在播放: {song_name} - {artist_name}")
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
                                    # 尝试从完整歌单重新创建临时列表
                                    if not self.playlist_manager.temp_playlist and self.playlist_manager.full_playlist:
                                        print("列表循环模式：重新创建临时列表")
                                        self.playlist_manager._recreate_temp_playlist()
                                        self.playlist_manager._refill_playlist_from_temp()

                                    await self.message_callback(self.message_obj, "列表播放完毕，将重新开始播放")
                                except Exception as e:
                                    print(f"发送列表循环通知时出错: {e}")

                        # 正常处理下一首歌
                        self.playlist_manager.current_song = None
                        self.playlist_manager.current_song_notified = False

                        # 检查播放列表是否太短，可能需要从临时列表填充
                        if len(self.playlist_manager.playlist) < self.playlist_manager.buffer_size:
                            if self.playlist_manager.temp_playlist:
                                self.playlist_manager._refill_playlist_from_temp()

                        # 获取下一首歌，即将播放的信息
                        if self.playlist_manager.playlist and self.message_callback and self.message_obj:
                            # 获取下一首歌的信息
                            next_song_path = None
                            next_song_title = "未知歌曲"

                            # 对于随机播放，需要特殊处理
                            if self.playlist_manager.play_mode == "random":
                                # 随机模式下，通知将随机播放
                                if self.playlist_manager.playlist:
                                    # 尽管是随机模式，但即将播放的歌曲已经在队列前端
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
                                        if self._running:  # 只有在仍然运行时才发送消息
                                            await self.message_callback(self.message_obj,
                                                                        f"即将播放: {next_song_title}")
                                    except Exception as e:
                                        print(f"发送下一首歌曲通知时出错: {e}")
                            else:
                                # 对于非随机播放，正常处理
                                if self.playlist_manager.playlist:
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
                                        if self._running:  # 只有在仍然运行时才发送消息
                                            await self.message_callback(self.message_obj,
                                                                        f"即将播放: {next_song_title}")
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

    async def _manage_downloads(self):
        """管理下载队列，按需下载歌曲"""
        try:
            print("启动下载管理任务")

            # 添加一个缓存列表，用于存储已下载但尚未添加到播放列表的歌曲
            downloaded_songs = []

            while self._running:
                # 首先处理已下载的歌曲，将它们添加到播放列表
                if downloaded_songs:
                    for song_info in downloaded_songs:
                        file_path = song_info.get('file_path')
                        if file_path and os.path.exists(file_path):
                            self.playlist_manager.add_song(file_path, song_info)
                            print(
                                f"将下载完成的歌曲添加到播放列表: {song_info.get('song_name', os.path.basename(file_path))}")

                    # 清空已处理的下载歌曲
                    downloaded_songs = []

                # 如果队列为空，等待并检查临时播放列表
                if not self.playlist_manager.download_queue:
                    # 检查是否需要从临时列表填充更多歌曲
                    if (len(self.playlist_manager.playlist) < self.playlist_manager.buffer_size and
                            self.playlist_manager.temp_playlist):
                        self.playlist_manager._refill_playlist_from_temp()

                    await asyncio.sleep(1)
                    continue

                # 获取下载队列长度和播放列表长度
                queue_len = len(self.playlist_manager.download_queue)
                playlist_len = len(self.playlist_manager.playlist)

                # 判断是否需要下载更多歌曲
                # 策略：保持播放列表中至少有buffer_size首歌曲
                max_songs_to_download = self.playlist_manager.buffer_size - playlist_len if playlist_len < self.playlist_manager.buffer_size else 0

                # 如果播放列表为空，至少下载一首歌曲
                if playlist_len == 0 and queue_len > 0:
                    max_songs_to_download = max(1, max_songs_to_download)

                if max_songs_to_download > 0 and queue_len > 0 and not self.playlist_manager.is_downloading:
                    # 设置下载中标志
                    self.playlist_manager.is_downloading = True

                    try:
                        # 从队列中取出歌曲信息
                        song_info = self.playlist_manager.download_queue.popleft()
                        song_id = song_info.get('id')

                        if not song_id:
                            print(f"歌曲信息缺少ID，跳过下载: {song_info}")
                            self.playlist_manager.is_downloading = False
                            continue

                        # 检查文件是否已经存在
                        from os.path import join, exists, abspath
                        relative_path = "./AudioLib"
                        absolute_path = abspath(relative_path)
                        file_path = join(absolute_path, f"{song_id}.mp3")
                        file_exists = exists(file_path)

                        if file_exists:
                            print(f"歌曲已存在本地，无需下载: {song_info.get('song_name', song_id)}")
                            # 更新歌曲信息
                            song_info['file_path'] = file_path
                            # 直接添加到播放列表而不是放入downloaded_songs
                            added = self.playlist_manager.add_song(file_path, song_info)
                            if added:
                                print(
                                    f"将已存在歌曲直接添加到播放列表: {song_info.get('song_name', os.path.basename(file_path))}")
                                # 随机模式下重新随机化队列
                                if self.playlist_manager.play_mode == "random" and len(
                                        self.playlist_manager.playlist) > 1:
                                    current_playlist = list(self.playlist_manager.playlist)
                                    random.shuffle(current_playlist)
                                    self.playlist_manager.playlist = deque(current_playlist)
                                    print(f"随机模式：重新随机排序播放列表({len(self.playlist_manager.playlist)}首歌曲)")
                        else:
                            print(f"下载歌曲: {song_info.get('song_name', '')} (ID: {song_id})")

                            # 动态导入NeteaseAPI，避免循环导入
                            import importlib
                            NeteaseAPI = importlib.import_module("NeteaseAPI")

                            try:
                                # 下载歌曲
                                result = await NeteaseAPI.download_music_by_id(song_id)

                                if "error" in result:
                                    print(f"下载歌曲出错: {result['error']}")
                                else:
                                    # 直接添加到播放列表而不是放入downloaded_songs
                                    file_path = result.get('file_path')
                                    if not file_path and 'file_name' in result:
                                        file_path = result['file_name']
                                        result['file_path'] = file_path

                                    if file_path and os.path.exists(file_path):
                                        added = self.playlist_manager.add_song(file_path, result)
                                        if added:
                                            print(
                                                f"下载完成并直接添加到播放列表: {result.get('song_name', os.path.basename(file_path))}")
                                            # 随机模式下重新随机化队列
                                            if self.playlist_manager.play_mode == "random" and len(
                                                    self.playlist_manager.playlist) > 1:
                                                current_playlist = list(self.playlist_manager.playlist)
                                                random.shuffle(current_playlist)
                                                self.playlist_manager.playlist = deque(current_playlist)
                                                print(
                                                    f"随机模式：重新随机排序播放列表({len(self.playlist_manager.playlist)}首歌曲)")
                                    else:
                                        # 尝试使用ID创建备用路径
                                        fallback_path = join(absolute_path, f"{song_id}.mp3")
                                        if os.path.exists(fallback_path):
                                            result['file_path'] = fallback_path
                                            added = self.playlist_manager.add_song(fallback_path, result)
                                            if added:
                                                print(
                                                    f"使用备用路径添加到播放列表: {result.get('song_name', os.path.basename(fallback_path))}")
                                                # 随机模式下重新随机化队列
                                                if self.playlist_manager.play_mode == "random" and len(
                                                        self.playlist_manager.playlist) > 1:
                                                    current_playlist = list(self.playlist_manager.playlist)
                                                    random.shuffle(current_playlist)
                                                    self.playlist_manager.playlist = deque(current_playlist)
                                                    print(
                                                        f"随机模式：重新随机排序播放列表({len(self.playlist_manager.playlist)}首歌曲)")
                                        else:
                                            print(f"下载完成但文件路径无效: {result}")

                                    # 处理完一首歌
                                    max_songs_to_download -= 1
                            except Exception as e:
                                print(f"调用NeteaseAPI.download_music_by_id出错: {e}")
                                import traceback
                                print(traceback.format_exc())
                    except Exception as e:
                        print(f"下载歌曲时出错: {e}")
                        import traceback
                        print(traceback.format_exc())
                    finally:
                        self.playlist_manager.is_downloading = False

                # 如果播放列表仍然很短且队列中还有歌曲，继续下载
                # 但先暂停一下，避免CPU占用过高
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            print("下载管理任务被取消")
        except Exception as e:
            print(f"下载管理任务异常: {e}")
            import traceback
            print(traceback.format_exc())
        finally:
            if hasattr(self.playlist_manager, 'is_downloading'):
                self.playlist_manager.is_downloading = False
            print("下载管理任务结束")

    async def stop(self):
        """停止所有FFmpeg进程"""
        self._running = False

        # 设置退出标志为False，避免触发自动退出逻辑
        self.exit_due_to_empty_playlist = False

        # 确保播放列表管理器的通知标志被重置，避免发送不必要的消息
        if hasattr(self, 'playlist_manager'):
            self.playlist_manager.current_song_notified = True

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

        # 确保清空所有列表，避免资源泄漏
        if hasattr(self, 'playlist_manager'):
            self.playlist_manager.playlist.clear()
            self.playlist_manager.download_queue.clear()
            self.playlist_manager.temp_playlist.clear()
            self.playlist_manager.current_song = None
            # 重置通知标志，避免在退出时发送"即将播放"消息
            self.playlist_manager.current_song_notified = True

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
            # 确保播放列表中确实有歌曲，避免误判断
            if self.playlist_manager.has_songs():
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
    # 创建RTP地址
    rtp_url = "rtp://127.0.0.1:5004?rtcpport=5005&ssrc=1111&payload_type=111"
    # 初始化FFmpegPipeStreamer
    streamer = FFmpegPipeStreamer(
        rtp_url=rtp_url,
        bitrate="48k",
        volume="0.8",
        channel_id="test"
    )

    # 启动推流
    await streamer.start()

    try:
        await command_interface(streamer)
    except KeyboardInterrupt:
        print("\n接收到中断信号，正在退出...")
    finally:
        await streamer.stop()


if __name__ == "__main__":
    asyncio.run(main())
