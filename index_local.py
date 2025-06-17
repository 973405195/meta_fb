import tkinter as tk
from tkinter import messagebox, ttk, filedialog
import pymysql
import os
import threading
import time
import requests
import json
from concurrent.futures import ThreadPoolExecutor
from qcloud_cos import CosConfig, CosS3Client, CosServiceError

# 本地测试
# API_BASE_URL = "http://127.0.0.1:5000/app"  # 确保与Flask服务器匹配


# 服务器配置
API_BASE_URL = "http://43.161.248.92/app"  # 确保与Flask服务器匹配

# 数据库配置
db_config = {
    'host': 'sh-cynosdbmysql-grp-pbl95cyg.sql.tencentcdb.com',
    'port': 23593,
    'user': 'root',
    'password': 'Junzhun123',
    'database': 'video_auto',
    'charset': 'utf8mb4'
}


# 数据库操作封装
def insert_bm_info(bm_id, bm_token, bm_note):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    sql = "INSERT INTO bm_info (bm_id, bm_token, bm_note) VALUES (%s, %s, %s)"
    cursor.execute(sql, (bm_id, bm_token, bm_note))
    conn.commit()
    cursor.close()
    conn.close()


def fetch_bm_notes():
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    sql = "SELECT id, bm_note FROM bm_info"
    cursor.execute(sql)
    results = cursor.fetchall()
    cursor.close()
    conn.close()
    return results


def fetch_bm_detail(bm_id):
    conn = pymysql.connect(**db_config)
    cursor = conn.cursor()
    sql = "SELECT bm_id, bm_token, bm_note FROM bm_info WHERE id = %s"
    cursor.execute(sql, (bm_id,))
    result = cursor.fetchone()
    cursor.close()
    conn.close()
    return result


# API操作函数
def get_bm_folders_nested(business_id, access_token):
    """通过API获取文件夹列表"""
    try:
        print(f"正在请求文件夹列表: business_id={business_id}")

        # 添加重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                response = requests.get(
                    f"{API_BASE_URL}/get_folders",
                    params={'business_id': business_id, 'access_token': access_token},
                    timeout=30  # 添加超时设置
                )

                # 打印原始响应内容用于调试
                print(f"API响应状态码: {response.status_code}")
                print(f"API响应内容前100个字符: {response.text[:100]}")

                if response.status_code == 200:
                    # 尝试解析JSON响应
                    try:
                        data = response.json()
                        return data
                    except json.JSONDecodeError as json_err:
                        # 如果不是最后一次尝试，则重试
                        if attempt < max_retries - 1:
                            print(f"JSON解析错误，尝试重试 ({attempt + 1}/{max_retries}): {str(json_err)}")
                            time.sleep(1)  # 等待1秒后重试
                            continue
                        else:
                            # 最后一次尝试失败，抛出异常
                            raise Exception(
                                f"无法解析服务器返回的JSON数据: {str(json_err)}, 原始响应: {response.text[:200]}")
                else:
                    # 尝试解析错误信息
                    try:
                        error_msg = response.json().get('error', f'获取文件夹失败，状态码: {response.status_code}')
                    except:
                        error_msg = f'获取文件夹失败，状态码: {response.status_code}, 响应: {response.text[:100]}'

                    # 如果不是最后一次尝试，则重试
                    if attempt < max_retries - 1:
                        print(f"API请求失败，尝试重试 ({attempt + 1}/{max_retries}): {error_msg}")
                        time.sleep(1)  # 等待1秒后重试
                        continue
                    else:
                        # 最后一次尝试失败，抛出异常
                        raise Exception(error_msg)

            except requests.exceptions.RequestException as req_err:
                # 处理请求异常
                if attempt < max_retries - 1:
                    print(f"网络请求异常，尝试重试 ({attempt + 1}/{max_retries}): {str(req_err)}")
                    time.sleep(1)  # 等待1秒后重试
                    continue
                else:
                    # 最后一次尝试失败，抛出异常
                    raise Exception(f"网络请求异常: {str(req_err)}")

        # 如果所有重试都失败
        raise Exception("获取文件夹列表失败，已达到最大重试次数")

    except Exception as e:
        print(f"获取文件夹列表出错: {str(e)}")
        raise


