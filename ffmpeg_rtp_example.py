import json
import os
import platform
import random
import subprocess
import threading
import time
from collections import deque

# 仅在 Windows 上导入 pywin32 相关模块
if platform.system() == 'Windows':
    import win32pipe
    import win32file


def open_file(path: str):
    with open(path, 'r', encoding='utf-8') as f:
        tmp = json.load(f)
    return tmp


# 获取当前脚本的目录
script_dir = os.path.dirname(os.path.abspath(__file__))

config = open_file(os.path.join(script_dir, 'config', 'ffmpeg_config.json'))

# 将相对路径转换为绝对路径
config["audio_files"] = os.path.abspath(os.path.join(script_dir, config["audio_files"]))
config["output_dir"] = os.path.abspath(os.path.join(script_dir, config["output_dir"]))


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
            # result = subprocess.run(ffmpeg_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            subprocess.run(ffmpeg_command, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # 如果需要调试，可以打印 ffmpeg 的输出
            # print(result.stdout.decode('utf-8'))
            # print(result.stderr.decode('utf-8'))
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
    bitrate = config["bitrate"]
    bitrate_k = str(int(bitrate) // 1000) + "k"

    ffmpeg_command = [
        "ffmpeg",
        "-re",
        "-f", "concat",
        "-safe", "0",
        "-i", pipe_path,
        "-af", f"volume={volume}",
        "-acodec", "libopus",
        "-b:a", f"{bitrate_k}",
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
                    # 使用绝对路径，并确保路径中的反斜杠被正确转义
                    line = f"file '{next_song}'\n"
                    data = line.encode('utf-8')
                    win32file.WriteFile(pipe, data)
        except Exception as e:
            print(f"管道错误: {e}")
        finally:
            win32file.CloseHandle(pipe)

    pipe_thread = threading.Thread(target=write_to_pipe)
    pipe_thread.start()

    return process, pipe_thread


def get_audio_files_from_directory(directory, extensions=None):
    """
    遍历目录并返回所有指定扩展名的音频文件列表。

    :param directory: 要遍历的文件夹路径
    :param extensions: 包含要匹配的音频文件扩展名的列表，例如 ['.wav', '.flac', '.mp3']
    :return: 包含音频文件路径的列表
    """
    if extensions is None:
        extensions = ['.wav', '.flac', '.mp3', '.aac', '.ogg', '.m4a']  # 常见音频格式

    audio_files = []

    # 遍历目录及其子目录，寻找匹配扩展名的文件
    for root, _, files in os.walk(directory):
        for file in files:
            if any(file.lower().endswith(ext) for ext in extensions):
                audio_files.append(os.path.join(root, file))

    return audio_files


def check_ffmpeg_process(process):
    """每秒检查一次 ffmpeg 进程是否仍在运行"""
    while process.poll() is None:  # 如果进程仍在运行
        a = 0
        for _ in range(a):
            print(f"{a}ffmpeg 正在运行...")
            time.sleep(1)
    print("ffmpeg 进程已关闭。")


def main():
    # 指定文件夹路径（已转换为绝对路径）
    directory = config["audio_files"]

    # 获取文件夹内的所有音频文件
    audio_files = get_audio_files_from_directory(directory)

    if not audio_files:
        print("没有找到任何音频文件。")
        return
    else:
        print(f"找到 {len(audio_files)} 个音频文件：")
        for file in audio_files:
            print(file)

    output_dir = config["output_dir"]
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
    rtp_address = config["rtp_url"]
    ssrc = 1111
    payload_type = 111
    volume = 0.8

    # 开始推流
    process, pipe_thread = stream_audio_files_with_pipe(playlist_manager, rtp_address, ssrc, payload_type, volume)
    check_thread = threading.Thread(target=check_ffmpeg_process, args=(process,))
    check_thread.start()

    # 等待推流完成
    pipe_thread.join()
    process.wait()

    # 如果需要查看 ffmpeg 的输出，可以在这里打印
    # stdout, stderr = process.communicate()
    # print(stdout.decode('utf-8'))
    # print(stderr.decode('utf-8'))


if __name__ == "__main__":
    main()
