import sys
import os
import json
import subprocess
import platform
import shutil
import pandas as pd
import zipfile
from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *
from concurrent.futures import ThreadPoolExecutor
from PIL import Image, ImageFile

ImageFile.LOAD_TRUNCATED_IMAGES = True  # 避免损坏图片报错



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
    finished = pyqtSignal(int, int)          # 更新数量、跳过数量

    def __init__(self, folders_data, excel_path):
        super().__init__()
        self.folders_data = folders_data
        self.excel_path = excel_path

    def run(self):
        updated_count = 0
        skipped_count = 0

        try:
            # 明确指定列名读取，跳过第一行标题
            df = pd.read_excel(self.excel_path, header=0, names=["name", "_", "remark"])
        except Exception as e:
            print(f"读取Excel失败: {e}")
            self.finished.emit(0, 0)
            return

        # 用 name 作为索引（self.folders_data 中已有）
        existing_items = {item.get("name", ""): item for item in self.folders_data}

        # 获取A列非空数据（排除空值）
        valid_rows = df[~df["name"].isna() & df["name"].astype(str).str.strip().ne("")]
        total_names = len(valid_rows) # 有效name总数（已排除空值）

        if total_names == 0:
            self.finished.emit(0, 0)
            return

        for i, (idx, row) in enumerate(valid_rows.iterrows()):
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

            # 更新进度
            percent = int((i + 1) / total_names * 100)
            self.progress_changed.emit(percent, name)

        # 完成时发射信号
        self.finished.emit(updated_count, skipped_count)
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
    folder_found = pyqtSignal(str, str, str, str)  
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
                    # 实时更新状态
                    self.update_status.emit(
                        f"扫描中：{item_path}\n已写入：{self.found_count} 个，已跳过：{self.skipped_count} 个"
                    )

                    # 已添加路径跳过
                    if item_path in self.added_paths:
                        self.skipped_count += 1
                        continue

                    # 匹配关键词
                    # 将搜索词按空格分割成多个关键词
                    search_terms = self.search_term.split()

                    # 检查是否有任何关键词匹配（或关系）
                    if any(term.lower() in item.lower() for term in search_terms):
                        if item_path not in self.scanned_paths:
                            self.scanned_paths.add(item_path)

                            # 只扫描匹配文件夹里的 "已修" 子文件夹
                            fixed_folder = os.path.join(item_path, "已修")
                            thumbnail_path = ""
                            remark = ""  # 新增备注字段
                            if os.path.exists(fixed_folder):
                                # 生成缩略图（如果有图片）
                                thumbnail_path = self._generate_thumbnail(item_path, item)

                                # 尝试读取产品信息 JSON
                                safe_name = "".join(c for c in item if c not in "\\/:*?\"<>|")
                                json_file_path = os.path.join(fixed_folder, f"{safe_name}_产品信息.json")
                                if os.path.exists(json_file_path):
                                    try:
                                        with open(json_file_path, 'r', encoding='utf-8') as f:
                                            data = json.load(f)
                                            remark = data.get("remark", "")
                                    except Exception:
                                        remark = ""

                            # 发射信号
                            self.folder_found.emit(item, item_path, thumbnail_path, remark)
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


# ==================== 高性能虚拟列表 ====================
class HighPerformanceVirtualList(QAbstractScrollArea):
    """高性能虚拟列表 - 专为大数据量设计"""
    
    # 自定义信号
    itemClicked = pyqtSignal(int, dict)  # 点击信号：(索引, 数据)
    itemDoubleClicked = pyqtSignal(int, dict)  # 双击信号
    itemRightClicked = pyqtSignal(int, dict, QPoint)  # 右键信号
    
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

    # 支持 Home/End
    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Home:
            # 滚动到顶部
            self.verticalScrollBar().setValue(0)
            # 选中第一项（如果有数据）
            if self.items_data:
                self.current_index = 0
                self.viewport().update()
        elif event.key() == Qt.Key_End:
            # 滚动到底部
            self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())
            # 选中最后一项（如果有数据）
            if self.items_data:
                self.current_index = len(self.items_data) - 1
                self.viewport().update()
        else:
            super().keyPressEvent(event)

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


