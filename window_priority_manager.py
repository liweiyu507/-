import os
import sys
import time
import threading
import ctypes
import ctypes.wintypes
import tkinter as tk
from tkinter import ttk, messagebox
from dataclasses import dataclass
from typing import Dict, List, Optional

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

user32 = ctypes.windll.user32

# 定义正确的Windows API函数参数类型
user32.SetWindowPos.restype = ctypes.wintypes.BOOL
user32.SetWindowPos.argtypes = [
    ctypes.wintypes.HWND,  # hWnd
    ctypes.wintypes.HWND,  # hWndInsertAfter
    ctypes.wintypes.INT,   # X
    ctypes.wintypes.INT,   # Y
    ctypes.wintypes.INT,   # cx
    ctypes.wintypes.INT,   # cy
    ctypes.wintypes.UINT   # uFlags
]

user32.GetWindowLongW.restype = ctypes.wintypes.LONG
user32.GetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.INT]

user32.SetWindowLongW.restype = ctypes.wintypes.LONG
user32.SetWindowLongW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.INT, ctypes.wintypes.LONG]

user32.GetWindowTextLengthW.restype = ctypes.wintypes.INT
user32.GetWindowTextLengthW.argtypes = [ctypes.wintypes.HWND]

user32.GetWindowTextW.restype = ctypes.wintypes.INT
user32.GetWindowTextW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.wintypes.INT]

user32.GetClassNameW.restype = ctypes.wintypes.INT
user32.GetClassNameW.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.LPWSTR, ctypes.wintypes.INT]

user32.IsWindowVisible.restype = ctypes.wintypes.BOOL
user32.IsWindowVisible.argtypes = [ctypes.wintypes.HWND]

user32.IsIconic.restype = ctypes.wintypes.BOOL
user32.IsIconic.argtypes = [ctypes.wintypes.HWND]

user32.IsWindow.restype = ctypes.wintypes.BOOL
user32.IsWindow.argtypes = [ctypes.wintypes.HWND]

user32.GetWindowThreadProcessId.restype = ctypes.wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [ctypes.wintypes.HWND, ctypes.POINTER(ctypes.wintypes.DWORD)]

user32.BringWindowToTop.restype = ctypes.wintypes.BOOL
user32.BringWindowToTop.argtypes = [ctypes.wintypes.HWND]

user32.ShowWindow.restype = ctypes.wintypes.BOOL
user32.ShowWindow.argtypes = [ctypes.wintypes.HWND, ctypes.wintypes.INT]

HWND_TOPMOST = ctypes.wintypes.HWND(-1)
HWND_NOTOPMOST = ctypes.wintypes.HWND(-2)
HWND_TOP = ctypes.wintypes.HWND(0)
HWND_BOTTOM = ctypes.wintypes.HWND(1)

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_SHOWWINDOW = 0x0040


@dataclass
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    process_name: str
    process_id: int
    is_visible: bool
    is_minimized: bool
    is_topmost: bool = False
    priority: int = 0


