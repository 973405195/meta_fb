import logging

from flask import Flask, request, jsonify
import os
import requests
import uuid
import datetime

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024
BASE_FOLDER = 'uploads'
os.makedirs(BASE_FOLDER, exist_ok=True)

@app.route('/app/upload_video', methods=['POST'])
def upload_video():
    if 'video' not in request.files:
        return jsonify({'success': False, 'error': '没有找到名为 video 的文件字段'}), 400
    if 'folder_id' not in request.form:
        return jsonify({'success': False, 'error': '没有提供文件夹ID（folder_id）'}), 400
    if 'business_id' not in request.form:
        return jsonify({'success': False, 'error': '没有提供BM ID（business_id）'}), 400
    if 'access_token' not in request.form:
        return jsonify({'success': False, 'error': '没有提供访问令牌（access_token）'}), 400
    
    # 获取相对路径，如果没提供则使用文件名
    relative_path = request.form.get('relative_path', '')

    file = request.files['video']
    folder_id = request.form['folder_id']
    business_id = request.form['business_id']
    access_token = request.form['access_token']

    if file.filename == '':
        return jsonify({'success': False, 'error': '文件名为空'}), 400
    if not file.filename.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
        return jsonify({'success': False, 'error': '只支持视频文件'}), 400

    # 使用相对路径构建保存路径
    if relative_path:
        # 处理路径分隔符，确保一致性
        relative_path = relative_path.replace('\\', '/').strip('/')
        # 提取相对路径
        path_parts = relative_path.split('/')
        
        # 如果是完整路径如 D:/新版测试/4468/1.mp4，只保留最后两部分：4468/1.mp4
        if ':' in path_parts[0]:  # 检测是否是带驱动器名的完整路径
            # 如果是完整路径，只取后两部分
            relative_path = '/'.join(path_parts[-2:]) if len(path_parts) >= 2 else path_parts[-1]
        
        # 创建目标目录
        target_dir = os.path.join(BASE_FOLDER, os.path.dirname(relative_path))
        os.makedirs(target_dir, exist_ok=True)
        
        # 构建保存文件路径
        file_path = os.path.join(BASE_FOLDER, relative_path)
    else:
        # 如果没有提供相对路径，直接使用文件名保存在根目录
        file_path = os.path.join(BASE_FOLDER, file.filename)
    
    # 保存文件到服务器
    try:
        # 确保目标目录存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        file.save(file_path)
        print(f"文件已保存到: {file_path}")
    except Exception as e:
        return jsonify({'success': False, 'error': f'保存文件失败: {str(e)}'}), 500
    
    # 调用Meta API上传视频到BM素材库
    try:
        result = upload_to_meta(file_path, business_id, access_token, folder_id, os.path.basename(file_path))
        
        # 上传成功后记录信息到日志
        if result.get('success'):
            log_upload_success(business_id, folder_id, file_path, result.get('id'))
        
        return jsonify(result), 200 if result.get('success') else 400
    except Exception as e:
        error_msg = str(e)
        print(f"上传失败: {error_msg}")
        print(f"--------------------------------------------------------------------")
        return jsonify({'success': False, 'error': error_msg}), 400

@app.route('/app/create_folder', methods=['POST'])
def create_folder():
    # 检查必要参数
    if not all(key in request.json for key in ['name', 'business_id', 'access_token']):
        return jsonify({'success': False, 'error': '必须提供文件夹名称(name)、业务ID(business_id)和访问令牌(access_token)'}), 400
    
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

def upload_to_meta(video_path, business_id, access_token, folder_id, title):
    """将视频上传到Meta商业素材库，使用分片上传方式"""
    graph_video_url = f'https://graph-video.facebook.com/v22.0/{business_id}/videos'

    try:
        # STEP 1: Start upload
        file_size = os.path.getsize(video_path)
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

        if finish_result.get('success') is True or 'id' in finish_result:
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
        print(f"上传过程中发生异常: {str(e)}")
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
                        print(f"删除尝试 {attempt+1} 失败: {str(e)}，等待后重试...")
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
    
    log_file = os.path.join(log_folder, f"upload_log_{datetime.datetime.now().strftime('%Y-%m-%d')}.txt")
    with open(log_file, "a", encoding="utf-8") as f:
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        f.write(f"[{timestamp}] 上传成功: 文件={file_path}, BM={business_id}, 文件夹={folder_id}, Meta ID={meta_id}\n")

@app.route('/app/server_status', methods=['GET'])
def server_status():
    """检查服务器状态的接口"""
    return jsonify({
        'status': 'running',
        'version': '1.0',
        'upload_directory': os.path.abspath(BASE_FOLDER),
        'files_count': count_uploaded_files(),
        'timestamp': datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })

def count_uploaded_files():
    """统计已上传的文件数量"""
    count = 0
    for root, dirs, files in os.walk(BASE_FOLDER):
        for file in files:
            if file.lower().endswith(('.mp4', '.mov', '.avi', '.mkv')):
                count += 1
    return count

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)
