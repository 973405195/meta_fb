import logging
import threading
import psutil
from concurrent.futures import ThreadPoolExecutor
import queue
from logging.handlers import RotatingFileHandler
import time
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import os
import requests
import uuid
from qcloud_cos import CosConfig, CosS3Client, CosServiceError
from qcloud_cos.cos_threadpool import SimpleThreadPool

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
BASE_FOLDER = 'uploads'
os.makedirs(BASE_FOLDER, exist_ok=True)

# 创建全局线程池，控制并发
MAX_WORKERS = 4  # 根据服务器CPU核心数调整
task_executor = ThreadPoolExecutor(max_workers=MAX_WORKERS)
active_tasks = 0
task_lock = threading.Lock()


# 创建一个任务管理函数
def execute_task(func, *args, **kwargs):
    global active_tasks
    with task_lock:
        if active_tasks >= MAX_WORKERS:
            return None, "服务器负载过高，请稍后重试"
        active_tasks += 1

    try:
        result = func(*args, **kwargs)
        return result, None
    except Exception as e:
        return None, str(e)
    finally:
        with task_lock:
            active_tasks -= 1


# 在app.py中添加任务队列和结果存储
task_queue = queue.Queue()
task_results = {}  # 存储任务结果


# 添加后台工作线程函数
def worker_thread():
    while True:
        try:
            task_id, func, args, kwargs = task_queue.get()
            try:
                # 设置全局任务ID，使处理函数能够访问
                global current_task_id
                current_task_id = task_id

                # 更新任务状态为处理中
                task_results[task_id] = {"status": "processing", "message": "任务正在处理中"}

                # 执行处理函数
                result = func(*args, **kwargs)

                # 确保任务状态更新为已完成
                task_results[task_id] = {"status": "completed", "result": result}

                # 清理全局任务ID
                del current_task_id

            except Exception as e:
                task_results[task_id] = {"status": "failed", "error": str(e)}
            finally:
                task_queue.task_done()
        except Exception as e:
            print(f"工作线程发生错误: {str(e)}")


# 启动工作线程
for _ in range(MAX_WORKERS):
    t = threading.Thread(target=worker_thread, daemon=True)
    t.start()

# 配置日志
log_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
log_file = 'app.log'
log_handler = RotatingFileHandler(log_file, maxBytes=10 * 1024 * 1024, backupCount=5)
log_handler.setFormatter(log_formatter)

app_logger = logging.getLogger('app')
app_logger.setLevel(logging.INFO)
app_logger.addHandler(log_handler)


@app.route('/app/upload_video', methods=['POST'])
def upload_video():
    # 检查系统资源
    if not check_system_resources():
        return jsonify({'success': False, 'error': '服务器负载过高，请稍后再试'}), 503

    # 处理请求参数...
    data = request.json

    # 创建一个任务ID
    task_id = str(uuid.uuid4())

    # 将任务添加到队列
    task_queue.put((
        task_id,
        process_video,
        (data,),
        {}
    ))

    # 立即返回任务ID
    return jsonify({
        'success': True,
        'message': '视频处理请求已接受，正在后台处理',
        'task_id': task_id
    }), 202  # 202 Accepted