class WindowManager:
    def __init__(self):
        self.topmost_windows: Dict[int, int] = {}
        self.monitor_thread: Optional[threading.Thread] = None
        self.priority_monitor_thread: Optional[threading.Thread] = None
        self.stop_monitor: bool = False
        self.stop_priority_monitor: bool = False
        self.update_callback: Optional[callable] = None
        self.manager_hwnd: Optional[int] = None  # 管理工具窗口句柄
        self.manager_priority: int = 999999  # 管理工具最高优先级

    def get_all_windows(self) -> List[WindowInfo]:
        windows: List[WindowInfo] = []
        seen_titles = set()

        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)

        def callback(hwnd, extra):
            if not user32.IsWindowVisible(hwnd):
                return True

            length = user32.GetWindowTextLengthW(hwnd)
            if length == 0:
                return True

            title_buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buffer, length + 1)
            title = title_buffer.value

            if not title or title in seen_titles:
                return True

            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buffer, 256)
            class_name = class_buffer.value

            pid = ctypes.wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            process_id = pid.value

            process_name = "Unknown"
            if PSUTIL_AVAILABLE:
                try:
                    process = psutil.Process(process_id)
                    process_name = process.name()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            is_minimized = user32.IsIconic(hwnd)
            ex_style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            is_topmost = (ex_style & WS_EX_TOPMOST) != 0

            windows.append(WindowInfo(
                hwnd=hwnd,
                title=title,
                class_name=class_name,
                process_name=process_name,
                process_id=process_id,
                is_visible=True,
                is_minimized=is_minimized,
                is_topmost=is_topmost
            ))
            seen_titles.add(title)
            return True

        user32.EnumWindows(WNDENUMPROC(callback), 0)
        return sorted(windows, key=lambda w: w.title.lower())

    def set_topmost(self, hwnd: int, topmost: bool) -> bool:
        try:
            # 将hwnd转换为正确的HWND类型
            hwnd_handle = ctypes.wintypes.HWND(hwnd)
            
            # 验证窗口有效性
            if not user32.IsWindow(hwnd_handle):
                print(f"Invalid window handle: {hwnd}")
                return False
            
            # 获取窗口标题和类名用于日志
            length = user32.GetWindowTextLengthW(hwnd_handle)
            window_title = ""
            if length > 0:
                title_buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd_handle, title_buffer, length + 1)
                window_title = title_buffer.value
            
            class_buffer = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd_handle, class_buffer, 256)
            class_name = class_buffer.value
            
            print(f"Setting topmost for '{window_title}' (class: {class_name})")
            
            # 如果窗口最小化，先恢复它
            if user32.IsIconic(hwnd_handle):
                print(f"Window is minimized, restoring...")
                user32.ShowWindow(hwnd_handle, 9)  # SW_RESTORE
            
            # 获取当前样式
            ex_style_before = user32.GetWindowLongW(hwnd_handle, GWL_EXSTYLE)
            is_topmost_before = (ex_style_before & WS_EX_TOPMOST) != 0
            print(f"Before: ExStyle=0x{ex_style_before:08X}, Topmost={is_topmost_before}")
            
            # 设置置顶
            if topmost:
                # 方法1: 使用 SetWindowPos
                result = user32.SetWindowPos(
                    hwnd_handle,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                )
                
                # 方法2: 同时设置窗口样式（双重保险）
                new_ex_style = ex_style_before | WS_EX_TOPMOST
                user32.SetWindowLongW(hwnd_handle, GWL_EXSTYLE, new_ex_style)
                
                # 再次调用 SetWindowPos 确保生效
                user32.SetWindowPos(
                    hwnd_handle,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                )
                
                # 将窗口带到前台
                user32.BringWindowToTop(hwnd_handle)
            else:
                # 取消置顶
                new_ex_style = ex_style_before & ~WS_EX_TOPMOST
                user32.SetWindowLongW(hwnd_handle, GWL_EXSTYLE, new_ex_style)
                
                result = user32.SetWindowPos(
                    hwnd_handle,
                    HWND_NOTOPMOST,
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                )
            
            # 验证结果
            ex_style_after = user32.GetWindowLongW(hwnd_handle, GWL_EXSTYLE)
            is_topmost_after = (ex_style_after & WS_EX_TOPMOST) != 0
            print(f"After: ExStyle=0x{ex_style_after:08X}, Topmost={is_topmost_after}")
            
            # 检查是否成功
            if topmost:
                if is_topmost_after:
                    print(f"SUCCESS: Window '{window_title}' is now topmost")
                    return True
                else:
                    print(f"WARNING: SetWindowPos returned success but topmost flag not set")
                    print(f"This may be a special window type (class: {class_name})")
                    # 即使标志未设置，SetWindowPos可能已经改变了Z-order
                    return True  # 返回True让用户自己验证
            else:
                if not is_topmost_after:
                    print(f"SUCCESS: Window '{window_title}' is no longer topmost")
                    return True
                else:
                    print(f"Failed to remove topmost from '{window_title}'")
                    return False
                    
        except Exception as e:
            print(f"Exception in set_topmost for hwnd {hwnd}: {e}")
            return False

    def update_priority_order(self, priority_map: Dict[int, int]):
        """更新优先级顺序并立即应用"""
        self.topmost_windows = priority_map.copy()
        
        # 确保管理工具窗口在优先级列表中且优先级最高
        if self.manager_hwnd and self.manager_hwnd not in self.topmost_windows:
            self.topmost_windows[self.manager_hwnd] = self.manager_priority
        elif self.manager_hwnd in self.topmost_windows:
            # 强制管理工具优先级为最高
            self.topmost_windows[self.manager_hwnd] = self.manager_priority
        
        self._apply_priority_order()

    def _apply_priority_order(self):
        """应用当前的优先级顺序到窗口"""
        if not self.topmost_windows:
            return
            
        # 按优先级排序（高优先级在前）
        sorted_windows = sorted(self.topmost_windows.items(), key=lambda x: x[1], reverse=True)
        
        # 确保管理工具窗口在最前面
        if self.manager_hwnd in self.topmost_windows:
            # 先处理管理工具窗口，确保它在最顶层
            try:
                hwnd_handle = ctypes.wintypes.HWND(self.manager_hwnd)
                # 管理工具窗口使用HWND_TOPMOST
                user32.SetWindowPos(
                    hwnd_handle,
                    HWND_TOPMOST,
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                )
            except Exception as e:
                print(f"Failed to set manager window topmost: {e}")
        
        # 然后处理其他窗口，按优先级顺序
        for idx, (hwnd, priority) in enumerate(sorted_windows):
            # 跳过管理工具窗口（已经处理）
            if hwnd == self.manager_hwnd:
                continue
                
            try:
                hwnd_handle = ctypes.wintypes.HWND(hwnd)
                
                # 验证窗口有效性
                if not user32.IsWindow(hwnd_handle) or not user32.IsWindowVisible(hwnd_handle):
                    continue
                
                # 使用HWND_TOP作为插入位置，让窗口在管理工具之下但仍在其他窗口之上
                result = user32.SetWindowPos(
                    hwnd_handle,
                    HWND_TOP,  # 使用HWND_TOP而不是HWND_TOPMOST
                    0, 0, 0, 0,
                    SWP_NOSIZE | SWP_NOMOVE
                )
                
                if not result:
                    error = ctypes.GetLastError()
                    if error != 0:
                        print(f"SetWindowPos failed for hwnd {hwnd} (priority {priority}), error: {error}")
            except Exception as e:
                print(f"Failed to update priority for hwnd {hwnd}: {e}")

    def is_window_valid(self, hwnd: int) -> bool:
        try:
            return user32.IsWindow(hwnd) and user32.IsWindowVisible(hwnd)
        except:
            return False

    def start_monitor(self, callback: callable):
        self.update_callback = callback
        self.stop_monitor = False
        self.stop_priority_monitor = False
        
        # 启动窗口状态监控线程
        self.monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.monitor_thread.start()
        
        # 启动优先级维护线程
        self.priority_monitor_thread = threading.Thread(target=self._priority_monitor_loop, daemon=True)
        self.priority_monitor_thread.start()

    def _monitor_loop(self):
        """监控窗口状态（关闭、最小化等）"""
        while not self.stop_monitor:
            time.sleep(1)
            invalid_hwnds = []

            for hwnd in list(self.topmost_windows.keys()):
                if hwnd == self.manager_hwnd:  # 跳过管理工具窗口
                    continue
                if not self.is_window_valid(hwnd):
                    invalid_hwnds.append(hwnd)

            if invalid_hwnds and self.update_callback:
                for hwnd in invalid_hwnds:
                    del self.topmost_windows[hwnd]
                self.update_callback()

    def _priority_monitor_loop(self):
        """持续监控并维护优先级顺序"""
        while not self.stop_priority_monitor:
            time.sleep(0.5)  # 每0.5秒检查一次
            
            if self.topmost_windows:
                # 定期重新应用优先级顺序
                self._apply_priority_order()
                
                # 确保管理工具窗口始终置顶
                if self.manager_hwnd:
                    try:
                        hwnd_handle = ctypes.wintypes.HWND(self.manager_hwnd)
                        if user32.IsWindow(hwnd_handle) and user32.IsWindowVisible(hwnd_handle):
                            # 检查管理工具是否仍为置顶
                            ex_style = user32.GetWindowLongW(hwnd_handle, GWL_EXSTYLE)
                            is_topmost = (ex_style & WS_EX_TOPMOST) != 0
                            
                            if not is_topmost:
                                # 如果管理工具失去置顶状态，重新设置
                                user32.SetWindowPos(
                                    hwnd_handle,
                                    HWND_TOPMOST,
                                    0, 0, 0, 0,
                                    SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                                )
                    except Exception as e:
                        print(f"Priority monitor error for manager window: {e}")

    def stop_monitor(self):
        self.stop_monitor = True
        self.stop_priority_monitor = True
        if self.monitor_thread:
            self.monitor_thread.join(timeout=2)
        if self.priority_monitor_thread:
            self.priority_monitor_thread.join(timeout=2)


class PriorityManagerGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("窗口置顶优先级管理器")
        self.root.geometry("750x500")
        self.root.minsize(700, 450)

        self.window_manager = WindowManager()
        self.priority_map: Dict[int, int] = {}
        self.selected_items: List[int] = []
        self.last_refresh_time = 0
        self.manager_hwnd: Optional[int] = None  # 管理工具窗口句柄

        self._setup_ui()
        
        # 获取管理工具窗口句柄并设置为最高优先级
        self.root.update()  # 确保窗口已创建
        self._set_manager_topmost()
        
        self._refresh_window_list()
        self.window_manager.start_monitor(self._on_monitor_update)

    def _set_manager_topmost(self):
        """设置管理工具窗口为最高优先级置顶"""
        # 获取Tkinter窗口的HWND
        try:
            # 使用tkinter的winfo_id()获取窗口ID
            window_id = self.root.winfo_id()
            
            # 在Windows上，winfo_id()返回的是HWND
            self.manager_hwnd = window_id
            self.window_manager.manager_hwnd = window_id
            
            print(f"Manager window HWND: {window_id}")
            
            # 立即将管理工具窗口设置为置顶
            hwnd_handle = ctypes.wintypes.HWND(window_id)
            
            # 设置WS_EX_TOPMOST样式
            ex_style = user32.GetWindowLongW(hwnd_handle, GWL_EXSTYLE)
            new_ex_style = ex_style | WS_EX_TOPMOST
            user32.SetWindowLongW(hwnd_handle, GWL_EXSTYLE, new_ex_style)
            
            # 调用SetWindowPos确保置顶生效
            user32.SetWindowPos(
                hwnd_handle,
                HWND_TOPMOST,
                0, 0, 0, 0,
                SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
            )
            
            # 将管理工具添加到优先级映射
            self.priority_map[window_id] = self.window_manager.manager_priority
            self.window_manager.update_priority_order(self.priority_map)
            
            print("Manager window set to topmost with highest priority")
            
        except Exception as e:
            print(f"Failed to set manager window topmost: {e}")

    def _setup_ui(self):
        main_frame = ttk.Frame(self.root, padding="10")
        main_frame.pack(fill=tk.BOTH, expand=True)

        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.X, pady=(0, 10))

        ttk.Label(top_frame, text="窗口列表", font=("Microsoft YaHei", 11, "bold")).pack(anchor=tk.W)

        self.tree = ttk.Treeview(top_frame, columns=("Title", "Process", "Priority", "Status"),
                                  show="headings", height=12)
        self.tree.heading("Title", text="窗口标题")
        self.tree.heading("Process", text="进程名称")
        self.tree.heading("Priority", text="置顶优先级")
        self.tree.heading("Status", text="状态")

        self.tree.column("Title", width=300, stretch=True)
        self.tree.column("Process", width=150, stretch=False)
        self.tree.column("Priority", width=100, stretch=False, anchor=tk.CENTER)
        self.tree.column("Status", width=100, stretch=False, anchor=tk.CENTER)

        scrollbar = ttk.Scrollbar(top_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scrollbar.set)

        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))

        left_buttons = ttk.Frame(button_frame)
        left_buttons.pack(side=tk.LEFT)

        ttk.Button(left_buttons, text="刷新列表", command=self._refresh_window_list,
                   width=12).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(left_buttons, text="置顶选中", command=self._set_topmost_selected,
                   width=12).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(left_buttons, text="取消置顶", command=self._unset_topmost_selected,
                   width=12).pack(side=tk.LEFT, padx=(0, 5))

        right_buttons = ttk.Frame(button_frame)
        right_buttons.pack(side=tk.RIGHT)

        ttk.Button(right_buttons, text="优先级↑", command=self._increase_priority,
                   width=10).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(right_buttons, text="优先级↓", command=self._decrease_priority,
                   width=10).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(right_buttons, text="置顶列表↑", command=self._priority_list_up,
                   width=10).pack(side=tk.LEFT, padx=(0, 5))

        ttk.Button(right_buttons, text="置顶列表↓", command=self._priority_list_down,
                   width=10).pack(side=tk.LEFT, padx=(0, 5))

        priority_frame = ttk.LabelFrame(main_frame, text="置顶窗口优先级列表（数字越大优先级越高）", padding="10")
        priority_frame.pack(fill=tk.BOTH, expand=True, pady=(10, 0))

        self.priority_list = tk.Listbox(priority_frame, font=("Microsoft YaHei", 10),
                                         selectmode=tk.SINGLE, height=6)
        self.priority_list.pack(fill=tk.BOTH, expand=True)

        self.priority_list.bind("<Double-Button-1>", lambda e: self._on_priority_list_double_click())

        info_frame = ttk.Frame(priority_frame)
        info_frame.pack(fill=tk.X, pady=(5, 0))

        ttk.Label(info_frame, text="提示：双击列表项可直接编辑优先级数值", 
                 foreground="gray").pack(anchor=tk.W)

        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill=tk.X, pady=(10, 0))

        self.status_label = ttk.Label(status_frame, text="就绪 - 点击「刷新列表」查看窗口")
        self.status_label.pack(anchor=tk.W)

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_window_list(self):
        current_time = time.time()
        if current_time - self.last_refresh_time < 0.5:
            return
        self.last_refresh_time = current_time

        for item in self.tree.get_children():
            self.tree.delete(item)

        try:
            windows = self.window_manager.get_all_windows()

            for window in windows:
                priority = self.priority_map.get(window.hwnd, 0)
                
                # 标记管理工具窗口
                if window.hwnd == self.manager_hwnd:
                    status = "系统窗口"
                    priority_display = f"{priority} (最高)"
                    tags = ("manager",)
                else:
                    status = "置顶" if priority > 0 else ("最小化" if window.is_minimized else "正常")
                    priority_display = priority if priority > 0 else "-"
                    tags = ("topmost",) if priority > 0 else ()

                self.tree.insert("", tk.END, iid=str(window.hwnd),
                                 values=(window.title, window.process_name,
                                         priority_display, status),
                                 tags=tags)

            self.tree.tag_configure("topmost", background="#e6f3ff")
            self.tree.tag_configure("manager", background="#fff3e6")  # 管理工具窗口用不同颜色标记

            self._update_priority_list()
            self.status_label.config(text=f"已加载 {len(windows)} 个窗口")

        except Exception as e:
            messagebox.showerror("错误", f"刷新窗口列表失败: {str(e)}")
            self.status_label.config(text="刷新失败")

    def _update_priority_list(self):
        self.priority_list.delete(0, tk.END)

        sorted_windows = sorted(self.priority_map.items(), key=lambda x: x[1], reverse=True)

        for hwnd, priority in sorted_windows:
            try:
                # 检查窗口是否有效
                hwnd_handle = ctypes.wintypes.HWND(hwnd)
                if not user32.IsWindow(hwnd_handle):
                    del self.priority_map[hwnd]
                    continue
                    
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    title_buffer = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, title_buffer, length + 1)
                    title = title_buffer.value
                    
                    # 标记管理工具窗口
                    if hwnd == self.manager_hwnd:
                        self.priority_list.insert(tk.END, f"[{priority}] {title} [系统窗口-不可调整]")
                    else:
                        self.priority_list.insert(tk.END, f"[{priority}] {title}")
                else:
                    del self.priority_map[hwnd]
            except:
                if hwnd in self.priority_map:
                    del self.priority_map[hwnd]

    def _on_tree_select(self, event):
        selected = self.tree.selection()
        self.selected_items = [int(item) for item in selected]

    def _set_topmost_selected(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请先选择要置顶的窗口")
            return

        # 检查是否包含管理工具窗口
        if self.manager_hwnd in self.selected_items:
            messagebox.showinfo("提示", "管理工具窗口已自动置顶且优先级最高，无需手动设置")
            # 从选择列表中移除管理工具窗口
            self.selected_items = [h for h in self.selected_items if h != self.manager_hwnd]
            if not self.selected_items:
                return

        max_priority = max([p for h, p in self.priority_map.items() if h != self.manager_hwnd], default=0)

        for hwnd in self.selected_items:
            if hwnd not in self.priority_map:
                max_priority += 1
                self.priority_map[hwnd] = max_priority
                self.window_manager.set_topmost(hwnd, True)

        self.window_manager.update_priority_order(self.priority_map)
        self._refresh_window_list()
        self.status_label.config(text=f"已置顶 {len(self.selected_items)} 个窗口")

    def _unset_topmost_selected(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请先选择要取消置顶的窗口")
            return
        
        # 检查是否包含管理工具窗口
        if self.manager_hwnd in self.selected_items:
            messagebox.showwarning("提示", "管理工具窗口不可取消置顶")
            # 从选择列表中移除管理工具窗口
            self.selected_items = [h for h in self.selected_items if h != self.manager_hwnd]
            if not self.selected_items:
                return

        for hwnd in self.selected_items:
            if hwnd in self.priority_map:
                del self.priority_map[hwnd]
                self.window_manager.set_topmost(hwnd, False)

        self.window_manager.update_priority_order(self.priority_map)
        self._refresh_window_list()
        self.status_label.config(text=f"已取消 {len(self.selected_items)} 个窗口的置顶")

    def _increase_priority(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请先选择要调整优先级的窗口")
            return

        hwnd = self.selected_items[0]
        
        # 检查是否是管理工具窗口
        if hwnd == self.manager_hwnd:
            messagebox.showwarning("提示", "管理工具窗口优先级最高且不可调整")
            return
        
        if hwnd not in self.priority_map:
            messagebox.showwarning("提示", "该窗口尚未置顶，请先置顶")
            return

        current_priority = self.priority_map[hwnd]
        # 获取除管理工具外的最大优先级
        max_priority = max([p for h, p in self.priority_map.items() if h != self.manager_hwnd], default=0)

        if current_priority >= max_priority:
            messagebox.showinfo("提示", "该窗口已是最高优先级（仅次于管理工具）")
            return

        for h, p in list(self.priority_map.items()):
            if h != self.manager_hwnd and p > current_priority:
                self.priority_map[h] = p - 1

        self.priority_map[hwnd] = max_priority
        self.window_manager.update_priority_order(self.priority_map)
        self._refresh_window_list()
        self.status_label.config(text="优先级已提升")

    def _decrease_priority(self):
        if not self.selected_items:
            messagebox.showwarning("提示", "请先选择要调整优先级的窗口")
            return

        hwnd = self.selected_items[0]
        
        # 检查是否是管理工具窗口
        if hwnd == self.manager_hwnd:
            messagebox.showwarning("提示", "管理工具窗口优先级最高且不可调整")
            return
        
        if hwnd not in self.priority_map:
            messagebox.showwarning("提示", "该窗口尚未置顶，请先置顶")
            return

        current_priority = self.priority_map[hwnd]
        # 获取除管理工具外的最小优先级
        min_priority = min([p for h, p in self.priority_map.items() if h != self.manager_hwnd], default=0)

        if current_priority <= min_priority:
            messagebox.showinfo("提示", "该窗口已是最低优先级")
            return

        for h, p in list(self.priority_map.items()):
            if h != self.manager_hwnd and p < current_priority:
                self.priority_map[h] = p + 1

        self.priority_map[hwnd] = min_priority
        self.window_manager.update_priority_order(self.priority_map)
        self._refresh_window_list()
        self.status_label.config(text="优先级已降低")

    def _priority_list_up(self):
        """在置顶列表中上移选中项（提高优先级）"""
        selection = self.priority_list.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先在置顶列表中选择要调整的窗口")
            return

        index = selection[0]
        sorted_items = sorted(self.priority_map.items(), key=lambda x: x[1], reverse=True)
        
        current_hwnd = sorted_items[index][0]
        
        # 检查是否是管理工具窗口
        if current_hwnd == self.manager_hwnd:
            messagebox.showwarning("提示", "管理工具窗口优先级最高且不可调整")
            return

        if index > 0:
            prev_hwnd = sorted_items[index - 1][0]
            
            # 如果上一项是管理工具窗口，不允许上移
            if prev_hwnd == self.manager_hwnd:
                messagebox.showinfo("提示", "管理工具窗口优先级最高，无法超越")
                return

            # 交换优先级
            current_priority = self.priority_map[current_hwnd]
            prev_priority = self.priority_map[prev_hwnd]

            self.priority_map[current_hwnd] = prev_priority + 1
            self.priority_map[prev_hwnd] = prev_priority

            # 调整其他窗口的优先级
            for h, p in list(self.priority_map.items()):
                if h != current_hwnd and h != prev_hwnd and h != self.manager_hwnd and p == prev_priority + 1:
                    self.priority_map[h] = p - 1

            self.window_manager.update_priority_order(self.priority_map)
            self._refresh_window_list()
            self._update_priority_list_selection(index - 1)
            self.status_label.config(text="已上移")

    def _priority_list_down(self):
        """在置顶列表中下移选中项（降低优先级）"""
        selection = self.priority_list.curselection()
        if not selection:
            messagebox.showwarning("提示", "请先在置顶列表中选择要调整的窗口")
            return

        index = selection[0]
        sorted_items = sorted(self.priority_map.items(), key=lambda x: x[1], reverse=True)
        
        current_hwnd = sorted_items[index][0]
        
        # 检查是否是管理工具窗口
        if current_hwnd == self.manager_hwnd:
            messagebox.showwarning("提示", "管理工具窗口优先级最高且不可调整")
            return

        if index < len(sorted_items) - 1:
            next_hwnd = sorted_items[index + 1][0]

            # 交换优先级
            current_priority = self.priority_map[current_hwnd]
            next_priority = self.priority_map[next_hwnd]

            self.priority_map[current_hwnd] = next_priority - 1
            self.priority_map[next_hwnd] = next_priority

            # 调整其他窗口的优先级
            for h, p in list(self.priority_map.items()):
                if h != current_hwnd and h != next_hwnd and h != self.manager_hwnd and p == next_priority - 1:
                    self.priority_map[h] = p + 1

            self.window_manager.update_priority_order(self.priority_map)
            self._refresh_window_list()
            self._update_priority_list_selection(index + 1)
            self.status_label.config(text="已下移")

    def _update_priority_list_selection(self, index):
        """更新优先级列表的选中项"""
        if 0 <= index < self.priority_list.size():
            self.priority_list.selection_clear(0, tk.END)
            self.priority_list.see(index)
            self.priority_list.select_set(index)

    def _on_priority_list_double_click(self):
        """双击优先级列表项，打开编辑对话框"""
        selection = self.priority_list.curselection()
        if not selection:
            return

        index = selection[0]
        sorted_items = sorted(self.priority_map.items(), key=lambda x: x[1], reverse=True)
        hwnd = sorted_items[index][0]
        
        # 检查是否是管理工具窗口
        if hwnd == self.manager_hwnd:
            messagebox.showwarning("提示", "管理工具窗口优先级最高且不可调整")
            return
        
        current_priority = self.priority_map[hwnd]

        # 获取窗口标题
        try:
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                title_buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title_buffer, length + 1)
                title = title_buffer.value
            else:
                title = "Unknown"
        except:
            title = "Unknown"

        # 创建输入对话框
        dialog = tk.Toplevel(self.root)
        dialog.title("设置优先级")
        dialog.geometry("400x150")
        dialog.resizable(False, False)
        dialog.transient(self.root)
        dialog.grab_set()

        # 居中显示
        dialog.geometry(f"+{self.root.winfo_x() + 50}+{self.root.winfo_y() + 50}")

        ttk.Label(dialog, text=f"窗口: {title}", font=("Microsoft YaHei", 10)).pack(pady=10)
        ttk.Label(dialog, text=f"当前优先级: {current_priority}", font=("Microsoft YaHei", 10)).pack(pady=5)

        input_frame = ttk.Frame(dialog)
        input_frame.pack(pady=10)

        ttk.Label(input_frame, text="新优先级:").pack(side=tk.LEFT, padx=5)
        priority_var = tk.StringVar(value=str(current_priority))
        priority_entry = ttk.Entry(input_frame, textvariable=priority_var, width=10)
        priority_entry.pack(side=tk.LEFT, padx=5)
        priority_entry.select_range(0, tk.END)
        priority_entry.focus()

        def save_priority():
            try:
                new_priority = int(priority_var.get())
                if new_priority < 1:
                    messagebox.showerror("错误", "优先级必须大于0", parent=dialog)
                    return

                # 更新优先级
                self.priority_map[hwnd] = new_priority
                self.window_manager.update_priority_order(self.priority_map)
                self._refresh_window_list()
                dialog.destroy()
                self.status_label.config(text=f"优先级已设置为 {new_priority}")
            except ValueError:
                messagebox.showerror("错误", "请输入有效的数字", parent=dialog)

        def cancel():
            dialog.destroy()

        button_frame = ttk.Frame(dialog)
        button_frame.pack(pady=15)

        ttk.Button(button_frame, text="确定", command=save_priority, width=10).pack(side=tk.LEFT, padx=5)
        ttk.Button(button_frame, text="取消", command=cancel, width=10).pack(side=tk.LEFT, padx=5)

        # 绑定回车键
        priority_entry.bind("<Return>", lambda e: save_priority())
        priority_entry.bind("<Escape>", lambda e: cancel())

        # 居中对话框
        dialog.update_idletasks()
        x = (dialog.winfo_screenwidth() // 2) - (dialog.winfo_width() // 2)
        y = (dialog.winfo_screenheight() // 2) - (dialog.winfo_height() // 2)
        dialog.geometry(f"+{x}+{y}")

    def _on_monitor_update(self):
        self.root.after(0, self._refresh_window_list)

    def _on_close(self):
        # 取消所有用户窗口的置顶（保留管理工具窗口）
        for hwnd in list(self.priority_map.keys()):
            if hwnd != self.manager_hwnd:  # 跳过管理工具窗口
                try:
                    self.window_manager.set_topmost(hwnd, False)
                except:
                    pass

        self.window_manager.stop_monitor = True
        self.root.destroy()


def main():
    root = tk.Tk()
    app = PriorityManagerGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()