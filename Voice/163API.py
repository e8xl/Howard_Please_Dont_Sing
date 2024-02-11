from NeteaseCloudMusic import NeteaseCloudMusicApi

netease_cloud_music_api = NeteaseCloudMusicApi()  # 初始化API


def captcha_sent(_phone):
    response = netease_cloud_music_api.request("/captcha/sent", {"phone": f"{_phone}"})
    return response


def login_cellphone(_phone, _captcha):
    response = netease_cloud_music_api.request("/login/cellphone", {"phone": f"{_phone}", "captcha": f"{_captcha}"})
    return response


def song_url_v1(song_id):
    # 获取歌曲mp3地址
    response = netease_cloud_music_api.request("song_url_v1", {"id": song_id, "level": "exhigh"})
    return response


def song_detail(song_id):
    # 获取歌曲详情
    response = netease_cloud_music_api.request("song_detail", {"ids": str(song_id)})
    # 这里记得传一个字符串，其实所有参数都传字符串就行，需要数字的话内部会自己转换的，但是它默认你传入的时候是字符串，所以你传数字他不会自动转字符串，
    # 这时如果遇到操作字符串的方法就会报错，所以最好都传字符串，避免出现意外
    return response


def login_status():
    response = netease_cloud_music_api.request("/login/status")
    return response


def refersh_login():
    response = netease_cloud_music_api.request("/login/refresh")
    return response


# 登录
if not netease_cloud_music_api.cookie:
    print("请设置cookie")
    phone = input("请输入手机号：")
    result = captcha_sent(phone)
    print(result)
    if result.get("code") == 200:
        print("验证码已发送，请查收")
        captcha = input("请输入验证码：")
        result = login_cellphone(phone, captcha)
        if result.get("code") == 200:
            print("登录成功")
            if netease_cloud_music_api.cookie:
                print("cookie已自动设置")
        else:
            print("登录失败")

# 获取登录状态
login_status_result = login_status()
# pprint(login_status_result)
if login_status_result['data']['data']["code"] == 200:
    print(f'当前登录账号：{login_status_result["data"]["data"]["profile"]["nickname"]}')

version_result = netease_cloud_music_api.request("inner_version")
print(
    f'当前使用NeteaseCloudMusicApi版本号：{version_result["NeteaseCloudMusicApi"]}\n当前使用NeteaseCloudMusicApi_V8版本号：{version_result["NeteaseCloudMusicApi_V8"]}')  # 退出登录
# 获取歌曲mp3地址
song_url_result = song_url_v1(33894312)
if song_url_result.get("code") == 200:
    song_url = song_url_result['data']["data"][0]['url']
else:
    print("获取歌曲mp3地址失败")
    exit(1)
# 获取歌曲详情
song_detail_result = song_detail(33894312)
if song_detail_result.get("code") == 200:
    song_name = song_detail_result['data']['songs'][0]['name']
    song_artist = song_detail_result['data']['songs'][0]['ar'][0]['name']
else:
    print("获取歌曲详情失败")
    exit(1)
