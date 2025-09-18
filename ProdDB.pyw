import sys
import os
import json
import subprocess
import platform
import shutil
import zipfile
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QLineEdit, QListWidget, QLabel, 
                             QFileDialog, QMessageBox, QSplitter, QGroupBox, QListWidgetItem,
                             QMenu, QAction, QProgressDialog, QAbstractItemView)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon

class ZipGeneratorThread(QThread):
    """压缩包生成线程"""
    progress_updated = pyqtSignal(int)  # 进度更新信号
    task_completed = pyqtSignal(str, str)  # 单个任务完成信号 (folder_name, result)
    all_completed = pyqtSignal(list)  # 所有任务完成信号
    error_occurred = pyqtSignal(str, str)  # 错误信号 (folder_name, error_message)
    current_task = pyqtSignal(str, str)  # 当前任务信号 (task_type, detail)
    
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
                
                # 发送当前任务信息
                self.current_task.emit("处理文件夹", f"正在处理: {folder_name} ({i+1}/{total_tasks})")
                
                # 生成压缩包路径
                zip_name = f"{folder_name}.zip"
                zip_path = os.path.join(self.save_directory, zip_name).replace('/', '\\')
                
                # 创建压缩包（传递任务索引用于进度计算）
                self.create_single_zip_with_progress(folder_name, folder_path, zip_path, i, total_tasks)
                
                if not self.should_stop:
                    self.task_completed.emit(folder_name, "成功")
                    self.results.append((folder_name, zip_path, "成功"))
                
            except Exception as e:
                error_msg = str(e)
                self.error_occurred.emit(folder_name, error_msg)
                self.results.append((folder_name, "", f"失败: {error_msg}"))
            
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
            # 步骤1: 统计文件数量（占总进度的5%）
            self.current_task.emit("统计文件", f"统计 {folder_name} 中的文件数量...")
            total_files = self.count_files_in_directory(folder_path)
            self.update_task_progress(task_index, total_tasks, 0.05)  # 5%
            
            if self.should_stop:
                return
            
            # 在 work_dir 下直接放子文件夹内容
            temp_folder_path = work_dir
            os.makedirs(temp_folder_path, exist_ok=True)

            # 步骤2: 复制子文件夹（占总进度的20%）
            self.current_task.emit("复制文件", f"复制 {folder_name} 的子文件夹...")
            self.copy_subfolders_only_with_progress(folder_path, temp_folder_path, task_index, total_tasks, 0.05, 0.25)
            
            if self.should_stop:
                return

            # 步骤3: 复制声明文件（占总进度的5%）
            self.current_task.emit("复制声明", f"复制原图声明文件...")
            proof_filename = os.path.basename(self.proof_file_path)
            temp_proof_path = os.path.join(temp_folder_path, proof_filename).replace('/', '\\')
            shutil.copy2(self.proof_file_path, temp_proof_path)
            self.update_task_progress(task_index, total_tasks, 0.3)  # 30%
            
            if self.should_stop:
                return

            # 步骤4: 压缩文件（占总进度的70%）
            self.current_task.emit("压缩文件", f"正在压缩 {folder_name}...")
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


class FolderScanner(QThread):
    """文件夹扫描线程"""
    folder_found = pyqtSignal(str, str)  # 发现文件夹信号 (名称, 路径)
    scan_finished = pyqtSignal(int)  # 扫描完成信号 (找到的文件夹数量)
    
    def __init__(self, root_path, search_term):
        super().__init__()
        self.root_path = root_path
        self.search_term = search_term.lower()
        self.found_count = 0
    
    def run(self):
        """在后台线程中扫描文件夹"""
        self._scan_directory(self.root_path)
        self.scan_finished.emit(self.found_count)
    
    def _scan_directory(self, path):
        """递归扫描目录"""
        try:
            for item in os.listdir(path):
                item_path = os.path.join(path, item).replace('/', '\\')
                
                # 只处理文件夹
                if os.path.isdir(item_path):
                    # 检查文件夹名称是否包含搜索词
                    if self.search_term in item.lower():
                        self.folder_found.emit(item, item_path)
                        self.found_count += 1
                        # 找到匹配的文件夹后不再遍历其子文件夹
                        continue
                    
                    # 如果当前文件夹不匹配，继续扫描其子文件夹
                    self._scan_directory(item_path)
                    
        except (PermissionError, OSError):
            # 忽略权限错误和其他文件系统错误
            pass


