import requests
import os

GRAPH_API_VERSION = 'v22.0'



def create_folder(name,BUSINESS_ID,ACCESS_TOKEN):
    """
    创建 BM 素材库中的文件夹，用于分类管理上传的创意视频。

    参数：
        name (str): 文件夹名称（可自定义）

    返回：
        folder_id (str): 创建成功后返回的文件夹 ID
    """

    url = f"https://graph.facebook.com/v22.0/{BUSINESS_ID}/creative_folders"
    payload = {
        'access_token': ACCESS_TOKEN,
        'name': name,
        'folder_type': 'VIDEO',
    }
    r = requests.post(url, data=payload)
    print(r.json())
    return r.json().get('id')


def create_subfolder_api(name, parent_folder_id, BUSINESS_ID, ACCESS_TOKEN,parent_name):
    """
        在指定的一级文件夹下创建子文件夹。

        参数：
            name (str): 子文件夹名称
            parent_folder_id (str): 一级文件夹的 ID
            access_token (str): 有权访问该 BM 的令牌

        返回：
            subfolder_id (str): 创建成功后返回的子文件夹 ID
        """
    url = f"https://graph.facebook.com/v22.0/{BUSINESS_ID}/creative_folders"
    payload = {
        "access_token": ACCESS_TOKEN,
        "name": name,
        "parent_folder_id": parent_folder_id,
        # "description": description,
        # “folder_type” 可保留一级创建时相同类型
        "folder_type": "VIDEO",
    }

    resp = requests.post(url, data=payload)
    data = resp.json()
    if "id" in data:
        print(f"✅ 子文件夹 '{name}' 创建成功，ID = {data['id']}")
        return data["id"]
    else:
        err = data.get("error", {})
        msg = err.get("message", resp.text)
        print(f"❌ 子文件夹创建失败：{msg}")
        return None

def get_bm_folders_nested(business_id, access_token):
    """
    获取 BM 下所有素材文件夹，仅包含两级结构。
    """
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
    print(folders)
    return folders


# def upload_video_to_bm_library(VIDEO_PATH,BUSINESS_ID,ACCESS_TOKEN,folder_id,title):
#     """
#     将本地视频上传到 Meta 商业素材库中的指定文件夹。
#
#     参数：
#         folder_id (str): 素材文件夹 ID，视频将归入此文件夹
#     """
#     print(folder_id)
#     url = f"https://graph.facebook.com/v22.0/{BUSINESS_ID}/videos"
#
#     with open(VIDEO_PATH, 'rb') as video_file:
#         files = {
#             'source': video_file,
#         }
#         data = {
#             'access_token': ACCESS_TOKEN,
#             'title': title[:-4],
#             'description': ' ',
#             'published': 'false',  # 不发布，只作为素材存储
#             'creative_folder_id':folder_id,  # 你的文件夹ID
#         }
#
#         response = requests.post(url, files=files, data=data)
#         try:
#             res = response.json()
#         except Exception as e:
#             print("⚠️ 返回不是合法 JSON：", response.text)
#             return
#
#         if 'id' in res:
#             print("✅ 上传成功，素材 ID：", res['id'])
#         else:
#             print("❌ 上传失败：", res)


def upload_video_to_bm_library(video_path, business_id, access_token, folder_id, title):
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





