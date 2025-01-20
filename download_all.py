import datetime
import json
import os
import sqlite3
import subprocess
import datetime
import cv2

import hashlib
import cv2
def calculate_md5(file_path):
    """计算文件的 MD5 值"""
    hash_md5 = hashlib.md5()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(4096), b""):
            hash_md5.update(chunk)
    return hash_md5.hexdigest()

def calculate_frame_md5(frame):
    """计算帧的 MD5 值"""
    _, buffer = cv2.imencode('.jpg', frame)
    return hashlib.md5(buffer).hexdigest()

log_path = "log.txt"
def write_log(detail, level="INFO"):
    with open(log_path, 'a', encoding="utf-8") as f:
        log_level = level.upper()
        f.write(f"[{log_level}]{datetime.datetime.now()} {detail}\n")

try:
    import requests
except ImportError as e:
    if "urllib3 v2.0 only supports OpenSSL 1.1.1+" in str(e):
        print("忽略 OpenSSL 版本不兼容的错误")
    else:
        raise e

database = "database.db"


def check_status_file_exist():
    if not os.path.exists('./.status.json'):
        status_data = {
            "start_time": datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S'),
            "download_count": 0,
            "failed_count": 0
        }
        with open('./.status.json', 'w') as f:
            json.dump(status_data, f)
        return False
    else:
        return True


def read_status_file():
    with open('./.status.json', 'r') as f:
        status_data = json.load(f)
        return status_data['start_time'], status_data['download_count'], status_data['failed_count']


def change_status(status):
    with open('./.status.json', 'r+') as f:
        status_data = json.load(f)
        if status == 1:
            status_data["download_count"] += 1
        elif status == 2:
            status_data["failed_count"] += 1
        elif status == 0:
            clean_status_file()
            return
        f.seek(0)  # 将指针移动到文件开头以便写入新数据
        json.dump(status_data, f)
        f.truncate()  # 删除原文件内容中json.dump后剩余的部分


def clean_status_file():
    os.remove('./.status.json')

def insert_video(title):
    video_file_path = f"files/{title}.mp4"
    if not os.path.exists(video_file_path):
        write_log(f"{title}视频文件不存在，请检查", level="error")
        return False

    cap = cv2.VideoCapture(video_file_path)
    if not cap.isOpened():
        write_log(f"无法打开视频文件{video_file_path}", level="error")
        return False

    ret, frame = cap.read()
    if not ret:
        write_log(f"无法读取{video_file_path}的视频帧", level="ERROR")
        cap.release()
        return False

    frame_md5 = calculate_frame_md5(frame)
    thumbnail_file_path = f"thumbnails/{frame_md5}.jpg"
    # 保存帧为缩略图
    cv2.imwrite(thumbnail_file_path, frame)
    cap.release()

    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("INSERT INTO videos (title, cover) VALUES (?, ?)", (title, thumbnail_file_path))
    conn.commit()
    write_log(f"成功保存视频:{title}")
    conn.close()

def download(video_id, title, url):
    # 确保下载目录存在
    download_folder = 'files/'
    if not os.path.exists(download_folder):
        os.makedirs(download_folder)

    # 构建输出路径并确保标题安全
    # sanitized_title = "".join([c for c in title if c.isalnum() or c in (' ', '.', '_')]).rstrip()
    # output_path = os.path.join(download_folder, f'{sanitized_title}.mp4')
    output_path = os.path.join(download_folder, f'{title}.mp4')

    # 构建FFmpeg命令列表
    download_command = [
        'ffmpeg',
        '-user_agent', 'stagefright/1.2 (Linux;Android 10)',
        '-allowed_extensions', 'ALL',
        '-protocol_whitelist', 'file,http,https,tls,tcp,crypto',
        '-i', url,
        '-c', 'copy',
        output_path
    ]

    try:
        # 执行命令
        result = subprocess.run(download_command, check=True)
        print(f"视频ID：{video_id} 下载成功")
        # 检查文件是否已存在且非空
        if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
            # 更新数据库记录为已下载
            update_query = f"UPDATE downloads SET status = 1 WHERE id = {video_id}"
            connection = sqlite3.connect(database)
            c = connection.cursor()
            c.execute(update_query)
            connection.commit()
            file_path = os.path.join(download_folder, f"{title}.mp4")

            if insert_video(title) is None:
                print(f"视频ID：{video_id} 已成功下载.")
            return True  # 如果文件存在且不为空，则认为下载成功
        else:
            print(f"视频ID：{video_id} 下载过程中出现问题，输出文件不存在或为空.")
            # 更新数据库记录为下载失败
            update_query = f"UPDATE downloads SET status = 2 WHERE id = {video_id}"
            connection = sqlite3.connect(database)
            c = connection.cursor()
            c.execute(update_query)
            connection.commit()
            return False
    except Exception as e:
        print(f"视频ID：{video_id} 下载失败: {e}")
        # 更新数据库记录为下载失败
        update_query = f"UPDATE downloads SET status = 1 WHERE id = {video_id}"
        connection = sqlite3.connect(database)
        c = connection.cursor()
        c.execute(update_query)
        connection.commit()
        return False  # 下载失败


def download_all():
    connection = sqlite3.connect(database)
    c = connection.cursor()
    check_status_file_exist()
    c.execute("SELECT * FROM downloads where status != 1")
    videos = c.fetchall()
    with open('download.log', 'a', encoding='utf-8') as log_file:
        for video in videos:
            video_id, video_name, video_url, status = video
            download(video_id, video_name, video_url)
            if download:
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')
                log_message = f'√ {timestamp} 视频ID：{video_id} ({video_name}) 已成功下载.'
                log_file.write(log_message + '\n')
                change_status(1)
            else:
                print(f"视频ID：{video_id} 下载失败，已跳过.")
                timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H-%M-%S')
                log_message = f'X {timestamp} 视频ID：{video_id} ({video_name}) 下载失败.'
                log_file.write(log_message + '\n')
                change_status(2)


if __name__ == '__main__':
    download_all()
