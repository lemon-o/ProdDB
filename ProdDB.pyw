import sys
import os
import json
import subprocess
import platform
import shutil
import time
import zipfile
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QLineEdit, QListWidget, QLabel, 
                             QFileDialog, QMessageBox, QSplitter, QGroupBox, QListWidgetItem,
                             QMenu, QAction, QProgressDialog, QAbstractItemView, QDialog, QTextEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize, QPoint, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter
from PIL import Image, ImageFile
ImageFile.LOAD_TRUNCATED_IMAGES = True  # 避免损坏图片报错


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
    
    def stop_processing(self):
        """停止压缩处理"""
        self.should_stop = True
    
    def run(self):
        """在后台线程中生成压缩包"""
        total_tasks = len(self.folders_data)
        
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
                # 任务完成后的进度更新
                progress = int((i + 1) * 100 / total_tasks)
                self.progress_updated.emit(progress)
        
        if not self.should_stop:
            self.all_completed.emit(self.results)
    
    def create_single_zip_with_progress(self, folder_name, folder_path, zip_path, task_index, total_tasks):
        """创建单个压缩包并提供进度反馈"""
        work_dir = os.path.join(self.temp_dir, f"work_{folder_name}").replace('/', '\\')
        os.makedirs(work_dir, exist_ok=True)

        try:
            current_index = task_index + 1
            
            # 步骤1: 统计文件数量（占总进度的5%）
            self.current_task.emit("统计文件", f"统计 {folder_name} 中的文件数量...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "统计文件数量")
            total_files = self.count_files_in_directory(folder_path)
            self.update_task_progress(task_index, total_tasks, 0.05)  # 5%
            
            if self.should_stop:
                return
            
            # 在 work_dir 下直接放子文件夹内容
            temp_folder_path = work_dir
            os.makedirs(temp_folder_path, exist_ok=True)

            # 步骤2: 复制子文件夹（占总进度的20%）
            self.current_task.emit("复制文件", f"复制 {folder_name} 的子文件夹...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "复制子文件夹")
            self.copy_subfolders_only_with_progress(folder_path, temp_folder_path, task_index, total_tasks, 0.05, 0.25)
            
            if self.should_stop:
                return

            # 步骤3: 复制声明文件（占总进度的5%）
            self.current_task.emit("复制声明", f"复制原图声明文件...")
            self.progress_text_updated.emit(current_index, total_tasks, folder_name, "复制声明文件")
            proof_filename = os.path.basename(self.proof_file_path)
            temp_proof_path = os.path.join(temp_folder_path, proof_filename).replace('/', '\\')
            shutil.copy2(self.proof_file_path, temp_proof_path)
            self.update_task_progress(task_index, total_tasks, 0.3)  # 30%
            
            if self.should_stop:
                return

            # 步骤4: 压缩文件（占总进度的70%）
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
            last_progress = -1
            
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
                            
                            # 计算压缩进度
                            if estimated_files > 0:
                                file_progress = min(processed_files / estimated_files, 1.0)
                                current_progress = start_progress + (end_progress - start_progress) * file_progress
                                
                                # 只在进度有明显变化时更新（避免过于频繁）
                                progress_int = int(current_progress * 100)
                                if progress_int != last_progress:
                                    self.update_task_progress(task_index, total_tasks, current_progress)
                                    last_progress = progress_int
                                    
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
            
            # 确保压缩完成时进度达到100%
            if not self.should_stop:
                self.update_task_progress(task_index, total_tasks, end_progress)
                
        except Exception as e:
            raise Exception(f"创建压缩包时出错: {str(e)}")
    
    def update_task_progress(self, task_index, total_tasks, task_progress):
        """更新任务进度"""
        if self.should_stop:
            return
            
        # 计算总体进度
        base_progress = task_index / total_tasks
        current_task_contribution = task_progress / total_tasks
        overall_progress = int((base_progress + current_task_contribution) * 100)
        
        # 确保进度在合理范围内
        overall_progress = max(0, min(100, overall_progress))
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

# -------------------- 子线程 扫描文件夹 --------------------
class FolderScanner(QThread):
    folder_found = pyqtSignal(str, str, str)  # name, path, thumbnail_path
    scan_finished = pyqtSignal(int, int)      # found_count, skipped_count
    update_status = pyqtSignal(str)           # 实时状态

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
                    # 实时更新状态
                    self.update_status.emit(
                        f"扫描中：{item_path}\n已找到：{self.found_count} 个，已跳过：{self.skipped_count} 个"
                    )

                    # 已添加路径跳过
                    if item_path in self.added_paths:
                        self.skipped_count += 1
                        continue

                    # 匹配关键词
                    if self.search_term in item.lower():
                        if item_path not in self.scanned_paths:
                            self.scanned_paths.add(item_path)

                            # 只扫描匹配文件夹里的 "已修" 子文件夹
                            fixed_folder = os.path.join(item_path, "已修")
                            thumbnail_path = ""
                            if os.path.exists(fixed_folder):
                                # 生成缩略图（如果有图片）
                                thumbnail_path = self._generate_thumbnail(item_path, item)

                            # 发射信号
                            self.folder_found.emit(item, item_path, thumbnail_path)
                            self.found_count += 1

                        # 不再递归扫描子目录
                        continue

                    # 如果不是匹配文件夹，继续递归扫描子目录
                    self._scan_directory(item_path)

        except (PermissionError, OSError):
            pass

    def _generate_thumbnail(self, folder_path, folder_name):
        """生成 400x400 缩略图"""
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
class ZoomableLabel(QLabel):
    def __init__(self, image_path):
        super().__init__()
        self.pixmap_orig = QPixmap(image_path)
        self.setPixmap(self.pixmap_orig)
        self.setAlignment(Qt.AlignCenter)
        self.scale_factor = 1.0
        self.offset = QPoint(0, 0)  # 图片相对于 QLabel 的偏移，用于拖动
        self.last_pos = None
        self.setMouseTracking(True)
        self.setMinimumSize(1, 1)

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

    def mouseMoveEvent(self, event):
        if self.last_pos is not None:
            # 计算移动的偏移量
            delta = event.pos() - self.last_pos
            self.offset += delta
            self.last_pos = event.pos()
            self.update_pixmap()

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
        self.setFixedSize(425, 425)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.offset = offset
        self.main_window = main_window
        if main_window:
            self.setWindowIcon(main_window.windowIcon())

        layout = QVBoxLayout(self)
        self.label = ZoomableLabel(image_path)
        layout.addWidget(self.label)

    def showEvent(self, event):
        super().showEvent(event)
        if self.main_window:
            main_geom = self.main_window.frameGeometry()
            main_center = main_geom.center()
            dialog_geom = self.frameGeometry()
            dialog_geom.moveCenter(main_center)
            self.move(dialog_geom.topLeft() + self.offset)

# ------------------ 文件夹列表项 Widget ------------------
class FolderItemWidget(QWidget):
    def __init__(self, name, thumbnail_path=None, note=''):
        super().__init__()
        self.thumbnail_path = thumbnail_path
        self.note = note
        self.preview_window = None  # 保存预览窗口引用

        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 0, 0, 0)
        layout.setSpacing(5)
        layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)

        # 文件夹名称
        self.name_label = QLabel(name)
        self.name_label.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        self.name_label.setFixedWidth(100)
        layout.addWidget(self.name_label)

        # 缩略图容器 70x70
        self.icon_label = ClickableLabel()
        self.icon_label.setFixedSize(70, 70)
        self.icon_label.setStyleSheet("border:1px solid #ccc;")
        if thumbnail_path and os.path.exists(thumbnail_path):
            pixmap = QPixmap(thumbnail_path).scaled(
                70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.icon_label.setPixmap(pixmap)
            self.icon_label.clicked.connect(self.show_preview)
        layout.addWidget(self.icon_label)

        # 备注信息区域（垂直布局）
        self.info_layout = QVBoxLayout()
        self.info_layout.setContentsMargins(30, 5, 10, 5)
        self.info_layout.setSpacing(5)
        self.info_layout.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        
        # 备注标签（如果有备注才显示）
        self.note_label = QLabel()
        self.note_label.setWordWrap(True)
        self.note_label.setStyleSheet("""
            color: #495057; 
            font-size: 12px; 
        """)
        self.update_note_display()
        self.info_layout.addWidget(self.note_label)

        # 在缩略图后面插入弹簧，把 info_layout 推到最右边
        layout.addStretch(1)

        layout.addLayout(self.info_layout)

    def show_preview(self):
        if self.thumbnail_path and os.path.exists(self.thumbnail_path):
            # 直接传主窗口实例
            main_window = QApplication.activeWindow()  
            self.preview_window = PreviewDialog(
                self.thumbnail_path, main_window=main_window, offset=QPoint(150, 170) #预览窗口偏移距离
            )
            self.preview_window.show()

    def update_thumbnail(self, new_path):
        """更新缩略图"""
        self.thumbnail_path = new_path
        if new_path and os.path.exists(new_path):
            pixmap = QPixmap(new_path)
            pixmap = pixmap.scaled(
                70, 70, Qt.KeepAspectRatio, Qt.SmoothTransformation
            )
            self.icon_label.setPixmap(pixmap)
            # 重新连接点击事件
            if not self.icon_label.clicked.connect(self.show_preview):
                self.icon_label.clicked.connect(self.show_preview)

    def update_note(self, note):
        """更新备注显示"""
        self.note = note
        self.update_note_display()
    def update_note_display(self):
        """更新备注显示状态"""
        self.note_label.setText(self.note)
    def get_note(self):
        """获取当前备注"""
        return self.note

    def set_name(self, name):
        """设置文件夹名称"""
        self.name_label.setText(name)

# -------------------- 子线程 加载数据库 --------------------
class LoadFoldersThread(QThread):
    folder_loaded = pyqtSignal(dict, int, int)  # 增加当前索引 & 总数
    load_finished = pyqtSignal(int)             # 加载完成时传递总数

    def __init__(self, database_file):
        super().__init__()
        self.database_file = database_file

    def run(self):
        if not os.path.exists(self.database_file):
            print(f"[LoadFoldersThread] 数据库文件不存在：{self.database_file}")
            self.load_finished.emit(0)
            return

        try:
            import json, time
            with open(self.database_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, list):
                total = len(data)
                for i, folder in enumerate(data, start=1):
                    self.folder_loaded.emit(folder, i, total)
                    time.sleep(0.01)
            else:
                print("[LoadFoldersThread] JSON 格式错误，期望 list")
                total = 0
        except Exception as e:
            print(f"[LoadFoldersThread] 加载数据库失败：{e}")
            total = 0
        finally:
            self.load_finished.emit(total)


# -------------------- 主程序 --------------------
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
        self.added_folder_paths = set()  # 用于记录所有已经添加到数据库的文件夹路径
        self.folders_data = []
        self.database_load_finished = False
        self.total_num = 0
        
        self.init_ui()
        self.center_window()  # 窗口居中

        # 启动子线程加载数据（不阻塞UI）
        self.load_thread = LoadFoldersThread(self.database_file)
        self.load_thread.folder_loaded.connect(self.add_folder_to_list_realtime)  # 每加载一个文件夹就显示
        self.load_thread.load_finished.connect(self.on_load_finished)    # 所有加载完成后调用
        self.load_thread.start()
        
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
            
            /* 危险按钮（清空数据库） */
            QPushButton#clearButton {
                background-color: #f5f5f5;
                color: #495057;
            }
            
            QPushButton#clearButton:hover {
                background-color: #dc3545;
                color: white;
            }
            
            QPushButton#clearButton:pressed {
                background-color: #bd2130;
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
            
            /* 标签样式 */
            QLabel {
                color: #495057;
                font-size: 13px;
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
                padding: 0 8px 0 8px;
                background-color: white;
            }
            
            /* 列表控件样式 */
            QListWidget {
                border: 2px solid #e9ecef;
                border-radius: 6px;
                background-color: white;
                alternate-background-color: #f8f9fa;
                selection-background-color: #e3f2fd;
                selection-color: #1976d2;
                font-size: 13px;
                padding: 4px;
            }
            
            QListWidget::item {
                border-radius: 4px;
                padding: 8px 12px;
                margin: 1px 0px;
            }
            
            QListWidget::item:hover {
                background-color: #f0f8ff;
            }
            
            QListWidget::item:selected {
                background-color: #e3f2fd;
                color: #1976d2;
                border: 1px solid #90caf9;
            }
            
            QListWidget::item:selected:active {
                background-color: #bbdefb;
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
            
            /* 工具提示样式 */
            QToolTip {
                background-color: #343a40;
                color: white;
                border: none;
                border-radius: 4px;
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
        splitter.setSizes([200, 400])
        
        # 状态标签
        self.status_label = QLabel("🟢就绪")
        self.status_label.setObjectName("statusLabel")
        main_layout.addWidget(self.status_label)

    def create_control_panel(self):
        """创建控制面板"""
        group_box = QGroupBox("扫描控制")
        layout = QVBoxLayout(group_box)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 文件夹选择行
        folder_layout = QHBoxLayout()
        folder_layout.setSpacing(10)
        
        # folder_label = QLabel("扫描文件夹:")
        # folder_label.setMinimumWidth(80)
        # folder_layout.addWidget(folder_label)
        
        self.folder_path_edit = QLineEdit()
        self.folder_path_edit.setPlaceholderText("点击'选择文件夹'按钮选择要扫描的根目录")
        self.folder_path_edit.setReadOnly(True)
        self.folder_path_edit.setMinimumHeight(36)
        folder_layout.addWidget(self.folder_path_edit)
        
        self.browse_button = QPushButton("选择文件夹")
        self.browse_button.setObjectName("selectButton")
        self.browse_button.clicked.connect(self.browse_folder)
        self.browse_button.setMinimumWidth(120)
        self.browse_button.setToolTip("点击选择要扫描的根目录")
        folder_layout.addWidget(self.browse_button)
        
        layout.addLayout(folder_layout)
        
        # 搜索词输入行
        search_layout = QHBoxLayout()
        search_layout.setSpacing(10)
        
        # search_label = QLabel("搜索词:")
        # search_label.setMinimumWidth(80)
        # search_layout.addWidget(search_label)
        
        self.search_term_edit = QLineEdit()
        self.search_term_edit.setPlaceholderText("输入要写入数据库的子文件夹名称关键词，例如: LM")
        self.search_term_edit.setMinimumHeight(36)
        
        # 加载上次保存的搜索词
        last_search_term = self.config.get('last_search_term', '')
        if last_search_term:
            self.search_term_edit.setText(last_search_term)
        
        search_layout.addWidget(self.search_term_edit)
        
        self.add_button = QPushButton("写入数据库")
        self.add_button.clicked.connect(self.scan_and_add)
        self.add_button.setMinimumWidth(120)
        self.add_button.setToolTip("扫描并添加匹配的文件夹到数据库")
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
        
        # search_label = QLabel("搜索数据库:")
        # search_label.setMinimumWidth(90)
        # db_search_layout.addWidget(search_label)
        
        self.db_search_edit = QLineEdit()
        self.db_search_edit.setPlaceholderText("输入关键词搜索已保存的文件夹，可用空格分隔多个关键词")
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
        
        self.clear_db_button = QPushButton("清空数据库")
        self.clear_db_button.setObjectName("clearButton")
        self.clear_db_button.clicked.connect(self.clear_database)
        self.clear_db_button.setMinimumWidth(120)
        self.clear_db_button.setToolTip("清空所有数据库记录")
        db_search_layout.addWidget(self.clear_db_button)
        
        layout.addLayout(db_search_layout)
        
        # 文件夹列表
        self.folder_list = QListWidget()
        self.folder_list.itemDoubleClicked.connect(self.open_folder)
        self.folder_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.folder_list.customContextMenuRequested.connect(self.show_context_menu)
        # 设置多选模式
        self.folder_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.folder_list.setAlternatingRowColors(True)
        
        layout.addWidget(self.folder_list)
        
        return group_box

    def show_context_menu(self, position):
        """显示右键菜单"""
        selected_items = self.folder_list.selectedItems()
        if not selected_items:
            return
        context_menu = QMenu(self)
        context_menu.setFixedWidth(200)

        # 生成原图证明文件
        generate_text = f"生成原图证明文件 ({len(selected_items)}个)" if len(selected_items) > 1 else "生成原图证明文件"
        generate_action = QAction(generate_text, self)
        generate_action.setToolTip("为选中的文件夹生成原图证明文档")
        generate_action.triggered.connect(lambda: self.generate_original_proof(selected_items))
        context_menu.addAction(generate_action)
        
        context_menu.addSeparator()
        
        # 编辑备注操作（仅单选时显示）
        if len(selected_items) == 1:
            context_menu.addSeparator()
            edit_note_action = QAction("编辑备注", self)
            edit_note_action.setToolTip("编辑此文件夹的备注信息")
            edit_note_action.triggered.connect(lambda: self.edit_folder_note(selected_items[0]))
            context_menu.addAction(edit_note_action)
        
        # 更换缩略图操作
        if len(selected_items) == 1:
            context_menu.addSeparator()
            change_thumb_action = QAction("更换缩略图", self)
            change_thumb_action.setToolTip("选择新图片作为此文件夹的缩略图")
            change_thumb_action.triggered.connect(lambda: self.change_thumbnail(selected_items[0]))
            context_menu.addAction(change_thumb_action)
        
        # 打开文件夹操作（仅单选时才显示）
        if len(selected_items) == 1:
            context_menu.addSeparator()
            open_action = QAction("打开文件夹", self)
            open_action.setToolTip("在文件资源管理器中打开此文件夹")
            open_action.triggered.connect(lambda: self.open_folder(selected_items[0]))
            context_menu.addAction(open_action)

        context_menu.addSeparator()

        # 删除操作
        delete_text = f"从数据库中删除 ({len(selected_items)}个)" if len(selected_items) > 1 else "从数据库中删除"
        delete_action = QAction(delete_text, self)
        delete_action.setToolTip("从数据库中删除选中的文件夹记录")
        delete_action.triggered.connect(lambda: self.delete_folders(selected_items))
        context_menu.addAction(delete_action)
        
        # 显示菜单
        context_menu.exec_(self.folder_list.mapToGlobal(position))

    def edit_folder_note(self, item):
        """编辑文件夹备注"""
        folder_path = item.data(Qt.UserRole)
        
        # 从 folders_data 中找到对应的文件夹数据
        folder_data = None
        folder_index = None
        for i, folder in enumerate(self.folders_data):
            if folder.get('path') == folder_path:
                folder_data = folder
                folder_index = i
                break
        
        if folder_data is None:
            QMessageBox.warning(self, "警告", "未找到文件夹数据")
            return
        
        # 获取当前备注
        current_note = folder_data.get('note', '')
        
        # 创建备注编辑对话框
        dialog = QDialog(self)
        dialog.setWindowTitle("编辑备注")
        dialog.setFixedSize(400, 300)
        dialog.setWindowModality(Qt.WindowModal)

        # 布局
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(5, 5, 5, 5)  # 控制布局的四周间距
        layout.setSpacing(10)  # 控件之间的间距

        # 文件夹信息标签
        folder_name = folder_data.get('name', '未知文件夹')
        info_label = QLabel(f"文件夹：{folder_name}")
        info_label.setStyleSheet("font-weight: bold; margin: 0; padding: 0;")
        layout.addWidget(info_label)

        # 备注输入框
        note_text = QTextEdit()
        note_text.setPlainText(current_note)
        note_text.setPlaceholderText("请输入备注信息...")
        layout.addWidget(note_text)
        
        # 按钮布局
        button_layout = QHBoxLayout()
        
        # 确定按钮
        ok_button = QPushButton("确定")
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        
        # 取消按钮
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(dialog.reject)
        button_layout.addWidget(cancel_button)
        
        layout.addLayout(button_layout)
        
        # 设置焦点到文本框
        note_text.setFocus()
        
        # 显示对话框
        if dialog.exec_() == QDialog.Accepted:
            # 获取新的备注内容
            new_note = note_text.toPlainText().strip()
            
            # 更新 folders_data 中的备注
            self.folders_data[folder_index]['note'] = new_note
            
            # 更新列表显示（如果您的 FolderItemWidget 支持显示备注）
            widget = self.folder_list.itemWidget(item)
            if hasattr(widget, 'update_note'):
                widget.update_note(new_note)

    def change_thumbnail(self, item):
        """更换缩略图"""
        widget = self.folder_list.itemWidget(item)
        folder_name = widget.name_label.text()
        folder_path = item.data(Qt.UserRole)

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
            widget.update_thumbnail(new_thumb_path)

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

    #-----------------以下是生成原图证明文件压缩包逻辑----------------------------------------------
    def generate_original_proof(self, selected_items):
        """批量生成原图证明文件压缩包"""
        if not selected_items:
            return
        
        # 检查所有文件夹是否存在
        invalid_folders = []
        valid_folders = []
        
        for item in selected_items:
            folder_path = item.data(Qt.UserRole)
            # 从路径中取最后一部分作为 folder_name
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
        self.status_label.setText(f"正在生成原图证明文件...")

    def update_progress(self, value):
        """更新进度条"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setValue(value)

    def update_progress_text(self, current_index, total_count, folder_name, task_detail):
        """更新进度对话框的文本"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            progress_text = f"正在处理 ({current_index}/{total_count}): {folder_name} - {task_detail}"
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
        
        self.status_label.setText("处理已取消")
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
        
        self.status_label.setText(f"处理完成: 成功 {success_count}/{total_count}")
        QMessageBox.information(self, "处理完成", result_message)
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")   
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
        
        if not folder_path:
            QMessageBox.warning(self, "警告", "请先选择要扫描的文件夹！")
            return
        if not search_term:
            QMessageBox.warning(self, "警告", "请输入子文件夹名称关键词！")
            return
        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "警告", "选择的文件夹不存在！")
            return

        # ---- 设置按钮状态 ----
        self.add_button.setEnabled(False)  # 禁用按钮，防止重复点击
        self.add_button.setText("扫描中...")  # 设置为扫描中状态
        self.status_label.setText(f"正在扫描文件夹: {folder_path}")
        # ---- 结束按钮状态 ----

        # 创建并启动扫描线程
        self.scanner_thread = FolderScanner(folder_path, search_term, added_paths=self.added_folder_paths)
        self.scanner_thread.folder_found.connect(self.add_folder_to_list)
        self.scanner_thread.scan_finished.connect(self.scan_completed)
        self.scanner_thread.update_status.connect(self.update_status_label)  # ✅ 连接实时状态信号
        self.scanner_thread.start()  # 启动子线程，异步扫描

    def update_status_label(self, text):
        self.status_label.setText(text)
        QApplication.processEvents()  # 强制刷新界面

    def add_folder_to_list(self, folder_name, folder_path, thumbnail_path):
        # 避免重复添加（双重保险，也可以只依赖 added_folder_paths）
        if folder_path not in self.added_folder_paths:
            # 添加到数据模型
            self.folders_data.append({
                'name': folder_name,
                'path': folder_path,
                'thumbnail': thumbnail_path
            })
            # 记录已添加路径
            self.added_folder_paths.add(folder_path)  # ✅ 关键：记录已添加的路径

            # 添加到界面列表
            item = QListWidgetItem()
            widget = FolderItemWidget(folder_name, thumbnail_path)
            item.setSizeHint(QSize(300, 89))
            item.setData(Qt.UserRole, folder_path)
            item.setToolTip(folder_path)
            self.folder_list.addItem(item)
            self.folder_list.setItemWidget(item, widget)
    def scan_completed(self, found_count, skipped_count):
        # 恢复按钮状态
        self.add_button.setEnabled(True)  # 重新启用按钮
        self.add_button.setText("写入数据库")  # 恢复为原始文字，比如“写入数据库”
        status_text = f"扫描完成，找到 {found_count} 个匹配的文件夹，跳过了 {skipped_count} 个已添加的文件夹"
        self.status_label.setText(status_text)

        msg = f"成功找到并添加了 {found_count} 个文件夹到数据库！\n\n"
        msg += f"跳过了 {skipped_count} 个已经添加过的文件夹。\n"

        if found_count > 0:
            msg += f"总计：新增 {found_count} 个，跳过 {skipped_count} 个。"
        else:
            msg += "未找到新的匹配文件夹。"

        QMessageBox.information(self, "扫描完成", msg)
        self.total_num = found_count
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")
        self.save_database()
    def generate_thumbnail_from_folder(self, folder_path, folder_name):
        """从已修文件夹生成 400x400 缩略图"""
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
  # -------------------- 以上为扫描逻辑 --------------------

    #搜索文件夹
    def filter_folders(self):
        """根据搜索词过滤文件夹列表（匹配路径最后一级目录名，支持多关键字 OR）"""
        search_text = self.db_search_edit.text().lower().strip()
        
        # 按空格拆分多个关键字
        keywords = [kw for kw in search_text.split() if kw]

        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            folder_path = item.data(Qt.UserRole)  # 获取完整路径
            folder_last = os.path.basename(folder_path).lower()  # 提取最后一级目录名

            if not keywords:
                # 没输入关键字 → 显示所有
                item.setHidden(False)
            else:
                # 任意关键字匹配最后一级目录名就显示
                matched = any(kw in folder_last for kw in keywords)
                item.setHidden(not matched)

    #双击打开文件夹目录
    def open_folder(self, item):
        """双击打开文件夹"""
        folder_path = item.data(Qt.UserRole)

        if not os.path.exists(folder_path):
            QMessageBox.warning(self, "警告", f"文件夹不存在：{folder_path}")
            return

        try:
            # 统一使用反斜杠路径
            normalized_path = folder_path.replace('/', '\\')

            system = platform.system()
            if system == "Windows":
                # 使用 os.startfile 打开文件夹（不会闪 cmd 窗口）
                try:
                    os.startfile(normalized_path)
                except OSError as e:
                    # 如果 os.startfile 打不开网络路径，尝试 Popen 方法
                    try:
                        subprocess.Popen(['explorer', normalized_path],
                                        shell=False,
                                        creationflags=subprocess.CREATE_NO_WINDOW)
                    except Exception as e2:
                        QMessageBox.critical(self, "错误",
                                            f"无法打开文件夹：{folder_path}\n错误: {str(e2)}")
            elif system == "Darwin":  # macOS
                subprocess.run(["open", normalized_path], check=True)
            else:  # Linux
                subprocess.run(["xdg-open", normalized_path], check=True)

        except Exception as e:
            QMessageBox.critical(self, "错误", f"无法打开文件夹：{folder_path}\n错误: {str(e)}")

    #删除文件夹
    def delete_folders(self, selected_items):
        try:
            folder_count = len(selected_items)
            folder_names = []

            # 弹出确认对话框时显示文件夹名称
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
            paths_to_delete = [item.data(Qt.UserRole) for item in selected_items]
            self.folders_data = [f for f in self.folders_data if f['path'] not in paths_to_delete]
            self.save_database()

            # 从列表中删除
            for item in selected_items:
                row = self.folder_list.row(item)
                self.folder_list.takeItem(row)

            for item in selected_items:
                folder_path = item.data(Qt.UserRole)
                self.added_folder_paths.discard(folder_path)  # ✅ 从已添加集合中移除

            # 先收集所有文件夹名称
            for item in selected_items:
                folder_path = item.data(Qt.UserRole)
                folder_record = next((f for f in self.folders_data if f['path'] == folder_path), None)
                if folder_record:
                    folder_names.append(folder_record['name'])
                    # 删除缩略图
                    thumb_path = folder_record.get('thumbnail')
                    if thumb_path and os.path.exists(thumb_path):
                        try:
                            os.remove(thumb_path)
                        except Exception as e:
                            print(f"删除缩略图失败: {thumb_path} -> {e}")

            self.status_label.setText(f"已从数据库删除 {folder_count} 个文件夹记录及其缩略图: {', '.join(folder_names)}")
            QMessageBox.information(
                self,
                "删除成功",
                f"已删除 {folder_count} 个文件夹记录及其缩略图:\n" + "\n".join(folder_names)
            )
            self.total_num = self.total_num - folder_count
            self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")

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
            self.folders_data = []
            self.folder_list.clear()
            self.added_folder_paths.clear()  # 清空所有已添加路径集合
            self.save_database()
            self.status_label.setText("数据库已清空，所有缩略图已删除")
            QMessageBox.information(self, "完成", "数据库已清空，所有缩略图已删除！")
            self.total_num = 0
            self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")
    
  # -------------------- 以下为加载数据库逻辑 --------------------
    def add_folder_to_list_realtime(self, folder, current=0, total=0):
        self.folders_data.append(folder)
        name = folder.get('name', '未知文件夹')
        path = folder.get('path', '')
        thumbnail_path = folder.get('thumbnail', '')
        note = folder.get('note', '')

        if path not in self.added_folder_paths:
            self.added_folder_paths.add(path)
            item = QListWidgetItem()
            widget = FolderItemWidget(name, thumbnail_path, note)
            item.setSizeHint(QSize(300, 89))
            item.setData(Qt.UserRole, path)
            item.setToolTip(f"{path}\n{note}" if note else path)
            self.folder_list.addItem(item)
            self.folder_list.setItemWidget(item, widget)

        #动态计数更新状态栏
        self.status_label.setText(f"正在加载 {name}（{current}/{total}）")
        self.total_num = total
    def on_load_finished(self, total=0):
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")
        self.database_load_finished = True
        self.save_database()
  # -------------------- 以上为加载数据库逻辑 --------------------

    #保存数据库
    def save_database(self):
        """保存数据库到JSON文件"""
        try:
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