## 菜单功能
1. - [x] 通过指令打开帮助菜单
   - [x] we命令实现调用高德API查询天气
   - [x] 实现简单的娱乐功能
   - [x] ~~帮助菜单内实现一言功能~~（网络环境不稳定暂时移除）<br>
   - [x] 实现本地一言数据库

## 点歌功能
因为需要点歌网易云并未拥有版权资源的歌曲 所以需要构建本地音乐库 或者互联网直链音乐库
1. - [x] 频道内输入指令 ffmpeg推流音频
   1. - [x] 发出指令获取用户所在频道ID
      - [x] 加入频道并加载ffmpeg进行推流
2. - [x] 通过指令附带参数进行播放
   1. - [x] 输入指令后获取用户所在语音频道ID
   2. - [x] 进入频道 
   3. - [x] 播放指定音频
   4. - [x] 播放指定音频并推流  
~~3. - [ ] 调用ncmpy实现网易云的点歌播放搜索歌词功能~~  
   ~~1. - [ ] 调用ncmpy进行搜索~~  
      ~~- [ ] 实现手机号密码登录 若不稳定更换cookie登录~~  
   ~~2. - [ ] 调用ncmpy进行播放~~  
   ~~3. - [ ] 调用ncmpy进行搜索歌词进行展示~~  
   - #### 由于ncmpy没用明白 所以改用NeteaseCloudMusicApi
3. - [x] 使用NeteaseCloudMusicApi实现网易云的点歌播放搜索歌词功能
   1. - [x] 调用API进行搜索
   2. - [x] 调用API进行歌曲下载
   3. - [x] 调用API和推流逻辑对下载歌曲进行播放
   4. - [x] 调用API实现登出后登录 自动检索cookie是否存活
4. - [ ] 实现推流歌曲播放列表 使用Pipe实现多个歌曲的推流
   - [ ] 实现歌词展示功能
   - [ ] 实现歌曲切换功能
   - [ ] 实现歌曲暂停功能
   - [ ] 实现重连功能 (实现方法：需要外部的client_manager实现进程管理工作) 


使用PIPE连接多个FFmpeg进程：可以创建一个主FFmpeg进程负责接收音频流，通过pipe将音频传递给负责RTP推流的第二个FFmpeg进程。这样无论播放多少首歌曲，都只有一个FFmpeg进程与KOOK的RTP地址交互。

正在播放歌曲的卡片！！