# ==================== 2. 虚拟列表专用的FolderItemWidget ====================
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

        elif event.button() == Qt.RightButton and parent_list:
            # 如果当前已是多选，右键不改变选中状态
            if len(parent_list.selected_indices) <= 1:
                # 普通右键单选
                parent_list.current_index = self.get_index()
                parent_list.selected_indices = [self.get_index()]

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
        
        self.init_ui()
        self.center_window()

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
        self.status_label = QLabel("🟢就绪")
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
        import_action = self.menu.addAction("导入产品信息")
        import_action.triggered.connect(self.import_product_info)
        
        # export_action = self.menu.addAction("导出数据")
        # export_action.triggered.connect(self.export_data)
        # self.menu.addSeparator()
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
        self.progress_dialog.show()

        # 创建子线程
        self.import_thread = ImportProductThread(self.folders_data, file_path)
        self.import_thread.progress_changed.connect(
            lambda percent, name: self.progress_dialog.setValue(percent) or self.progress_dialog.setLabelText(f"正在处理: {name}")
        )
        self.import_thread.finished.connect(self._on_import_finished)
        self.import_thread.start()
        self.status_label.setText(f"正在导入产品信息")

    def _on_import_finished(self, updated_count, skipped_count):
        self.progress_dialog.close()
        # 保存数据库并刷新列表
        self.save_database()
        self.folder_list.update()
        self.refresh_folder_list()
        self.status_label.setText(f"导入完成")
        QMessageBox.information(self, "导入完成", f"导入完成！\n已更新数量：{updated_count}\n跳过数量：{skipped_count}")    
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}）")

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
        
    def copy_path(self, folder_data):
        """复制文件夹路径"""
        folder_path = folder_data.get("path", "")
        if folder_path:
            clipboard = QApplication.clipboard()
            clipboard.setText(folder_path)
            self.status_label.setText(f"已复制路径：{folder_path}")
            QTimer.singleShot(2000, lambda: self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}）"))

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
        QTimer.singleShot(2000, lambda: self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}）"))
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

        # ---- 设置按钮状态 ----
        self.add_button.setEnabled(False)  # 禁用按钮，防止重复点击
        self.add_button.setText("扫描中...")  # 设置为扫描中状态
        self.status_label.setText(f"正在扫描文件夹: {folder_path}")
        # ---- 结束按钮状态 ----

        # 创建并启动扫描线程
        self.scanner_thread = FolderScanner(folder_path, search_term, added_paths=self.added_folder_paths)

        # 连接信号
        self.scanner_thread.folder_found.connect(
            lambda name, path, thumb, remark: self.add_folder_realtime({
                'name': name,
                'path': path,
                'thumbnail': thumb,
                'remark': remark
            })
        )
        self.scanner_thread.scan_finished.connect(self.scan_completed)
        self.scanner_thread.update_status.connect(self.update_status_label)

        # 启动线程
        self.scanner_thread.start()

    def update_status_label(self, text):
        self.status_label.setText(text)
        QApplication.processEvents()  # 强制刷新界面
        
    def add_folder_realtime(self, folder):
        """单条数据实时添加到虚拟列表"""
        path = folder.get("path", "")
        if not path or path in self.added_folder_paths:
            return

        # 添加到数据源
        self.folders_data.append(folder)
        self.added_folder_paths.add(path)

        # 刷新虚拟列表
        self.folder_list.set_data(self.folders_data[:])  # 传副本，避免引用问题
        QApplication.processEvents()  # 强制刷新界面

    def scan_completed(self, found_count, skipped_count):
        # 恢复按钮状态
        self.add_button.setEnabled(True)  # 重新启用按钮
        self.add_button.setText("写入数据库")  
        status_text = f"扫描完成，找到 {found_count} 个匹配的文件夹，跳过了 {skipped_count} 个已添加的文件夹"
        self.status_label.setText(status_text)

        msg = f"成功找到并添加了 {found_count} 个文件夹到数据库！\n\n"
        msg += f"跳过了 {skipped_count} 个已经添加过的文件夹。\n"

        if found_count > 0:
            msg += f"总计：新增 {found_count} 个，跳过 {skipped_count} 个。"
        else:
            msg += "未找到新的匹配文件夹。"

        QMessageBox.information(self, "扫描完成", msg)
        self.total_num = self.total_num + found_count
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")
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
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}）")

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
            self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}）")
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
            self.status_label.setText("数据库已清空，所有缩略图已删除")
            QMessageBox.information(self, "完成", "数据库已清空，所有缩略图已删除！")
            self.total_num = 0
            self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}） ")

    #刷新数据库
    def refresh_folder_list(self):
        """刷新文件夹列表"""
        self.folder_list.set_data(self.folders_data[:])
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
        self.status_label.setText(f"正在收集数据 {current}/{total}")
        QApplication.processEvents()

    def on_load_finished(self, total=0):
        """数据库加载完成"""
        # 最终更新虚拟列表
        self.folder_list.set_data(self.folders_data[:])
        
        self.status_label.setText(f"🟢 就绪 （总计：{self.total_num}）")
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