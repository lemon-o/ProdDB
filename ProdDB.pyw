import sys
import os
import json
import subprocess
import platform
import shutil
import pandas as pd
import zipfile
import subprocess
import sys
import time
import zipfile
import tempfile   
import subprocess
import shutil
import requests
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from PyQt5.QtCore import pyqtProperty
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageFile
from datetime import datetime

ImageFile.LOAD_TRUNCATED_IMAGES = True  # 避免损坏图片报错

CURRENT_VERSION = "v1.0.5" #版本号


        
#---------------子线程 检查更新----------------------------------
class CheckUpdateThread(QThread):
    update_checked = pyqtSignal(dict, str)  # 传递检查结果和错误信息

    def __init__(self, current_version):
        super().__init__()
        self.current_version = current_version
        self.api_url = "https://api.github.com/repos/lemon-o/ProdDB/releases/latest"

    def run(self):
        try:
            response = requests.get(self.api_url, timeout=10)
            response.raise_for_status()
            self.update_checked.emit(response.json(), "")
        except Exception as e:
            self.update_checked.emit({}, str(e))

# 检测更新窗口
class UpdateDialog(QDialog):
    def __init__(self, parent=None, current_version=""):
        super().__init__(parent)
        self.current_version = current_version
        self.latest_version = ""
        self.download_url = ""
        self.setup_ui()
        self.show()  # 立即显示窗口
        self.start_check_update()  # 使用专用线程检查更新
        
    def setup_ui(self):
        self.setWindowTitle("检查更新")
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
        self.resize(400, 150)
        
        layout = QVBoxLayout()    
        
        # 状态信息
        self.status_label = QLabel("正在检查更新...")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("""
            QLabel {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                background-color: white;
                selection-background-color: #007bff;
                min-height: 60px;
            }
        """)
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()  # 初始隐藏
        layout.addWidget(self.progress_bar)
        
        # 按钮布局 - 只在检查更新窗口显示
        button_height1 = self.height() // 5
        button_style = """
        QPushButton {
            background-color: #ffffff;
            color: #3b3b3b;
            border-radius: 6%; /* 圆角半径使用相对单位，可以根据需要调整 */
            border: 1px solid #f5f5f5;
        }

        QPushButton:hover {
            background-color: #0773fc;
            color: #ffffff;
            border: 0.1em solid #0773fc; /* em为相对单位 */
        }

        QPushButton:disabled {
            background-color: #f0f0f0;  /* 禁用时的背景色（浅灰色） */
            color: #a0a0a0;           /* 禁用时的文字颜色（灰色） */
            border: 1px solid #d0d0d0; /* 禁用时的边框颜色 */
        }
        """
        self.button_layout = QHBoxLayout()
        self.update_button = QPushButton("更新")
        self.update_button.setFixedHeight(button_height1)
        self.update_button.setStyleSheet(button_style)
        self.update_button.clicked.connect(self.start_update)
        self.update_button.setEnabled(False)  # 初始不可用
        self.button_layout.addWidget(self.update_button)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.setFixedHeight(button_height1)
        self.cancel_button.setStyleSheet(button_style)
        self.cancel_button.clicked.connect(self.close)
        self.button_layout.addWidget(self.cancel_button)
        
        layout.addLayout(self.button_layout)
        self.setLayout(layout)
        
    def start_check_update(self):
        """启动异步检查更新"""
        self.status_label.setText("正在检查更新...")
        self.check_thread = CheckUpdateThread(self.current_version)
        self.check_thread.update_checked.connect(self.handle_update_result)
        self.check_thread.start()

    def handle_update_result(self, release_info, error):
        """处理检查结果"""
        if error:
            self.status_label.setText(f"检查失败: {error}")
            self.cancel_button.setText("关闭")
            return

        # 解析版本信息
        self.latest_version = release_info.get("tag_name", "")
        if not self.latest_version:
            self.status_label.setText("无法获取版本号")
            self.cancel_button.setText("关闭")
            return

        self.status_label.setText(f"当前版本: {self.current_version}\n最新版本: {self.latest_version}")

        if self.latest_version == self.current_version:
            self.status_label.setText("已经是最新版本")
            self.cancel_button.setText("关闭")
            return

        # 获取下载链接
        assets = release_info.get("assets", [])
        for asset in assets:
            name = asset.get("name", "").lower()
            if name.endswith((".exe", ".zip")):
                self.download_url = asset.get("browser_download_url")
                break

        if not self.download_url:
            self.status_label.setText("未找到可下载的安装文件")
            self.cancel_button.setText("关闭")
            return

        # 发现新版本，启用更新按钮
        self.status_label.setText(f"发现新版本 {self.latest_version}，当前版本{CURRENT_VERSION}")
        self.update_button.setEnabled(True)

    def start_update(self):
        """开始下载更新"""
        if hasattr(self, 'download_url') and self.download_url:
            # 重置UI状态
            self.update_button.hide()
            self.cancel_button.hide()
            self.progress_bar.show()
            self.progress_bar.setValue(0)
            self.status_label.setText("准备下载更新...")
            
            # 强制立即更新UI
            QApplication.processEvents()
            
            # 创建下载线程
            self.download_thread = DownloadThread(self.download_url)
            
            # 正确连接所有信号
            self.download_thread.download_progress.connect(self.handle_download_progress)
            self.download_thread.download_finished.connect(self.on_download_finished)
            self.download_thread.download_failed.connect(self.on_download_failed)
            self.download_thread.message.connect(self.status_label.setText)
            
            self.download_thread.start()

    def handle_download_progress(self, progress, downloaded_size, speed_str):
        """处理下载进度和网速"""
        # 格式化大小显示
        def format_size(size):
            if size < 1024:
                return f"{size}B"
            elif size < 1024 * 1024:
                return f"{size/1024:.1f}KB"
            else:
                return f"{size/(1024 * 1024):.1f}MB"
        
        # 更新UI
        total_size = self.download_thread.total_size
        total_str = format_size(total_size) if total_size > 0 else "未知大小"
        
        self.progress_bar.setValue(progress)
        self.status_label.setText(
            f"正在下载更新({format_size(downloaded_size)}/{total_str}) | 速度: {speed_str}"
        )
        QApplication.processEvents()

    def on_download_failed(self, error_msg):
        """下载失败处理"""
        self.progress_bar.hide()
        self.status_label.setText(f"下载失败: {error_msg}")
        # 只显示关闭按钮
        self.cancel_button.setText("关闭")
        self.cancel_button.show()

    def on_download_finished(self, local_path):
        """下载完成处理"""
        self.status_label.setText("下载完成，准备安装...")
        self.progress_bar.setValue(100)
        
        try:
            if local_path.endswith(".exe"):
                # 最小化所有窗口并启动安装程序
                self.minimize_all_windows()
                subprocess.Popen(
                    [local_path], 
                    shell=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                )     
                print(local_path)    
                
            elif local_path.endswith(".zip"):
                self.status_label.setText(f"更新包已下载到: {local_path}")
                # 只显示关闭按钮
                self.cancel_button.setText("关闭")
                self.cancel_button.show()
                
        except Exception as e:
            self.status_label.setText(f"安装失败: {e}")
            # 只显示关闭按钮
            self.cancel_button.setText("关闭")
            self.cancel_button.show()

    def minimize_all_windows(self):
        """最小化主窗口和所有子窗口"""
        # 最小化主窗口
        if self.parent():
            self.parent().showMinimized()
        
        # 最小化所有对话框
        for window in QApplication.topLevelWidgets():
            if window.isWindow() and window.isVisible():
                window.showMinimized()

        # 退出当前实例
        QApplication.quit()

#-----------子线程 下载更新--------------------------------------------
class DownloadThread(QThread):
    download_progress = pyqtSignal(int, int, str)  # 进度, 已下载大小, 网速字符串
    download_finished = pyqtSignal(str)
    download_failed = pyqtSignal(str)
    message = pyqtSignal(str)
    
    def __init__(self, download_url):
        super().__init__()
        self.download_url = download_url
        self.total_size = 0
        self._is_running = True
        self._start_time = None
        self._last_update_time = None
        self._last_size = 0
        self._speed_history = []

    def run(self):
        try:
            tmp_dir = tempfile.mkdtemp()
            local_path = os.path.join(tmp_dir, os.path.basename(self.download_url))
            
            self.message.emit(f"开始下载: {os.path.basename(self.download_url)}")
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._last_size = 0
            
            with requests.get(self.download_url, stream=True, timeout=30) as r:
                r.raise_for_status()
                self.total_size = int(r.headers.get('content-length', 0))
                downloaded_size = 0
                
                with open(local_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        if not self._is_running:
                            os.remove(local_path)
                            self.message.emit("下载已取消")
                            return
                            
                        f.write(chunk)
                        downloaded_size += len(chunk)
                        
                        # 计算实时网速（每100ms更新一次）
                        current_time = time.time()
                        if current_time - self._last_update_time >= 0.1:  # 100ms更新频率
                            elapsed = current_time - self._last_update_time
                            speed = (downloaded_size - self._last_size) / elapsed  # B/s
                            
                            # 平滑处理（最近3次平均值）
                            self._speed_history.append(speed)
                            if len(self._speed_history) > 3:
                                self._speed_history.pop(0)
                            avg_speed = sum(self._speed_history) / len(self._speed_history)
                            
                            # 格式化网速显示
                            speed_str = self.format_speed(avg_speed)
                            
                            progress = int(downloaded_size * 100 / self.total_size) if self.total_size > 0 else 0
                            self.download_progress.emit(progress, downloaded_size, speed_str)
                            
                            self._last_update_time = current_time
                            self._last_size = downloaded_size
                
            self.download_finished.emit(local_path)
            
        except Exception as e:
            self.download_failed.emit(str(e))
    
    def format_speed(self, speed_bps):
        """格式化网速显示"""
        if speed_bps < 1024:  # <1KB/s
            return f"{speed_bps:.0f} B/s"
        elif speed_bps < 1024 * 1024:  # <1MB/s
            return f"{speed_bps/1024:.1f} KB/s"
        else:
            return f"{speed_bps/(1024 * 1024):.1f} MB/s"

#--------------自定义QLineEdit右键菜单----------------------------
class QLineEdit(QLineEdit):
    def contextMenuEvent(self, event):
        menu = QMenu(self)

        undo_action = QAction("撤销", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.setShortcutVisibleInContextMenu(True)
        undo_action.triggered.connect(self.undo)
        menu.addAction(undo_action)

        redo_action = QAction("重做", self)
        redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        redo_action.setShortcutVisibleInContextMenu(True)
        redo_action.triggered.connect(self.redo)
        menu.addAction(redo_action)

        menu.addSeparator()

        cut_action = QAction("剪切", self)
        cut_action.setShortcut(QKeySequence("Ctrl+X"))
        cut_action.setShortcutVisibleInContextMenu(True)
        cut_action.triggered.connect(self.cut)
        menu.addAction(cut_action)

        copy_action = QAction("复制", self)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.setShortcutVisibleInContextMenu(True)
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)

        paste_action = QAction("粘贴", self)
        paste_action.setShortcut(QKeySequence("Ctrl+V"))
        paste_action.setShortcutVisibleInContextMenu(True)
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        delete_action = QAction("删除", self)
        delete_action.setShortcut(QKeySequence("Del"))
        delete_action.setShortcutVisibleInContextMenu(True)
        delete_action.triggered.connect(lambda: self.del_selected_text())
        menu.addAction(delete_action)

        menu.addSeparator()

        select_all_action = QAction("全选", self)
        select_all_action.setShortcut(QKeySequence("Ctrl+A"))
        select_all_action.setShortcutVisibleInContextMenu(True)
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)

        menu.exec_(event.globalPos())

    def del_selected_text(self):
        cursor = self.cursorPosition()
        selected_text = self.selectedText()
        if selected_text:
            text = self.text()
            start = self.selectionStart()
            self.setText(text[:start] + text[start+len(selected_text):])
            self.setCursorPosition(start)

#--------------自定义QTextEdit右键菜单----------------------------
class QTextEdit(QTextEdit):
    def contextMenuEvent(self, event):
        menu = QMenu(self)

        # 撤销
        undo_action = QAction("撤销", self)
        undo_action.setShortcut(QKeySequence("Ctrl+Z"))
        undo_action.setShortcutVisibleInContextMenu(True)
        undo_action.triggered.connect(self.undo)
        menu.addAction(undo_action)

        # 重做
        redo_action = QAction("重做", self)
        redo_action.setShortcut(QKeySequence("Ctrl+Y"))
        redo_action.setShortcutVisibleInContextMenu(True)
        redo_action.triggered.connect(self.redo)
        menu.addAction(redo_action)

        menu.addSeparator()

        # 剪切/复制/粘贴
        cut_action = QAction("剪切", self)
        cut_action.setShortcut(QKeySequence("Ctrl+X"))
        cut_action.setShortcutVisibleInContextMenu(True)
        cut_action.triggered.connect(self.cut)
        menu.addAction(cut_action)

        copy_action = QAction("复制", self)
        copy_action.setShortcut(QKeySequence("Ctrl+C"))
        copy_action.setShortcutVisibleInContextMenu(True)
        copy_action.triggered.connect(self.copy)
        menu.addAction(copy_action)

        paste_action = QAction("粘贴", self)
        paste_action.setShortcut(QKeySequence("Ctrl+V"))
        paste_action.setShortcutVisibleInContextMenu(True)
        paste_action.triggered.connect(self.paste)
        menu.addAction(paste_action)

        # 删除选中/整行
        delete_action = QAction("删除", self)
        delete_action.setShortcut(QKeySequence("Del"))
        delete_action.setShortcutVisibleInContextMenu(True)
        delete_action.triggered.connect(self.del_selected_text)
        menu.addAction(delete_action)

        menu.addSeparator()

        # 全选
        select_all_action = QAction("全选", self)
        select_all_action.setShortcut(QKeySequence("Ctrl+A"))
        select_all_action.setShortcutVisibleInContextMenu(True)
        select_all_action.triggered.connect(self.selectAll)
        menu.addAction(select_all_action)

        menu.exec_(event.globalPos())

    def del_selected_text(self):
        cursor = self.textCursor()
        if cursor.hasSelection():
            # 删除选中内容
            cursor.removeSelectedText()
        else:
            # 没有选中则删除整行
            cursor.select(QTextCursor.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()  # 删除换行符
        self.setTextCursor(cursor)

#----------自定义滑动开关组件--------------------------------------------- 
class ToggleSwitch(QWidget):
    toggled = pyqtSignal(bool)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(24, 12)  # 开关大小
        self.checked = False
        self._slider_position = 0.0  # 初始化滑块位置
        
        # 动画
        self.animation = QPropertyAnimation(self, b"sliderPosition")
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.OutCubic)
        
    @pyqtProperty(float)
    def sliderPosition(self):
        return self._slider_position
        
    @sliderPosition.setter
    def sliderPosition(self, pos):
        self._slider_position = pos
        self.update()
        
    def setChecked(self, checked):
        if self.checked != checked:
            self.checked = checked
            self.animation.setStartValue(self._slider_position)
            if checked:
                self.animation.setEndValue(1.0)
            else:
                self.animation.setEndValue(0.0)
            self.animation.start()
            
    def isChecked(self):
        return self.checked
        
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.setChecked(not self.checked)
            self.toggled.emit(self.checked)
            
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        
        # 背景轨道
        track_rect = QRectF(0, 0, self.width(), self.height())
        track_color = QColor(0, 123, 255) if self.checked else QColor(206, 212, 218)  # 改为 #007bff
        
        # 渐变色
        if self._slider_position > 0:
            # 混合颜色
            ratio = self._slider_position
            r = int(206 + (0 - 206) * ratio)      # 0, 123, 255 对应 #007bff
            g = int(212 + (123 - 212) * ratio)
            b = int(218 + (255 - 218) * ratio)
            track_color = QColor(r, g, b)
            
        painter.setBrush(QBrush(track_color))
        painter.setPen(Qt.NoPen)
        painter.drawRoundedRect(track_rect, self.height()/2, self.height()/2)
        
        # 滑块
        slider_size = self.height() - 2  # 稍微调整滑块大小以适应更小的开关
        slider_x = 1 + (self.width() - slider_size - 2) * self._slider_position
        slider_rect = QRectF(slider_x, 1, slider_size, slider_size)
        
        painter.setBrush(QBrush(Qt.white))
        painter.setPen(QPen(QColor(0, 0, 0, 30), 1))
        painter.drawEllipse(slider_rect)

#----------菜单项样式---------------------------------------------        
class RoundMenu(QMenu):
    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        # 设置无边框 + 透明背景
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # 设置菜单基本样式（仅用于菜单项，不影响圆角背景）
        self.setStyleSheet("""
            QMenu {
                background-color: white;  /* 背景色，会被paintEvent覆盖，但可以留着备用 */
                border: none;
                padding: 2px;
            }
            QMenu::item {
                background-color: transparent;
                padding: 8px 16px;
                margin: 1px;
                color: black;
            }
            QMenu::item:selected {
                background-color: #e3f2fd;  /* 选中项背景色 */
                color: black;
            }
            QMenu::item:disabled {
                color: gray;
            }
            QMenu::separator {
                height: 1px;
                background: #cccccc;
                margin: 4px 8px;
            }
        """)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # 自定义背景颜色和圆角
        bg_color = QColor(255, 255, 255)  # 白色背景，可换成其它颜色，如 #FFFFFF 或 QColor(240, 240, 240)
        radius = 10  # 圆角半径，越大越圆，比如 8, 10, 12

        # 绘制一个带圆角的矩形作为菜单背景
        rect = self.rect()  # 菜单的整个矩形区域
        painter.setBrush(bg_color)
        painter.setPen(Qt.NoPen)  # 无边框线
        painter.drawRoundedRect(rect, radius, radius)

    def sizeHint(self):
        # 可选：调整默认大小提示（根据需求）
        sh = super().sizeHint()
        return sh

# ---------------- 子线程 导入产品信息----------------

class ImportProductThread(QThread):
    progress_changed = pyqtSignal(int, str)  # 百分比 + 当前处理的文件夹名
    finished = pyqtSignal(int, int, bool)    # 更新数量、跳过数量、是否被取消

    def __init__(self, folders_data, excel_path):
        super().__init__()
        self.folders_data = folders_data
        self.excel_path = excel_path
        self.should_stop = False  # 取消标志

    def stop_processing(self):
        """停止处理"""
        self.should_stop = True

    def run(self):
        updated_count = 0
        skipped_count = 0
        was_cancelled = False

        try:
            # 检查是否在开始前就被取消
            if self.should_stop:
                self.finished.emit(0, 0, True)
                return

            # 明确指定列名读取，跳过第一行标题
            df = pd.read_excel(self.excel_path, header=0, names=["name", "_", "remark"])
        except Exception as e:
            print(f"读取Excel失败: {e}")
            self.finished.emit(0, 0, False)
            return

        # 用 name 作为索引（self.folders_data 中已有）
        existing_items = {item.get("name", ""): item for item in self.folders_data}

        # 获取A列非空数据（排除空值）
        valid_rows = df[~df["name"].isna() & df["name"].astype(str).str.strip().ne("")]
        total_names = len(valid_rows)  # 有效name总数（已排除空值）

        if total_names == 0:
            self.finished.emit(0, 0, False)
            return

        # 初始进度设置为3%
        self.progress_changed.emit(3, "开始处理...")

        for i, (idx, row) in enumerate(valid_rows.iterrows()):
            # 检查是否需要停止
            if self.should_stop:
                was_cancelled = True
                break

            name = str(row["name"]).strip()
            remark = str(row["remark"]).strip() if not pd.isna(row["remark"]) else ""

            json_written = False  # 标记是否生成了 JSON

            if name in existing_items:
                item = existing_items[name]
                item["remark"] = remark

                # 生成 JSON 文件到【已修】文件夹
                folder_path = item.get("path", "")
                folder_name = item.get("name", "未知文件夹")
                if folder_path:
                    try:
                        # 再次检查是否需要停止（在文件操作前）
                        if self.should_stop:
                            was_cancelled = True
                            break

                        fixed_folder_path = os.path.join(folder_path, "已修")
                        os.makedirs(fixed_folder_path, exist_ok=True)
                        safe_name = "".join(c for c in folder_name if c not in "\\/:*?\"<>|")
                        json_file_path = os.path.join(fixed_folder_path, f"{safe_name}_产品信息.json")
                        json_data = {
                            "name": folder_name,
                            "remark": remark,
                        }
                        with open(json_file_path, "w", encoding="utf-8") as f:
                            json.dump(json_data, f, ensure_ascii=False, indent=2)
                        json_written = True
                    except Exception as e:
                        print(f"生成JSON失败: {folder_path} -> {e}")

            # 更新计数
            if json_written:
                updated_count += 1
            else:
                skipped_count += 1

            # 更新进度 - 从3%开始到100%
            start_percent = 3
            end_percent = 100
            progress_range = end_percent - start_percent

            percent = int(start_percent + ((i + 1) / total_names * progress_range))
            self.progress_changed.emit(percent, name)

        # 如果没有被取消，确保进度达到100%
        if not was_cancelled:
            self.progress_changed.emit(100, "处理完成")

        # 完成时发射信号
        self.finished.emit(updated_count, skipped_count, was_cancelled)

