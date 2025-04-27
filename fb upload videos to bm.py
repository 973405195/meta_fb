import requests
import os

# Facebook Graph API 访问令牌
ACCESS_TOKEN = "EAALvgBr8xJQBO4sMRQu6nFxmZBPLuZBMmcjhF5vVHQqk8MQkfz6q2PZCfAQR7n0ZAryQYwbxv9RTyMKjl74K872WtQPedT0LoknMZBExwFSWZC18owPwNNneh5PWd69tYZApnmJ23vwdZCNmWRVhVFpXtwtk19c7AMQPErfL3IXsgwtyiYhryxvcsq2HWPK2VtFzEQZDZD"
BUSINESS_ID = '1076674681127972'

folder_id = "1225233022938803"

# 视频上传接口，使用 graph-video 子域，v22.0 版本
GRAPH_VIDEO_URL = f'https://graph-video.facebook.com/v22.0/{BUSINESS_ID}/videos'


# 分片上传（transfer 阶段）
def upload_chunk(file_path, upload_session_id, start_offset, end_offset):
    print("upload_chunk:", file_path, upload_session_id, start_offset, end_offset)

    # 打开文件并读取对应片段
    with open(file_path, 'rb') as f:
        f.seek(int(start_offset))  # 移动到起始偏移位置
        chunk = f.read(int(end_offset) - int(start_offset))  # 读取一个分片

    # 构建 multipart/form-data 请求，上传视频片段
    files = {
        'video_file_chunk': (
            'sample-video',  # 文件名
            chunk,  # 分片数据
            'application/octet-stream'  # 二进制数据类型
        )
    }

    data = {
        'title': 'sample-video',  # 视频标题（可选）
        'creative_folder_id': folder_id,  # 创意素材文件夹 ID
        'access_token': ACCESS_TOKEN,  # 访问令牌
        'upload_phase': 'transfer',  # 当前上传阶段为传输（分片）
        'upload_session_id': upload_session_id,  # 当前会话 ID
        'start_offset': start_offset  # 当前分片的起始偏移
    }

    # 发送 POST 请求进行分片上传
    res = requests.post(GRAPH_VIDEO_URL, data=data, files=files)
    return res.json()  # 返回 JSON 响应


# 启动上传会话（start 阶段）
def start_upload(file_path):
    params = {
        'title': 'sample-video',  # 视频标题
        'access_token': ACCESS_TOKEN,  # 访问令牌
        'upload_phase': 'start',  # 上传阶段为 start
        'file_size': str(os.path.getsize(file_path)),  # 获取文件总大小
        'creative_folder_id': folder_id  # 创意文件夹 ID
    }

    # 发送 start 请求以初始化上传会话
    res = requests.post(GRAPH_VIDEO_URL, data=params)
    return res.json()  # 返回初始化后的会话信息


# 完成上传（finish 阶段）
def finish_upload(session_id):
    print('finish_upload:', session_id)

    params = {
        'access_token': ACCESS_TOKEN,  # 访问令牌
        'upload_phase': 'finish',  # 当前阶段为 finish
        'upload_session_id': session_id,  # 会话 ID
        'title': 'sample-video',  # 视频标题
        'creative_folder_id': folder_id  # 可选的素材文件夹 ID
    }

    # 发送 finish 请求提交上传完成
    res = requests.post(GRAPH_VIDEO_URL, data=params)
    print(res.json())  # 输出最终响应结果


# 本地视频文件路径
video_file_path = 'D:/新版测试/4468/1.mp4'

# 打印视频总大小（单位：字节）
print(str(os.path.getsize(video_file_path)))

# 启动上传，获取初始的 offset 和 session ID
upload_session = start_upload(video_file_path)
print(upload_session)

# 初始偏移位置
start_offset = upload_session['start_offset']
end_offset = upload_session['end_offset']
session_id = upload_session['upload_session_id']

response = {}

# 持续上传分片，直到上传完毕（start_offset == end_offset）
while start_offset != end_offset:
    response = upload_chunk(video_file_path, session_id, start_offset, end_offset)
    print("upload trans response", response)

    # 更新偏移量，进行下一片段上传
    start_offset = response['start_offset']
    end_offset = response['end_offset']

# 所有分片上传完毕后，调用 finish 完成整个视频上传流程
finish_upload(session_id)
