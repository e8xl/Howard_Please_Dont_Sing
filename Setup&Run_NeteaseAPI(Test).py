import glob
import os
import subprocess

# 配置路径
tools_path = "Tools"
node_folder_pattern = "node*"  # Node.js 文件夹通配符
netease_api_folder = "neteasecloudmusicapi-main"  # Netease API 主目录
app_file = "app.js"  # 运行的主文件


# 设置 PATH，确保 npm 和 node 使用脚本中指定的路径
def configure_path(node_path):
    node_dir = os.path.dirname(node_path)
    os.environ["PATH"] = f"{node_dir};{os.environ['PATH']}"
    print(f"已配置 PATH 环境变量：{node_dir}")


# 获取 Node.js 和 npm 的完整路径
def get_node_and_npm_paths():
    tools_full_path = os.path.abspath(tools_path)
    node_dirs = glob.glob(os.path.join(tools_full_path, node_folder_pattern))
    if not node_dirs:
        print(f"错误：未在 {tools_full_path} 下找到符合条件的 Node.js 文件夹！")
        return None, None

    node_dir = node_dirs[0]
    node_executable = os.path.join(node_dir, "node.exe")
    npm_executable = os.path.join(node_dir, "npm.cmd")

    if not os.path.exists(node_executable):
        print(f"错误：未在 {node_dir} 下找到 node.exe 文件！")
        return None, None

    if not os.path.exists(npm_executable):
        print(f"错误：未在 {node_dir} 下找到 npm.cmd 文件！")
        return None, None

    print(f"成功：找到 Node.js 路径：{node_executable}")
    print(f"成功：找到 npm 路径：{npm_executable}")
    return node_executable, npm_executable


# 检查是否有 Netease API
def verify_api_exists():
    api_dir_path = os.path.join(os.getcwd(), tools_path, netease_api_folder)
    if not os.path.exists(api_dir_path):
        print(f"错误：未在 {tools_path} 下找到 Netease API 文件夹 {netease_api_folder}！")
        return False
    print(f"成功：找到 Netease API 文件夹 {netease_api_folder}")
    return True


# 更改 npm 镜像源
def change_npm_registry(npm_path):
    try:
        print("正在设置 npm 镜像源为 https://registry.npmmirror.com/... ")
        subprocess.run([npm_path, "config", "set", "registry", "https://registry.npmmirror.com/"], check=True)
        print("npm 镜像源设置完成。")
    except subprocess.CalledProcessError as e:
        print(f"设置 npm 镜像源失败：{e}")


# 修复 husky 并安装依赖
def fix_husky_and_install(npm_path):
    package_json_path = os.path.join(tools_path, netease_api_folder, "package.json")

    if not os.path.exists(package_json_path):
        print("package.json 文件不存在，请检查路径。")
        return False

    try:
        print("正在安装依赖（跳过 postinstall 脚本）...")
        subprocess.run([npm_path, "install", "--ignore-scripts"], cwd=os.path.join(tools_path, netease_api_folder),
                       check=True)
        print("依赖安装完成。")

        # 单独安装 axios
        print("正在单独安装 axios 模块...")
        subprocess.run([npm_path, "install", "axios@latest", "--save"],
                       cwd=os.path.join(tools_path, netease_api_folder), check=True)
        print("axios 安装完成。")
        return True
    except subprocess.CalledProcessError as e:
        print(f"npm install 失败：{e}")
        return False


# 运行目标命令
def run_command(node_path):
    app_file_path = os.path.abspath(os.path.join(tools_path, netease_api_folder, app_file))
    try:
        subprocess.run([node_path, app_file_path], check=True)
        print("API 已成功启动！")
        return True
    except subprocess.CalledProcessError as e:
        print(f"运行目标命令失败：{e}")
        return False


# 主逻辑
def main():
    node_path, npm_path = get_node_and_npm_paths()
    if not node_path or not npm_path:
        print("未找到 Node.js 或 npm，脚本终止。")
        return

    configure_path(node_path)  # 确保 npm 使用脚本指定的 node

    if not verify_api_exists():
        print("API 文件夹验证失败，脚本终止。")
        return

    print("尝试启动 API...")
    if not run_command(node_path):
        print("API 启动失败，尝试修复依赖...")
        change_npm_registry(npm_path)  # 更改 npm 镜像源
        if not fix_husky_and_install(npm_path):
            print("修复依赖失败，脚本终止。")
        else:
            print("依赖修复完成，尝试重新启动 API...")
            if not run_command(node_path):
                print("API 启动仍然失败，请手动检查！")
            else:
                print("API 已成功启动！")


if __name__ == "__main__":
    main()
