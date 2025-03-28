#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
FFmpeg音频推流工具测试脚本
"""

import asyncio
import os
import sys

from ffmpeg_stream_tool import FFmpegPipeStreamer

# 测试RTP地址
TEST_RTP_URL = "rtp://127.0.0.1:7890"


async def test_stream(audio_dir=None):
    """测试音频推流"""
    print("=" * 50)
    print("FFmpeg音频推流工具测试")
    print("=" * 50)

    # 确保FFmpeg工具可用
    try:
        # 创建推流器实例
        streamer = FFmpegPipeStreamer(TEST_RTP_URL)
        await streamer.start()

        print(f"\n推流地址: {TEST_RTP_URL}")
        print("推流器已启动\n")

        # 如果提供了音频目录，添加所有音频文件
        if audio_dir and os.path.isdir(audio_dir):
            print(f"正在从目录 {audio_dir} 添加音频文件...")

            # 支持的音频格式
            audio_extensions = ['.mp3', '.wav', '.flac', '.ogg', '.m4a', '.aac']

            # 遍历目录中的文件
            added = 0
            for file in os.listdir(audio_dir):
                if any(file.lower().endswith(ext) for ext in audio_extensions):
                    file_path = os.path.join(audio_dir, file)
                    if streamer.playlist_manager.add_song(file_path):
                        print(f"已添加: {file}")
                        added += 1

            print(f"共添加了 {added} 个音频文件\n")

        print("=" * 50)
        print("测试命令:")
        print("  add <文件路径> - 添加歌曲到播放列表")
        print("  list - 显示播放列表")
        print("  skip - 跳过当前歌曲")
        print("  now - 显示正在播放的歌曲")
        print("  quit - 退出测试")
        print("=" * 50)

        # 简单的命令处理
        while True:
            print("\n> ", end="", flush=True)
            cmd = await asyncio.get_event_loop().run_in_executor(None, input)

            if cmd.lower() == "quit":
                print("停止测试...")
                await streamer.stop()
                break

            elif cmd.lower().startswith("add "):
                filepath = cmd[4:].strip()
                if streamer.playlist_manager.add_song(filepath):
                    print(f"已添加: {os.path.basename(filepath)}")
                else:
                    print(f"文件不存在: {filepath}")

            elif cmd.lower() == "list":
                songs = streamer.playlist_manager.list_songs()
                if songs:
                    print("播放列表:")
                    for song in songs:
                        print(song)
                else:
                    print("播放列表为空")

            elif cmd.lower() == "skip":
                old, new = streamer.playlist_manager.skip_current()
                if old:
                    print(f"已跳过: {os.path.basename(old)}")
                    if new:
                        print(f"即将播放: {os.path.basename(new)}")
                else:
                    print("没有正在播放的歌曲")

            elif cmd.lower() == "now":
                if streamer.playlist_manager.current_song:
                    info = streamer.playlist_manager.current_song_info
                    print(f"正在播放: {info['title']} "
                          f"({int(info['duration'] // 60)}:"
                          f"{int(info['duration'] % 60):02d})")
                else:
                    print("没有正在播放的歌曲")

            else:
                print("未知命令，可用命令: add, list, skip, now, quit")

    except FileNotFoundError as e:
        print(f"错误: {e}")
        print("\nFFmpeg未找到。请确保以下路径存在FFmpeg工具:")
        print("项目根目录/Tools/ffmpeg/bin/ffmpeg.exe")
        print("项目根目录/Tools/ffmpeg/bin/ffprobe.exe")
        print("\n您可以从 https://ffmpeg.org/download.html 下载FFmpeg并将其放置在正确位置。")
    except Exception as e:
        print(f"发生错误: {e}")
        return


if __name__ == "__main__":
    # 检查是否提供了音频目录参数
    audio_directory = None
    if len(sys.argv) > 1:
        audio_directory = sys.argv[1]
        if not os.path.isdir(audio_directory):
            print(f"警告: 提供的路径 '{audio_directory}' 不是有效目录")
            audio_directory = None

    asyncio.run(test_stream(audio_directory))
