# Howard, Please Don't Sing

8XL_Kook_Music_bot  
About KookAPP Music BOT from [khl.py](https://github.com/TWT233/khl.py)

***

项目名称是因为我的朋友Howard经常喜欢在打游戏的时候激情演唱他喜欢的歌曲  
而我实在无能为力欣赏他的美妙歌喉 不得已寻找更为方便的点歌机器人 方便我们更为愉快的打游戏  
因为之前用的[*KO-ON Bot*](https://github.com/Gunale0926/KO-ON-Bot)经常出现一些问题 但由于本人*技术力过低*
无法查出问题原因  
不如加上自己喜欢的功能再写一个点歌bot自用  
非常建议各位 **仔细阅读[khl.py](https://github.com/TWT233/khl.py)的文档内容** 这可以帮助你很多
***

## 机器人频道内指令前缀

代码内出现了部分用"/"为前缀的文字示例 仅为演示作用  
代码最后已经修改了指令前缀为空 请自行修改满足需求

```shell
bot.command.update_prefixes(".")  # 修改引号内的内容为你的指令前缀 留空则无前缀 直接输入指令
```

---

### 使用网易平台需要安装NodeJS和[NeteaseCloudMusicApi](https://gitlab.com/Binaryify/neteasecloudmusicapi)

### 点歌API使用方法

#### 手动方法

- 安装FFMPEG /Tools/ffmpeg/bin

1. 参考[NeteaseCloudMusicApi](https://gitlab.com/Binaryify/neteasecloudmusicapi) 安装Node和依赖
2. 将API文件放到 Tools/neteasecloudmusicapi-main , Node目录配置环境变量或者放到Tools/node*
3. 使用根目录NeteaseRun.py启动程序

#### 自动方法

- 安装FFMPEG 到/Tools/ffmpeg/bin

1. 解压[NeteaseCloudMusicApi](https://gitlab.com/Binaryify/neteasecloudmusicapi)的源代码文件到Tools/ (可能下不到了
   我也不好分享。。)
2. 到Node.js官网下载二进制版本 解压到/Tools Node版本无限制 大于18.0即可  
   请注意：需要保证 Tools/ 文件夹内文件结构为

   ```shell
   Tools  
   {   
   -- neteasecloudmusicapi-main  
   -- node-v20.18.0-win-x64  
   -- .../  
   }
   ```

3. 运行 Setup&Run_NeteaseAPI(Test).py 完成API的依赖安装和运行  
   ↑基本上没什么问题 但不保证所有系统都能操作成功 若失败请自行解决API问题  
   代码的推流逻辑并不需要API支持 但机器人的点歌功能依赖了API返回的数据

### 或者等机器人完成全部功能后在release中下载携带环境的版本

---

### 主机器人使用方法

1. git本项目到本地

2. 安装依赖

   ```shell
   pip install -r requirements.txt
   ```

3. 在项目文件夹内创建config文件夹 并于其中添加config.json文件 格式如下\
   amap_api_key为高德地图API 需自行申请 即可使用/we 天气功能

   ```json
   {
     "token": "KookdeveloperbotToken",
     "amap_api_key": "Gaode_WeatherAPI",
     "ffmpge_volume": "0.8"
   }
   ```

4. 运行index.py

   ```shell
   python index.py
   ```

5. 机器人成功运行后在频道内输入指令

   ```shell
   帮助
   ```

## 小工具

### 机器人状态

***你也可以用更简单的办法 这样比较麻烦但很直观 所有操作都是GUI形式的***

在脚本目录Tools文件夹内CreateGame.py内运行运行机器人状态生成器  
需要提前配置config文件保证token正确 机器人可以正常运行
之后在机器人所在任何文字频道内输入如下指令 机器人会在频道内返回你游戏ID 随后修改index.py使用

```shell
/game-c {游戏名称} {游戏LOGO URL}
```

注:项目暂未支持webhook模式 若需使用webhook模式请参照[khl.py](https://github.com/TWT233/khl.py)自行修改代码


---

## 致谢

- 部分娱乐功能参考自[Kook-Valorant-Bot](https://github.com/Valorant-Shop-CN/Kook-Valorant-Bot)
- 音频推流部分基于[Kook_VoiceAPI](https://github.com/e8xl/Kook_VoiceAPI) (有点烂 其实就是封装了一下语音接口
  等什么时候有时间把整个点歌机器人的核心封装了再发布)
- 网易云音乐API使用[NeteaseCloudMusicApi](https://github.com/Binaryify/NeteaseCloudMusicApi)
- 感谢「KOOK」开发者中心的各位大佬提供的帮助

# To-Do List

## 📝 Pending Tasks

- [ ] 歌曲播放时的歌词显示
- [ ] 歌曲暂停功能
- [ ] 重连功能 (实现方法：需要外部的client_manager实现进程管理工作)  
  核心需要解决的问题就是 进程推流的时间节点 和 程序能获取的时间节点（对于正在推流音频的进度获取问题）

---

- [ ] 支持URL直链点歌功能
- [ ] 在导入歌单的情况下 使用点歌命令 被点的歌应该作为 下一首播放的歌曲被直接插入
- [ ] 推流功能分离 使其作为单独的库被调用(双ffmpeg对单个实例（频道）实现推流的进程管理模块)
- [ ] 实现周杰伦的歌曲推流功能
- [ ] 将程序模块化 使其支持被调用形式更加丰富 而不是在 [index.py](index.py) 里面进行过多内容的注册和判断
- [ ] 将程序抽离 支持webUI操作 而不是单纯的指令操控
- [ ] 细化每个模块的结构 使其不会重复使用 例如 推流模块不会调用khl.py 每个部分都应该抽离 保证其是被调用 而不会互相影响
- [ ] 可能存在的ffmpeg推流超速问题需要解决 （歌曲刚开始，歌曲切换，在倒计时十秒内点歌都会稳定复现）
- [ ] 抽离 [index.py](index.py) 将其作为程序的主入口 指令注册的程序 而不是重复指令的判断条件 判断条件应该移动到单独的模块进行处理
- [ ] 尝试支持Unix系统的ffmpeg推流

## ✅ Completed Tasks

- [x] 多频道单文件独立推流功能
- [x] 多文件（歌单列表）多频道推流功能
- [x] 内存控制 对AudioLib的数据大小控制
- [x] 支持导入网易云歌单
- [x] 歌曲播放时的卡片显示
- [x] 歌曲播放时的进度条显示

## 开源协议

本项目采用 [MIT](LICENSE) 许可证开源。