# -------------------- 子线程 生成原图证明文件 --------------------
class ZipGeneratorThread(QThread):
    """压缩包生成线程"""
    progress_updated = pyqtSignal(int)  # 进度更新信号
    task_completed = pyqtSignal(str, str)  # 单个任务完成信号 (folder_name, result)
    all_completed = pyqtSignal(list)  # 所有任务完成信号
    error_occurred = pyqtSignal(str, str)  # 错误信号 (folder_name, error_message)
    current_task = pyqtSignal(str, str)  # 当前任务信号 (task_type, detail)
    # 新增：进度文本更新信号 (current_index, total_count, folder_name, task_detail)
    progress_text_updated = pyqtSignal(int, int, str, str)
    
    def __init__(self, folders_data, proof_file_path, save_directory, temp_dir):
        super().__init__()
        self.folders_data = folders_data  # [(folder_name, folder_path), ...]
        self.proof_file_path = proof_file_path
        self.save_directory = save_directory
        self.temp_dir = temp_dir  # 使用指定的临时目录
        self.results = []
        self.should_stop = False  # 停止标志
        self.last_progress = 3  # 记录上次发送的进度，初始为3%
    
    def stop_processing(self):
        """停止压缩处理"""
        self.should_stop = True
    
    def run(self):
        """在后台线程中生成压缩包"""
        total_tasks = len(self.folders_data)
        
        # 初始化进度为3%
        self.progress_updated.emit(3)
        
        for i, (folder_name, folder_path) in enumerate(self.folders_data):
            if self.should_stop:
                break
                
            try:
                # 检查文件夹是否存在
                if not os.path.exists(folder_path):
                    self.error_occurred.emit(folder_name, f"文件夹不存在: {folder_path}")
                    continue
                
                # 发送当前任务信息和进度文本
                current_index = i + 1
                self.current_task.emit("处理文件夹", f"正在处理: {folder_name} ({current_index}/{total_tasks})")
                self.progress_text_updated.emit(current_index, total_tasks, folder_name, "开始处理")
                
                # 生成压缩包路径
                zip_name = f"{folder_name}.zip"
                zip_path = os.path.join(self.save_directory, zip_name).replace('/', '\\')
                
                # 创建压缩包（传递任务索引用于进度计算）
                self.create_single_zip_with_progress(folder_name, folder_path, zip_path, i, total_tasks)
                
                if not self.should_stop:
                    self.task_completed.emit(folder_name, "成功")
                    self.results.append((folder_name, zip_path, "成功"))
                    # 发送完成状态的进度文本
                    self.progress_text_updated.emit(current_index, total_tasks, folder_name, "处理完成")
                
            except Exception as e:
                error_msg = str(e)
                self.error_occurred.emit(folder_name, error_msg)
                self.results.append((folder_name, "", f"失败: {error_msg}"))
                # 发送错误状态的进度文本
                current_index = i + 1
                self.progress_text_updated.emit(current_index, total_tasks, folder_name, f"处理失败: {error_msg}")
        
        if not self.should_stop:
            # 所有任务完成，设置进度为100%
            self.progress_updated.emit(100)
            self.all_completed.emit(self.results)
    
    def create_single_zip_with_progress(self, folder_name, folder_path, zip_path, task_index, total_tasks):
        """创建单个压缩包并提供进度反馈"""
        work_dir = os.path.join(self.temp_dir, f"work_{folder_name}").replace('/', '\\')
        os.makedirs(work_dir, exist_ok=True)

        try:
            current_index = task_index + 1
            
            # 步骤1: 统计文件数量（占当前任务的5%）
            self.current_task.emit("统计文件", f"统计 {folder_name} 中的文件数量...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "统计文件数量")
            total_files = self.count_files_in_directory(folder_path)
            self.update_task_progress(task_index, total_tasks, 0.05)  # 5%
            
            if self.should_stop:
                return
            
            # 在 work_dir 下直接放子文件夹内容
            temp_folder_path = work_dir
            os.makedirs(temp_folder_path, exist_ok=True)

            # 步骤2: 复制子文件夹（占当前任务的20%）
            self.current_task.emit("复制文件", f"复制 {folder_name} 的子文件夹...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "复制子文件夹")
            self.copy_subfolders_only_with_progress(folder_path, temp_folder_path, task_index, total_tasks, 0.05, 0.25)
            
            if self.should_stop:
                return

            # 步骤3: 复制声明文件（占当前任务的5%）
            self.current_task.emit("复制声明", f"复制原图声明文件...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "复制声明文件")
            proof_filename = os.path.basename(self.proof_file_path)
            temp_proof_path = os.path.join(temp_folder_path, proof_filename).replace('/', '\\')
            shutil.copy2(self.proof_file_path, temp_proof_path)
            self.update_task_progress(task_index, total_tasks, 0.3)  # 30%
            
            if self.should_stop:
                return

            # 步骤4: 压缩文件（占当前任务的70%）
            self.current_task.emit("压缩文件", f"正在压缩 {folder_name}...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "正在压缩")
            self.create_zip_file_with_progress(work_dir, zip_path, folder_name, task_index, total_tasks, 0.3, 1.0, total_files)

        finally:
            if os.path.exists(work_dir):
                shutil.rmtree(work_dir, ignore_errors=True)
    
    def count_files_in_directory(self, directory_path):
        """统计目录中的文件总数"""
        total_files = 0
        try:
            for root, dirs, files in os.walk(directory_path):
                if self.should_stop:
                    break
                total_files += len(files)
        except Exception as e:
            print(f"警告: 无法统计目录文件数量 {directory_path}: {e}")
            return 1  # 返回1避免除零错误
        
        return max(total_files, 1)  # 确保至少为1
    
    def copy_subfolders_only_with_progress(self, source_path, target_path, task_index, total_tasks, start_progress, end_progress):
        """只复制子文件夹，不复制文件，并提供进度反馈"""
        try:
            items = [item for item in os.listdir(source_path) 
                    if os.path.isdir(os.path.join(source_path, item))]
            
            if not items:
                self.update_task_progress(task_index, total_tasks, end_progress)
                return
            
            for i, item in enumerate(items):
                if self.should_stop:
                    break
                    
                source_item_path = os.path.join(source_path, item).replace('/', '\\')
                target_item_path = os.path.join(target_path, item).replace('/', '\\')
                
                if os.path.isdir(source_item_path):
                    # 复制整个子文件夹
                    shutil.copytree(source_item_path, target_item_path)
                    
                    # 更新进度
                    progress = start_progress + (end_progress - start_progress) * (i + 1) / len(items)
                    self.update_task_progress(task_index, total_tasks, progress)
                    
        except Exception as e:
            raise Exception(f"复制子文件夹时出错: {str(e)}")
    
    def create_zip_file_with_progress(self, source_folder, zip_path, folder_name, task_index, total_tasks, start_progress, end_progress, estimated_files):
        """创建压缩包文件，包含完整的文件夹结构，并提供进度反馈"""
        try:
            processed_files = 0
            
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as zipf:
                for root, dirs, files in os.walk(source_folder):
                    if self.should_stop:
                        break
                        
                    relative_root = os.path.relpath(root, source_folder).replace('/', '\\')
                    
                    for file in files:
                        if self.should_stop:
                            break
                            
                        file_path = os.path.join(root, file).replace('/', '\\')
                        try:
                            if relative_root == '.':
                                arcname = os.path.join(folder_name, file).replace('/', '\\')
                            else:
                                arcname = os.path.join(folder_name, relative_root, file).replace('/', '\\')
                            zipf.write(file_path, arcname)
                            processed_files += 1
                            
                            # 计算压缩进度，每处理10个文件更新一次进度
                            if processed_files % 10 == 0 or processed_files == estimated_files:
                                if estimated_files > 0:
                                    file_progress = min(processed_files / estimated_files, 1.0)
                                    current_progress = start_progress + (end_progress - start_progress) * file_progress
                                    self.update_task_progress(task_index, total_tasks, current_progress)
                                    
                        except Exception as e_file:
                            print(f"压缩文件出错: {file_path} -> {str(e_file)}")
                            raise Exception(f"压缩文件出错: {file_path} -> {str(e_file)}")
                    
                    # 处理空文件夹
                    if not files and not dirs:
                        if self.should_stop:
                            break
                            
                        if relative_root == '.':
                            folder_arcname = folder_name + '\\'
                        else:
                            folder_arcname = os.path.join(folder_name, relative_root).replace('/', '\\') + '\\'
                        try:
                            zipf.writestr(folder_arcname, '')
                        except Exception as e_folder:
                            print(f"压缩空文件夹出错: {folder_arcname} -> {str(e_folder)}")
                            raise Exception(f"压缩空文件夹出错: {folder_arcname} -> {str(e_folder)}")
            
            # 确保压缩完成时进度达到当前任务的结束进度
            if not self.should_stop:
                self.update_task_progress(task_index, total_tasks, end_progress)
                
        except Exception as e:
            raise Exception(f"创建压缩包时出错: {str(e)}")
    
    def update_task_progress(self, task_index, total_tasks, task_progress):
        """更新任务进度 - 确保进度单调递增"""
        if self.should_stop:
            return
            
        # 计算总体进度：从3%开始，到100%结束
        start_percent = 3
        end_percent = 100
        progress_range = end_percent - start_percent
        
        # 每个任务在总进度中占用的比例
        task_weight = progress_range / total_tasks
        
        # 计算当前总体进度
        base_progress = task_index * task_weight  # 前面已完成任务的进度
        current_task_progress = task_progress * task_weight  # 当前任务的进度
        overall_progress = int(start_percent + base_progress + current_task_progress)
        
        # 确保进度单调递增，不会出现跳动
        if overall_progress > self.last_progress:
            self.last_progress = overall_progress
            self.progress_updated.emit(overall_progress)
    
    def create_single_zip(self, folder_name, folder_path, zip_path):
        """创建单个压缩包（保持向后兼容）"""
        # 为了向后兼容，调用带进度的版本
        self.create_single_zip_with_progress(folder_name, folder_path, zip_path, 0, 1)
    
    def copy_subfolders_only(self, source_path, target_path):
        """只复制子文件夹，不复制文件（保持向后兼容）"""
        self.copy_subfolders_only_with_progress(source_path, target_path, 0, 1, 0, 1)
        
    def create_zip_file(self, source_folder, zip_path, folder_name):
        """创建压缩包文件，包含完整的文件夹结构（保持向后兼容）"""
        estimated_files = self.count_files_in_directory(source_folder)
        self.create_zip_file_with_progress(source_folder, zip_path, folder_name, 0, 1, 0, 1, estimated_files)

class FolderScanner(QThread):
    folder_found = pyqtSignal(str, str, str, str, str, str)  # name, path, thumb, remark, add_date, modify_date
    scan_finished = pyqtSignal(int, int)
    update_status = pyqtSignal(str)

    def __init__(self, root_path, search_term, added_paths=None):
        super().__init__()
        self.root_path = root_path
        self.search_term = search_term.lower()
        self.found_count = 0
        self.skipped_count = 0
        self.scanned_paths = set()
        self.added_paths = added_paths or set()

    def run(self):
        self._scan_directory(self.root_path)
        self.scan_finished.emit(self.found_count, self.skipped_count)

    def _scan_directory(self, path):
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item).replace('/', '\\')
                if os.path.isdir(item_path):
                    folder_name = os.path.basename(item_path)
                    self.update_status.emit(
                        f"<span style='color: #ffdb29;'>●</span> 扫描中：{folder_name}（已写入：{self.found_count} 个 / 已跳过：{self.skipped_count} 个）"
                    )

                    if item_path in self.added_paths:
                        self.skipped_count += 1
                        continue

                    search_terms = self.search_term.split()
                    if any(term.lower() in item.lower() for term in search_terms):
                        if item_path not in self.scanned_paths:
                            self.scanned_paths.add(item_path)

                            fixed_folder = os.path.join(item_path, "已修")
                            thumbnail_path = ""
                            remark = ""

                            if os.path.exists(fixed_folder):
                                thumbnail_path = self._generate_thumbnail(item_path, item)
                                safe_name = "".join(c for c in item if c not in "\\/:*?\"<>|")
                                json_file_path = os.path.join(fixed_folder, f"{safe_name}_产品信息.json")
                                if os.path.exists(json_file_path):
                                    try:
                                        with open(json_file_path, 'r', encoding='utf-8') as f:
                                            data = json.load(f)
                                            remark = data.get("remark", "")
                                    except Exception:
                                        remark = ""

                            # 计算添加日期和修改日期
                            add_timestamp = os.path.getctime(item_path)
                            modify_timestamp = os.path.getmtime(item_path)
                            add_date = datetime.fromtimestamp(add_timestamp).strftime("%Y-%m-%d %H:%M:%S")
                            modify_date = datetime.fromtimestamp(modify_timestamp).strftime("%Y-%m-%d %H:%M:%S")

                            # 发射信号
                            self.folder_found.emit(item, item_path, thumbnail_path, remark, add_date, modify_date)
                            self.found_count += 1

                        continue

                    self._scan_directory(item_path)

        except (PermissionError, OSError):
            pass

    def _generate_thumbnail(self, folder_path, folder_name):
        from PIL import Image
        thumbnail_dir = os.path.join(os.getcwd(), "thumbnail")
        os.makedirs(thumbnail_dir, exist_ok=True)
        fixed_folder = os.path.join(folder_path, "已修")
        if not os.path.exists(fixed_folder):
            return ""

        for file in os.listdir(fixed_folder):
            if file.lower().endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                image_path = os.path.join(fixed_folder, file)
                try:
                    img = Image.open(image_path).convert("RGBA")
                    img = img.resize((400, 400), Image.Resampling.LANCZOS)
                    save_path = os.path.join(thumbnail_dir, f"{folder_name}.png")
                    img.save(save_path, "PNG")
                    return save_path
                except Exception as e:
                    print(f"生成缩略图失败: {e}")
                    return ""
        return ""

# ------------------ 可点击 QLabel ------------------
class ClickableLabel(QLabel):
    clicked = pyqtSignal()
    def mousePressEvent(self, event):
        self.clicked.emit()

# ------------------ 预览窗口 ------------------
class NavigationButton(QPushButton):
    def __init__(self, direction, parent=None):
        super().__init__(parent)
        self.direction = direction  # 'left' or 'right'
        self.setFixedSize(40, 60)  # 改小按钮尺寸
        self.setStyleSheet("""
            QPushButton {
                background-color: rgba(0, 0, 0, 100);
                border: none;
                border-radius: 6px;
                color: white;
                font-size: 20px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: rgba(0, 0, 0, 150);
            }
            QPushButton:pressed {
                background-color: rgba(0, 0, 0, 200);
            }
        """)
        
        # 设置箭头文字
        if direction == 'left':
            self.setText('‹')
        else:
            self.setText('›')
        
        # 初始隐藏
        self.hide()

class ZoomableLabel(QLabel):
    # 添加切换图片的信号
    imageChanged = pyqtSignal(str)  # 发送当前图片路径
    
    def __init__(self, image_path):
        super().__init__()
        self.current_image_path = image_path
        self.image_list = []
        self.current_index = 0
        
        # 获取同目录下的所有图片文件
        self._load_image_list()
        
        self.pixmap_orig = QPixmap(image_path)
        self.setPixmap(self.pixmap_orig)
        self.setAlignment(Qt.AlignCenter)
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0)
        self.last_pos = None
        self.setMouseTracking(True)
        self.setMinimumSize(1, 1)
        
        # 创建左右导航按钮
        self.left_button = NavigationButton('left', self)
        self.right_button = NavigationButton('right', self)
        
        # 连接按钮信号
        self.left_button.clicked.connect(self.prev_image)
        self.right_button.clicked.connect(self.next_image)
        
        # 创建定时器用于隐藏按钮
        self.hide_timer = QTimer()
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide_buttons)
        self.hide_delay = 2000  # 2秒后隐藏
        
        # 按钮显示区域的偏移距离
        self.button_area_offset = 30  # 按钮周围30像素范围内都会显示按钮
    
    def _load_image_list(self):
        """加载同目录下的所有图片文件"""
        if not os.path.exists(self.current_image_path):
            return
            
        image_dir = os.path.dirname(self.current_image_path)
        image_name = os.path.basename(self.current_image_path)
        
        # 支持的图片格式
        image_extensions = ['.jpg', '.jpeg', '.png', '.bmp', '.gif', '.tiff', '.webp']
        
        try:
            all_files = os.listdir(image_dir)
            # 筛选图片文件并排序
            self.image_list = sorted([
                f for f in all_files 
                if os.path.splitext(f.lower())[1] in image_extensions
            ])
            
            # 找到当前图片的索引
            if image_name in self.image_list:
                self.current_index = self.image_list.index(image_name)
        except Exception as e:
            print(f"加载图片列表时出错: {e}")
    
    def load_image(self, image_path):
        """加载新图片"""
        if os.path.exists(image_path):
            # 记录当前鼠标位置
            current_mouse_pos = self.mapFromGlobal(QCursor.pos())
            
            self.current_image_path = image_path
            self.pixmap_orig = QPixmap(image_path)
            # 重置缩放和偏移
            self.scale_factor = 1.0
            self.offset = QPoint(0, 0)
            self.update_pixmap()
            # 发送图片改变信号
            self.imageChanged.emit(image_path)
            
            # 延迟检查鼠标位置，确保按钮位置已更新
            QTimer.singleShot(50, lambda: self.check_mouse_in_button_area(current_mouse_pos))
    
    def prev_image(self):
        """切换到上一张图片"""
        if len(self.image_list) <= 1:
            return
        
        # 记录按钮点击，暂时停止隐藏定时器
        self.hide_timer.stop()
        
        self.current_index = (self.current_index - 1) % len(self.image_list)
        image_dir = os.path.dirname(self.current_image_path)
        new_path = os.path.join(image_dir, self.image_list[self.current_index])
        self.load_image(new_path)
    
    def next_image(self):
        """切换到下一张图片"""
        if len(self.image_list) <= 1:
            return
        
        # 记录按钮点击，暂时停止隐藏定时器
        self.hide_timer.stop()
        
        self.current_index = (self.current_index + 1) % len(self.image_list)
        image_dir = os.path.dirname(self.current_image_path)
        new_path = os.path.join(image_dir, self.image_list[self.current_index])
        self.load_image(new_path)
    
    def show_buttons(self):
        """显示导航按钮"""
        if len(self.image_list) > 1:  # 只有多张图片时才显示按钮
            self.left_button.show()
            self.right_button.show()
        
        # 停止隐藏定时器
        self.hide_timer.stop()
    
    def hide_buttons(self):
        """隐藏导航按钮"""
        self.left_button.hide()
        self.right_button.hide()
    
    def check_mouse_in_button_area(self, mouse_pos=None):
        """检查鼠标是否在按钮区域内并相应显示/隐藏按钮"""
        if mouse_pos is None:
            mouse_pos = self.mapFromGlobal(QCursor.pos())
        
        if self.is_mouse_in_button_area(mouse_pos):
            self.show_buttons()
        else:
            # 如果不在按钮区域，启动隐藏定时器
            if not self.hide_timer.isActive():
                self.hide_timer.start(500)
    
    def update_button_positions(self):
        """更新按钮位置"""
        # 左按钮位置
        self.left_button.move(15, (self.height() - self.left_button.height()) // 2)
        # 右按钮位置
        self.right_button.move(
            self.width() - self.right_button.width() - 15,
            (self.height() - self.right_button.height()) // 2
        )
        
        # 按钮位置更新后，检查鼠标是否仍在按钮区域
        if self.underMouse():  # 只有当鼠标在widget内才检查
            self.check_mouse_in_button_area()
    
    def resizeEvent(self, event):
        """窗口大小改变时更新按钮位置"""
        super().resizeEvent(event)
        self.update_button_positions()
        self.update_pixmap()
    
    def get_button_detection_rects(self):
        """获取按钮检测区域（按钮周围扩展一定范围）"""
        left_btn_rect = self.left_button.geometry()
        right_btn_rect = self.right_button.geometry()
        
        # 扩展检测区域
        offset = self.button_area_offset
        left_detection_rect = left_btn_rect.adjusted(-offset, -offset, offset, offset)
        right_detection_rect = right_btn_rect.adjusted(-offset, -offset, offset, offset)
        
        return left_detection_rect, right_detection_rect
    
    def is_mouse_in_button_area(self, pos):
        """检查鼠标是否在按钮检测区域内"""
        left_rect, right_rect = self.get_button_detection_rects()
        return left_rect.contains(pos) or right_rect.contains(pos)
    
    def enterEvent(self, event):
        """鼠标进入时检查是否在按钮区域"""
        super().enterEvent(event)
        # 不再自动显示按钮，只有在按钮区域内才显示
    
    def leaveEvent(self, event):
        """鼠标离开时隐藏按钮"""
        super().leaveEvent(event)
        self.hide_timer.start(200)  # 0.2秒后隐藏
    
    def mouseMoveEvent(self, event):
        """鼠标移动时的处理"""
        mouse_pos = event.pos()
        
        # 检查鼠标是否在按钮检测区域并更新按钮状态
        self.check_mouse_in_button_area(mouse_pos)
        
        # 原有的拖拽功能
        if self.last_pos is not None:
            delta = event.pos() - self.last_pos
            self.offset += delta
            self.last_pos = event.pos()
            self.update_pixmap()
    
    def keyPressEvent(self, event):
        """键盘事件：支持左右箭头键和空格键切换"""
        if event.key() == Qt.Key_Left or event.key() == Qt.Key_A:
            self.prev_image()
        elif event.key() == Qt.Key_Right or event.key() == Qt.Key_D or event.key() == Qt.Key_Space:
            self.next_image()
        else:
            super().keyPressEvent(event)
    
    def wheelEvent(self, event):
        # 鼠标滚轮缩放
        delta = event.angleDelta().y()
        old_factor = self.scale_factor
        if delta > 0:
            self.scale_factor *= 1.1
        else:
            self.scale_factor *= 0.9
        # 限制缩放比例
        self.scale_factor = max(0.1, min(self.scale_factor, 5.0))
        
        # 获取鼠标在 QLabel 的位置
        cursor_pos = event.pos()
        
        # 计算缩放后偏移量，使鼠标位置保持不动
        if old_factor != self.scale_factor:
            self.offset = cursor_pos - (cursor_pos - self.offset) * (self.scale_factor / old_factor)
        self.update_pixmap()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = event.pos()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.last_pos = None

    def update_pixmap(self):
        # 缩放图片
        scaled_pixmap = self.pixmap_orig.scaled(
            self.pixmap_orig.size() * self.scale_factor,
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation
        )
        # 在 QLabel 上显示偏移后的图片
        pixmap_with_offset = QPixmap(self.size())
        pixmap_with_offset.fill(Qt.transparent)
        
        painter = QPainter(pixmap_with_offset)
        painter.drawPixmap(self.offset, scaled_pixmap)
        painter.end()
        
        self.setPixmap(pixmap_with_offset)

class PreviewDialog(QDialog):
    def __init__(self, image_path, main_window=None, offset=QPoint(50, 50)):
        super().__init__(parent=None)
        self.setWindowTitle("预览")
        
        # 根据图片大小调整窗口大小
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            # 获取屏幕大小
            screen = QApplication.primaryScreen().geometry()
            max_width = int(screen.width() * 0.8)
            max_height = int(screen.height() * 0.8)
            
            # 计算合适的窗口大小，保持图片比例
            img_width = pixmap.width()
            img_height = pixmap.height()
            
            if img_width > max_width or img_height > max_height:
                # 需要缩放
                scale_w = max_width / img_width
                scale_h = max_height / img_height
                scale = min(scale_w, scale_h)
                
                window_width = int(img_width * scale)
                window_height = int(img_height * scale)
            else:
                # 不需要缩放
                window_width = img_width
                window_height = img_height
            
            # 设置最小尺寸
            window_width = max(300, window_width)
            window_height = max(200, window_height)
            
            self.resize(window_width, window_height)
        else:
            # 如果图片加载失败，使用默认大小
            self.resize(800, 600)
        
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.offset = offset
        self.main_window = main_window
        
        if main_window:
            # 设置图标
            self.setWindowIcon(main_window.windowIcon())
            # 在初始化阶段就设定位置
            main_geom = main_window.frameGeometry()
            main_center = main_geom.center()
            dialog_geom = self.frameGeometry()
            dialog_geom.moveCenter(main_center)
            self.move(dialog_geom.topLeft() + self.offset)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)  # 移除边距让按钮可以贴边显示
        
        self.label = ZoomableLabel(image_path)
        layout.addWidget(self.label)
        
        # 连接图片改变信号来更新窗口标题
        self.label.imageChanged.connect(self.update_title)
        
        # 设置焦点，使键盘事件生效
        self.setFocusPolicy(Qt.StrongFocus)
        self.label.setFocusPolicy(Qt.StrongFocus)
    
    def update_title(self, image_path):
        """更新窗口标题显示当前图片名"""
        image_name = os.path.basename(image_path)
        current_index = self.label.current_index + 1
        total_images = len(self.label.image_list)
        self.setWindowTitle(f"预览 - {image_name} ({current_index}/{total_images})")
        
        # 图片改变时可能需要调整窗口大小，延迟更新按钮位置
        QTimer.singleShot(10, self.label.update_button_positions)
    
    def keyPressEvent(self, event):
        """将键盘事件转发给 ZoomableLabel"""
        self.label.keyPressEvent(event)
    
    def showEvent(self, event):
        super().showEvent(event)
        if self.main_window:
            main_geom = self.main_window.frameGeometry()
            main_center = main_geom.center()
            dialog_geom = self.frameGeometry()
            dialog_geom.moveCenter(main_center)
            self.move(dialog_geom.topLeft() + self.offset)
        
        # 初始化标题
        self.update_title(self.label.current_image_path)

# ==================== 高性能虚拟列表 ====================
class HighPerformanceVirtualList(QAbstractScrollArea):
    """高性能虚拟列表 - 专为大数据量设计"""
    
    # 自定义信号
    itemClicked = pyqtSignal(int, dict)  # 点击信号：(索引, 数据)
    itemDoubleClicked = pyqtSignal(int, dict)  # 双击信号
    itemRightClicked = pyqtSignal(int, dict, QPoint)  # 右键信号
    selectionChanged = pyqtSignal(set)  # 选择状态改变信号：(选中的索引集合)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        
        # 基本配置
        self.item_height = 89  # 每个项目的高度
        self.items_data = []   # 存储所有数据
        
        # Widget池 - 核心优化，只创建少量widget循环使用
        self.visible_widgets = {}  # 当前可见的widget {index: widget}
        self.widget_pool = []      # widget对象池
        self.pool_size = 25        # 池大小，根据需要调整
        
        # 缩略图异步加载
        self.thumbnail_executor = ThreadPoolExecutor(max_workers=3)
        self.thumbnail_cache = {}     # 缩略图缓存 {path: pixmap}
        self.loading_thumbnails = set()  # 正在加载的缩略图路径
        
        # 选中状态管理
        self.selected_indices = set()
        self.current_index = -1
        
        # 多选模式设置
        self.multi_select_enabled = True  # 是否启用多选
        
        # 初始化
        self._init_widget_pool()
        self._setup_scrollbars()
        self._setup_styling()
        
        # 性能监控
        self.performance_stats = {
            'render_count': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
    
    def _init_widget_pool(self):
        """初始化widget对象池"""
        for _ in range(self.pool_size):
            widget = VirtualFolderItemWidget()
            widget.hide()  # 初始隐藏
            # 连接widget的信号到虚拟列表
            widget.clicked.connect(self._on_widget_clicked)
            widget.double_clicked.connect(self._on_widget_double_clicked)
            widget.right_clicked.connect(self._on_widget_right_clicked)
            self.widget_pool.append(widget)

    # 支持 Home/End/Ctrl+A
    def keyPressEvent(self, event):
        """处理键盘事件"""
        if event.key() == Qt.Key_Home:
            # 滚动到顶部
            self.verticalScrollBar().setValue(0)
            # 选中第一项（如果有数据）
            if self.items_data:
                if not (event.modifiers() & Qt.ShiftModifier):
                    self.selected_indices.clear()
                self.current_index = 0
                self.selected_indices.add(0)
                self._update_visible_items()
                self.selectionChanged.emit(self.selected_indices.copy())
                
        elif event.key() == Qt.Key_End:
            # 滚动到底部
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            # 选中最后一项（如果有数据）
            if self.items_data:
                last_index = len(self.items_data) - 1
                if not (event.modifiers() & Qt.ShiftModifier):
                    self.selected_indices.clear()
                self.current_index = last_index
                self.selected_indices.add(last_index)
                self._update_visible_items()
                self.selectionChanged.emit(self.selected_indices.copy())
                
        elif event.key() == Qt.Key_A and event.modifiers() & Qt.ControlModifier:
            # Ctrl+A 全选
            self.select_all()
            
        elif event.key() == Qt.Key_Escape:
            # Esc 取消所有选择
            self.clear_selection()
            
        elif event.key() in (Qt.Key_Up, Qt.Key_Down):
            # 上下箭头键导航
            self._handle_arrow_navigation(event)
            
        else:
            super().keyPressEvent(event)
    
    def _handle_arrow_navigation(self, event):
        """处理箭头键导航"""
        if not self.items_data:
            return
            
        old_current = self.current_index
        
        if event.key() == Qt.Key_Up:
            self.current_index = max(0, self.current_index - 1)
        elif event.key() == Qt.Key_Down:
            self.current_index = min(len(self.items_data) - 1, self.current_index + 1)
        
        if self.current_index != old_current:
            # 滚动到当前项
            self._scroll_to_item(self.current_index)
            
            # 处理选择
            if event.modifiers() & Qt.ShiftModifier:
                # Shift + 箭头：范围选择
                if self.selected_indices:
                    # 扩展选择范围
                    start = min(min(self.selected_indices), self.current_index)
                    end = max(max(self.selected_indices), self.current_index)
                    self.selected_indices = set(range(start, end + 1))
                else:
                    self.selected_indices.add(self.current_index)
            elif event.modifiers() & Qt.ControlModifier:
                # Ctrl + 箭头：不改变选择，只移动焦点
                pass
            else:
                # 普通箭头：单选
                self.selected_indices = {self.current_index}
            
            self._update_visible_items()
            self.selectionChanged.emit(self.selected_indices.copy())
    
    def _scroll_to_item(self, index):
        """滚动到指定项目"""
        if not (0 <= index < len(self.items_data)):
            return
            
        item_y = index * self.item_height
        viewport_height = self.viewport().height()
        current_scroll = self.verticalScrollBar().value()
        
        # 如果项目不在可见区域，则滚动
        if item_y < current_scroll:
            # 项目在上方，滚动到项目顶部
            self.verticalScrollBar().setValue(item_y)
        elif item_y + self.item_height > current_scroll + viewport_height:
            # 项目在下方，滚动到项目底部可见
            self.verticalScrollBar().setValue(item_y + self.item_height - viewport_height)

    def select_all(self):
        """全选所有项目"""
        if not self.items_data or not self.multi_select_enabled:
            return
            
        old_selection = self.selected_indices.copy()
        self.selected_indices = set(range(len(self.items_data)))
        
        # 如果没有当前项，设置第一项为当前项
        if self.current_index == -1:
            self.current_index = 0
            
        # 更新UI
        self._update_visible_items()
        
        # 发射选择改变信号
        if old_selection != self.selected_indices:
            self.selectionChanged.emit(self.selected_indices.copy())
    
    def clear_selection(self):
        """清空所有选择"""
        if not self.selected_indices:
            return
            
        old_selection = self.selected_indices.copy()
        self.selected_indices.clear()
        self.current_index = -1
        
        # 更新UI
        self._update_visible_items()
        
        # 发射选择改变信号
        if old_selection:
            self.selectionChanged.emit(self.selected_indices.copy())
    
    def select_items(self, indices):
        """选择指定的项目"""
        if not self.multi_select_enabled:
            # 单选模式下只选择第一个
            indices = indices[:1] if indices else []
            
        old_selection = self.selected_indices.copy()
        self.selected_indices = set(i for i in indices if 0 <= i < len(self.items_data))
        
        # 设置当前项
        if self.selected_indices:
            self.current_index = min(self.selected_indices)
        else:
            self.current_index = -1
            
        # 更新UI
        self._update_visible_items()
        
        # 发射选择改变信号
        if old_selection != self.selected_indices:
            self.selectionChanged.emit(self.selected_indices.copy())
    
    def get_selected_indices(self):
        """获取选中的索引列表"""
        return sorted(list(self.selected_indices))
    
    def get_selected_data(self):
        """获取选中项的数据列表"""
        return [self.items_data[i] for i in sorted(self.selected_indices) if 0 <= i < len(self.items_data)]
    
    def set_multi_select_enabled(self, enabled):
        """设置是否启用多选模式"""
        self.multi_select_enabled = enabled
        if not enabled and len(self.selected_indices) > 1:
            # 切换到单选模式时，只保留第一个选中项
            first_selected = min(self.selected_indices) if self.selected_indices else -1
            if first_selected >= 0:
                self.selected_indices = {first_selected}
                self.current_index = first_selected
            else:
                self.selected_indices.clear()
                self.current_index = -1
            self._update_visible_items()
            self.selectionChanged.emit(self.selected_indices.copy())

    # 自动获取焦点
    def mousePressEvent(self, event):
        self.setFocus()
        super().mousePressEvent(event)

    def wheelEvent(self, event):
        self.setFocus()
        super().wheelEvent(event)
    
    def _setup_scrollbars(self):
        """设置滚动条"""
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll)
        
    def _setup_styling(self):
        """设置样式"""
        self.setStyleSheet("""
            QAbstractScrollArea {
                background-color: black;
                border: 1px solid #ddd;
            }
        """)
    
    def set_data(self, data_list):
        """设置数据 - 核心方法，瞬间完成"""
        self.items_data = data_list[:]  # 复制数据
        self.selected_indices.clear()
        self.current_index = -1
        
        self._update_scrollbar_range()
        self._update_visible_items()
        self.selectionChanged.emit(self.selected_indices.copy())
    
    def _update_scrollbar_range(self):
        """更新滚动条范围"""
        if not self.items_data:
            self.verticalScrollBar().setRange(0, 0)
            return
            
        total_height = len(self.items_data) * self.item_height
        viewport_height = self.viewport().height()
        max_scroll = max(0, total_height - viewport_height)
        
        self.verticalScrollBar().setRange(0, max_scroll)
        self.verticalScrollBar().setPageStep(viewport_height)
        self.verticalScrollBar().setSingleStep(self.item_height)
    
    def _on_scroll(self):
        """滚动事件处理"""
        self._update_visible_items()
    
    def _update_visible_items(self):
        """更新可见项目 - 核心渲染逻辑"""
        self.performance_stats['render_count'] += 1

        if not self.items_data:
            self._clear_all_widgets()
            return

        viewport_rect = self.viewport().rect()
        scroll_value = self.verticalScrollBar().value()

        # 可见范围 + 缓冲
        buffer_size = 3
        start_index = max(0, scroll_value // self.item_height - buffer_size)
        end_index = min(len(self.items_data), (scroll_value + viewport_rect.height()) // self.item_height + buffer_size + 1)

        current_visible = set(range(start_index, end_index))
        old_visible = set(self.visible_widgets.keys())

        # 回收不可见widget
        for index in old_visible - current_visible:
            self._return_widget_to_pool(index)

        # 创建新可见widget
        for index in current_visible - old_visible:
            if 0 <= index < len(self.items_data):
                self._create_visible_widget(index)

        # 更新位置、状态和缩略图
        for index, widget in self.visible_widgets.items():
            y_pos = index * self.item_height - scroll_value
            widget.setGeometry(0, y_pos, viewport_rect.width(), self.item_height)
            widget.show()
            
            # 更新 widget 数据内容
            widget.update_data(self.items_data[index], index)
            
            widget.set_selected(index in self.selected_indices)
            widget.set_current(index == self.current_index)

            # 缩略图缓存立即显示
            thumbnail_path = self.items_data[index].get("thumbnail", "")
            if thumbnail_path in self.thumbnail_cache:
                widget.set_thumbnail(self.thumbnail_cache[thumbnail_path])
                self.performance_stats['cache_hits'] += 1

        # 异步加载未缓存的缩略图
        self._load_visible_thumbnails(start_index, end_index)
    
    def _create_visible_widget(self, index):
        """创建可见widget"""
        data = self.items_data[index]
        widget = self._get_widget_from_pool()
        widget.update_data(data, index)
        widget.setParent(self.viewport())

        # 如果缩略图已缓存，立即显示
        thumbnail_path = data.get("thumbnail", "")
        if thumbnail_path in self.thumbnail_cache:
            widget.set_thumbnail(self.thumbnail_cache[thumbnail_path])
            self.performance_stats['cache_hits'] += 1

        self.visible_widgets[index] = widget
    
    def _get_widget_from_pool(self):
        """从对象池获取widget"""
        if self.widget_pool:
            return self.widget_pool.pop()
        else:
            # 池空了，创建新的（正常情况不应该发生）
            widget = VirtualFolderItemWidget()
            widget.clicked.connect(self._on_widget_clicked)
            widget.double_clicked.connect(self._on_widget_double_clicked)
            widget.right_clicked.connect(self._on_widget_right_clicked)
            return widget
    
    def _return_widget_to_pool(self, index):
        """将widget返回对象池"""
        if index not in self.visible_widgets:
            return
            
        widget = self.visible_widgets.pop(index)
        widget.hide()
        widget.setParent(None)
        
        # 清理状态
        widget.clear_data()
        
        # 返回池中
        if len(self.widget_pool) < self.pool_size:
            self.widget_pool.append(widget)
    
    def _clear_all_widgets(self):
        """清空所有widget"""
        for index in list(self.visible_widgets.keys()):
            self._return_widget_to_pool(index)
    
    def _load_visible_thumbnails(self, start_index, end_index):
        """异步加载可见区域尚未缓存的缩略图"""
        for i in range(start_index, min(end_index, len(self.items_data))):
            if i not in self.visible_widgets:
                continue

            data = self.items_data[i]
            thumbnail_path = data.get("thumbnail", "")
            if not thumbnail_path or not os.path.exists(thumbnail_path):
                continue

            # 已缓存或正在加载则跳过
            if thumbnail_path in self.thumbnail_cache or thumbnail_path in self.loading_thumbnails:
                continue

            self.loading_thumbnails.add(thumbnail_path)
            self.thumbnail_executor.submit(self._load_thumbnail, i, thumbnail_path)
    
    def _load_thumbnail(self, index, thumbnail_path):
        """在后台线程加载缩略图"""
        try:
            pixmap = QPixmap(thumbnail_path)
            if not pixmap.isNull():
                scaled_pixmap = pixmap.scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                self.thumbnail_cache[thumbnail_path] = scaled_pixmap
                self.performance_stats['cache_misses'] += 1
                
                # 通知主线程更新UI
                QMetaObject.invokeMethod(self, "_update_thumbnail_ui", 
                                       Qt.QueuedConnection,
                                       Q_ARG(int, index),
                                       Q_ARG(str, thumbnail_path))
        except Exception as e:
            print(f"加载缩略图失败 {thumbnail_path}: {e}")
        finally:
            self.loading_thumbnails.discard(thumbnail_path)
    
    @pyqtSlot(int, str)
    def _update_thumbnail_ui(self, index, thumbnail_path):
        """在主线程更新缩略图UI"""
        if (index in self.visible_widgets and 
            thumbnail_path in self.thumbnail_cache):
            widget = self.visible_widgets[index]
            widget.set_thumbnail(self.thumbnail_cache[thumbnail_path])
            self.performance_stats['cache_hits'] += 1
    
    # ==================== 事件处理 ====================
    
    def _on_scroll(self):
        """滚动事件处理"""
        self._update_visible_items()
    
    def _on_widget_clicked(self, widget):
        """处理widget点击事件"""
        index = widget.get_index()
        if 0 <= index < len(self.items_data):
            self.current_index = index
            
            # 处理选中状态
            modifiers = QApplication.keyboardModifiers()
            if modifiers & Qt.ControlModifier:
                # Ctrl+点击：切换选中状态
                if index in self.selected_indices:
                    self.selected_indices.remove(index)
                else:
                    self.selected_indices.add(index)
            elif modifiers & Qt.ShiftModifier:
                # Shift+点击：范围选择
                if self.selected_indices:
                    start = min(self.selected_indices)
                    end = max(self.selected_indices)
                    self.selected_indices = set(range(min(start, index), max(end, index) + 1))
                else:
                    self.selected_indices = {index}
            else:
                # 普通点击：单选
                self.selected_indices = {index}
            
            self._update_visible_items()  # 刷新选中状态显示
            self.itemClicked.emit(index, self.items_data[index])

    def _on_widget_right_clicked(self, widget, pos):
        """右键点击时处理选中状态，并发射右键信号"""
        index = widget.get_index()
        if 0 <= index < len(self.items_data):
            # 如果当前只有一个或没有选中，则右键单选
            if len(self.selected_indices) <= 1:
                self.selected_indices = {index}
                self.current_index = index
                self._update_visible_items()  # 刷新选中状态显示

            # 发射右键信号（不管是多选还是单选都发射）
            global_pos = widget.mapToGlobal(pos)
            self.itemRightClicked.emit(index, self.items_data[index], global_pos)
   
    def _on_widget_double_clicked(self, widget):
        """处理widget双击事件"""
        index = widget.get_index()
        if 0 <= index < len(self.items_data):
            self.itemDoubleClicked.emit(index, self.items_data[index])
    
    def resizeEvent(self, event):
        """窗口大小改变事件"""
        super().resizeEvent(event)
        self._update_scrollbar_range()
        self._update_visible_items()
    
    def paintEvent(self, event):
        """绘制事件 - 基本为空，由widget自己绘制"""
        painter = QPainter(self.viewport())
        painter.fillRect(self.viewport().rect(), Qt.transparent)
    
    # ==================== 公共API ====================
    
    def get_selected_data(self):
        """获取选中的数据"""
        return [self.items_data[i] for i in self.selected_indices if 0 <= i < len(self.items_data)]
    
    def get_current_data(self):
        """获取当前数据"""
        if 0 <= self.current_index < len(self.items_data):
            return self.items_data[self.current_index]
        return None
    
    def clear_selection(self):
        """清空选择"""
        self.selected_indices.clear()
        self.current_index = -1
        self._update_visible_items()
    
    def select_all(self):
        """全选"""
        self.selected_indices = set(range(len(self.items_data)))
        self._update_visible_items()
    
    def scroll_to_item(self, index):
        """滚动到指定项目"""
        if 0 <= index < len(self.items_data):
            target_y = index * self.item_height
            self.verticalScrollBar().setValue(target_y)
    
    def get_performance_stats(self):
        """获取性能统计"""
        return self.performance_stats.copy()


# ==================== 虚拟列表专用的FolderItemWidget ====================
class VirtualFolderItemWidget(QWidget):
    """专为虚拟列表设计的文件夹项目widget"""
    
    # 自定义信号
    clicked = pyqtSignal(object)  # 传递widget自身
    double_clicked = pyqtSignal(object)
    right_clicked = pyqtSignal(object, QPoint)
    
    def __init__(self):
        super().__init__()
        self._index = -1
        self._data = {}
        self._selected = False
        self._current = False
        self._hovered = False  # 新增：hover状态
        self.preview_window = None
        
        self._setup_ui()
        
        # 启用鼠标追踪以获取hover事件
        self.setMouseTracking(True)
    
    def _setup_ui(self):
        """设置UI结构"""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        # 文件夹名称
        self.name_label = QLabel()
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse) # 允许鼠标托选复制
        self.name_label.setContentsMargins(15, 5, 5, 5)
        self.name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.name_label.setFixedWidth(100)
        layout.addWidget(self.name_label)

        # 缩略图容器
        self.icon_label = QLabel()
        self.icon_label.setFixedSize(70, 70)
        self.icon_label.setStyleSheet("border:1px solid #ccc; background-color: #f8f9fa;")
        self.icon_label.setAlignment(Qt.AlignCenter)
        self._set_default_icon()
        layout.addWidget(self.icon_label)

        # 备注信息区域
        info_layout = QVBoxLayout()
        info_layout.setContentsMargins(30, 5, 20, 5)
        info_layout.setSpacing(5)
        info_layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        
        self.remark_label = QLabel()
        self.remark_label.setTextInteractionFlags(Qt.TextSelectableByMouse) # 允许鼠标托选复制
        self.remark_label.setWordWrap(True)
        info_layout.addWidget(self.remark_label)

        layout.addStretch(1)
        layout.addLayout(info_layout)
        
        # 设置默认样式
        self._update_style()
    
    def _set_default_icon(self):
        """设置默认文件夹图标"""
        pixmap = QPixmap(70, 70)
        pixmap.fill(QColor("#f0f0f0"))
        painter = QPainter(pixmap)
        painter.setPen(QColor("#ccc"))
        painter.drawRect(0, 0, 69, 69)
        # 简单的文件夹图标
        painter.fillRect(20, 25, 30, 25, QColor("#ffd700"))
        painter.fillRect(20, 20, 15, 8, QColor("#ffd700"))
        painter.end()
        self.icon_label.setPixmap(pixmap)
    
    def update_data(self, data, index):
        """更新widget数据"""
        self._data = data
        self._index = index
        
        # 更新显示内容
        name = data.get("name", "未知文件夹")
        remark = data.get("remark", "")
        path = data.get("path", "")
        
        self.name_label.setText(name)
        self.remark_label.setText(remark)
        
        # 设置tooltip
        tooltip = f"路径: {path}"
        if remark:
            tooltip += f"\n备注: {remark}"
        self.setToolTip(tooltip)
        
        # 重置为默认图标，缩略图将异步加载
        self._set_default_icon()
    
    def clear_data(self):
        """清理数据时也要重置hover状态"""
        self._data = {}
        self._index = -1
        self._selected = False
        self._current = False
        self._hovered = False  # 重置hover状态
        self.name_label.setText("")
        self.remark_label.setText("")
        self.setToolTip("")
        self._set_default_icon()
        self._update_style()
    
    def set_thumbnail(self, pixmap):
        """设置缩略图"""
        self.icon_label.setPixmap(pixmap)
        # 连接预览功能
        self.icon_label.mousePressEvent = self._on_icon_clicked
    
    def _on_icon_clicked(self, event):
        """缩略图点击事件"""
        if event.button() == Qt.LeftButton and self._data.get("thumbnail"):
            self._show_preview()
    
    def _show_preview(self):
        """显示预览窗口"""
        thumbnail_path = self._data.get("thumbnail", "")
        if thumbnail_path and os.path.exists(thumbnail_path):
            main_window = QApplication.activeWindow()  
            self.preview_window = PreviewDialog(
                thumbnail_path, main_window=main_window, offset=QPoint(150, 170)
            )
            self.preview_window.show()
    
    def set_selected(self, selected):
        self._selected = selected
        self._update_style()
    
    def set_current(self, current):
        self._current = current
        self._update_style()
    
    def set_hovered(self, hovered):
        self._hovered = hovered
        self._update_style()
    
    def _update_style(self):
        """只更新文字颜色"""
        text_color = "#495057"
        
        self.name_label.setStyleSheet(f"color: {text_color}; background-color: transparent;")
        self.remark_label.setStyleSheet(f"color: {text_color}; background-color: transparent;")
        self.update()  # 刷新 widget，触发 paintEvent

    def paintEvent(self, event):
        """绘制圆角背景，实现整行高亮"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)  # 开启抗锯齿
        
        # 选择背景颜色
        if self._current:
            bg_color = QColor("#bbdefb")
        elif self._selected:
            bg_color = QColor("#bbdefb")
        elif self._hovered:
            bg_color = QColor("#e3f2fd")
        else:
            bg_color = Qt.transparent
        
        painter.setBrush(QBrush(bg_color))
        painter.setPen(Qt.NoPen)  # 去掉边框
        
        # 绘制圆角矩形
        radius = 6  # 圆角半径
        rect = self.rect().adjusted(0, 0, -1, -1)  # 避免右下角被裁切
        painter.drawRoundedRect(rect, radius, radius)
        
        # 调用父类绘制子控件
        super().paintEvent(event)
    
    def get_index(self):
        """获取索引"""
        return self._index
    
    def get_data(self):
        """获取数据"""
        return self._data.copy()
    
    #事件处理
    def mousePressEvent(self, event):
        """鼠标按下事件"""
        parent_list = self.parent()
        while parent_list and not isinstance(parent_list, HighPerformanceVirtualList):
            parent_list = parent_list.parent()

        if event.button() == Qt.LeftButton:
            self.clicked.emit(self)

        elif event.button() == Qt.MiddleButton and parent_list:
            # 中键点击：单选当前项目，不支持多选
            parent_list.current_index = self.get_index()
            parent_list.selected_indices = {self.get_index()}  # 只选中当前点击的项目
            parent_list._update_visible_items()  # 刷新选中状态显示
            parent_list.selectionChanged.emit(parent_list.selected_indices.copy())
            parent_list.itemClicked.emit(self.get_index(), self.get_data())

        elif event.button() == Qt.RightButton and parent_list:
            # 如果当前已是多选，右键不改变选中状态
            if len(parent_list.selected_indices) <= 1:
                # 普通右键单选
                parent_list.current_index = self.get_index()
                parent_list.selected_indices = {self.get_index()}

            # 调用右键回调
            parent_list._on_widget_right_clicked(self, event.pos())

        super().mousePressEvent(event)

    
    def mouseDoubleClickEvent(self, event):
        """鼠标双击事件"""
        if event.button() == Qt.LeftButton:
            self.double_clicked.emit(self)
        super().mouseDoubleClickEvent(event)

    #手动hover事件处理 
    def enterEvent(self, event):
        """鼠标进入事件"""
        self.set_hovered(True)
        super().enterEvent(event)
    
    def leaveEvent(self, event):
        """鼠标离开事件"""
        self.set_hovered(False)
        super().leaveEvent(event)
    
    def mouseMoveEvent(self, event):
        """鼠标移动事件 - 确保hover状态正确"""
        if not self._hovered:
            self.set_hovered(True)
        super().mouseMoveEvent(event)

# -------------------- 子线程 加载数据库 --------------------
class LoadFoldersThread(QThread):
    """优化后的数据加载线程"""
    folder_loaded = pyqtSignal(dict, int, int)
    load_finished = pyqtSignal(int)
    batch_loaded = pyqtSignal(list, int, int)  # 新增批量信号

    def __init__(self, database_file, batch_size=100):
        super().__init__()
        self.database_file = database_file
        self.batch_size = batch_size  # 批量大小

    def run(self):
        if not os.path.exists(self.database_file):
            print(f"[LoadFoldersThread] 数据库文件不存在：{self.database_file}")
            self.load_finished.emit(0)
            return

        try:
            with open(self.database_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                
            if isinstance(data, list):
                total = len(data)
                print(f"[LoadFoldersThread] 开始加载 {total} 条记录")    
                # 批量发送模式
                self._send_batch_data(data, total)
            else:
                print("[LoadFoldersThread] JSON 格式错误，期望 list")
                total = 0
        except Exception as e:
            print(f"[LoadFoldersThread] 加载数据库失败：{e}")
            total = 0
        finally:
            self.load_finished.emit(total)
    
    def _send_batch_data(self, data, total):
        """批量发送数据（推荐）"""
        for i in range(0, len(data), self.batch_size):
            batch = data[i:i + self.batch_size]
            current = min(i + self.batch_size, total)
            
            # 发送批量数据
            self.batch_loaded.emit(batch, current, total)
            
            # 适当休眠，避免UI阻塞
            if i % (self.batch_size * 10) == 0:  # 每1000条休眠一次
                self.msleep(1)

# -------------------- 主线程/主程序 --------------------
class FolderDatabaseApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # 配置文件放在程序所在目录
        app_dir = os.path.dirname(os.path.abspath(__file__))
        self.database_file = os.path.join(app_dir, "folder_database.json").replace('/', '\\')
        self.config_file = os.path.join(app_dir, "app_config.json").replace('/', '\\')
        
        self.config = self.load_config()
        self.scanner_thread = None
        self.zip_thread = None
        self.added_folder_paths = set()
        self.database_load_finished = False
        self.total_num = 0
        
        self.folders_data = []  # 只存储数据，不创建widget
        self.stolen_img_link_data = {}
        
        self.init_ui()
        self.center_window()

        # 设置窗口置顶
        # self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        # 加载数据库
        self.load_database()         
        
    def center_window(self):
        """窗口居中显示"""
        screen = QApplication.desktop().screenGeometry()
        window = self.geometry()
        x = (screen.width() - window.width()) // 2
        y = (screen.height() - window.height()) // 2
        self.move(x, y)
    
    def init_ui(self):
        """初始化用户界面"""
        self.setWindowTitle("​​ProdDB")
        self.setGeometry(100, 100, 630, 700)
        icon_path = "./icon/ProdDB.ico"
        self.setWindowIcon(QIcon(icon_path))
        
        # 设置现代扁平化样式
        self.setStyleSheet("""
            /* 全局字体设置 */
            * {
                font-family: 'Microsoft YaHei UI', 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', sans-serif;
            }
            
            /* 主窗口样式 */
            QMainWindow {
                background-color: #f8f9fa;
            }
            
            /* 按钮样式 */
            QPushButton {
                background-color: #f5f5f5;
                color: #495057;
                border: none;
                padding: 10px 20px;
                border-radius: 6px;
                font-size: 13px;
                font-weight: 500;
                min-height: 16px;
            }
            
            QPushButton:hover {
                background-color: #007bff;
                color: white;
            }
            
            QPushButton:pressed {
                background-color: #004085;
            }
            
            QPushButton:disabled {
                background-color: #6c757d;
                color: #adb5bd;
            }  
                           
            /* 选择文件夹按钮 */
            QPushButton#selectButton {
                background-color: #ffdb29;
                color: #495057;
            }
            
            QPushButton#selectButton:hover {
                background-color: #212429;
                color: #ffdb29;
            }
            
            QPushButton#selectButton:pressed {
                background-color: #0d0d0f;
            }

            
            /* 输入框样式 */
            QLineEdit {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                background-color: white;
                selection-background-color: #007bff;
            }
            
            QLineEdit:focus {
                border-color: #007bff;
                outline: none;
            }

            QLineEdit:read-only {
                background-color: #f8f9fa;
                color: #6c757d;
            }

            /* 文本框样式 */
            QTextEdit {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 13px;
                background-color: white;
                selection-background-color: #007bff;
            }
            
            QTextEdit:focus {
                border-color: #007bff;
                outline: none;
            }
            
            QTextEdit:read-only {
                background-color: #f8f9fa;
                color: #6c757d;
            }

            /* 滚动区域框样式 */
            QScrollArea {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                background-color: white;
            }

            QScrollArea QWidget {  /* 设置内部 widget 背景 */
                background-color: white;
                padding: 8px 12px;
            }

            QScrollArea:hover {
                border-color: #007bff;
            }

            QScrollBar:vertical {
                width: 10px;
                background: #f8f9fa;
                margin: 0px 0px 0px 0px;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical {
                background: #ced4da;
                border-radius: 5px;
            }

            QScrollBar::handle:vertical:hover {
                background: #007bff;
            }

            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
            
            /* 标签样式 */
            QLabel {
                color: #495057;
                font-size: 12px;
                font-weight: 500;
            }
            
            /* 分组框样式 */
            QGroupBox {
                font-size: 14px;
                font-weight: 600;
                color: #343a40;
                border: 2px solid #e9ecef;
                border-radius: 8px;
                margin-top: 12px;
                padding-top: 10px;
                background-color: white;
            }
            
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 2px 8px 2px 8px;
                background-color: white;
                border-radius: 8px;   /* 添加圆角 */
            }
            
            /* 右键菜单样式 */
            QMenu {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 4px 0px;
                font-size: 13px;
            }
            
            QMenu::item {
                padding: 8px 20px;
                margin: 2px 4px;
                border-radius: 4px;
                color: #495057;
            }
            
            QMenu::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            
            QMenu::item:pressed {
                background-color: #bbdefb;
            }
            
            QMenu::separator {
                height: 1px;
                background-color: #dee2e6;
                margin: 4px 8px;
            }
            
            /* 分割器样式 */
            QSplitter::handle {
                background-color: #dee2e6;
                height: 6px;
                border-radius: 3px;
            }
            
            QSplitter::handle:hover {
                background-color: #adb5bd;
            }
            
            /* 状态标签样式 */
            QLabel#statusLabel {
                background-color: #e9ecef;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 6px 12px;
                color: #495057;
                font-size: 12px;
            }
            
            /* 滚动条样式 */
            QScrollBar:vertical {
                border: none;
                background-color: #f8f9fa;
                width: 12px;
                border-radius: 6px;
            }
            
            QScrollBar::handle:vertical {
                background-color: #ced4da;
                border-radius: 6px;
                min-height: 20px;
            }
            
            QScrollBar::handle:vertical:hover {
                background-color: #adb5bd;
            }
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                border: none;
                background: none;
            }
            
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }

            /* 进度条样式 */
            QProgressBar {
                border: 1px solid #dee2e6;
                border-radius: 6px;
                background-color: #ced4da;   
                height: 12px;
                text-align: center;
                color: transparent;
                font-size: 0px;
                animation: none;
                transition: none;
            }
            QProgressBar::chunk {
                border: none;
                border-radius: 5px;  /* 比外框小1px */
                background-color: #007bff;
                margin: 1px;
                /* 确保不会超出父容器 */
                max-width: calc(100% - 2px);
                max-height: calc(100% - 2px);
            }   
            
            /* 工具提示样式 */
            QToolTip {
                background-color: white;
                color: #343a40;
                border: none;
                border-radius: 10px;
                padding: 8px;
                font-size: 12px;
            }
        """)
        
        # 创建中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 创建主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 创建分割器
        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)
        
        # 上半部分：控制面板
        control_panel = self.create_control_panel()
        splitter.addWidget(control_panel)
        
        # 下半部分：文件夹列表
        list_panel = self.create_list_panel()
        splitter.addWidget(list_panel)
        
        # 设置分割器比例
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([150, 550])
        
        # 状态标签
        self.status_label = QLabel("<span style='color: #00d26a;'>●</span> 就绪")
        self.status_label.setObjectName("statusLabel")
        main_layout.addWidget(self.status_label)

    def create_control_panel(self):
        """创建控制面板"""
        group_box = QGroupBox("扫描控制")
        layout = QVBoxLayout(group_box)
        layout.setContentsMargins(20, 0, 20, 0)
        
        # 文件夹选择行
        folder_layout = QHBoxLayout()
        folder_layout.setSpacing(10)
        
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("点击'选择文件夹'按钮选择要扫描的根目录")
        self.folder_path_edit.setReadOnly(True)
        self.folder_path_edit.setMinimumHeight(36)
        folder_layout.addWidget(self.folder_path_edit)
        
        self.browse_button = QPushButton("选择文件夹")
        self.browse_button.setObjectName("selectButton")
        self.browse_button.clicked.connect(self.browse_folder)
        self.browse_button.setMinimumWidth(120)
        folder_layout.addWidget(self.browse_button)
        
        layout.addLayout(folder_layout)
        
        # 搜索词输入行
        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)
        
        self.search_term_edit = QLineEdit()
        self.search_term_edit.setPlaceholderText("输入子文件夹名称关键词，可用空格分隔多个关键词")
        self.search_term_edit.setMinimumHeight(36)
        
        # 加载上次保存的搜索词
        last_search_term = self.config.get('last_search_term', '')
        if last_search_term:
            self.search_term_edit.setText(last_search_term)
        
        search_layout.addWidget(self.search_term_edit)
        
        self.add_button = QPushButton("写入数据库")
        self.add_button.clicked.connect(self.scan_and_add)
        self.add_button.setMinimumWidth(120)
        search_layout.addWidget(self.add_button)
        
        layout.addLayout(search_layout)
        
        return group_box

    def create_list_panel(self):
        """创建文件夹列表面板"""
        group_box = QGroupBox("产品图库数据库")
        layout = QVBoxLayout(group_box)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 数据库搜索行
        db_search_layout = QHBoxLayout()
        db_search_layout.setSpacing(10)
        
        self.db_search_edit = QLineEdit()
        self.db_search_edit.setPlaceholderText("输入关键词搜索文件夹，可用空格分隔多个关键词")
        self.db_search_edit.setMinimumHeight(36)

        icon_path = os.path.join(os.getcwd(), "icon", "search.png")

        # 添加图标到右侧（纯装饰，不绑定事件）
        self.db_search_edit.addAction(
            QIcon(icon_path),
            QLineEdit.TrailingPosition
        )

        # 输入文字时实时搜索
        self.db_search_edit.textChanged.connect(self.filter_folders)

        db_search_layout.addWidget(self.db_search_edit)
        
        # 清空数据库按钮
        self.clear_db_button = QPushButton()
        self.clear_db_button.setObjectName("clearButton")
        self.clear_db_button.clicked.connect(self.clear_database)
        self.clear_db_button.setMinimumWidth(36)
        self.clear_db_button.setMinimumHeight(36)
        self.clear_db_button.setIcon(QIcon("icon/clear.png"))
        self.clear_db_button.setIconSize(QSize(20, 20))
        self.clear_db_button.setToolTip("清空数据库")
        db_search_layout.addWidget(self.clear_db_button)

        # 清除内边距
        self.clear_db_button.setStyleSheet("""
            QPushButton#clearButton {
                background-color: #f0f0f0;
                border: none;
                padding: 10px 15px 10px 15px;
                margin: 0px 0px 0px 0px;
            }
            QPushButton#clearButton:hover {
                background-color: #dc3545;
                border-radius: 4px;
            }
            QPushButton#clearButton:pressed {
                background-color: #bd2130;
            }
        """)
        # 设置图标hover效果
        self.setup_hover_effects()

        # 菜单按钮
        self.setup_menu_button()
        db_search_layout.addWidget(self.menu_button)

        layout.addLayout(db_search_layout)
        
        # 创建虚拟列表
        self.folder_list = HighPerformanceVirtualList()
        self.folder_list.setStyleSheet("""
            HighPerformanceVirtualList {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                background-color: white;
            }
        """)
        
        # 连接虚拟列表的信号
        # self.folder_list.itemClicked.connect(self.on_folder_item_clicked)
        self.folder_list.itemDoubleClicked.connect(self.open_folder)
        self.folder_list.itemRightClicked.connect(self.show_context_menu)
        
        layout.addWidget(self.folder_list)
        
        return group_box

    #---------以下是菜单项逻辑------------------------------------------------
    def setup_menu_button(self):
        """设置菜单按钮和相关功能"""
        # 创建菜单按钮
        self.menu_button = QPushButton()
        self.menu_button.setObjectName("menuButton")
        self.menu_button.setMinimumWidth(50)
        self.menu_button.setMinimumHeight(36)
        self.menu_button.setIcon(QIcon("icon/menu.png"))
        self.menu_button.setIconSize(QSize(20, 20))
        
        # 按钮样式定义
        self.normal_style = """
            QPushButton#menuButton {
                background-color: #f0f0f0;
                border: none;
                padding: 10px 15px 10px 15px;
                margin: 0px 0px 0px 0px;
                border-radius: 4px;
            }
        """
        
        self.hover_style = """
            QPushButton#menuButton {
                background-color: #007bff;
                border: none;
                padding: 10px 15px 10px 15px;
                margin: 0px 0px 0px 0px;
                border-radius: 4px;
            }
        """
        
        # 设置初始样式
        self.menu_button.setStyleSheet(self.normal_style)
        
        # 安装事件过滤器并开启鼠标跟踪
        self.menu_button.setMouseTracking(True)
        self.menu_button.installEventFilter(self)
        
        # 创建菜单
        self.menu = QMenu(self)
        self.menu.setWindowFlags(self.menu.windowFlags() | Qt.FramelessWindowHint)
        self.menu.setAttribute(Qt.WA_TranslucentBackground)
        
        # 菜单样式
        self.menu.setStyleSheet("""
            QMenu {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 4px 0px;
                font-size: 13px;
            }
            
            QMenu::item {
                padding: 8px 20px;
                margin: 2px 4px;
                border-radius: 4px;
                color: #495057;
            }
            
            QMenu::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
            }
            
            QMenu::item:pressed {
                background-color: #bbdefb;
            }
            
            QMenu::separator {
                height: 1px;
                background-color: #dee2e6;
                margin: 4px 8px;
            }
        """)
        
        # 添加菜单项
        generate_action = self.menu.addAction("生成举报邮件")
        generate_action.triggered.connect(self.generate_html_email)
        self.menu.addSeparator()  
        import_action = self.menu.addAction("导入产品信息")
        import_action.triggered.connect(self.import_product_info)
        self.menu.addSeparator()  
        sort_action = self.menu.addAction("排序方式")
        sort_action.triggered.connect(self.show_sort_dialog)
        self.menu.addSeparator()          
        check_action = self.menu.addAction("检查更新")
        check_action.triggered.connect(self.check_update)
        self.menu.addSeparator()
        # settings_action = self.menu.addAction("设置")
        # settings_action.triggered.connect(self.show_settings)
        
        # 安装事件过滤器并开启鼠标跟踪
        self.menu.setMouseTracking(True)
        self.menu.installEventFilter(self)
        
        # 连接菜单项点击信号
        self.menu.triggered.connect(self._on_menu_triggered)
        
        # leave_timer：当鼠标完全移出时，延迟隐藏菜单
        self.leave_timer = QTimer(self)
        self.leave_timer.setSingleShot(True)
        self.leave_timer.timeout.connect(self._try_hide)
        
        # click_block_timer：短暂屏蔽菜单重现的定时器
        self.click_block_timer = QTimer(self)
        self.click_block_timer.setSingleShot(True)
        self.click_block_timer.timeout.connect(self._reset_just_clicked)
        
        # 状态标记
        self.just_clicked = False
        self.ignore_menu_area = False
        
    def eventFilter(self, obj, event):
        """
        事件过滤器：处理菜单按钮和菜单的鼠标事件
        hover图标跟随菜单的显示隐藏，而不是实时跟随鼠标
        """
        if event.type() in (QEvent.Enter, QEvent.Leave, QEvent.MouseMove, QEvent.HoverMove):
            cursor_pos = QCursor.pos()
            
            # 计算按钮在屏幕上的全局矩形
            btn_top_left = self.menu_button.mapToGlobal(QPoint(0, 0))
            btn_rect_global = self.menu_button.rect().translated(btn_top_left)
            
            # 菜单的全局矩形
            menu_rect_global = self.menu.geometry()
            
            # 判断是否在相关区域内
            if self.ignore_menu_area:
                # 限制模式：只识别按钮区域
                in_relevant_area = btn_rect_global.contains(cursor_pos)
            else:
                # 正常模式：识别按钮或菜单区域
                in_relevant_area = btn_rect_global.contains(cursor_pos) or menu_rect_global.contains(cursor_pos)
            
            if in_relevant_area:
                if self.ignore_menu_area and btn_rect_global.contains(cursor_pos):
                    # 限制模式下鼠标在按钮上
                    if not self.just_clicked:
                        self.show_menu()  # 这里会处理图标显示
                    self.just_clicked = False
                    return super().eventFilter(obj, event)
                elif not self.ignore_menu_area:
                    # 正常模式
                    if self.just_clicked:
                        # 如果刚点击过菜单项，只停止隐藏定时器
                        if self.leave_timer.isActive():
                            self.leave_timer.stop()
                        return super().eventFilter(obj, event)
                    # 显示菜单（会处理图标显示）
                    self.show_menu()
            else:
                # 鼠标不在相关区域：启动延迟隐藏菜单（会处理图标隐藏）
                if self.menu.isVisible() and not self.leave_timer.isActive():
                    self.leave_timer.start(300)
        
        return super().eventFilter(obj, event)

    def show_menu(self):
        """显示菜单时同时显示hover图标"""
        # 菜单已经可见时，只停止隐藏定时器，不重复弹出
        if self.menu.isVisible():
            self.leave_timer.stop()
            return
        
        # 从按钮重新打开菜单时，恢复识别菜单区域
        self.ignore_menu_area = False
        # 取消任何待执行的隐藏操作
        self.leave_timer.stop()
        
        # 显示菜单时：设置hover样式和hover图标
        self.menu_button.setStyleSheet(self.hover_style)
        self.menu_button.setIcon(QIcon("icon/menu_h.png"))
        
        # 计算菜单位置
        button_rect = self.menu_button.rect()
        button_pos = self.menu_button.mapToGlobal(QPoint(0, 0))
        
        # 确保菜单已经布局完成，能获取正确尺寸
        self.menu.adjustSize()
        
        # 计算位置：在按钮下方显示
        menu_x = button_pos.x()
        menu_y = button_pos.y() + button_rect.height() + 2
        
        # 显示菜单
        self.menu.popup(QPoint(int(menu_x), int(menu_y)))

    def _try_hide(self):
        """
        定时器超时后检查是否隐藏菜单
        只有真正隐藏菜单时才隐藏hover图标
        """
        cursor_pos = QCursor.pos()
        
        btn_top_left = self.menu_button.mapToGlobal(QPoint(0, 0))
        btn_rect_global = self.menu_button.rect().translated(btn_top_left)
        menu_rect_global = self.menu.geometry()
        
        # 根据当前模式判断相关区域
        if self.ignore_menu_area:
            in_relevant_area = btn_rect_global.contains(cursor_pos)
        else:
            in_relevant_area = btn_rect_global.contains(cursor_pos) or menu_rect_global.contains(cursor_pos)
        
        # 如果光标仍在相关区域，不做任何操作（保持菜单和hover图标显示）
        if in_relevant_area:
            return
        
        # 否则，隐藏菜单和hover图标
        self._hide_menu_and_reset()

    def _hide_menu_and_reset(self):
        """隐藏菜单时同时隐藏hover图标"""
        # 隐藏菜单
        self.menu.hide()
        # 恢复按钮正常状态：普通样式和普通图标
        self.menu_button.setStyleSheet(self.normal_style)
        self.menu_button.setIcon(QIcon("icon/menu.png"))

    def _on_menu_triggered(self, action):
        """
        菜单项被点击时：立即隐藏菜单和hover图标
        """
        # 屏蔽短时重新弹出
        self.just_clicked = True
        if self.click_block_timer.isActive():
            self.click_block_timer.stop()
        self.click_block_timer.start(200)
        
        # 去除对菜单区域的识别，直到下一次从按钮触发
        self.ignore_menu_area = True
        # 立即隐藏菜单和hover图标
        self._hide_menu_and_reset()

    def _reset_just_clicked(self):
        """200ms 后自动重置 just_clicked 标记"""
        self.just_clicked = False

    def _try_hide(self):
        """
        定时器超时后再次检查光标位置
        如果光标仍不在相关区域，就隐藏菜单和hover图标
        """
        cursor_pos = QCursor.pos()
        
        btn_top_left = self.menu_button.mapToGlobal(QPoint(0, 0))
        btn_rect_global = self.menu_button.rect().translated(btn_top_left)
        menu_rect_global = self.menu.geometry()
        
        # 如果光标仍在按钮或菜单区域，保持hover图标和菜单显示
        if btn_rect_global.contains(cursor_pos) or menu_rect_global.contains(cursor_pos):
            return
        
        # 否则，隐藏菜单和hover图标，恢复正常状态
        self._hide_menu_and_reset()

    def _hide_menu_and_reset(self):
        """隐藏菜单并恢复按钮正常状态（包括图标）"""
        self.menu.hide()
        self.menu_button.setStyleSheet(self.normal_style)
        # 恢复普通图标
        self.menu_button.setIcon(QIcon("icon/menu.png"))

    # 导入产品信息
    def import_product_info(self):
        """导入产品信息""" 
        # 创建对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("产品信息导入")
        dialog.setFixedSize(300, 100)
        dialog.setWindowModality(Qt.ApplicationModal)
        
        # 工作目录配置
        work_dir = os.getcwd()
        template_file = os.path.join(work_dir, "产品信息模板.xlsx")
        
        # 创建布局
        layout = QVBoxLayout()
            
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 下载模板文件按钮
        download_btn = QPushButton("下载模板文件")
        download_btn.setMinimumHeight(36)
        button_layout.addWidget(download_btn)
        
        # 从模板文件导入按钮
        import_btn = QPushButton("从模板文件导入")
        import_btn.setMinimumHeight(36)
        button_layout.addWidget(import_btn)
        
        layout.addLayout(button_layout)
        
        dialog.setLayout(layout)
        
        # 下载模板文件功能
        def download_template():
            try:
                # 检查模板文件是否存在
                if not os.path.exists(template_file):
                    QMessageBox.warning(dialog, "错误", f"模板文件不存在：{template_file}")
                    return
                
                # 让用户选择保存路径
                save_path, _ = QFileDialog.getSaveFileName(
                    dialog, 
                    "保存模板文件", 
                    r"C:\产品信息模板.xlsx",  # 默认路径+文件名
                    "Excel文件 (*.xlsx)"
                )

                if save_path:
                    # 复制文件
                    shutil.copy2(template_file, save_path)
                    QMessageBox.information(dialog, "成功", f"模板文件已保存到：\n{save_path}")
                    
            except Exception as e:
                QMessageBox.critical(dialog, "错误", f"下载模板文件失败：\n{str(e)}")
        
        # 从模板导入功能
        def import_from_template():
            # 让用户选择要导入的Excel文件
            file_path, _ = QFileDialog.getOpenFileName(
                dialog,  # 用对话框作为父窗口
                "选择要导入的模板文件",
                r"C:\产品信息模板.xlsx",
                "Excel文件 (*.xlsx *.xls)"
            )
            
            if not file_path:
                return
            #开始导入
            self.start_imort(file_path)
            dialog.close()
                    
        # 连接按钮信号
        download_btn.clicked.connect(download_template)
        import_btn.clicked.connect(import_from_template)
        
        # 显示对话框
        dialog.exec_()

    def start_imort(self, file_path):
        """开始导入"""
        # 创建进度条对话框
        self.progress_dialog = QProgressDialog("准备开始处理...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("导入进度")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setMinimumWidth(500)
        self.progress_dialog.resize(500, 120)
        
        # 设置初始进度为3%
        self.progress_dialog.setValue(3)
        self.progress_dialog.show()

        # 创建子线程
        self.import_thread = ImportProductThread(self.folders_data, file_path)
        
        # 连接信号
        self.import_thread.progress_changed.connect(self._on_import_progress_changed)
        self.import_thread.finished.connect(self._on_import_finished)
        
        # 连接取消按钮信号
        self.progress_dialog.canceled.connect(self._on_import_cancelled)
        
        self.import_thread.start()
        self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 正在导入产品信息")

    def _on_import_progress_changed(self, percent, name):
        """处理进度更新（忽略子线程错误信息）"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog and not self.progress_dialog.wasCanceled():
            try:
                self.progress_dialog.setValue(percent)
                # 只显示任务名称，不显示任何错误信息
                safe_name = name.split("->")[0]  # 如果 name 中包含异常描述，取前半部分
                self.progress_dialog.setLabelText(f"正在处理: {safe_name}")
            except (RuntimeError, AttributeError):
                # 对话框已被销毁，停止处理
                if hasattr(self, 'import_thread') and self.import_thread:
                    self.import_thread.stop_processing()

    def _on_import_cancelled(self):
        """处理取消操作"""
        if hasattr(self, 'import_thread') and self.import_thread and self.import_thread.isRunning():
            # 停止线程处理
            self.import_thread.stop_processing()
            # 更新状态
            self.status_label.setText(f"<span style='color: #ff6b6b;'>●</span> 正在取消导入...")
        
        # 标记对话框为None，避免后续访问
        if hasattr(self, 'progress_dialog'):
            self.progress_dialog = None

    def _on_import_finished(self, updated_count, skipped_count, was_cancelled):
        """处理导入完成"""
        # 安全关闭进度对话框
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            try:
                if not self.progress_dialog.wasCanceled():
                    self.progress_dialog.close()
            except (RuntimeError, AttributeError):
                pass  # 对话框已被销毁
            finally:
                self.progress_dialog = None

        if was_cancelled:
            # 处理取消情况
            self.status_label.setText(f"<span style='color: #ff6b6b;'>●</span> 导入已取消")
            QMessageBox.information(
                self, 
                "导入已取消", 
                f"导入已取消！\n已处理数量：{updated_count}\n跳过数量：{skipped_count}"
            )
        else:
            # 处理正常完成情况
            # 保存数据库并刷新列表
            try:
                self.save_database()
                self.folder_list.update()
                self.refresh_folder_list()
            except Exception as e:
                print(f"保存数据库或刷新列表时出错: {e}")
            
            self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 导入完成")
            QMessageBox.information(
                self, 
                "导入完成", 
                f"导入完成！\n已更新数量：{updated_count}\n跳过数量：{skipped_count}"
            )
        
        # 最终状态更新
        try:
            self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}）")
        except AttributeError:
            self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪")
        
        # 清理线程引用
        if hasattr(self, 'import_thread'):
            self.import_thread = None

    #排序逻辑
    def show_sort_dialog(self):
        """弹出排序设置对话框并排序虚拟列表"""
        dialog = QDialog(self)
        dialog.setWindowTitle("排序设置")
        dialog.setFixedSize(280, 350)
        dialog.setWindowModality(Qt.ApplicationModal)

        layout = QVBoxLayout(dialog)

        # ---------------- 排序方式组 ----------------
        order_groupbox = QGroupBox("排序方式")
        order_layout = QVBoxLayout(order_groupbox)

        asc_radio = QRadioButton("升序")
        desc_radio = QRadioButton("降序")
        desc_radio.setChecked(True)  # 默认降序

        order_group = QButtonGroup(dialog)
        order_group.addButton(asc_radio)
        order_group.addButton(desc_radio)

        order_layout.addWidget(asc_radio)
        order_layout.addWidget(desc_radio)

        layout.addWidget(order_groupbox)

        # ---------------- 排序字段组 ----------------
        field_groupbox = QGroupBox("排序字段")
        field_layout = QVBoxLayout(field_groupbox)

        name_radio = QRadioButton("名称")
        add_date_radio = QRadioButton("添加日期")
        modify_date_radio = QRadioButton("修改日期")
        add_date_radio.setChecked(True)  # 默认添加日期

        field_group = QButtonGroup(dialog)
        field_group.addButton(name_radio)
        field_group.addButton(add_date_radio)
        field_group.addButton(modify_date_radio)

        field_layout.addWidget(name_radio)
        field_layout.addWidget(add_date_radio)
        field_layout.addWidget(modify_date_radio)

        layout.addWidget(field_groupbox)

        # ---------------- 按钮 ----------------
        btn_layout = QHBoxLayout()
        btn_layout.setContentsMargins(2, 0, 2, 0)  # 内边距
        ok_btn = QPushButton("应用排序")
        cancel_btn = QPushButton("取消")

        btn_layout.addWidget(ok_btn)
        btn_layout.addWidget(cancel_btn)

        layout.addLayout(btn_layout)

        # ---------------- 从配置文件读取默认选项 ----------------
        sort_order = self.config.get('sort_order', 'desc')
        sort_field = self.config.get('sort_field', 'add_date')

        if sort_order == 'asc':
            asc_radio.setChecked(True)
        else:
            desc_radio.setChecked(True)

        if sort_field == 'name':
            name_radio.setChecked(True)
        elif sort_field == 'add_date':
            add_date_radio.setChecked(True)
        else:
            modify_date_radio.setChecked(True)

        #按钮事件
        def apply_sort():
            order = 'asc' if asc_radio.isChecked() else 'desc'
            if name_radio.isChecked():
                field = 'name'
            elif add_date_radio.isChecked():
                field = 'add_date'
            else:
                field = 'modify_date'

            # 保存配置
            self.config['sort_order'] = order
            self.config['sort_field'] = field
            self.save_config()

            # 调用统一排序函数
            self.sort_folders()
            dialog.accept()

        ok_btn.clicked.connect(apply_sort)
        cancel_btn.clicked.connect(dialog.reject)

        # 显示窗口
        dialog.exec_() 

    #统一排序函数
    def sort_folders(self):
        """根据配置文件排序虚拟列表和数据库文件"""
        # 读取配置
        order = self.config.get('sort_order', 'desc')       # 默认降序
        field = self.config.get('sort_field', 'add_date')   # 默认添加日期
        reverse = order == 'desc'

        def sort_key(item):
            return item.get(field, "")

        # 排序虚拟列表
        self.folder_list.items_data.sort(key=sort_key, reverse=reverse)
        # 同步更新主数据源
        self.folders_data = self.folder_list.items_data.copy()

        # 清空选中状态
        self.folder_list.selected_indices.clear()
        self.folder_list.current_index = -1
        self.folder_list._update_visible_items()
        self.folder_list.selectionChanged.emit(self.folder_list.selected_indices.copy())

        # 保存数据库文件
        try:
            with open(self.database_file, 'w', encoding='utf-8') as f:
                json.dump(self.folders_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存数据库文件失败：{e}")

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            selected_data = self.folder_list.get_selected_data()
            folder_data = selected_data[0]
            # 鼠标中键点击时触发
            self.add_bind_link(folder_data)
        else:
            # 其他按钮正常处理
            super().mousePressEvent(event)

    #生成举报邮件
    def generate_html_email(self):
        """生成侵权举报 HTML 邮件"""
        # 检查是否有至少一个文件夹有链接
        has_links = any(links for links in self.stolen_img_link_data.values())

        if not self.stolen_img_link_data or not has_links:
            QMessageBox.warning(self, "生成举报邮件", "请先右键列表项-【添加绑定盗图链接】添加绑定侵权链接")
            return

        # 读取配置
        config_path = self.config_file
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                app_config = json.load(f)
        else:
            app_config = {}

        dialog = QDialog(self)
        dialog.setWindowTitle("生成举报邮件")
        dialog.setFixedSize(800, 600)
        dialog.setWindowModality(Qt.ApplicationModal)
        
        # 主水平布局
        main_layout = QHBoxLayout(dialog)
        
        # 左侧垂直布局（控件区域）
        left_layout = QVBoxLayout()
        
        # 右侧垂直布局（预览区域）
        right_layout = QVBoxLayout()

        # 权利人主体
        reporter_groupbox = QGroupBox("权利人主体")
        reporter_layout = QVBoxLayout(reporter_groupbox)
        company_radio = QRadioButton("公司")
        person_radio = QRadioButton("个人")
        
        # 从配置文件读取上次选择的选项
        is_company = app_config.get("reporter_type", "company") == "company"
        company_radio.setChecked(is_company)
        person_radio.setChecked(not is_company)
        
        reporter_layout.addWidget(company_radio)
        reporter_layout.addWidget(person_radio)
        left_layout.addWidget(reporter_groupbox)

        # 权利人信息
        info_groupbox = QGroupBox("权利人信息")
        info_layout = QFormLayout(info_groupbox)

        company_edit = QLineEdit()
        contact_edit = QLineEdit()
        phone_edit = QLineEdit()
        email_edit_input = QLineEdit()

        # 设置 placeholder 并填充默认值
        company_edit.setPlaceholderText("公司名称")
        company_edit.setText(app_config.get("company_name", ""))

        contact_edit.setPlaceholderText("联系人")
        contact_edit.setText(app_config.get("contact_name", ""))

        phone_edit.setPlaceholderText("电话")
        phone_edit.setText(app_config.get("phone", ""))

        email_edit_input.setPlaceholderText("邮箱")
        email_edit_input.setText(app_config.get("email", ""))

        # 直接添加控件，不用 Label
        info_layout.addRow(company_edit)
        info_layout.addRow(contact_edit)
        info_layout.addRow(phone_edit)
        info_layout.addRow(email_edit_input)

        left_layout.addWidget(info_groupbox)

        def toggle_company_fields():
            company_edit.setVisible(company_radio.isChecked())

            # 如果已经生成过邮件，切换选项时自动重新生成
            if hasattr(dialog, 'email_generated') and dialog.email_generated:
                build_email()

        company_radio.toggled.connect(toggle_company_fields)
        person_radio.toggled.connect(toggle_company_fields)
        toggle_company_fields()

        # 按钮
        btn_layout = QHBoxLayout()
        generate_btn = QPushButton("生成邮件")
        copy_btn = QPushButton("复制HTML邮件")

        btn_layout.addWidget(generate_btn)
        btn_layout.addWidget(copy_btn)
        left_layout.addLayout(btn_layout)
        
        # 附件名称
        attachment_groupbox = QGroupBox("附件名称")
        attachment_layout = QVBoxLayout(attachment_groupbox)
        
        attachment_edit = QTextEdit()
        attachment_edit.setReadOnly(True)  # 设置为只读
        attachment_layout.addWidget(attachment_edit)
        
        left_layout.addWidget(attachment_groupbox)
        
        # 右侧邮件预览
        preview_groupbox = QGroupBox("邮件预览")
        preview_layout = QVBoxLayout(preview_groupbox)
        
        email_preview = QTextEdit()
        email_preview.setReadOnly(True)
        preview_layout.addWidget(email_preview)
        
        right_layout.addWidget(preview_groupbox)
        
        # 将左右布局添加到主布局
        main_layout.addLayout(left_layout, 1)  # 左侧占1份
        main_layout.addLayout(right_layout, 2)  # 右侧占2份

        # 用于存储原始HTML内容
        dialog.html_content = ""
        dialog.email_generated = False

        def check_and_set_attachment_path():
            """检查并设置附件路径"""
            attachment_path = app_config.get("attachment_folder_path", "")
            
            if not attachment_path or not os.path.exists(attachment_path):
                QMessageBox.information(dialog, "提示", "未设置附件检测路径，请点击【OK】后选择附件（原图证明文件）所在文件夹。\n若暂未生成过原图证明文件，请先指定一个文件夹用来存放附件（原图证明文件）")
                # 弹出设置框设置附件路径
                folder_path = QFileDialog.getExistingDirectory(dialog, "选择附件所在文件夹", "")
                if folder_path:
                    app_config["attachment_folder_path"] = folder_path
                    self.config["attachment_folder_path"] = folder_path
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(app_config, f, ensure_ascii=False, indent=2)
                    return folder_path
                else:
                    return None
            return attachment_path

        def check_missing_attachments(attachment_path, attachment_keys):
            """检查缺失的附件"""
            missing_attachments = []
            for key in attachment_keys:
                zip_file_path = os.path.join(attachment_path, f"{key}.zip")
                if not os.path.exists(zip_file_path):
                    missing_attachments.append(f"{key}.zip")
            return missing_attachments

        def show_missing_attachments_dialog(missing_attachments, attachment_keys):
            """显示缺失附件的自定义对话框"""
            missing_dialog = QDialog(dialog)
            missing_dialog.setWindowTitle("附件检测结果")
            missing_dialog.setFixedSize(350, 270)
            missing_dialog.setWindowModality(Qt.ApplicationModal)
            
            layout = QVBoxLayout(missing_dialog)
            
            # 标题
            title_label = QLabel("以下附件不存在，是否生成附件（原图证明文件）？")
            title_label.setWordWrap(True)
            layout.addWidget(title_label)
            
            # 缺失附件列表
            list_widget = QTextEdit()
            list_widget.setReadOnly(True)
            list_widget.setPlainText("\n".join(missing_attachments))
            layout.addWidget(list_widget)
            
            # 按钮布局
            button_layout = QHBoxLayout()
            reselect_btn = QPushButton("重设附件路径")
            generate_btn = QPushButton("生成")
            ignore_btn = QPushButton("忽略")
            
            button_layout.addWidget(reselect_btn)
            button_layout.addWidget(generate_btn)
            button_layout.addWidget(ignore_btn)
            layout.addLayout(button_layout)
            
            def reselect_path():
                """重设附件路径"""
                default_path = self.config.get("attachment_folder_path", "")
                folder_path = QFileDialog.getExistingDirectory(
                    missing_dialog, 
                    "选择附件所在文件夹", 
                    default_path
                )
                if folder_path:
                    app_config["attachment_folder_path"] = folder_path
                    self.config["attachment_folder_path"] = folder_path
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(app_config, f, ensure_ascii=False, indent=2)

                    # 重新检测
                    detect_missing(folder_path)

            def detect_missing(folder_path):
                """统一的缺失附件检测函数"""
                new_missing = check_missing_attachments(folder_path, attachment_keys)
                if new_missing:
                    list_widget.setPlainText("\n".join(new_missing))
                else:
                    QMessageBox.information(missing_dialog, "提示", "所有附件都已存在！")
                    missing_dialog.accept()
                    
            def generate_attachments():
                """生成附件"""
                missing_dialog.accept()
                selected_data = []
                for key in attachment_keys:
                    if f"{key}.zip" in missing_attachments:
                        for original_key, _ in self.stolen_img_link_data.items():
                            if original_key == key:
                                folder_path = self.get_folder_path_by_key(key)
                                if folder_path:
                                    selected_data.append({"path": folder_path})
                                break

                if selected_data:
                    self.generate_original_proof(selected_data)
                    # 重新检测
                    detect_missing(folder_path)
            
            def ignore_missing():
                """忽略缺失的附件"""
                missing_dialog.reject()
            
            reselect_btn.clicked.connect(reselect_path)
            generate_btn.clicked.connect(generate_attachments)
            ignore_btn.clicked.connect(ignore_missing)
            
            return missing_dialog.exec_()

        def check_attachments_after_copy():
            """复制成功后检测附件"""
            # 获取当前的附件keys
            attachment_keys = [key for key, links in self.stolen_img_link_data.items() if links]
            
            if not attachment_keys:
                return
            
            # 检查并设置附件路径
            attachment_path = check_and_set_attachment_path()
            if not attachment_path:
                return
            
            # 检查缺失的附件
            missing_attachments = check_missing_attachments(attachment_path, attachment_keys)
            
            if missing_attachments:
                show_missing_attachments_dialog(missing_attachments, attachment_keys)

        def build_email():
            # 校验必填信息
            if company_radio.isChecked() and not company_edit.text().strip():
                QMessageBox.warning(dialog, "提示", "请填写公司名称")
                return
            if not contact_edit.text().strip():
                QMessageBox.warning(dialog, "提示", "请填写联系人")
                return
            if not phone_edit.text().strip():
                QMessageBox.warning(dialog, "提示", "请填写电话")
                return
            if not email_edit_input.text().strip():
                QMessageBox.warning(dialog, "提示", "请填写邮箱")
                return

            main_body = "本人" if person_radio.isChecked() else "本公司"
            company_name = company_edit.text() if company_radio.isChecked() else ""
            contact = contact_edit.text()
            phone = phone_edit.text()
            email_addr = email_edit_input.text()
            signature_name = contact if person_radio.isChecked() else company_name

            # 保存输入到配置，包括选项类型
            reporter_type = "person" if person_radio.isChecked() else "company"
            app_config.update({
                "reporter_type": reporter_type,
                "company_name": company_edit.text(),
                "contact_name": contact_edit.text(),
                "phone": phone_edit.text(),
                "email": email_addr
            })
            
            # 同时更新主配置对象，避免程序关闭时被覆盖
            self.config.update({
                "reporter_type": reporter_type,
                "company_name": company_edit.text(),
                "contact_name": contact_edit.text(),
                "phone": phone_edit.text(),
                "email": email_addr
            })
            
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(app_config, f, ensure_ascii=False, indent=2)

            # 构造侵权链接 HTML
            links_html = ""
            for key, urls in self.stolen_img_link_data.items():
                for url in urls:
                    links_html += f'<div class="links" style="background-color: rgb(249, 249, 249); padding: 12px; border-left: 4px solid rgb(254, 172, 28); margin: 12px 0px; word-break: break-all; font-family: &quot;Microsoft YaHei&quot;, sans-serif; font-size: 14px; border-radius: 3px;"><span>{url} 证明材料附件名称：{key}</span></div>\n'

            # 根据选择的类型决定是否显示公司名称
            company_info_html = ""
            if company_radio.isChecked():
                company_info_html = f"公司名称：{company_name}<br>"

            # 原始 HTML 模板，保持不变
            html_content = f"""<div style="clear: both;"></div><meta charset="UTF-8"><div style="clear: both;">
                    </div><title>产品图片侵权通知</title><div style="clear: both;">
                    </div><div class="email-container" style="max-width: 600px; margin: 0px auto; background-color: #fff; overflow: hidden; padding: 0px; font-family: 'Microsoft YaHei', sans-serif;">
                    <div class="content" style="padding: 0px 0px 20px;">

                        <p style="margin: 20px 0px 12px; line-height: 22.4px; font-size: 14px;">尊敬的 Temu 知识产权保护单位：</p>

                        <p style="margin: 12px 0px; line-height: 22.4px; font-size: 14px;">本公司发现以下商品未经授权使用了本公司拍摄的产品图片，特此通知并请求贵单位依据相关法律法规对涉案侵权商品在<strong>所有国家和地区站点（包括但不限于美国、欧洲、东南亚等）进行下架处理</strong>。</p>

                        <p style="margin: 12px 0px; line-height: 22.4px; font-size: 14px;">本公司的产品摄影图原图及相关证明材料见附件。</p>

                        <p style="margin: 12px 0px; line-height: 22.4px; font-size: 14px;"><strong>侵权产品：</strong></p>
                        {links_html}

                        <p style="margin: 12px 0px; line-height: 22.4px; font-size: 14px;"><strong>声明：</strong></p>
                        <ul style="padding-left: 20px; margin: 10px 0px;">
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">本公司是上述产品图片的版权所有者。</li>
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">经核实，涉案商品在多个站点均由同一销售主体或关联账户运营，并且商品信息、图片完全一致，构成全平台范围的系统性侵权。</li>
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">本公司真诚地相信，上述商品中出现的侵权图片的使用行为，未经版权所有者、其代理人或法律授权。</li>
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">本通知中的信息真实准确。</li>
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">在作伪证将承担法律责任的前提下，本公司声明本公司是版权所有者。</li>
                        </ul>

                        <p style="margin: 12px 0px; font-size: 14px; line-height: 22.4px;"><strong>本公司要求：</strong></p>
                        <ul style="padding-left: 20px; margin: 10px 0px;">
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">Temu 平台应立即对涉案侵权商品在所有国家和地区站点（包括但不限于美国、欧洲、东南亚等）进行下架处理，而非仅限单一站点。</li>
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">对相关卖家进行处罚，并建立拦截机制，防止该商品在其他站点再次上架。</li>
                            <li style="margin: 6px 0px; font-size: 14px; line-height: 22.4px;">若 Temu 仅对部分站点处理，而继续允许其他站点销售侵权商品，则属于明知侵权仍纵容传播，本公司将保留进一步追究 Temu 平台连带责任的权利，包括但不限于向国家知识产权局、工商管理部门以及境外监管机构投诉，直至提起诉讼。</li>
                        </ul>

                        <p style="margin: 12px 0px; font-size: 14px; line-height: 22.4px;"><strong>权利人信息：</strong></p>
                        <p style="margin: 12px 0px; font-size: 14px; line-height: 22.4px;">
                            {company_info_html}联系人：{contact}<br>
                            电话：{phone}<br>
                            邮箱：<a href="mailto:{email_addr}" style="color: #FEAC1C; text-decoration: none;">{email_addr}</a>
                        </p>

                        <div class="signature" style="margin-top: 20px;">
                            <p style="margin: 12px 0px; font-size: 14px; line-height: 22.4px;">签名：{signature_name}</p>
                        </div>

                        <p style="margin: 12px 0px; font-size: 14px; line-height: 22.4px;">感谢贵单位的支持和协助！</p>

                        <p style="margin: 12px 0px; font-size: 14px; line-height: 22.4px;">此致<br>敬礼</p>

                    </div>
                    </div>"""

            # 保存原始HTML内容用于复制
            dialog.html_content = html_content
            dialog.email_generated = True

            #生成附件压缩包名称
            attachments = ' '.join(
                f'"{key}.zip"' 
                for key, links in self.stolen_img_link_data.items() 
                if links  # 只保留非空列表
            )

            # 显示在附件列表中
            attachment_edit.setText(attachments)
            
            # 在预览面板显示渲染的HTML
            email_preview.setHtml(html_content)

        def copy_email():
            if not dialog.html_content:
                QMessageBox.warning(dialog, "提示", "请先点击【生成举报邮件】来生成邮件")
                return

            clipboard = QApplication.clipboard()
            clipboard.setText(dialog.html_content)
            
            # 检查配置文件里是否已经设置过
            no_prompt = app_config.get("no_email_copy_prompt", False)

            if no_prompt:
                # 在主窗口中心显示放大的提示
                show_large_tooltip(dialog, "✓\n已复制")
            else:
                # 显示带勾选框的消息框
                msg_box = QMessageBox(dialog)
                msg_box.setWindowTitle("提示")
                msg_box.setText("举报邮件HTML代码已复制到剪贴板，请切换邮箱编辑界面为【源码】模式粘贴")
                msg_box.setIcon(QMessageBox.Information)
                
                # 添加不再提示勾选框
                no_prompt_cb = QCheckBox("不再提示")
                msg_box.setCheckBox(no_prompt_cb)
                
                # 显示消息框
                msg_box.exec_()
                
                # 如果勾选了不再提示，保存到配置文件
                if no_prompt_cb.isChecked():
                    self.no_email_copy_prompt = True
                    app_config["no_email_copy_prompt"] = True
                    self.config["no_email_copy_prompt"] = True
                    with open(config_path, "w", encoding="utf-8") as f:
                        json.dump(app_config, f, ensure_ascii=False, indent=2)

                    # 在主窗口中心显示放大的提示
                    show_large_tooltip(dialog, "✓\n已复制")

        def copy_name():
            clipboard = QApplication.clipboard()
            attachments = ' '.join(
                f'"{key}.zip"' 
                for key, links in self.stolen_img_link_data.items() 
                if links  # 只保留非空列表
            )
            clipboard.setText(attachments)
            show_small_tooltip(attachment_edit, "✓\n已复制")
            
            # 复制成功后检测附件
            QTimer.singleShot(100, check_attachments_after_copy)  # 延迟100ms执行，确保提示先显示

        def show_small_tooltip(parent, text):
            """在控件中心显示小提示"""
            tooltip = QLabel(parent)
            tooltip.setAlignment(Qt.AlignCenter)
            tooltip.setStyleSheet("""
                QLabel {
                    background-color: rgba(200, 200, 200, 150);
                    border-radius: 10px;
                    padding: 10px;
                    font: bold 12px;
                    min-width: 50px;
                    min-height: 50px;
                }
            """)
            tooltip.setText(text)
            tooltip.adjustSize()
            
            # 居中显示
            x = (parent.width() - tooltip.width()) // 2
            y = (parent.height() - tooltip.height()) // 2
            tooltip.move(x, y)
            tooltip.show()
            
            # 2秒后自动消失
            QTimer.singleShot(2000, tooltip.deleteLater)

        def show_large_tooltip(parent, text):
            """在主窗口中心显示大提示"""
            tooltip = QLabel(parent)
            tooltip.setAlignment(Qt.AlignCenter)
            tooltip.setStyleSheet("""
                QLabel {
                    background-color: rgba(200, 200, 200, 200);
                    border-radius: 15px;
                    padding: 20px;
                    font: bold 20px;
                    min-width: 100px;
                    min-height: 100px;
                }
            """)
            tooltip.setText(text)
            tooltip.adjustSize()
            
            # 居中显示
            x = (parent.width() - tooltip.width()) // 2
            y = (parent.height() - tooltip.height()) // 2
            tooltip.move(x, y)
            tooltip.show()
            
            # 2秒后自动消失
            QTimer.singleShot(2000, tooltip.deleteLater)

        generate_btn.clicked.connect(build_email)
        copy_btn.clicked.connect(copy_email)
        
        # 设置附件名称框的点击事件
        def on_attachment_edit_click(event):
            if dialog.email_generated:
                copy_name()
            else:
                QMessageBox.warning(dialog, "提示", "请先点击【生成举报邮件】来生成邮件")
            event.accept()
        
        attachment_edit.mousePressEvent = on_attachment_edit_click
        
        # 检查是否所有信息都已从配置文件加载成功，如果是则自动生成邮件
        auto_generate = all([
            app_config.get("company_name") or app_config.get("reporter_type") == "person",
            app_config.get("contact_name"),
            app_config.get("phone"),
            app_config.get("email")
        ])
        
        if auto_generate:
            build_email()

        # 给子窗口安装 closeEvent
        def on_close(event):
            self.stolen_img_link_data = {}
            event.accept()

        dialog.closeEvent = on_close  # 覆盖 closeEvent

        dialog.exec_()

    # 需要添加的辅助方法
    def get_folder_path_by_key(self, key):
        """根据key获取文件夹路径"""
        if hasattr(self, 'folders_data'):
            for folder_item in self.folders_data:
                if folder_item.get('name') == key:
                    return folder_item.get('path', '')
        return ""

    #---------以上是菜单项逻辑------------------------------------------------

    def setup_hover_effects(self):
        """设置按钮图标hover"""
        self.clear_db_button.enterEvent = lambda event: self.clear_db_button.setIcon(QIcon("icon/clear_h.png"))
        self.clear_db_button.leaveEvent = lambda event: self.clear_db_button.setIcon(QIcon("icon/clear.png"))

    #虚拟列表回调
    def get_selected_folders(self):
        """获取选中的文件夹"""
        return self.folder_list.get_selected_data()
    
    def get_current_folder(self):
        """获取当前文件夹"""
        return self.folder_list.get_current_data()
   
    #---------以下是右键菜单逻辑------------------------------------------------
    def show_context_menu(self, index, data, global_pos):
        # 直接用虚拟列表选中状态
        selected_data = self.folder_list.get_selected_data()
        selected_count = len(selected_data)

        menu = QMenu(self)
        menu.setFixedWidth(200)
        menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint)
        menu.setAttribute(Qt.WA_TranslucentBackground)

        # ---------------- 多选操作 ----------------
        if selected_count > 1:
            generate_text = f"生成原图证明文件 ({selected_count}个)"
            generate_action = QAction(generate_text, self)
            generate_action.triggered.connect(lambda: self.generate_original_proof(selected_data))
            menu.addAction(generate_action)

            menu.addSeparator()

            delete_text = f"从数据库中删除 ({selected_count}个)"
            delete_action = QAction(delete_text, self)
            delete_action.triggered.connect(lambda: self.delete_folders(selected_data))
            menu.addAction(delete_action)

        # ---------------- 单选操作 ----------------
        elif selected_count == 1:
            folder_data = selected_data[0]

            generate_action = QAction("生成原图证明文件", self)
            generate_action.triggered.connect(lambda: self.generate_original_proof(selected_data))
            menu.addAction(generate_action)

            menu.addSeparator()
            bind_link = QAction("添加绑定盗图链接", self)
            bind_link.triggered.connect(lambda: self.add_bind_link(folder_data))
            menu.addAction(bind_link)

            menu.addSeparator()
            copy_path_action = QAction("复制文件夹路径", self)
            copy_path_action.triggered.connect(lambda: self.copy_path(folder_data))
            menu.addAction(copy_path_action)

            menu.addSeparator()
            edit_action = QAction("编辑备注", self)
            edit_action.triggered.connect(lambda: self.edit_folder_remark(folder_data))
            menu.addAction(edit_action)

            menu.addSeparator()
            change_thumb_action = QAction("更换缩略图", self)
            change_thumb_action.triggered.connect(lambda: self.change_thumbnail(folder_data))
            menu.addAction(change_thumb_action)

            menu.addSeparator()
            open_action = QAction("打开文件夹", self)
            open_action.triggered.connect(lambda: self.open_folder(folder_data))
            menu.addAction(open_action)

            menu.addSeparator()
            delete_action = QAction("从数据库中删除", self)
            delete_action.triggered.connect(lambda: self.delete_folders(selected_data))
            menu.addAction(delete_action)

        # 显示菜单
        menu.exec_(global_pos)

    #添加绑定盗图侵权链接
    def add_bind_link(self, folder_data):
        name = folder_data.get("name", "未知文件夹")
        # 初始化字典
        if not hasattr(self, "stolen_img_link_data"):
            self.stolen_img_link_data = {}
        if name not in self.stolen_img_link_data:
            self.stolen_img_link_data[name] = []

        dialog = QDialog(self)
        dialog.setWindowTitle(f"添加绑定盗图链接 - {name}")
        dialog.setFixedWidth(500)
        main_layout = QVBoxLayout(dialog)

        # 顶部标题 + 总计放在右上角
        top_layout = QHBoxLayout()
        title_label = QLabel("已绑定的链接：")
        title_label.setStyleSheet("font-weight:bold;")
        top_layout.addWidget(title_label)
        top_layout.addStretch()
        total_label = QLabel(f"总计：{len(self.stolen_img_link_data[name])}")
        total_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top_layout.addWidget(total_label)
        main_layout.addLayout(top_layout)

        # 滚动区域显示链接
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setStyleSheet("""
            QScrollArea {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                background-color: transparent;
            }
            QScrollBar:vertical {
                width: 10px;
                background: #f8f9fa;
                margin: 0px;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical {
                background: #ced4da;
                border-radius: 5px;
            }
            QScrollBar::handle:vertical:hover {
                background: #007bff;
            }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
                height: 0;
            }
        """)

        scroll_widget = QWidget()
        scroll_widget.setStyleSheet("""
            background-color: white;
            border-radius: 6px;
            padding: 5px;
        """)
        scroll_layout = QVBoxLayout(scroll_widget)
        scroll_layout.setContentsMargins(5, 5, 5, 5)
        scroll_layout.setSpacing(5)
        scroll_area.setWidget(scroll_widget)
        scroll_area.setFixedHeight(30 * 5)  # 高度约显示5条
        main_layout.addWidget(scroll_area)

        # 输入框 + 粘贴 + 添加
        input_layout = QHBoxLayout()
        link_edit = QLineEdit()
        link_edit.setPlaceholderText("请粘贴盗图侵权链接")
        paste_btn = QPushButton("粘贴")
        add_btn = QPushButton("添加")
        input_layout.addWidget(link_edit)
        input_layout.addWidget(paste_btn)
        input_layout.addWidget(add_btn)
        main_layout.addLayout(input_layout)

        # 自动添加选项 - 使用自定义滑动开关
        auto_add_layout = QHBoxLayout()
        auto_add_layout.setContentsMargins(3, 5, 0, 5)        
        auto_add_switch = ToggleSwitch()
        
        auto_add_label = QLabel("复制链接后自动添加")
        auto_add_label.setStyleSheet("color: #495057; font-size: 12px;")
        
        # 从配置文件读取自动添加状态
        auto_add_enabled = self.config.get("auto_add_clipboard_links", False)
        auto_add_switch.setChecked(auto_add_enabled)
        
        auto_add_layout.addWidget(auto_add_switch)  
        auto_add_layout.addWidget(auto_add_label)
        auto_add_layout.addStretch()
        main_layout.addLayout(auto_add_layout)

        # 剪切板监控相关变量
        clipboard = QApplication.clipboard()
        last_clipboard_text = clipboard.text().strip()
        clipboard_timer = QTimer()
        clipboard_timer.setInterval(200)  # 每200ms检查一次剪切板
        
        # 如果配置中启用了自动添加，则启动监控
        if auto_add_enabled:
            clipboard_timer.start()

        # 刷新显示
        def refresh_links():
            # 清空原有布局
            for i in reversed(range(scroll_layout.count())):
                item = scroll_layout.itemAt(i).widget()
                if item:
                    item.setParent(None)

            # 重新添加每条链接和删除按钮
            for link in self.stolen_img_link_data[name]:
                item_widget = QWidget()
                item_layout = QHBoxLayout(item_widget)
                item_layout.setContentsMargins(0, 0, 0, 0)
                item_layout.setSpacing(5)

                link_label = QLineEdit(link)
                link_label.setReadOnly(True)
                link_label.setStyleSheet("background:transparent; border:none;")
                link_label.setSizePolicy(link_label.sizePolicy().horizontalPolicy(),
                                        link_label.sizePolicy().verticalPolicy())

                delete_btn = QPushButton("x")
                delete_btn.setFixedWidth(30)
                delete_btn.setStyleSheet("""
                    QPushButton {
                        color: #495057;
                        font-weight: bold;
                        background-color: transparent;
                        border: none;
                    }
                    QPushButton:hover {
                        color: white;
                        background-color: #dc3545;
                        border-radius: 4px;
                    }
                    QPushButton:pressed {
                        background-color: #bd2130;
                    }
                """)

                # 绑定删除事件
                def make_delete(l=link):
                    def on_delete():
                        if l in self.stolen_img_link_data[name]:
                            self.stolen_img_link_data[name].remove(l)
                            refresh_links()
                    return on_delete

                delete_btn.clicked.connect(make_delete())

                item_layout.addWidget(delete_btn)
                item_layout.addWidget(link_label)
                scroll_layout.addWidget(item_widget)

            total_label.setText(f"总计：{len(self.stolen_img_link_data[name])}")

        refresh_links()  # 初始化显示

        # 添加链接的通用函数
        def add_link_to_list(link):
            if link and link not in self.stolen_img_link_data[name]:
                # 简单的链接格式验证
                if link.startswith(('http://', 'https://', 'www.')):
                    self.stolen_img_link_data[name].append(link)
                    refresh_links()
                    return True
            return False

        # 添加链接按钮逻辑
        def on_add():
            link = link_edit.text().strip()
            if add_link_to_list(link):
                link_edit.clear()
            else:
                QMessageBox.information(dialog, "提示", "该链接已存在或格式不正确，请检查后重试。")

        add_btn.clicked.connect(on_add)

        # 粘贴按钮逻辑
        def on_paste():
            clip_text = clipboard.text().strip()
            if clip_text:
                link_edit.setText(clip_text)

        paste_btn.clicked.connect(on_paste)

        # 剪切板监控逻辑
        def check_clipboard():
            nonlocal last_clipboard_text
            if auto_add_switch.isChecked():
                current_text = clipboard.text().strip()
                # 检查是否有新内容且不为空
                if current_text and current_text != last_clipboard_text:
                    # 简单验证是否为链接格式
                    if current_text.startswith(('http://', 'https://', 'www.')):
                        if add_link_to_list(current_text):
                            # 可选：显示提示信息
                            auto_add_label.setText(f"启用复制链接后自动添加 (已添加: {len(current_text) if len(current_text) <= 20 else current_text[:20] + '...'})")
                            QTimer.singleShot(2000, lambda: auto_add_label.setText("启用复制链接后自动添加"))
                    last_clipboard_text = current_text

        clipboard_timer.timeout.connect(check_clipboard)

        # 开关状态改变事件
        def on_auto_add_changed(state):
            nonlocal last_clipboard_text
            # 保存状态到配置文件
            self.config["auto_add_clipboard_links"] = state
            self.save_config()
            
            if state:
                last_clipboard_text = clipboard.text().strip()  # 重置基准
                clipboard_timer.start()
            else:
                clipboard_timer.stop()

        auto_add_switch.toggled.connect(on_auto_add_changed)

        # 对话框关闭时停止定时器
        def on_dialog_finished():
            clipboard_timer.stop()

        dialog.finished.connect(on_dialog_finished)

        dialog.exec_()

    # 复制路径       
    def copy_path(self, folder_data):
        """复制文件夹路径"""
        folder_path = folder_data.get("path", "")
        if folder_path:
            clipboard = QApplication.clipboard()
            clipboard.setText(folder_path)
            self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 已复制路径：{folder_path}")
            QTimer.singleShot(2000, lambda: self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}）"))

    # 编辑备注
    def edit_folder_remark(self, folder_data):
        """编辑文件夹备注"""
        folder_name = folder_data.get("name", "未知文件夹")
        folder_path = folder_data.get("path", "")
        
        # 获取当前备注
        current_remark = folder_data.get("remark", "")
        
        # 创建备注编辑对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑备注")
        dialog.setFixedSize(400, 300)
        dialog.setWindowModality(Qt.WindowModal)

        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        info_label = QLabel(f"文件夹：{folder_name}")
        info_label.setStyleSheet("font-weight: bold; margin: 0; padding: 0;")
        layout.addWidget(info_label)

        remark_text = QTextEdit()
        remark_text.setPlainText(current_remark)
        remark_text.setPlaceholderText("请输入备注信息...")
        layout.addWidget(remark_text)

        button_layout = QHBoxLayout()
        ok_button = QPushButton("确定")
        ok_button.clicked.connect(dialog.accept)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

        remark_text.setFocus()

        if dialog.exec_() == QDialog.Accepted:
            new_remark = remark_text.toPlainText().strip()
            folder_data["remark"] = new_remark  # 更新数据字典
            # 更新修改日期（自动使用当前时间）
            self.update_folder_field_value(folder_data, "modify_date")

            # 更新虚拟列表中对应 widget
            for index, data in enumerate(self.folder_list.items_data):
                if data == folder_data:
                    widget = self.folder_list.visible_widgets.get(index)
                    if widget and hasattr(widget, "remark_label"):
                        widget.remark_label.setText(new_remark)
                    break

            # 保存备注到【已修】子文件夹
            try:
                fixed_folder_path = os.path.join(folder_path, "已修")
                os.makedirs(fixed_folder_path, exist_ok=True)
                safe_name = "".join(c for c in folder_name if c not in "\\/:*?\"<>|")
                json_file_path = os.path.join(fixed_folder_path, f"{safe_name}_产品信息.json")
                
                # 保存 JSON，新增 name 字段
                with open(json_file_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "name": folder_name,
                        "remark": new_remark
                    }, f, ensure_ascii=False, indent=2)

                self.save_database()
            except Exception as e:
                QMessageBox.warning(self, "保存失败", f"无法保存产品信息文件：{e}")

    #更换缩略图
    def change_thumbnail(self, folder_data):
        """更换缩略图"""
        folder_name = folder_data.get("name", "未知文件夹")
        folder_path = folder_data.get("path", "")

        fixed_folder = os.path.join(folder_path, "已修")
        if not os.path.exists(fixed_folder):
            QMessageBox.warning(self, "警告", f"未找到 {fixed_folder}")
            return

        # 选择原图（默认打开已修文件夹）
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择新的缩略图原图",
            fixed_folder,
            "图片文件 (*.png *.jpg *.jpeg *.bmp *.gif)"
        )
        if not file_path:
            return

        # 生成缩略图（主线程）
        new_thumb_path = self._generate_thumbnail_from_image(file_path, folder_name)
        if new_thumb_path:
            # 更新数据字典
            folder_data["thumbnail"] = new_thumb_path
            # 更新修改日期（自动使用当前时间）
            self.update_folder_field_value(folder_data, "modify_date")

            # 缓存新的缩略图
            pixmap = QPixmap(new_thumb_path).scaled(70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.folder_list.thumbnail_cache[new_thumb_path] = pixmap

            # 更新虚拟列表中的可见 widget
            for index, data in enumerate(self.folder_list.items_data):
                if data == folder_data:
                    widget = self.folder_list.visible_widgets.get(index)
                    if widget:
                        widget.set_thumbnail(pixmap)
                    break

    def _generate_thumbnail_from_image(self, image_path, folder_name):
        """根据用户选择的图片生成 400x400 缩略图 (主线程调用)"""
        thumbnail_dir = os.path.join(os.getcwd(), "thumbnail")
        os.makedirs(thumbnail_dir, exist_ok=True)

        if not os.path.exists(image_path):
            return ""

        try:
            img = Image.open(image_path).convert("RGBA")
            img = img.resize((400, 400), Image.Resampling.LANCZOS)
            save_path = os.path.join(thumbnail_dir, f"{folder_name}.png")
            img.save(save_path, "PNG")
            return save_path
        except Exception as e:
            print(f"生成缩略图失败: {e}")
            return ""
    #---------以上是右键菜单逻辑------------------------------------------------

    #-----------------以下是生成原图证明文件压缩包逻辑----------------------------------------------
    def generate_original_proof(self, selected_data):
        """批量生成原图证明文件压缩包"""
        if not selected_data:
            return

        invalid_folders = []
        valid_folders = []

        for data in selected_data:
            folder_path = data.get("path", "")
            folder_name = os.path.basename(folder_path.rstrip(os.sep))

            if not os.path.exists(folder_path):
                invalid_folders.append(folder_name)
            else:
                valid_folders.append((folder_name, folder_path))
        
        if invalid_folders:
            QMessageBox.warning(self, "警告", f"以下文件夹不存在，将跳过处理：\n" + "\n".join(invalid_folders))
        
        if not valid_folders:
            return
        
        # 检查是否有原创摄影作品声明文件路径配置
        proof_file_path = self.config.get('proof_file_path', '')
        
        if not proof_file_path or not os.path.exists(proof_file_path):
            # 显示自定义提示对话框
            if not self.show_proof_file_dialog():
                return
            proof_file_path = self.config.get('proof_file_path', '')
            if not proof_file_path:
                return
        
        # 选择保存目录
        last_save_dir = self.config.get('last_save_directory', '')
        save_directory = QFileDialog.getExistingDirectory(
            self, "选择保存目录", last_save_dir
        )
        
        if not save_directory:
            return
        
        # 记住选择的目录
        self.config['last_save_directory'] = save_directory.replace('/', '\\')
        self.save_config()
        
        # 创建程序工作目录的临时文件夹
        app_dir = os.path.dirname(os.path.abspath(__file__))
        temp_base_dir = os.path.join(app_dir, "temp_work").replace('/', '\\')
        os.makedirs(temp_base_dir, exist_ok=True)
        
        # 创建进度对话框
        self.progress_dialog = QProgressDialog("准备开始处理...", "取消", 0, 100, self)
        self.progress_dialog.setWindowTitle("生成进度")
        self.progress_dialog.setWindowModality(Qt.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setMinimumWidth(500)  # 设置进度条更长
        self.progress_dialog.resize(500, 120)  # 设置对话框大小
        self.progress_dialog.show()
        
        # 创建并启动压缩线程
        self.zip_thread = ZipGeneratorThread(valid_folders, proof_file_path, save_directory, temp_base_dir)
        self.zip_thread.progress_updated.connect(self.update_progress)
        self.zip_thread.task_completed.connect(self.on_task_completed)
        self.zip_thread.all_completed.connect(self.on_all_completed)
        self.zip_thread.error_occurred.connect(self.on_error_occurred)
        # 新增：连接进度文本更新信号
        self.zip_thread.progress_text_updated.connect(self.update_progress_text)
        
        # 连接取消按钮
        self.progress_dialog.canceled.connect(self.cancel_zip_generation)
        
        self.zip_thread.start()
        self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 正在生成原图证明文件...")

    def update_progress(self, value):
        """更新进度条"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setValue(value)

    def update_progress_text(self, current_index, total_count, folder_name, task_detail):
        """更新进度对话框文本，不显示错误信息"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            # 只显示普通任务描述，过滤掉可能包含“出错”的 task_detail
            safe_detail = "" if "出错" in task_detail else task_detail
            progress_text = f"正在处理 ({current_index}/{total_count}): {folder_name}"
            if safe_detail:
                progress_text += f" - {safe_detail}"
            self.progress_dialog.setLabelText(progress_text)

    def on_task_completed(self, folder_name, result):
        """单个任务完成处理"""
        # 这个方法可以保留用于其他用途，文本更新现在由 update_progress_text 处理
        pass

    def on_error_occurred(self, folder_name, error_message):
        """错误处理"""
        print(f"处理 {folder_name} 时出错: {error_message}")

    def cancel_zip_generation(self):
        """取消压缩生成"""
        if hasattr(self, 'zip_thread') and self.zip_thread.isRunning():
            self.zip_thread.stop_processing()
            self.zip_thread.wait(3000)  # 等待3秒
            if self.zip_thread.isRunning():
                self.zip_thread.terminate()
        
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        self.status_label.setText("<span style='color: #ffdb29;'>●</span> 处理已取消")
        QTimer.singleShot(2000, lambda: self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}）"))
    
    def on_all_completed(self, results):
        """所有任务完成处理"""
        # 关闭进度对话框
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        # 清理临时目录
        try:
            app_dir = os.path.dirname(os.path.abspath(__file__))
            temp_base_dir = os.path.join(app_dir, "temp_work").replace('/', '\\')
            if os.path.exists(temp_base_dir):
                shutil.rmtree(temp_base_dir, ignore_errors=True)
        except:
            pass  # 忽略清理错误
        
        # 统计结果
        success_count = sum(1 for _, _, result in results if result == "成功")
        total_count = len(results)
        
        # 显示结果
        result_message = f"处理完成！\n\n成功: {success_count}/{total_count}\n\n"
        
        if success_count > 0:
            result_message += "成功生成的压缩包:\n"
            success_items = []
            for folder_name, zip_path, result in results:
                if result == "成功":
                    success_items.append(f"{folder_name}.zip")
            
            # 分列显示成功项目
            if len(success_items) >= 20:
                # 计算每列的项目数
                items_per_column = 20
                columns = []
                for i in range(0, len(success_items), items_per_column):
                    columns.append(success_items[i:i + items_per_column])
                
                # 计算每列的最大宽度
                max_width = max(len(item) for item in success_items)
                
                # 构建多列显示
                max_rows = max(len(col) for col in columns)
                for row in range(max_rows):
                    row_items = []
                    for col in columns:
                        if row < len(col):
                            row_items.append(col[row].ljust(max_width))
                        else:
                            row_items.append(" " * max_width)
                    result_message += "    ".join(row_items).rstrip() + "\n"
            else:
                # 少于20个项目，正常单列显示
                for item in success_items:
                    result_message += f"{item}\n"
        
        failed_count = total_count - success_count
        if failed_count > 0:
            result_message += f"\n失败: {failed_count} 个\n"
            failed_items = []
            for folder_name, _, result in results:
                if result != "成功":
                    failed_items.append(f"{folder_name}: {result}")
            
            # 分列显示失败项目
            if len(failed_items) >= 20:
                # 计算每列的项目数
                items_per_column = 20
                columns = []
                for i in range(0, len(failed_items), items_per_column):
                    columns.append(failed_items[i:i + items_per_column])
                
                # 计算每列的最大宽度
                max_width = max(len(item) for item in failed_items)
                
                # 构建多列显示
                max_rows = max(len(col) for col in columns)
                for row in range(max_rows):
                    row_items = []
                    for col in columns:
                        if row < len(col):
                            row_items.append(col[row].ljust(max_width))
                        else:
                            row_items.append(" " * max_width)
                    result_message += "    ".join(row_items).rstrip() + "\n"
            else:
                # 少于20个项目，正常单列显示
                for item in failed_items:
                    result_message += f"{item}\n"
        
        self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 处理完成: 成功 {success_count}/{total_count}")
        QMessageBox.information(self, "处理完成", result_message)
        self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}） ")   
    
    def show_proof_file_dialog(self):
        """显示原创摄影作品声明文件提示对话框"""
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("提示")
        msg_box.setText("请先提供【原创摄影作品声明】文件")
        msg_box.setIcon(QMessageBox.Information)
        
        # 添加自定义按钮
        template_button = msg_box.addButton("查看声明模板", QMessageBox.ActionRole)
        select_button = msg_box.addButton("选择声明文件", QMessageBox.ActionRole)
        cancel_button = msg_box.addButton("取消", QMessageBox.RejectRole)
        
        msg_box.exec_()
        
        clicked_button = msg_box.clickedButton()
        
        if clicked_button == template_button:
            # 查看声明模板
            self.open_template_file()
            return False
        elif clicked_button == select_button:
            # 选择声明文件
            return self.select_proof_file()
        else:
            return False
    
    def open_template_file(self):
        """打开原创摄影作品声明模板文件"""
        template_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "原创摄影作品声明模板.png").replace('/', '\\')
        
        if not os.path.exists(template_path):
            QMessageBox.warning(self, "文件不存在", f"模板文件不存在: {template_path}")
            return
        
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(template_path)
            elif system == "Darwin":  # macOS
                subprocess.run(["open", template_path])
            else:  # Linux
                subprocess.run(["xdg-open", template_path])
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开模板文件：{str(e)}")
    
    def select_proof_file(self):
        """选择原创摄影作品声明文件"""
        proof_file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "选择原创摄影作品声明文件",
            "",
            "所有文件 (*.*)"
        )
        
        if proof_file_path:
            # 保存配置
            self.config['proof_file_path'] = proof_file_path.replace('/', '\\')
            self.save_config()
            return True
        
        return False
    
    def copy_subfolders_only(self, source_path, target_path):
        """只复制子文件夹，不复制文件"""
        try:
            for item in os.listdir(source_path):
                source_item_path = os.path.join(source_path, item).replace('/', '\\')
                target_item_path = os.path.join(target_path, item).replace('/', '\\')
                
                if os.path.isdir(source_item_path):
                    # 复制整个子文件夹
                    shutil.copytree(source_item_path, target_item_path)
                    
        except Exception as e:
            raise Exception(f"复制子文件夹时出错: {str(e)}")
    
    def create_zip(self, source_folder, zip_path, folder_name):
        """创建压缩包"""
        try:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                # 遍历源文件夹
                for root, dirs, files in os.walk(source_folder):
                    for file in files:
                        file_path = os.path.join(root, file).replace('/', '\\')
                        # 计算在压缩包中的相对路径
                        arcname = os.path.relpath(file_path, source_folder).replace('/', '\\')
                        zipf.write(file_path, arcname)
                    
                    # 为空文件夹创建条目
                    if not files and not dirs:
                        folder_path = os.path.relpath(root, source_folder).replace('/', '\\') + '\\'
                        zipf.writestr(folder_path, '')
                        
        except Exception as e:
            raise Exception(f"创建压缩包时出错: {str(e)}")
    
    def browse_folder(self):
        """浏览选择文件夹"""
        # 记住上次选择的文件夹
        last_folder = self.config.get('last_browse_folder', '')
        folder_path = QFileDialog.getExistingDirectory(self, "选择要扫描的文件夹", last_folder)
        if folder_path:
            self.folder_path_edit.setText(folder_path)
            # 记住这次选择的文件夹
            self.config['last_browse_folder'] = folder_path.replace('/', '\\')
            self.save_config()
    #-----------------以上是生成原图证明文件压缩包逻辑----------------------------------------------
    
    # -------------------- 以下为扫描逻辑 --------------------
    def scan_and_add(self):
        folder_path = self.folder_path_edit.text().strip()
        search_term = self.search_term_edit.text().strip()
        self.config['last_search_term'] = search_term.replace('/', '\\')
        self.save_config()

        if not folder_path:
            QMessageBox.warning(self, "警告", "请先选择要扫描的文件夹！")
            return
        if not search_term:
            QMessageBox.warning(self, "警告", "请输入子文件夹名称关键词！")
            return
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "警告", "选择的文件夹不存在！")
            return

        self.add_button.setEnabled(False)
        self.add_button.setText("扫描中...")
        self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 正在扫描文件夹: {folder_path}")

        self.scanner_thread = FolderScanner(folder_path, search_term, added_paths=self.added_folder_paths)

        # 接收日期字段
        self.scanner_thread.folder_found.connect(
            lambda name, path, thumb, remark, _, modify_date: self.add_folder_realtime({
                'name': name,
                'path': path,
                'thumbnail': thumb,
                'remark': remark,
                'add_date': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # 扫描时的时间
                'modify_date': modify_date
            })
        )
        self.scanner_thread.scan_finished.connect(self.scan_completed)
        self.scanner_thread.update_status.connect(self.update_status_label)

        self.scanner_thread.start()

    def update_status_label(self, text):
        self.status_label.setText(text)
        QApplication.processEvents()  # 强制刷新界面
        
    def add_folder_realtime(self, folder):
        """单条数据实时添加到虚拟列表（最新添加在最上面）"""
        path = folder.get("path", "")
        if not path or path in self.added_folder_paths:
            return

        # 添加到数据源开头
        self.folders_data.insert(0, folder)
        self.added_folder_paths.add(path)

        # 刷新虚拟列表
        self.folder_list.set_data(self.folders_data[:])  # 传副本，避免引用问题
        QApplication.processEvents()  # 强制刷新界面

    def scan_completed(self, found_count, skipped_count):
        self.sort_folders() #应用排序
        # 恢复按钮状态
        self.add_button.setEnabled(True)  # 重新启用按钮
        self.add_button.setText("写入数据库")  
        status_text = f"<span style='color: #ffdb29;'>●</span> 扫描完成，找到 {found_count} 个匹配的文件夹，跳过了 {skipped_count} 个已添加的文件夹"
        self.status_label.setText(status_text)

        msg = f"成功写入 {found_count} 个文件夹到数据库！\n\n"
        msg += f"跳过 {skipped_count} 个已在数据库的文件夹。\n"

        if found_count > 0:
            msg += f"总计：新增 {found_count} 个，跳过 {skipped_count} 个。"
        else:
            msg += "未扫描到新的匹配文件夹。"

        QMessageBox.information(self, "扫描完成", msg)
        self.total_num = self.total_num + found_count
        self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}） ")
        self.save_database()
  # -------------------- 以上为扫描逻辑 --------------------

    #搜索文件夹
    def filter_folders(self):
        """根据搜索词过滤虚拟列表文件夹（匹配路径最后一级目录名 + 备注，支持多关键字 OR）"""
        search_text = self.db_search_edit.text().lower().strip()
        keywords = [kw for kw in search_text.split() if kw]

        if not keywords:
            # 没输入关键字 → 显示全部
            filtered_data = self.folders_data[:]
        else:
            # 匹配最后一级目录名或备注
            filtered_data = []
            for f in self.folders_data:
                folder_last = os.path.basename(f.get('path', '')).lower()
                remark = f.get('remark', '').lower()
                if any(kw in folder_last or kw in remark for kw in keywords):
                    filtered_data.append(f)

        # 更新虚拟列表
        self.folder_list.set_data(filtered_data)
        self.total_num = len(filtered_data)
        self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}）")

    #双击打开文件夹目录
    def open_folder(self, index_or_data):
        """
        打开文件夹，可以传 index（int）或 data（dict）
        """
        # 如果传的是整数，则获取数据字典
        if isinstance(index_or_data, int):
            index = index_or_data
            try:
                data = self.folder_list.items_data[index]
            except IndexError:
                QMessageBox.warning(self, "警告", f"索引超出范围: {index}")
                return
        elif isinstance(index_or_data, dict):
            data = index_or_data
        else:
            QMessageBox.warning(self, "警告", f"无效参数: {index_or_data}")
            return

        folder_path = data.get("path", "")
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "警告", f"文件夹不存在：{folder_path}")
            return

        try:
            normalized_path = folder_path.replace('/', '\\')
            system = platform.system()
            if system == "Windows":
                try:
                    os.startfile(normalized_path)
                except OSError:
                    subprocess.Popen(
                        ['explorer', normalized_path],
                        shell=False,
                        creationflags=subprocess.CREATE_NO_WINDOW
                    )
            elif system == "Darwin":
                subprocess.run(["open", normalized_path], check=True)
            else:
                subprocess.run(["xdg-open", normalized_path], check=True)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件夹：{folder_path}\n错误: {str(e)}")

    #删除文件夹
    def delete_folders(self, selected_data_list):
        """
        删除虚拟列表中的文件夹记录及缩略图
        selected_data_list: list[dict]，每个元素都是 folder_data
        """
        try:
            folder_count = len(selected_data_list)
            if folder_count == 0:
                return

            # 收集文件夹名称用于提示
            folder_names = [f.get("name", "未知文件夹") for f in selected_data_list]

            # 弹出确认对话框
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定要从数据库中删除选中的 {folder_count} 个文件夹记录吗？\n\n" +
                "\n".join(folder_names) + 
                "\n\n此操作会同时删除相关缩略图，但不会影响源文件夹",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply != QMessageBox.Yes:
                return  # 用户取消删除

            # 删除数据库记录
            paths_to_delete = [f.get("path") for f in selected_data_list]
            self.folders_data = [f for f in self.folders_data if f.get('path') not in paths_to_delete]
            self.save_database()

            # 删除虚拟列表中的记录
            new_items_data = [f for f in self.folder_list.items_data if f.get("path") not in paths_to_delete]
            self.folder_list.set_data(new_items_data)  # 重置虚拟列表数据

            # 删除缩略图
            for f in selected_data_list:
                thumb_path = f.get("thumbnail")
                if thumb_path and os.path.exists(thumb_path):
                    try:
                        os.remove(thumb_path)
                    except Exception as e:
                        print(f"删除缩略图失败: {thumb_path} -> {e}")
                self.added_folder_paths.discard(f.get("path"))

            # 更新状态栏
            self.total_num = len(self.folder_list.items_data)
            self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}）")
            QMessageBox.information(
                self,
                "删除成功",
                f"已删除 {folder_count} 个文件夹记录及其缩略图:\n" + "\n".join(folder_names)
            )

        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"删除文件夹记录时发生错误：\n{str(e)}")

    #清空数据库
    def clear_database(self):
        """清空数据库"""
        reply = QMessageBox.question(
            self, "确认", "确定要清空整个产品图库数据库吗？此操作不可撤销，会删除所有缩略图，但不会影响源文件夹",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            # 删除所有缩略图
            thumbnail_dir = os.path.join(os.getcwd(), "thumbnail")
            if os.path.exists(thumbnail_dir):
                for file in os.listdir(thumbnail_dir):
                    if file.lower().endswith('.png'):
                        try:
                            os.remove(os.path.join(thumbnail_dir, file))
                        except Exception as e:
                            print(f"删除缩略图失败: {file} -> {e}")

            # 清空数据库
            self.folders_data.clear()
            self.added_folder_paths.clear()
            self.folder_list.set_data([])
            self.save_database()
            self.status_label.setText("<span style='color: #ffdb29;'>●</span> 数据库已清空，所有缩略图已删除")
            QMessageBox.information(self, "完成", "数据库已清空，所有缩略图已删除！")
            self.total_num = 0
            self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}） ")

    #刷新数据库
    def refresh_folder_list(self):
        """刷新文件夹列表"""
        self.folder_list.set_data(self.folders_data[:])
        self.save_database()

    #更新文件夹字段
    def update_folder_field_value(self, folder_data, key, value=None, save_db=True):
        """
        更新指定字段的值，不影响其他字段
        folder_data: 虚拟列表中某个数据项的字典引用
        key: 要修改的字段名，例如 'add_date' 或 'modify_date'
        value: 新值，如果 key 是 'modify_date' 则忽略，使用当前时间
        save_db: 是否更新数据库文件
        """
        if not folder_data or key not in folder_data:
            return

        if key == "modify_date":
            folder_data[key] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            folder_data[key] = value

        if save_db:
            self.save_database()

    
  # -------------------- 以下为加载数据库逻辑 --------------------
    def load_database(self):
        """首次启动时加载数据库"""
        if self.database_load_finished:
            print("[load_database] 数据库已加载，跳过")
            return

        self.folders_data = []
        self.added_folder_paths.clear()
        # 注意：虚拟列表不需要clear()，因为没有实际的item

        self.load_thread = LoadFoldersThread(self.database_file)
        self.load_thread.batch_loaded.connect(self.add_folders_batch_realtime)
        self.load_thread.load_finished.connect(self.on_load_finished)
        self.load_thread.start()

    def add_folders_batch_realtime(self, batch, current, total):
        """批量更新虚拟列表"""
        for folder in batch:
            path = folder.get("path", "")
            if path and path not in self.added_folder_paths:
                self.folders_data.append(folder)
                self.added_folder_paths.add(path)

        # 更新总数
        self.total_num = total

        # 刷新虚拟列表
        self.folder_list.set_data(self.folders_data[:])
        self.status_label.setText(f"<span style='color: #ffdb29;'>●</span> 正在收集数据 {current}/{total}")
        QApplication.processEvents()

    def on_load_finished(self, total=0):
        """数据库加载完成"""
        # 最终更新虚拟列表
        self.folder_list.set_data(self.folders_data[:])
        
        self.status_label.setText(f"<span style='color: #00d26a;'>●</span> 就绪 （总计：{self.total_num}）")

        self.database_load_finished = True
        # self.save_database()
        
        # 显示性能统计
        stats = self.folder_list.get_performance_stats()
        print(f"[性能统计] 渲染次数: {stats['render_count']}, 缓存命中: {stats['cache_hits']}")
  # -------------------- 以上为加载数据库逻辑 --------------------

    #保存数据库
    def save_database(self):
        """保存数据库到JSON文件，并更新列表项ToolTip"""
        try:
            for index, folder_data in enumerate(self.folders_data):
                remark = folder_data.get('remark', '')
                path = folder_data.get('path', '')

                # 如果当前 widget 可见，更新它的 ToolTip
                widget = self.folder_list.visible_widgets.get(index)
                if widget:
                    widget.setToolTip(f"{path}\n{remark}" if remark else path)

            # 保存数据库到 JSON 文件
            with open(self.database_file, 'w', encoding='utf-8') as f:
                json.dump(self.folders_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存数据库失败：{str(e)}\n请以管理员身份运行此程序！")

    #加载配置文件
    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败：{str(e)}")
        
        return {}
    
    #保存配置文件
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败：{str(e)}\n请以管理员身份运行此程序！")

    #检查更新
    def check_update(self):
        """显示更新对话框"""
        dialog = UpdateDialog(self, CURRENT_VERSION)
        dialog.exec_()
    
    # 关闭程序时保存数据库和配置
    def closeEvent(self, event):
        """程序关闭时保存数据库和配置"""
        if not self.database_load_finished:
            QMessageBox.information(self, "提示", "请等待数据库加载完成再关闭程序")
            event.ignore()
            return
        
        if self.scanner_thread and self.scanner_thread.isRunning():
            self.scanner_thread.terminate()
            self.scanner_thread.wait()
        
        if hasattr(self, 'zip_thread') and self.zip_thread and self.zip_thread.isRunning():
            self.zip_thread.terminate()
            self.zip_thread.wait()
        
        self.save_database()
        self.save_config()
        event.accept()

def main():
    app = QApplication(sys.argv)
    
    # 设置应用程序样式
    app.setStyle('Fusion')
    
    # 创建主窗口
    window = FolderDatabaseApp()
    window.show()
    
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