class FolderDatabaseApp(QMainWindow):
    def __init__(self):
        super().__init__()
        # 配置文件放在程序所在目录
        app_dir = os.path.dirname(os.path.abspath(__file__))
        self.database_file = os.path.join(app_dir, "folder_database.json").replace('/', '\\')
        self.config_file = os.path.join(app_dir, "app_config.json").replace('/', '\\')
        
        self.folders_data = self.load_database()
        self.config = self.load_config()
        self.scanner_thread = None
        self.zip_thread = None
        
        self.init_ui()
        self.center_window()  # 窗口居中
        self.load_folders_to_list()
    
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
        self.status_label = QLabel("就绪")
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

        # 删除操作
        delete_text = f"删除 ({len(selected_items)}个)" if len(selected_items) > 1 else "删除"
        delete_action = QAction(delete_text, self)
        delete_action.setToolTip("从数据库中删除选中的文件夹记录")
        delete_action.triggered.connect(lambda: self.delete_folders(selected_items))
        context_menu.addAction(delete_action)

        context_menu.addSeparator()

        # 生成原图证明文件
        generate_text = f"生成原图证明文件 ({len(selected_items)}个)" if len(selected_items) > 1 else "生成原图证明文件"
        generate_action = QAction(generate_text, self)
        generate_action.setToolTip("为选中的文件夹生成原图证明文档")
        generate_action.triggered.connect(lambda: self.generate_original_proof(selected_items))
        context_menu.addAction(generate_action)

        # 打开文件夹操作（仅单选时才显示）
        if len(selected_items) == 1:
            context_menu.addSeparator()
            open_action = QAction("打开文件夹", self)
            open_action.setToolTip("在文件资源管理器中打开此文件夹")
            open_action.triggered.connect(lambda: self.open_folder(selected_items[0]))
            context_menu.addAction(open_action)

        # 显示菜单
        context_menu.exec_(self.folder_list.mapToGlobal(position))

    def delete_folders(self, selected_items):
        try:
            folder_count = len(selected_items)
            # 弹出确认对话框
            reply = QMessageBox.question(
                self,
                "确认删除",
                f"确定要从数据库中删除选中的 {folder_count} 个文件夹记录吗？此操作不影响源文件夹",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply != QMessageBox.Yes:
                return  # 用户取消删除

            # 收集要删除的路径
            paths_to_delete = [item.data(Qt.UserRole) for item in selected_items]

            # 从数据库中删除
            self.folders_data = [f for f in self.folders_data if f['path'] not in paths_to_delete]
            self.save_database()

            # 从列表中删除
            for item in selected_items:
                row = self.folder_list.row(item)
                self.folder_list.takeItem(row)

            self.status_label.setText(f"已从数据库删除 {folder_count} 个文件夹记录")
            QMessageBox.information(self, "删除成功", f"已从数据库中删除 {folder_count} 个文件夹记录！")

        except Exception as e:
            QMessageBox.critical(self, "删除失败", f"删除文件夹记录时发生错误：\n{str(e)}")
    
    def generate_original_proof(self, selected_items):
        """批量生成原图证明文件压缩包"""
        if not selected_items:
            return
        
        # 检查所有文件夹是否存在
        invalid_folders = []
        valid_folders = []
        
        for item in selected_items:
            folder_path = item.data(Qt.UserRole)
            folder_name = item.text()
            
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
        self.progress_dialog = QProgressDialog("正在生成原图证明文件...", "取消", 0, 100, self)
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
        
        # 连接取消按钮
        self.progress_dialog.canceled.connect(self.cancel_zip_generation)
        
        self.zip_thread.start()
    
    def update_progress(self, value):
        """更新进度条"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setValue(value)
    
    def on_task_completed(self, folder_name, result):
        """单个任务完成处理"""
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.setLabelText(f"正在处理: {folder_name} - {result}")
    
    def on_error_occurred(self, folder_name, error_message):
        """错误处理"""
        print(f"处理 {folder_name} 时出错: {error_message}")
    
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
        result_message = f"批量处理完成！\n\n成功: {success_count}/{total_count}\n\n"
        
        if success_count > 0:
            result_message += "成功生成的压缩包:\n"
            for folder_name, zip_path, result in results:
                if result == "成功":
                    result_message += f"- {folder_name}.zip\n"
        
        failed_count = total_count - success_count
        if failed_count > 0:
            result_message += f"\n失败: {failed_count} 个\n"
            for folder_name, _, result in results:
                if result != "成功":
                    result_message += f"- {folder_name}: {result}\n"
        
        self.status_label.setText(f"批量处理完成: 成功 {success_count}/{total_count}")
        QMessageBox.information(self, "处理完成", result_message)
    
    def cancel_zip_generation(self):
        """取消压缩包生成"""
        if self.zip_thread and self.zip_thread.isRunning():
            self.zip_thread.terminate()
            self.zip_thread.wait()
        
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None
        
        self.status_label.setText("操作已取消")
    
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
    
    def scan_and_add(self):
        """扫描并添加文件夹到数据库"""
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
        
        # 保存搜索词
        self.config['last_search_term'] = search_term
        self.save_config()
        
        # 禁用按钮，显示扫描状态
        self.add_button.setEnabled(False)
        self.add_button.setText("扫描中...")
        self.status_label.setText(f"正在扫描文件夹: {folder_path}")
        
        # 创建并启动扫描线程
        self.scanner_thread = FolderScanner(folder_path, search_term)
        self.scanner_thread.folder_found.connect(self.add_folder_to_database)
        self.scanner_thread.scan_finished.connect(self.scan_completed)
        self.scanner_thread.start()
    
    def add_folder_to_database(self, folder_name, folder_path):
        """添加文件夹到数据库"""
        # 统一使用反斜杠路径
        folder_path = folder_path.replace('/', '\\')
        
        # 避免重复添加
        if folder_path not in [item['path'] for item in self.folders_data]:
            self.folders_data.append({
                'name': folder_name,
                'path': folder_path
            })
            
            # 实时更新UI
            self.add_folder_to_list(folder_name, folder_path)
    
    def scan_completed(self, found_count):
        """扫描完成处理"""
        # 保存数据库
        self.save_database()
        
        # 恢复按钮状态
        self.add_button.setEnabled(True)
        self.add_button.setText("写入数据库")
        
        # 更新状态
        self.status_label.setText(f"扫描完成，找到 {found_count} 个匹配的文件夹")
        
        if found_count > 0:
            QMessageBox.information(self, "完成", f"成功找到并添加了 {found_count} 个文件夹到数据库！")
        else:
            QMessageBox.information(self, "完成", "未找到匹配的文件夹。")
    
    def add_folder_to_list(self, folder_name, folder_path):
        """添加文件夹到列表显示"""
        item = QListWidgetItem(folder_name)
        item.setData(Qt.UserRole, folder_path)  # 存储完整路径
        item.setToolTip(folder_path)  # 显示路径提示
        self.folder_list.addItem(item)
    
    def load_folders_to_list(self):
        """加载所有文件夹到列表"""
        self.folder_list.clear()
        for folder in self.folders_data:
            self.add_folder_to_list(folder['name'], folder['path'])
    
    def filter_folders(self):
        """根据搜索词过滤文件夹列表（支持多关键字并列匹配）"""
        search_text = self.db_search_edit.text().lower().strip()
        
        # 按空格拆分多个关键字
        keywords = [kw for kw in search_text.split() if kw]

        for i in range(self.folder_list.count()):
            item = self.folder_list.item(i)
            folder_name = item.text().lower()
            folder_path = item.data(Qt.UserRole).lower()
            
            # 文件夹名称或路径包含任意关键字就显示
            if not keywords:
                # 如果没有输入关键字，则全部显示
                item.setHidden(False)
            elif any(kw in folder_name or kw in folder_path for kw in keywords):
                item.setHidden(False)
            else:
                item.setHidden(True)
    
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

    
    def clear_database(self):
        """清空数据库"""
        reply = QMessageBox.question(self, "确认", "确定要清空整个产品图库数据库吗？此操作不可撤销。",
                                   QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        
        if reply == QMessageBox.Yes:
            self.folders_data = []
            self.folder_list.clear()
            self.save_database()
            self.status_label.setText("数据库已清空")
            QMessageBox.information(self, "完成", "数据库已清空！")
    
    def load_database(self):
        """从JSON文件加载数据库"""
        try:
            if os.path.exists(self.database_file):
                with open(self.database_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "警告", f"加载数据库失败：{str(e)}")
        
        return []
    
    def save_database(self):
        """保存数据库到JSON文件"""
        try:
            with open(self.database_file, 'w', encoding='utf-8') as f:
                json.dump(self.folders_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存数据库失败：{str(e)}\n请以管理员身份运行此程序！")
    
    def load_config(self):
        """加载配置文件"""
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            print(f"加载配置文件失败：{str(e)}")
        
        return {}
    
    def save_config(self):
        """保存配置文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"保存配置文件失败：{str(e)}\n请以管理员身份运行此程序！")
    
    def closeEvent(self, event):
        """程序关闭时保存数据库和配置"""
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