# 添加视频处理函数
def process_video(data):
    """后台处理视频的函数，原upload_video的主要逻辑移到这里"""
    global current_task_id
    task_id = current_task_id  # 在函数开始时保存task_id的本地副本

    # 添加开始处理的日志
    print(f"开始处理视频上传任务: {task_id}")

    folder_id = data['folder_id']
    business_id = data['business_id']
    access_token = data['access_token']
    filename = data['filename']
    folder_name = data['folder_name']
    cos_key = data.get('cos_key')

    # 腾讯云配置信息
    secret_id = ""
    secret_key = ""
    region = "ap-shanghai"
    bucket = "zh-video-1322637479"

    # 如果没有提供cos_key，则根据文件夹名和文件名构造
    if not cos_key:
        cos_key = f"zh_video/{folder_name}/{filename}".replace("\\", "/")

    # 初始化COS配置与客户端
    config = CosConfig(Region=region, SecretId=secret_id, SecretKey=secret_key)
    client = CosS3Client(config)

    # 检查COS是否存在该文件
    try:
        client.head_object(Bucket=bucket, Key=cos_key)
        cos_url = f'https://{bucket}.cos.{region}.myqcloud.com/{cos_key}'
        print(f"✅ 文件已在COS中: {cos_key}")

        # 创建临时目录
        temp_dir = os.path.join(BASE_FOLDER, 'temp')
        os.makedirs(temp_dir, exist_ok=True)

        # 创建文件夹存储目录
        folder_storage_dir = os.path.join(temp_dir, folder_name)
        os.makedirs(folder_storage_dir, exist_ok=True)

        # 下载文件到临时位置，保持原始文件名
        temp_file_path = os.path.join(folder_storage_dir, filename)

        print(f"开始从COS下载文件: {cos_url} → {temp_file_path}")

        # 使用COS SDK下载文件
        download_from_cos(client, bucket, cos_key, temp_file_path)

        # 下载文件完成后立即更新任务状态为"下载完成"
        if 'current_task_id' in globals():
            task_results[current_task_id] = {
                "status": "processing",
                "progress": "download_completed",
                "message": f"文件已从COS下载完成: {temp_file_path}"
            }

        print(f"文件下载完成: {temp_file_path}")

        # 使用原始文件名作为标题
        fb_title = filename
        print(f"开始上传到Facebook，标题: {fb_title}")

        # 将视频上传到META，传递任务ID
        result = upload_to_meta(temp_file_path, business_id, access_token, folder_id, fb_title, task_id)

        # Meta上传完成后立即更新任务状态，不等待清理操作
        if result.get('success'):
            log_upload_success(business_id, folder_id, cos_url, result.get('id'))
            print(f"上传成功，Meta ID: {result.get('id')}")

            # 重要：立即更新任务状态为已完成
            if 'current_task_id' in globals():
                task_results[current_task_id] = {
                    "status": "completed",
                    "result": result
                }

            # 创建成功标记文件
            success_dir = os.path.join(BASE_FOLDER, 'success_tasks')
            os.makedirs(success_dir, exist_ok=True)
            with open(os.path.join(success_dir, f"{task_id}.success"), 'w') as f:
                f.write('success')
        else:
            print(f"上传失败: {result.get('error')}")

        # 清理临时文件
        try:
            os.remove(temp_file_path)
            print("临时文件清理完成")
        except Exception as cleanup_error:
            print(f"清理临时文件失败: {str(cleanup_error)}")

        return result

    except CosServiceError as e:
        error_msg = f"在腾讯云COS中找不到文件: {cos_key}, 错误: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 404

    except Exception as e:
        error_msg = f"处理COS文件时出错: {str(e)}"
        print(f"❌ {error_msg}")
        return jsonify({'success': False, 'error': error_msg}), 500


