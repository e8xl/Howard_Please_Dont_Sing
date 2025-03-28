# FFmpeg音频推流工具

这是一个基于FFmpeg的音频推流工具，通过PIPE连接两个FFmpeg进程，一个负责音频处理，一个负责RTP推流。

## 功能特点

- 使用两个FFmpeg进程分离音频处理和推流功能
- 通过管道（PIPE）连接进程，降低延迟
- 支持播放列表管理（添加、删除、跳过等功能）
- 使用asyncio设计，非阻塞式运行
- 支持获取音频文件详细信息（时长等）

## 安装步骤

### 1. 安装依赖

```bash
pip install pywin32  # 仅Windows系统需要
```

### 2. 安装FFmpeg

本工具需要FFmpeg和FFprobe可执行文件。有两种方式可以配置：

#### 方法一：将FFmpeg放置在指定目录（推荐）

1. 从 [FFmpeg官网](https://ffmpeg.org/download.html) 下载FFmpeg
2. 解压下载的文件
3. 创建以下目录结构：
   ```
   项目根目录/
   ├── Tools/
   │   └── ffmpeg/
   │       └── bin/
   │           ├── ffmpeg.exe
   │           └── ffprobe.exe
   ```
4. 将ffmpeg.exe和ffprobe.exe放入bin目录

#### 方法二：使用环境变量

1. 从 [FFmpeg官网](https://ffmpeg.org/download.html) 下载FFmpeg
2. 将FFmpeg添加到系统PATH环境变量中
3. 修改ffmpeg_stream_tool.py文件，将FFmpeg路径设置为使用系统命令

### 3. 检查FFmpeg路径

运行检查工具确认FFmpeg配置是否正确：

```bash
python check_ffmpeg_path.py
```

## 配置

在`ffmpeg_stream_tool.py`文件开头修改以下变量：

```python
# 可以修改的RTP推流地址
RTP_URL = "rtp://127.0.0.1:7890"  # 修改为你的RTP地址
SAMPLE_RATE = 48000
CHANNELS = 2
BITRATE = "128k"
PAYLOAD_TYPE = 111
SSRC = 1111
```

## 运行

### 启动推流工具

```bash
python ffmpeg_stream_tool.py
```

### 使用测试脚本

```bash
# 不带参数启动
python test_streamer.py

# 带音频目录参数启动，自动添加目录中的音频文件
python test_streamer.py /path/to/audio/files
```

## 可用命令

启动后，可以使用以下命令：

- `add <文件路径>` - 添加歌曲到播放列表
- `list` - 显示播放列表
- `skip` - 跳过当前歌曲
- `now` - 显示正在播放的歌曲
- `quit` - 退出程序

## 工作原理

1. 启动时创建两个FFmpeg进程：
    - 第一个进程负责读取音频文件并转换为PCM数据
    - 第二个进程从管道读取PCM数据并推送至RTP地址

2. 通过管道连接两个进程，确保低延迟和连续播放

3. 即使切换音频文件，第二个进程也保持对RTP地址的稳定连接

## 适用场景

- 音频直播
- 在线会议系统
- 在线语音聊天室
- 音频广播系统（如KOOK等平台）

## 故障排除

如果遇到问题：

1. 确保RTP地址正确
2. 检查是否安装了所有依赖
3. 确保有合适的音频文件格式 