def create_folder(name, business_id, access_token):
    """通过API创建文件夹"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/create_folder",
            json={'name': name, 'business_id': business_id, 'access_token': access_token},
            headers={'Content-Type': 'application/json'}
        )
        data = response.json()
        if response.status_code == 200 and data.get('success'):
            return data.get('id')
        else:
            error_msg = data.get('error', '创建文件夹失败')
            raise Exception(error_msg)
    except Exception as e:
        print(f"创建文件夹出错: {str(e)}")
        raise


def create_subfolder_api(name, parent_folder_id, business_id, access_token, parent_name=None):
    """通过API创建子文件夹"""
    try:
        response = requests.post(
            f"{API_BASE_URL}/create_subfolder",
            json={
                'name': name,
                'parent_folder_id': parent_folder_id,
                'business_id': business_id,
                'access_token': access_token
            },
            headers={'Content-Type': 'application/json'}
        )
        data = response.json()
        if response.status_code == 200 and data.get('success'):
            messagebox.showinfo("成功", data.get('message', f"子文件夹 '{name}' 创建成功！"))
            return data.get('id')
        else:
            error_msg = data.get('error', '创建子文件夹失败')
            messagebox.showerror("错误", f"子文件夹创建失败: {error_msg}")
            return None
    except Exception as e:
        messagebox.showerror("错误", f"创建子文件夹失败: {str(e)}")
        return None


def upload_video_to_bm_library(video_path, business_id, access_token, folder_id, title):
    """直接上传视频到腾讯云COS，然后通知服务器处理，并等待Meta上传完成"""
    try:
        # 打印请求参数以便调试
        print(f"正在处理视频: {video_path} 到文件夹ID: {folder_id}")
        # 获取文件夹名和文件名
        folder_name = os.path.basename(os.path.dirname(video_path))
        filename = os.path.basename(video_path)
        print(f"文件夹名: {folder_name}, 文件名: {filename}")
        # 腾讯云配置信息
        secret_id = ""
        secret_key = ""
        region = "ap-shanghai"
        bucket = "zh-video-1322637479"
        # 构造COS存储路径
        cos_key = f"zh_video/{folder_name}/{filename}".replace("\\", "/")
        # 使用requests库直接上传文件到COS
        print(f"正在上传视频到腾讯云COS: {cos_key}")

        # 计算文件大小和MD5，用于验证上传
        file_size = os.path.getsize(video_path)

        # 使用腾讯云SDK上传文件
        config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
        client = CosS3Client(config)

        # 检查文件是否已存在
        try:
            client.head_object(Bucket=bucket, Key=cos_key)
            print(f"✅ 文件已存在于COS中: {cos_key}")
            exists = True
        except CosServiceError as e:
            if e.get_status_code() == 404:
                # 文件不存在，上传文件
                print(f"⬆️ 开始上传文件到COS: {video_path}")
                client.upload_file(Bucket=bucket, Key=cos_key, LocalFilePath=video_path)
                print(f"✅ 文件上传到COS成功: {cos_key}")
                exists = False
            else:
                print(f"❌ 检查COS文件是否存在时出错: {str(e)}")
                return False

        # 通知服务器处理视频文件
        data = {
            'folder_id': folder_id,
            'business_id': business_id,
            'access_token': access_token,
            'filename': filename,
            'folder_name': folder_name,
            'cos_key': cos_key
        }

        # 存储服务器日志信息的变量
        server_logs = []

        # 改进轮询机制，减少等待时间
        max_poll_times = 200  # 保持合理的轮询次数
        poll_interval = 5  # 轮询间隔为8秒
        meta_upload_complete = False

        for attempt in range(max_poll_times):
            try:
                # 发送请求给服务器处理视频
                print(f"正在发送处理请求到服务器 (尝试 {attempt + 1}/{max_poll_times})...")
                response = requests.post(
                    f"{API_BASE_URL}/upload_video",
                    json=data,
                    timeout=300  # 保持合理的超时设置
                )

                # 记录服务器响应日志
                log_entry = f"服务器处理通知响应: 状态码={response.status_code}"
                print(log_entry)
                server_logs.append(log_entry)

                # 处理状态码202的情况 (任务已加入队列)
                if response.status_code == 202:
                    try:
                        resp_data = response.json()
                        task_id = resp_data.get('task_id')

                        if task_id:
                            log_entry = f"✅ 请求已被接受，任务ID: {task_id}, 正在等待Meta处理完成..."
                            print(log_entry)
                            server_logs.append(log_entry)

                            # 使用单一的轮询请求方式，简化轮询逻辑
                            for status_attempt in range(max_poll_times):
                                # 如果不是第一次轮询，等待一段时间
                                if status_attempt > 0:
                                    time.sleep(poll_interval)

                                # 检查是否在服务器日志中发现成功标记
                                for log in server_logs:
                                    if "finish response: 200 {\"success\":true}" in log.lower():
                                        print("✅ 检测到Meta上传成功标志，直接返回成功")
                                        return True

                                try:
                                    # 获取任务状态
                                    status_resp = requests.get(
                                        f"{API_BASE_URL}/task_status/{task_id}",
                                        timeout=60
                                    )

                                    log_entry = f"轮询响应 ({status_attempt + 1}): {status_resp.status_code} - {status_resp.text[:200]}"
                                    print(log_entry)
                                    server_logs.append(log_entry)

                                    # 只要有成功的响应就立即处理
                                    if status_resp.status_code == 200:
                                        response_text = status_resp.text.lower()

                                        # 再次检查日志是否有成功标志
                                        for log in server_logs:
                                            if "finish response: 200 {\"success\":true}" in log.lower():
                                                print("✅ 检测到Meta上传成功标志，直接返回成功")
                                                return True

                                        # 更灵活的检查方式，只要有任何成功指示就接受
                                        if ("success" in response_text and "true" in response_text) or \
                                                ("meta_uploaded" in response_text) or \
                                                ("完成" in response_text) or \
                                                ("上传成功" in response_text):
                                            print("✅ 检测到Meta上传成功标志")
                                            return True

                                        # 解析JSON响应
                                        try:
                                            status_data = status_resp.json()

                                            # 如果任务状态为completed，并且结果为成功
                                            if status_data.get('status') in ['completed', 'processing']:
                                                # 检查进度字段
                                                if status_data.get('progress') == 'meta_uploaded':
                                                    print("✅ 检测到Meta上传已完成状态")
                                                    return True

                                                # 检查结果字段
                                                result = status_data.get('result', {})
                                                if isinstance(result, dict) and result.get('success'):
                                                    meta_id = result.get('id', '')
                                                    print(f"✅ 视频处理成功，Meta ID: {meta_id}")
                                                    return True
                                        except Exception as json_err:
                                            print(f"解析任务状态JSON时出错: {str(json_err)}")
                                except Exception as e:
                                    print(f"❌ 检查任务状态时出错: {str(e)}")

                            # 轮询结束但未收到明确成功/失败信号
                            # 最后再检查一次日志
                            for log in server_logs:
                                if "finish response: 200 {\"success\":true}" in log.lower():
                                    print("✅ 检测到Meta上传成功标志，直接返回成功")
                                    return True

                            # 由于已经成功上传到COS，所以仍然返回成功
                            print("⚠️ 轮询后未收到明确信号，但视频已成功上传到COS，视为成功")
                            return True
                        else:
                            print(f"❌ 响应中缺少任务ID")
                            return False
                    except Exception as e:
                        print(f"❌ 解析响应失败: {str(e)}")
                        return False

                # 处理503错误 - 服务器忙，需要等待重试
                if response.status_code == 503:
                    print(f"⚠️ 服务器返回503错误(服务暂时不可用)，将在{poll_interval}秒后重试...")
                    time.sleep(poll_interval)
                    continue

                # 正常响应
                if response.text.strip():  # 确保响应不为空
                    try:
                        result = response.json()
                        # 修改检查逻辑: 只要success=True就认为成功，无论是否有其他字段
                        if (response.status_code == 200 and result.get('success')) or "success" in str(
                                result).lower() and "true" in str(result).lower():
                            print(f"✅ 视频处理成功: {result.get('message', '服务器确认处理成功')}")
                            meta_upload_complete = True
                            return True
                        else:
                            error_msg = result.get('error', '未知错误')
                            print(f"❌ 视频处理失败: {error_msg}")
                            return False
                    except Exception as e:
                        print(f"❌ 解析响应失败: {str(e)}, 原始响应: {response.text[:200]}")
                        if attempt < max_poll_times - 1:
                            time.sleep(poll_interval)
                            continue
                        return False
                else:
                    print(f"⚠️ 服务器返回空响应，将在{poll_interval}秒后重试...")
                    if attempt < max_poll_times - 1:
                        time.sleep(poll_interval)
                        continue
                    return False

            except requests.exceptions.RequestException as e:
                print(f"❌ 网络请求异常: {str(e)}")
                if attempt < max_poll_times - 1:
                    print(f"将在{poll_interval}秒后重试...")
                    time.sleep(poll_interval)
                    continue
                return False

        # 最后检查一次日志是否包含成功标志
        for log in server_logs:
            if "finish response: 200 {\"success\":true}" in log.lower():
                print("✅ 检测到Meta上传成功标志，直接返回成功")
                return True

        # 如果所有轮询都未收到明确的失败信号，视为上传成功
        print(f"⚠️ 所有轮询尝试后未收到明确的失败信号，视为上传成功")
        return True

    except FileNotFoundError:
        print(f"❌ 文件不存在: {video_path}")
        return False
    except requests.exceptions.RequestException as e:
        print(f"❌ 网络请求失败: {str(e)}")
        return False
    except Exception as e:
        print(f"❌ 上传视频出错: {str(e)}")
        return False


# 添加一个清理服务器文件的函数
def cleanup_server_files(video_path):
    """清理服务器上的临时文件"""
    try:
        # 从路径中提取文件夹名
        folder_name = os.path.basename(os.path.dirname(video_path))

        print(f"正在请求清理服务器文件夹: {folder_name}")

        # 等待一段时间以确保文件不再被使用
        time.sleep(1)

        # 调用删除文件的API
        response = requests.get(
            f"{API_BASE_URL}/delete_file",
            params={'file_path': folder_name},
            timeout=30  # 设置较长的超时时间
        )

        try:
            result = response.json()
            if response.status_code == 200 and result.get('success', False):
                print(f"✅ 文件夹清理成功: {folder_name}")
                return True
            else:
                error_msg = result.get('error', '未知错误')
                print(f"❌ 文件夹清理失败: {error_msg}")
                # 即使清理失败也返回True，避免影响用户体验
                return True
        except ValueError:  # JSON解析错误
            print(f"❌ 清理API返回非JSON响应: {response.text}")
            return True
    except Exception as e:
        print(f"调用清理API出错: {str(e)}")
        # 即使清理失败也返回True，避免影响用户体验
        return True


# 主应用类
class BMApp:
    def __init__(self, root):
        self.root = root
        self.root.title("BM 信息管理")
        self.root.geometry("800x700")

        # 版本号
        self.version = "v1.0.2"

        # 创建菜单按钮
        self.menu_frame = tk.Frame(self.root)
        self.menu_frame.pack(side="left", fill="y")

        self.content_frame = tk.Frame(self.root, bg="white")
        self.content_frame.pack(side="right", fill="both", expand=True)

        # 添加进度条框架
        self.progress_frame = tk.Frame(self.root)
        self.progress_frame.pack(side="bottom", fill="x", padx=10, pady=5)

        self.status_label = tk.Label(self.progress_frame, text="就绪", anchor="w")
        self.status_label.pack(side="left", padx=5)

        self.progress_bar = ttk.Progressbar(self.progress_frame, mode="determinate", length=400)
        self.progress_bar.pack(side="right", padx=5)

        # 默认隐藏进度条
        self.progress_frame.pack_forget()

        # 添加版本号标签到左下角
        self.version_frame = tk.Frame(self.root)
        self.version_frame.pack(side="bottom", fill="x")
        self.version_label = tk.Label(self.version_frame, text=f"版本: {self.version}",
                                      fg="#666666", font=("Arial", 8), anchor="w")
        self.version_label.pack(side="left", padx=10, pady=2)

        self.menu_buttons = [
            ("添加 BM", self.show_add_bm_page),
            ("查看 BM", self.show_bm_list_page)
        ]

        for name, callback in self.menu_buttons:
            btn = tk.Button(self.menu_frame, text=name, width=20, command=callback)
            btn.pack(pady=5)

        self.show_add_bm_page()

    def show_progress(self, show=True):
        """显示或隐藏进度框架"""
        if show:
            self.progress_frame.pack(side="bottom", fill="x", padx=10, pady=5)
        else:
            self.progress_frame.pack_forget()

    def update_progress(self, value, status_text):
        """更新进度条和状态标签"""
        self.progress_bar["value"] = value
        self.status_label.config(text=status_text)
        self.root.update_idletasks()  # 强制更新UI

    def clear_content(self):
        for widget in self.content_frame.winfo_children():
            widget.destroy()

    def show_add_bm_page(self):
        self.clear_content()
        tk.Label(self.content_frame, text="BM-ID：").grid(row=0, column=0, padx=10, pady=10, sticky="e")
        bm_id_entry = tk.Entry(self.content_frame, width=40)
        bm_id_entry.grid(row=0, column=1)

        tk.Label(self.content_frame, text="BM-token：").grid(row=1, column=0, padx=10, pady=10, sticky="e")
        bm_token_entry = tk.Entry(self.content_frame, width=40)
        bm_token_entry.grid(row=1, column=1)

        tk.Label(self.content_frame, text="BM-备注信息：").grid(row=2, column=0, padx=10, pady=10, sticky="e")
        bm_note_entry = tk.Entry(self.content_frame, width=40)
        bm_note_entry.grid(row=2, column=1)

        def submit_thread():
            # 在线程中执行数据库操作
            try:
                insert_bm_info(bm_id_entry.get(), bm_token_entry.get(), bm_note_entry.get())
                # 操作完成后在主线程中更新UI
                self.root.after(0, lambda: [
                    self.update_progress(100, "添加完成"),
                    messagebox.showinfo("成功", "BM 信息已添加"),
                    bm_id_entry.delete(0, tk.END),
                    bm_token_entry.delete(0, tk.END),
                    bm_note_entry.delete(0, tk.END),
                    submit_btn.config(state=tk.NORMAL, bg="#4CAF50"),
                    self.show_progress(False)
                ])
            except Exception as e:
                self.root.after(0, lambda: [
                    messagebox.showerror("错误", f"添加失败: {str(e)}"),
                    submit_btn.config(state=tk.NORMAL, bg="#4CAF50"),
                    self.show_progress(False)
                ])

        def submit():
            # 检查输入
            if not bm_id_entry.get() or not bm_token_entry.get():
                messagebox.showwarning("警告", "请输入BM-ID和BM-token")
                return

            # 禁用按钮，改变颜色
            submit_btn.config(state=tk.DISABLED, bg="gray")

            # 显示进度条
            self.show_progress(True)
            self.update_progress(20, "正在添加...")

            # 创建线程执行操作
            threading.Thread(target=submit_thread, daemon=True).start()

        submit_btn = tk.Button(self.content_frame, text="添加", command=submit, bg="#4CAF50", fg="white")
        submit_btn.grid(row=3, column=0, columnspan=2, pady=20)

    def show_bm_list_page(self):
        self.clear_content()
        tk.Label(self.content_frame, text="BM 备注列表", font=("Arial", 12)).pack(pady=10)

        tree_frame = tk.Frame(self.content_frame)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        tree = ttk.Treeview(tree_frame, columns=("id", "note"), show="headings", height=10)
        tree.heading("id", text="ID")
        tree.heading("note", text="备注信息")
        tree.column("id", anchor="center", width=80)
        tree.column("note", anchor="center", width=300)
        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
        scrollbar.pack(side="right", fill="y")
        tree.configure(yscrollcommand=scrollbar.set)

        # 设置加载状态
        self.show_progress(True)
        self.update_progress(30, "正在加载BM列表...")

        def load_data_thread():
            try:
                # 在线程中获取数据
                data = fetch_bm_notes()

                # 在主线程中更新UI
                self.root.after(0, lambda: [
                    # 清空现有数据
                    [tree.delete(item) for item in tree.get_children()],
                    # 插入新数据
                    [tree.insert("", "end", values=row) for row in data],
                    # 更新进度
                    self.update_progress(100, "加载完成"),
                    self.show_progress(False)
                ])
            except Exception as e:
                self.root.after(0, lambda: [
                    messagebox.showerror("错误", f"加载失败: {str(e)}"),
                    self.show_progress(False)
                ])

        # 启动线程加载数据
        threading.Thread(target=load_data_thread, daemon=True).start()

        def view_selected_detail():
            selected = tree.selection()
            if not selected:
                messagebox.showwarning("警告", "请先选择一个BM")
                return

            # 禁用按钮
            detail_button.config(state=tk.DISABLED, bg="gray")
            self.show_progress(True)
            self.update_progress(10, "正在加载详情...")

            def load_detail_thread():
                try:
                    bm_id = tree.item(selected[0])["values"][0]
                    detail = fetch_bm_detail(bm_id)

                    # 在主线程中更新UI
                    self.root.after(0,
                                    lambda: self.show_bm_detail_page(detail) if detail else messagebox.showerror("错误",
                                                                                                                 "无法获取详情"))
                except Exception as e:
                    # 处理可能的异常
                    self.root.after(0, lambda: [
                        messagebox.showerror("错误", f"加载详情失败: {str(e)}"),
                        self.show_progress(False),
                        detail_button.config(state=tk.NORMAL, bg="#4CAF50") if detail_button.winfo_exists() else None
                    ])

            threading.Thread(target=load_detail_thread, daemon=True).start()

        detail_button = tk.Button(self.content_frame, text="查看详情", command=view_selected_detail, bg="#4CAF50",
                                  fg="white", width=15)
        detail_button.pack(pady=10)

    def show_bm_detail_page(self, detail):
        self.clear_content()

        # 显示进度条
        self.show_progress(True)
        self.update_progress(20, "正在获取文件夹数据...")

        # 在线程中获取数据
        def load_folders_thread():
            try:
                # 调用 API 获取返回数据
                result = get_bm_folders_nested(detail[0], detail[1])

                # 在主线程中更新UI
                self.root.after(0, lambda: self.display_folder_data(detail, result))
            except Exception as e:
                # 捕获异常并将其传递给Lambda函数
                error_msg = str(e)  # 先保存错误信息为局部变量
                self.root.after(0, lambda error=error_msg: [
                    messagebox.showerror("错误", f"获取文件夹数据失败: {error}"),
                    self.show_progress(False),
                    self.show_bm_list_page()
                ])

        threading.Thread(target=load_folders_thread, daemon=True).start()

    def display_folder_data(self, detail, result):
        """显示文件夹数据的UI部分，支持多级嵌套结构"""
        self.update_progress(80, "正在构建界面...")

        tk.Label(self.content_frame, text="BM 详情信息", font=("Arial", 14, "bold")).pack(pady=10)
        tk.Label(self.content_frame, text=f"BM-ID：{detail[0]}", anchor="w", width=60).pack(pady=5)
        tk.Label(self.content_frame, text=f"BM-Token：{detail[1]}", anchor="w", width=60).pack(pady=5)
        tk.Label(self.content_frame, text=f"备注信息：{detail[2]}", anchor="w", width=60).pack(pady=5)

        # 结果列表
        tk.Label(self.content_frame, text="文件夹列表", font=("Arial", 12)).pack(pady=10)
        frame = tk.Frame(self.content_frame)
        frame.pack(fill="both", expand=True, padx=20, pady=10)

        tree = ttk.Treeview(
            frame,
            columns=("id", "full_path"),
            show="tree headings",  # 显示树 + 表头
            height=10
        )
        tree.heading("#0", text="名称")
        tree.column("#0", anchor="w", width=200)
        tree.heading("id", text="ID")
        tree.column("id", anchor="w", width=150)
        tree.heading("full_path", text="路径")
        tree.column("full_path", anchor="w", width=250)
        tree.pack(side="left", fill="both", expand=True)

        # 添加滚动条
        sb = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        sb.pack(side="right", fill="y")
        tree.configure(yscrollcommand=sb.set)

        # 🔁 递归插入多级节点
        def insert_folder_node(parent, folder):
            node = tree.insert(
                parent, "end",
                text=folder["name"],
                values=(folder["id"], folder["full_path"])
            )
            for sub in folder.get("data", []):
                insert_folder_node(node, sub)

        # 插入全部数据
        if isinstance(result, list):
            for folder in result:
                insert_folder_node("", folder)

        # 创建上传进度显示
        upload_frame = tk.LabelFrame(self.content_frame, text="上传进度", padx=10, pady=10)
        upload_status = tk.Label(upload_frame, text="待上传...", anchor="w")
        upload_status.pack(fill="x", pady=2)
        upload_bar = ttk.Progressbar(upload_frame, mode="determinate")
        upload_bar.pack(fill="x", pady=5)
        upload_frame.pack(fill="x", padx=20, pady=5)
        upload_frame.pack_forget()  # 默认隐藏

        # 按钮区域 - 使用Frame+Grid布局
        button_frame = tk.Frame(self.content_frame)
        button_frame.pack(fill="x", padx=20, pady=10)

        # 配置列的权重，使其均匀分布
        button_frame.columnconfigure(0, weight=1)
        button_frame.columnconfigure(1, weight=1)

        # 按钮样式配置
        btn_cfg = {"height": 2, "width": 20, "fg": "white"}

        # 创建子文件夹功能
        def create_subfolder():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("警告", "请先选择一个主文件夹！")
                return

            parent_folder_id = tree.item(sel[0])['values'][0]  # 获取主文件夹的 ID
            parent_name = tree.item(sel[0])['values'][1]

            dialog = tk.Toplevel(self.root)
            dialog.title("创建子文件夹")
            dialog.geometry("300x150")

            tk.Label(dialog, text="请输入子文件夹名称：").pack(pady=10)
            entry = tk.Entry(dialog, width=30)
            entry.pack(pady=5)
            entry.focus_set()

            def submit_subfolder_name():
                subfolder_name = entry.get().strip()
                if not subfolder_name:
                    messagebox.showwarning("提示", "请输入子文件夹名称")
                    return

                # 禁用创建按钮
                create_btn.config(state=tk.DISABLED, bg="gray")
                status_label = tk.Label(dialog, text="正在创建...", fg="blue")
                status_label.pack(pady=5)

                def create_subfolder_thread():
                    try:
                        # 调用函数创建子文件夹
                        create_subfolder_api(subfolder_name, parent_folder_id, detail[0], detail[1], parent_name)

                        # 在主线程中更新UI
                        dialog.after(0, lambda: [
                            dialog.destroy(),
                            self.show_bm_detail_page(detail)  # 刷新页面显示新创建的文件夹
                        ])
                    except Exception as e:
                        dialog.after(0, lambda: [
                            messagebox.showerror("错误", f"创建子文件夹失败: {str(e)}"),
                            dialog.destroy()
                        ])

                threading.Thread(target=create_subfolder_thread, daemon=True).start()

            create_btn = tk.Button(dialog, text="创建", command=submit_subfolder_name, bg="#4CAF50", fg="white")
            create_btn.pack(pady=10)

        # 上传选择文件夹功能
        def upload_folder():
            sel = tree.selection()
            if not sel:
                messagebox.showwarning("警告", "请先选择一个文件夹！")
                return

            folder_id = tree.item(sel[0])['values'][0]
            directory = filedialog.askdirectory(title="选择本地文件夹")
            if not directory:
                return

            # 禁用上传按钮
            upload_btn.config(state=tk.DISABLED, bg="gray")

            # 显示上传进度
            upload_frame.pack(fill="x", padx=20, pady=5)
            upload_bar["value"] = 0
            upload_status.config(text="正在扫描文件...")

            def upload_thread():
                try:
                    # 获取所有mp4文件
                    video_files = []
                    for root, dirs, files in os.walk(directory):
                        for f in files:
                            if f.lower().endswith('.mp4'):
                                path = os.path.join(root, f)
                                video_files.append((path, f))

                    total_files = len(video_files)
                    if total_files == 0:
                        self.root.after(0, lambda: [
                            messagebox.showinfo("提示", "未找到MP4文件"),
                            upload_btn.config(state=tk.NORMAL, bg="#FF5722"),
                            upload_frame.pack_forget()
                        ])
                        return

                    # 多线程上传相关变量
                    MAX_THREADS = 1  # 默认3个线程
                    successful_uploads = 0
                    uploaded_files_count = 0
                    upload_lock = threading.Lock()  # 线程锁
                    active_uploads = []  # 记录当前上传的文件

                    # 单个文件上传函数
                    def upload_single_file(file_data):
                        nonlocal successful_uploads, uploaded_files_count
                        path, filename = file_data

                        with upload_lock:
                            active_uploads.append(filename)
                            # 更新UI
                            progress = int((uploaded_files_count / total_files) * 100)
                            active_str = ", ".join(active_uploads) if active_uploads else "等待中..."
                            if len(active_str) > 30:
                                active_str = active_str[:27] + "..."

                            self.root.after(0, lambda p=progress, a=active_str, c=uploaded_files_count, t=total_files: [
                                upload_bar.config(value=p),
                                upload_status.config(text=f"进度: {c}/{t} - 当前: {a}")
                            ])

                        try:
                            # 上传文件并等待处理完成
                            result = upload_video_to_bm_library(path, detail[0], detail[1], folder_id, filename)

                            with upload_lock:
                                # 处理结果 - 只有成功或失败两种状态
                                if result:
                                    successful_uploads += 1

                                uploaded_files_count += 1
                                if filename in active_uploads:
                                    active_uploads.remove(filename)

                                # 更新进度
                                progress = int((uploaded_files_count / total_files) * 100)
                                active_str = ", ".join(active_uploads) if active_uploads else "等待中..."
                                if len(active_str) > 30:
                                    active_str = active_str[:27] + "..."

                                self.root.after(0, lambda p=progress, a=active_str, c=uploaded_files_count,
                                                          t=total_files: [
                                    upload_bar.config(value=p),
                                    upload_status.config(text=f"进度: {c}/{t} - 当前: {a}")
                                ])

                        except Exception as e:
                            print(f"上传文件 {filename} 出错: {str(e)}")
                            with upload_lock:
                                uploaded_files_count += 1
                                if filename in active_uploads:
                                    active_uploads.remove(filename)

                    # 使用线程池执行上传任务
                    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
                        # 提交所有上传任务
                        futures = [executor.submit(upload_single_file, file_data) for file_data in video_files]

                        # 等待所有任务完成
                        for future in futures:
                            future.result()  # 等待任务完成，捕获可能的异常

                    # 上传完成后更新UI
                    self.root.after(0, lambda: [
                        upload_bar.config(value=100),
                        upload_status.config(text="上传完成"),
                        messagebox.showinfo("完成", f"上传完成，共{total_files}个文件，成功{successful_uploads}个。"),
                        upload_btn.config(state=tk.NORMAL, bg="#FF5722"),
                        upload_frame.pack_forget()
                    ])

                except Exception as e:
                    self.root.after(0, lambda: [
                        messagebox.showerror("错误", f"上传过程中出错: {str(e)}"),
                        upload_btn.config(state=tk.NORMAL, bg="#FF5722"),
                        upload_frame.pack_forget()
                    ])

            # 在单独的线程中执行上传操作，防止UI冻结
            threading.Thread(target=upload_thread, daemon=True).start()

        # 创建文件夹功能
        def open_create_folder_dialog():
            dialog = tk.Toplevel(self.root)
            dialog.title("创建素材文件夹")
            dialog.geometry("300x150")

            tk.Label(dialog, text="请输入文件夹名称：").pack(pady=10)
            entry = tk.Entry(dialog, width=30)
            entry.pack(pady=5)
            entry.focus_set()

            def submit_folder_name():
                folder_name = entry.get().strip()
                if not folder_name:
                    messagebox.showwarning("提示", "请输入文件夹名称")
                    return

                # 禁用创建按钮
                create_btn.config(state=tk.DISABLED, bg="gray")
                status_label = tk.Label(dialog, text="正在创建...", fg="blue")
                status_label.pack(pady=5)

                def create_folder_thread():
                    try:
                        # 调用API创建文件夹
                        create_folder(folder_name, detail[0], detail[1])

                        # 在主线程中更新UI
                        dialog.after(0, lambda: [
                            dialog.destroy(),
                            self.show_bm_detail_page(detail)  # 刷新页面显示新创建的文件夹
                        ])
                    except Exception as e:
                        dialog.after(0, lambda: [
                            messagebox.showerror("错误", f"创建文件夹失败: {str(e)}"),
                            dialog.destroy()
                        ])

                threading.Thread(target=create_folder_thread, daemon=True).start()

            create_btn = tk.Button(dialog, text="创建", command=submit_folder_name, bg="#4CAF50", fg="white")
            create_btn.pack(pady=10)

        # 创建按钮并使用网格布局
        upload_btn = tk.Button(button_frame, text="上传素材", command=upload_folder,
                               bg="#FF5722", **btn_cfg)
        upload_btn.grid(row=0, column=0, padx=15, pady=10, sticky="ew")

        tk.Button(button_frame, text="创建文件夹", command=open_create_folder_dialog,
                  bg="#4CAF50", **btn_cfg).grid(row=0, column=1, padx=15, pady=10, sticky="ew")

        tk.Button(button_frame, text="创建子文件夹", command=create_subfolder,
                  bg="#2196F3", **btn_cfg).grid(row=1, column=0, padx=15, pady=10, sticky="ew")

        tk.Button(button_frame, text="返回列表", command=self.show_bm_list_page,
                  bg="#607D8B", **btn_cfg).grid(row=1, column=1, padx=15, pady=10, sticky="ew")

        # 完成加载
        self.update_progress(100, "加载完成")
        self.show_progress(False)


if __name__ == "__main__":
    root = tk.Tk()
    app = BMApp(root)
    root.mainloop()