@app.route('/app/create_folder', methods=['POST'])
def create_folder():
    # 检查必要参数
    if not all(key in request.json for key in ['name', 'business_id', 'access_token']):
        return jsonify(
            {'success': False, 'error': '必须提供文件夹名称(name)、业务ID(business_id)和访问令牌(access_token)'}), 400

    name = request.json['name']
    business_id = request.json['business_id']
    access_token = request.json['access_token']

    # 调用Meta API创建文件夹
    url = f"https://graph.facebook.com/v22.0/{business_id}/creative_folders"
    payload = {
        'access_token': access_token,
        'name': name,
        'folder_type': 'VIDEO',
    }
    try:
        response = requests.post(url, data=payload)
        data = response.json()

        if 'id' in data:
            return jsonify({'success': True, 'id': data['id'], 'message': f"文件夹 '{name}' 创建成功"}), 200
        else:
            error = data.get('error', {}).get('message', '未知错误')
            return jsonify({'success': False, 'error': error}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/app/create_subfolder', methods=['POST'])
def create_subfolder():
    # 检查必要参数
    required_params = ['name', 'parent_folder_id', 'business_id', 'access_token']
    if not all(key in request.json for key in required_params):
        return jsonify({'success': False, 'error': '缺少必要参数。需要提供: ' + ', '.join(required_params)}), 400

    name = request.json['name']
    parent_folder_id = request.json['parent_folder_id']
    business_id = request.json['business_id']
    access_token = request.json['access_token']

    # 调用Meta API创建子文件夹
    url = f"https://graph.facebook.com/v22.0/{business_id}/creative_folders"
    payload = {
        "access_token": access_token,
        "name": name,
        "parent_folder_id": parent_folder_id,
        "folder_type": "VIDEO",
    }

    try:
        response = requests.post(url, data=payload)
        data = response.json()

        if "id" in data:
            return jsonify({
                'success': True,
                'id': data['id'],
                'message': f"子文件夹 '{name}' 创建成功"
            }), 200
        else:
            error = data.get('error', {}).get('message', '未知错误')
            return jsonify({'success': False, 'error': error}), 400
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/app/get_folders', methods=['GET'])
def get_folders():
    # 检查必要参数
    if 'business_id' not in request.args or 'access_token' not in request.args:
        return jsonify({'success': False, 'error': '必须提供业务ID(business_id)和访问令牌(access_token)'}), 400

    business_id = request.args.get('business_id')
    access_token = request.args.get('access_token')

    try:
        # 调用函数获取文件夹
        result = get_bm_folders_nested(business_id, access_token)
        return jsonify(result), 200
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


# 辅助函数
def get_bm_folders_nested(business_id, access_token):
    """获取BM下所有素材文件夹，仅包含两级结构"""

    def fetch_subfolders(folder_id, parent_path):
        url = f"https://graph.facebook.com/v22.0/{folder_id}/subfolders"
        params = {
            'access_token': access_token,
            'fields': 'id,name'
        }
        response = requests.get(url, params=params)
        data = response.json().get('data', [])

        subfolders = []
        for item in data:
            fid = item.get('id')
            name = item.get('name')
            full_path = f"{parent_path}/{name}"
            subfolders.append({
                'id': fid,
                'name': name,
                'full_path': full_path,
                'data': []  # 不再递归
            })
        return subfolders

    # 获取一级文件夹
    url = f"https://graph.facebook.com/v22.0/{business_id}/creative_folders"
    params = {
        'access_token': access_token,
        'fields': 'id,name'
    }
    response = requests.get(url, params=params)
    data = response.json().get('data', [])

    folders = []
    for item in data:
        fid = item.get('id')
        name = item.get('name')
        full_path = name
        folder = {
            'id': fid,
            'name': name,
            'full_path': full_path,
            'data': fetch_subfolders(fid, full_path)  # 只获取一级子目录
        }
        folders.append(folder)
    return folders


def upload_to_meta(video_path, business_id, access_token, folder_id, title, task_id=None):
    """将视频上传到Meta商业素材库，使用分片上传方式"""
    try:
        # 添加这一行，定义graph_video_url变量
        graph_video_url = f'https://graph-video.facebook.com/v22.0/{business_id}/videos'

        app_logger.info(f"开始上传视频到Meta: {video_path}")
        file_size = os.path.getsize(video_path)
        app_logger.info(f"视频大小: {file_size / 1024 / 1024:.2f}MB")

        # STEP 1: Start upload
        start_params = {
            'title': title,
            'access_token': access_token,
            'upload_phase': 'start',
            'file_size': str(file_size),
            'creative_folder_id': folder_id
        }
        start_response = requests.post(graph_video_url, data=start_params)
        print("Start upload:", start_response.status_code, start_response.text)
        upload_session = start_response.json()

        if 'error' in upload_session:
            return {'success': False, 'error': upload_session['error']['message'], 'file_path': video_path}

        start_offset = upload_session['start_offset']
        end_offset = upload_session['end_offset']
        session_id = upload_session['upload_session_id']

        # STEP 2: Transfer chunks
        while start_offset != end_offset:
            with open(video_path, 'rb') as f:
                f.seek(int(start_offset))
                chunk = f.read(int(end_offset) - int(start_offset))

            files = {
                'video_file_chunk': (
                    os.path.basename(video_path),  # 使用实际文件名而不是title
                    chunk,
                    'application/octet-stream'
                )
            }

            data = {
                'access_token': access_token,
                'upload_phase': 'transfer',
                'upload_session_id': session_id,
                'start_offset': start_offset,
                'creative_folder_id': folder_id  # ✅ 必须加上这行，否则 400 错误
            }

            chunk_response = requests.post(graph_video_url, data=data, files=files)
            print("Transfer response:", chunk_response.status_code, chunk_response.text)

            try:
                chunk_result = chunk_response.json()
            except ValueError:
                return {'success': False, 'error': 'transfer 阶段响应非 JSON', 'file_path': video_path}

            if 'error' in chunk_result:
                return {'success': False, 'error': chunk_result['error']['message'], 'file_path': video_path}

            start_offset = chunk_result['start_offset']
            end_offset = chunk_result['end_offset']

        # STEP 3: Finish upload
        finish_data = {
            'access_token': access_token,
            'upload_phase': 'finish',
            'upload_session_id': session_id,
            'title': title,
            'description': ' ',
            'published': 'false',
            'creative_folder_id': folder_id  # ✅ 必须加上
        }

        finish_response = requests.post(graph_video_url, data=finish_data)
        print("Finish response:", finish_response.status_code, finish_response.text)
        finish_result = finish_response.json()

        # Meta上传完成后立即更新任务状态
        if finish_result.get('success') is True or 'id' in finish_result:
            # 使用传入的task_id而不是全局变量
            if task_id is not None:
                with task_lock:  # 使用锁保护对共享字典的访问
                    task_results[task_id] = {
                        "status": "completed",
                        "result": {
                            'success': True,
                            'id': finish_result.get('id', ''),
                            'message': f"视频 '{title}' 上传成功",
                            'file_path': video_path
                        }
                    }
                    print(f"已更新任务 {task_id} 状态为已完成")

            # 创建成功标记文件
            success_dir = os.path.join(BASE_FOLDER, 'success_tasks')
            os.makedirs(success_dir, exist_ok=True)
            with open(os.path.join(success_dir, f"{task_id}.success"), 'w') as f:
                f.write('success')

            return {
                'success': True,
                'id': finish_result.get('id', ''),
                'message': f"视频 '{title}' 上传成功",
                'file_path': video_path
            }
        else:
            return {
                'success': False,
                'error': finish_result.get('error', {}).get('message', '完成阶段失败'),
                'file_path': video_path
            }

    except Exception as e:
        app_logger.error(f"上传视频时发生错误: {str(e)}", exc_info=True)
        return {'success': False, 'error': str(e), 'file_path': video_path}


@app.route('/app/delete_file', methods=['GET'])
def delete_file():
    file_path = request.args.get('file_path')
    if not file_path:
        return jsonify({'success': False, 'error': '缺少 file_path 参数'}), 400

    # 取文件夹名作为文件夹路径（而不是文件）
    folder_name = os.path.basename(file_path)
    full_path = os.path.join('./uploads', folder_name)

    try:
        # 检查路径是否存在
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'error': f'文件夹不存在: {full_path}'}), 404

        # 如果是文件夹，先确保所有文件都关闭
        if os.path.isdir(full_path):
            import shutil
            import time

            # 可以先尝试关闭可能正在使用的文件句柄
            # 在Windows上，可能需要先关闭文件句柄
            import gc
            gc.collect()  # 强制垃圾回收，释放文件句柄

            # 尝试几次删除操作，每次间隔一小段时间
            max_attempts = 3
            for attempt in range(max_attempts):
                try:
                    shutil.rmtree(full_path)
                    return jsonify({'success': True, 'message': f'文件夹 {folder_name} 及其内容删除成功'}), 200
                except Exception as e:
                    if attempt < max_attempts - 1:
                        print(f"删除尝试 {attempt + 1} 失败: {str(e)}，等待后重试...")
                        time.sleep(2)  # 等待2秒后重试
                    else:
                        # 最后一次尝试失败，尝试只删除文件保留目录结构
                        try:
                            for root, dirs, files in os.walk(full_path):
                                for file in files:
                                    try:
                                        file_to_remove = os.path.join(root, file)
                                        os.remove(file_to_remove)
                                        print(f"已删除文件: {file_to_remove}")
                                    except Exception as file_e:
                                        print(f"无法删除文件 {file}: {str(file_e)}")
                            return jsonify({'success': True, 'message': f'已删除文件夹 {folder_name} 中的文件'}), 200
                        except Exception as final_e:
                            raise final_e  # 如果连文件都无法删除，则抛出异常

            # 这一行不应该执行到，因为上面的循环会在成功时返回或抛出异常
            return jsonify({'success': False, 'error': '无法删除文件夹，超过最大尝试次数'}), 500

        # 如果是文件，则直接删除
        else:
            os.remove(full_path)
            return jsonify({'success': True, 'message': f'文件 {folder_name} 删除成功'}), 200
    except PermissionError as pe:
        error_message = f'权限不足，无法删除 {folder_name}: {str(pe)}'
        print(error_message)
        return jsonify({'success': False, 'error': error_message}), 403
    except Exception as e:
        error_message = f'删除时发生错误: {str(e)}'
        print(error_message)
        return jsonify({'success': False, 'error': error_message}), 500


