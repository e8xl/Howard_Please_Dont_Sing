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
        self.current_song = None
        self.current_song_info = None
        self.ffprobe_path = set_ffprobe_path() if platform.system() == 'Windows' else 'ffprobe'

    def add_song(self, song_path):
        """添加歌曲到播放列表"""
        if os.path.exists(song_path):
            self.playlist.append(song_path)
            return True
        return False

    def get_next_song(self):
        """获取下一首歌"""
        if not self.playlist:
            return None
        self.current_song = self.playlist.popleft()
        self.current_song_info = self.get_song_info(self.current_song)
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
            title = os.path.basename(song_path)

            # 尝试获取媒体标签中的标题
            tags = info.get('format', {}).get('tags', {})
            if 'title' in tags:
                title = tags['title']

            return {
                'title': title,
                'duration': duration,
                'path': song_path
            }
        except Exception as e:
            print(f"获取歌曲信息出错: {e}")
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

        for i, song in enumerate(self.playlist, 1):
            info = self.get_song_info(song)
            songs.append(f"{i}. {info['title']} "
                         f"({int(info['duration'] // 60)}:"
                         f"{int(info['duration'] % 60):02d})")

        return songs

    def has_songs(self):
        """检查是否还有歌曲"""
        return len(self.playlist) > 0 or self.current_song is not None


class FFmpegPipeStreamer:
    """FFmpeg管道流媒体播放器"""

    def __init__(self, rtp_url):
        self.rtp_url = rtp_url
        self.playlist_manager = PlaylistManager()
        self.pipe_path = self._get_pipe_path()
        self.ffmpeg_process_player = None
        self.ffmpeg_process_streamer = None
        self._running = False
        self._pipe = None
        self.ffmpeg_path = set_ffmpeg_path() if platform.system() == 'Windows' else 'ffmpeg'

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
            "-b:a", BITRATE,
            "-ac", str(CHANNELS),
            "-ar", str(SAMPLE_RATE),
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
        while self._running:
            if not self.playlist_manager.current_song:
                # 没有当前歌曲，尝试获取下一首
                next_song = self.playlist_manager.get_next_song()
                if not next_song:
                    # 播放列表为空，等待一秒
                    await asyncio.sleep(1)
                    continue

            # 播放当前歌曲
            current_song = self.playlist_manager.current_song
            print(f"播放: {os.path.basename(current_song)}")

            # 启动播放器FFmpeg进程
            player_cmd = [
                self.ffmpeg_path,
                "-v", "quiet",
                "-i", current_song,
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
            while self._running and self.playlist_manager.current_song == current_song:
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
            if self.playlist_manager.current_song == current_song:
                self.playlist_manager.current_song = None

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
