import os
import re
import shutil
import subprocess
import sys
from PyQt5.QtWidgets import QApplication, QInputDialog

# ---------------- 参数 ----------------
NETWORK_DIR = r"\\sa6400\文档\programming\ProdDB"
LOCAL_DIR = r"C:\virtual environment\ProdDB"
DIST_DIR = os.path.join(LOCAL_DIR, "dist", "ProdDB")
DESKTOP_DIR = os.path.join(os.path.expanduser("~"), "Desktop", "ProdDB")
VERSION_FILE_NAME = "version_info.txt"
PY_FILE_NAME = "ProdDB.pyw"
ISS_FILE = os.path.join(NETWORK_DIR, "ProdDB.iss")
TEMPLATE_FILES = ["产品信息模板.xlsx", "原创摄影作品声明模板.png"]
ICON_DIR = "icon"

# ---------------- PyQt 输入版本号 ----------------
app = QApplication(sys.argv)
ver, ok = QInputDialog.getText(None, "输入版本号", "请输入新的版本号（格式如 1.0.0）:", text="1.0.0")
if not ok or not ver.strip():
    print("未输入版本号，程序退出")
    sys.exit(0)
ver = ver.strip()

# ---------------- 修改 version_info.txt ----------------
version_file_path = os.path.join(NETWORK_DIR, VERSION_FILE_NAME)
if not os.path.exists(version_file_path):
    print(f"错误：找不到 {version_file_path}")
    sys.exit(1)

with open(version_file_path, "r", encoding="utf-8") as f:
    content = f.read()

try:
    major, minor, patch = ver.split(".")
except ValueError:
    print("版本号格式错误，应为 x.y.z")
    sys.exit(1)

content = re.sub(r"filevers=\(\d+, \d+, \d+, \d+\)", f"filevers=({major}, {minor}, {patch}, 0)", content)
content = re.sub(r"StringStruct\('FileVersion', '\d+\.\d+\.\d+\.0'\),", f"StringStruct('FileVersion', '{ver}.0'),", content)
content = re.sub(r"StringStruct\('ProductVersion', '\d+\.\d+\.\d+'\)\]\)", f"StringStruct('ProductVersion', '{ver}')])", content)

with open(version_file_path, "w", encoding="utf-8") as f:
    f.write(content)
print(f"{VERSION_FILE_NAME} 已更新为版本 {ver}")

# ---------------- 修改 .iss 文件里的 MyAppVersion ----------------
if os.path.exists(ISS_FILE):
    with open(ISS_FILE, "r", encoding="utf-8") as f:
        iss_content = f.read()
    iss_content = re.sub(r'MyAppVersion\s+"[^"]+"', f'MyAppVersion "{ver}"', iss_content)
    with open(ISS_FILE, "w", encoding="utf-8") as f:
        f.write(iss_content)
    print(f"{ISS_FILE} 中的 MyAppVersion 已更新为 {ver}")
else:
    print(f"警告：{ISS_FILE} 不存在")

# ---------------- 复制 ProdDB.pyw 和 version_info.txt ----------------
os.makedirs(LOCAL_DIR, exist_ok=True)
shutil.copy2(os.path.join(NETWORK_DIR, PY_FILE_NAME), LOCAL_DIR)
shutil.copy2(version_file_path, LOCAL_DIR)
print("源文件已复制到本地工作目录")

# ---------------- 打包 PyInstaller ----------------
pyinstaller_cmd = (
    'call Scripts\\activate && '
    f'pyinstaller "{os.path.join(LOCAL_DIR, PY_FILE_NAME)}" '
    f'--upx-dir=c:/upx -i "{os.path.join(LOCAL_DIR, ICON_DIR, "app.ico")}" '
    f'--version-file "{os.path.join(LOCAL_DIR, VERSION_FILE_NAME)}"'
)
print("开始打包，请稍等...")
res = subprocess.run(pyinstaller_cmd, shell=True, cwd=LOCAL_DIR)
if res.returncode != 0:
    print("打包失败")
    sys.exit(1)
print("打包成功完成！")

# ---------------- 复制模板和icon ----------------
os.makedirs(DIST_DIR, exist_ok=True)
for f in TEMPLATE_FILES:
    src_file = os.path.join(LOCAL_DIR, f)
    if os.path.exists(src_file):
        shutil.copy2(src_file, DIST_DIR)
        print(f"已复制 {f}")
    else:
        print(f"警告：文件 {f} 不存在")

icon_src = os.path.join(LOCAL_DIR, ICON_DIR)
icon_dst = os.path.join(DIST_DIR, ICON_DIR)
if os.path.exists(icon_src):
    if os.path.exists(icon_dst):
        shutil.rmtree(icon_dst)
    shutil.copytree(icon_src, icon_dst)
    print("已复制 icon 文件夹")
else:
    print("警告：icon 文件夹不存在")

# ---------------- 移动到桌面 ----------------
if os.path.exists(DESKTOP_DIR):
    shutil.rmtree(DESKTOP_DIR)
shutil.move(DIST_DIR, DESKTOP_DIR)
print(f"已移动 ProdDB 文件夹到桌面 {DESKTOP_DIR}")

# ---------------- 清理 build 和 dist ----------------
for d in ["build", "dist"]:
    path = os.path.join(LOCAL_DIR, d)
    if os.path.exists(path):
        shutil.rmtree(path)
        print(f"已删除 {d} 文件夹")

# ---------------- 打开 .iss 文件 ----------------
if os.path.exists(ISS_FILE):
    print(f"正在打开 {ISS_FILE} ...")
    # 用系统默认程序打开 .iss 文件
    if os.name == "nt":  # Windows
        os.startfile(ISS_FILE)
else:
    print(f"错误：找不到 {ISS_FILE}")

input("所有操作完成，按回车键退出...")
