import os
import platform
import random
import subprocess
import threading
from collections import deque

# 仅在 Windows 上导入 pywin32 相关模块
if platform.system() == 'Windows':
    import win32pipe
    import win32file
    import pywintypes


class PlaylistManager:
    def __init__(self, mode='FIFO'):
        self.playlist = deque()
        self.mode = mode

    def add_song(self, song_path):
        """将新歌添加到歌单"""
        self.playlist.append(song_path)

    def get_next_song(self):
        """根据当前模式获取下一首歌"""
        if not self.playlist:
            return None

        if self.mode == 'FIFO':
            return self.playlist.popleft()  # 先进先出
        elif self.mode == 'LIFO':
            return self.playlist.pop()  # 后进先出
        elif self.mode == 'RoundRobin':
            song = self.playlist.popleft()  # 取第一首歌
            self.playlist.append(song)  # 放到队列尾部，形成循环
            return song
        elif self.mode == 'Random':
            song = random.choice(self.playlist)  # 随机选择
            self.playlist.remove(song)  # 删除该歌曲
            return song
        else:
            raise ValueError(f"不支持的消费模式: {self.mode}")

    def has_songs(self):
        """判断歌单中是否还有歌曲"""
        return len(self.playlist) > 0


def preprocess_audio_files(audio_files, output_dir, sample_rate=48000, channels=2):
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    processed_files = []
    for file in audio_files:
        if not os.path.isfile(file):
            print(f"文件不存在: {file}")
            continue

        filename = os.path.basename(file)
        name, ext = os.path.splitext(filename)
        output_file = os.path.join(output_dir, f"{name}_processed.wav")

        ffmpeg_command = [
            "ffmpeg",
            "-y",  # 覆盖输出文件
            "-i", file,
            "-acodec", "pcm_s16le",  # 16位 PCM
            "-ar", str(sample_rate),  # 采样率
            "-ac", str(channels),  # 声道数
            output_file
        ]

        print(f"正在转换文件: {file} -> {output_file}")
        try:
            subprocess.run(ffmpeg_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            processed_files.append(output_file)
        except subprocess.CalledProcessError as e:
            print(f"转换失败: {file}")
            print(e.stderr.decode('utf-8'))

    return processed_files


def create_named_pipe(pipe_path):
    # 创建一个命名管道
    pipe = win32pipe.CreateNamedPipe(
        pipe_path,
        win32pipe.PIPE_ACCESS_OUTBOUND,
        win32pipe.PIPE_TYPE_BYTE | win32pipe.PIPE_WAIT,
        1, 65536, 65536,
        0,
        None
    )
    return pipe


def stream_audio_files_with_pipe(playlist_manager, rtp_address, ssrc=1111, payload_type=111, volume=0.8):
    pipe_path = r'\\.\pipe\audio_pipe'
    pipe = create_named_pipe(pipe_path)

    ffmpeg_command = [
        "ffmpeg",
        "-re",
        "-f", "concat",
        "-safe", "0",
        "-i", pipe_path,
        "-af", f"volume={volume}",
        "-acodec", "libopus",
        "-b:a", "32k",
        "-ac", "2",
        "-ar", "48000",
        "-ssrc", str(ssrc),
        "-payload_type", str(payload_type),
        "-f", "rtp",
        rtp_address
    ]

    print("执行的 ffmpeg 命令:")
    print(' '.join(ffmpeg_command))

    process = subprocess.Popen(ffmpeg_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    # 启动一个线程动态向管道中写入播放文件列表
    def write_to_pipe():
        try:
            win32pipe.ConnectNamedPipe(pipe, None)
            while playlist_manager.has_songs():
                next_song = playlist_manager.get_next_song()
                if next_song:
                    print(f"正在推流: {next_song}")
                    # 格式化路径
                    formatted_path = next_song.replace('\\', '\\\\')  # 或者使用正斜杠: next_song.replace('\\', '/')
                    line = f"file '{formatted_path}'\n"
                    data = line.encode('utf-8')
                    win32file.WriteFile(pipe, data)
        except pywintypes.error as e:
            print(f"管道错误: {e}")
        finally:
            win32file.CloseHandle(pipe)

    pipe_thread = threading.Thread(target=write_to_pipe)
    pipe_thread.start()

    return process, pipe_thread


def main():
    audio_files = [
        r"D:\Acode\PythonProject\KookBot\Kook_VoiceAPI\AudioLib\1111.WAV",
        r"D:\Acode\PythonProject\KookBot\Kook_VoiceAPI\AudioLib\1211.wav",
    ]

    output_dir = r"D:\Acode\PythonProject\KookBot\Kook_VoiceAPI\AudioLib\Processed"
    processed_files = preprocess_audio_files(audio_files, output_dir)

    if not processed_files:
        print("没有有效的预处理音频文件可推流。")
        return

    # 初始化歌单管理器，指定消费模式（FIFO、LIFO、RoundRobin、Random）
    playlist_manager = PlaylistManager(mode='FIFO')

    # 将预处理好的文件添加到歌单中
    for file in processed_files:
        playlist_manager.add_song(file)

    # 配置推流地址和参数
    rtp_address = "rtp://82.156.86.194:33338"
    ssrc = 1111
    payload_type = 111
    volume = 0.8

    # 开始推流
    process, pipe_thread = stream_audio_files_with_pipe(playlist_manager, rtp_address, ssrc, payload_type, volume)

    # 等待推流完成
    pipe_thread.join()
    process.wait()


if __name__ == "__main__":
    main()