def log_upload_success(business_id, folder_id, file_path, meta_id):
    """记录上传成功的信息到日志文件"""
    log_folder = os.path.join(BASE_FOLDER, "logs")
    os.makedirs(log_folder, exist_ok=True)

    log_file = os.path.join(log_folder, f"upload_log_{datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(log_file, "a", encoding="utf-8") as f:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] 上传成功: 文件={file_path}, BM={business_id}, 文件夹={folder_id}, Meta ID={meta_id}\n")


@app.route('/app/server_status', methods=['GET'])
def server_status():
    """检查服务器状态的接口"""
    return jsonify({
        'status': 'running',
        'version': '1.0',
        'upload_directory': os.path.abspath(BASE_FOLDER),
        'files_count': count_uploaded_files(),
        'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })


def count_uploaded_files():
    """统计已上传的文件数量"""
    count = 0
    for root, dirs, files in os.walk(BASE_FOLDER):
        for file in files:
            if file.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                count += 1
    return count


@app.route('/app/upload_from_url', methods=['POST'])
def upload_from_url():
    # 获取请求参数
    data = request.json
    url = data.get('url')
    filename = data.get('filename')
    business_id = data.get('business_id')
    access_token = data.get('access_token')
    folder_id = data.get('folder_id')

    # 验证必要参数
    if not all([url, filename, business_id, access_token, folder_id]):
        return jsonify({'success': False, 'error': '缺少必要参数'}), 400

    try:
        # 下载文件到临时位置
        temp_dir = os.path.join(BASE_FOLDER, 'temp')
        os.makedirs(temp_dir, exist_ok=True)
        local_path = os.path.join(temp_dir, filename)

        # 下载文件
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        with open(local_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # 调用现有的上传到FB函数
        result = upload_to_meta(local_path, business_id, access_token, folder_id, filename)

        # 清理临时文件
        try:
            os.remove(local_path)
        except:
            pass

        return jsonify(result)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def check_system_resources():
    """检查系统资源，决定是否接受新任务"""
    cpu_percent = psutil.cpu_percent(interval=0.1)
    memory_info = psutil.virtual_memory()
    memory_percent = memory_info.percent

    print(f"当前系统状态: CPU使用率={cpu_percent}%, 内存使用率={memory_percent}%")

    # 当CPU或内存使用率超过阈值时拒绝新请求
    if cpu_percent > 80 or memory_percent > 85:
        return False
    return True


def download_from_cos(client, bucket, cos_key, temp_file_path):
    """分块下载COS文件，避免内存占用过大"""
    file_info = client.head_object(Bucket=bucket, Key=cos_key)
    file_size = int(file_info['Content-Length'])

    # 大于10MB的文件使用分块下载
    if file_size > 10 * 1024 * 1024:
        print(f"大文件({file_size / 1024 / 1024:.2f}MB)使用分块下载")

        # 分块大小设为8MB
        part_size = 8 * 1024 * 1024

        with open(temp_file_path, 'wb') as f:
            # 计算分块数
            parts = (file_size + part_size - 1) // part_size

            for i in range(parts):
                start = i * part_size
                end = min(start + part_size - 1, file_size - 1)

                # 下载这一块
                response = client.get_object(
                    Bucket=bucket,
                    Key=cos_key,
                    Range=f'bytes={start}-{end}'
                )

                # 写入文件
                f.write(response['Body'].get_raw_stream().read())

                print(f"下载进度: {min((i + 1) / parts * 100, 100):.1f}%")
    else:
        # 小文件直接下载
        client.download_file(Bucket=bucket, Key=cos_key, DestFilePath=temp_file_path)

    return True


# 添加任务状态查询端点
@app.route('/app/task_status/<task_id>', methods=['GET'])
def task_status(task_id):
    # 先检查是否有成功标记文件
    success_file = os.path.join(BASE_FOLDER, 'success_tasks', f"{task_id}.success")
    if os.path.exists(success_file):
        return jsonify({
            'status': 'completed',
            'result': {
                'success': True,
                'message': '上传成功'
            }
        })

    # 检查任务是否存在于结果字典中
    if task_id not in task_results:
        return jsonify({
            'status': 'pending',
            'message': '任务正在处理中'
        })

    result = task_results[task_id]

    # 打印详细的任务状态用于调试
    print(f"任务{task_id}当前状态: {result}")

    # 如果任务处于处理中状态，但已经完成了Meta上传，返回成功
    if result.get('status') == 'processing' and result.get('progress') == 'meta_uploaded':
        print(f"任务 {task_id} Meta上传已完成，即使还在处理清理步骤，返回成功")
        return jsonify({
            'status': 'completed',
            'result': {
                'success': True,
                'message': '上传成功，正在清理临时文件'
            }
        })

    # 其他条件保持不变
    if result.get('status') == 'completed':
        # 如果结果是字典并且包含success字段
        if isinstance(result.get('result'), dict) and result.get('result').get('success') is True:
            print(f"任务 {task_id} 成功完成，返回结果")
            return jsonify({
                'status': 'completed',
                'result': {
                    'success': True,
                    'id': result.get('result', {}).get('id', ''),
                    'message': result.get('result', {}).get('message', '上传成功')
                }
            })
        # 扁平化处理：如果结果字典中有成功标志，直接返回成功
        elif isinstance(result.get('result'), dict) and 'success' in str(
                result.get('result')).lower() and 'true' in str(result.get('result')).lower():
            print(f"任务 {task_id} 检测到success=true标志，返回成功")
            return jsonify({
                'status': 'completed',
                'success': True,
                'message': '上传成功'
            })

    # 其他情况原样返回结果
    return jsonify(result)


def cleanup_temp_files():
    """清理超过24小时的临时文件"""
    temp_dir = os.path.join(BASE_FOLDER, 'temp')
    if not os.path.exists(temp_dir):
        return

    now = datetime.now()
    cutoff = now - timedelta(hours=24)

    app_logger.info("开始清理临时文件")
    deleted_count = 0
    error_count = 0

    for root, dirs, files in os.walk(temp_dir):
        for file in files:
            file_path = os.path.join(root, file)
            file_modified = datetime.fromtimestamp(os.path.getmtime(file_path))

            if file_modified < cutoff:
                try:
                    os.remove(file_path)
                    deleted_count += 1
                except Exception as e:
                    error_count += 1
                    app_logger.error(f"清理文件失败: {file_path}, 错误: {str(e)}")

    app_logger.info(f"清理完成: 删除了{deleted_count}个文件, {error_count}个错误")


# 添加定时任务调度
def schedule_cleanup():
    """每小时运行一次清理任务"""
    while True:
        try:
            cleanup_temp_files()
        except Exception as e:
            app_logger.error(f"清理临时文件时出错: {str(e)}")
        time.sleep(3600)  # 每小时执行一次


# 在app启动时启动清理线程
cleanup_thread = threading.Thread(target=schedule_cleanup, daemon=True)
cleanup_thread.start()

if __name__ == '__main__':
    # 仅在直接运行时使用开发服务器
    app.run(debug=True)
