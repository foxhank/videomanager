import string
from urllib.parse import urlparse, parse_qs, urlunparse
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS
import datetime
from functions.calculate_md5 import *
from functions.download import *
from functions.update_info import *
import sqlite3
import re
import jieba
from wordcloud import WordCloud
import matplotlib.pyplot as plt
import base64
from io import BytesIO
import shutil

app = Flask(__name__)
CORS(app)

database = "database.db"
temp_file_path = "temp.json"
thumbnail_path = "thumbnail"
video_path = "files"
log_path = "log.txt"


# print(os.getcwd())


def get_directory_size(path):
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # Skip if it is symbolic link
            if not os.path.islink(fp):
                total += os.path.getsize(fp)
    return total


def write_log(detail, level="INFO"):
    with open(log_path, 'a', encoding="utf-8") as f:
        log_level = level.upper()
        f.write(f"[{log_level}]{datetime.datetime.now()} {detail}\n")


def init(db_name):
    try:
        current_working_directory = os.getcwd()
        print(f"当前工作路径: {current_working_directory}")

        if not os.path.exists(db_name):
            conn = sqlite3.connect(db_name)
            c = conn.cursor()
            c.execute("""CREATE TABLE IF NOT EXISTS videos (
                        id INTEGER PRIMARY KEY,
                        title TEXT,
                        cover TEXT,
                        watch INTEGER default 0
                        )     
            """)
            c.execute("""CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY,
            title TEXT NOT NULL,
            url TEXT NOT NULL,
            status INTEGER default 0
            )
            """)
            c.execute("""CREATE TABLE IF NOT EXISTS system_settings (
            id INTEGER PRIMARY KEY,
            key TEXT NOT NULL,
            value TEXT NOT NULL
            )
            """)
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ('storage_space_used', '0'))
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ('video_count', '0'))
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)",
                      ("database_created_date", datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ("disk_write_count", '0'))
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ("disk_read_count", '0'))
            c.execute("INSERT INTO system_settings (key, value) VALUES (?, ?)", ("Network_out_count", '0'))

            conn.commit()
            conn.close()

            # 初始化文件夹
            os.makedirs(thumbnail_path, exist_ok=True)
            os.makedirs(video_path, exist_ok=True)
            print(f"文件夹 {thumbnail_path} 和 {video_path} 创建成功")
            write_log("初始化完成")
        else:
            print("数据库已存在，跳过初始化")
            pass
    except Exception as e:
        print(f"初始化过程中发生错误: {e}")
        write_log(f"初始化过程中发生错误: {e}", level="error")


def update():
    # 获取当前的磁盘和网络统计信息
    disk_write_current = get_disk_write_from_proc() or 0
    disk_read_current = get_disk_read_from_proc() or 0
    network_out_current = get_network_out_from_proc() or 0

    # 加载之前的统计信息
    state = load_state(temp_file_path)

    # 计算增量，并确保增量为非负值
    def safe_increment(current, last):
        increment = current - (state.get(last, 0) or 0)
        return max(increment, 0)  # 如果增量为负，则返回0

    disk_write_used = safe_increment(disk_write_current, 'disk_write_last')
    disk_read_used = safe_increment(disk_read_current, 'disk_read_last')
    network_out_used = safe_increment(network_out_current, 'network_out_last')

    # 更新状态字典并保存到临时文件
    state.update({
        'disk_write_last': disk_write_current,
        'disk_read_last': disk_read_current,
        'network_out_last': network_out_current,
        'last_update_time': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
    save_state(state, temp_file_path)

    # 更新数据库部分（假设你已经有了数据库连接）
    with sqlite3.connect(database) as conn:
        c = conn.cursor()

        # 定义一个辅助函数来安全地更新或插入新的记录
        def update_or_insert(key, value):
            try:
                float_value = float(value)
                if float_value > 0:  # 只有正值才进行累加
                    c.execute("SELECT value FROM system_settings WHERE key=?", (key,))
                    row = c.fetchone()
                    if row is not None:
                        existing_value = float(row[0])
                        new_value = existing_value + float_value
                    else:
                        new_value = float_value
                    c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)",
                              (key, str(new_value)))
            except ValueError:
                # 如果转换失败，直接插入新值
                c.execute("INSERT OR REPLACE INTO system_settings (key, value) VALUES (?, ?)", (key, value))

        # 计算文件数量
        video_count = len([f for f in os.listdir("files") if os.path.isfile(os.path.join("files", f))])


        storage_space_used_bytes = get_directory_size("files")
        # 更新或插入新的记录
        update_or_insert('storage_space_used', str(storage_space_used_bytes / 1024 / 1024))
        update_or_insert('disk_write_count', str(disk_write_used))
        update_or_insert('video_count', str(video_count))
        update_or_insert('disk_read_count', str(disk_read_used))
        update_or_insert('Network_out_count', str(network_out_used))

        conn.commit()


def insert_video(title):
    video_file_path = f"{video_path}/{title}.mp4"
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
    thumbnail_file_path = f"{thumbnail_path}/{frame_md5}.jpg"
    # 保存帧为缩略图
    cv2.imwrite(thumbnail_file_path, frame)
    cap.release()

    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("INSERT INTO videos (title, cover) VALUES (?, ?)", (title, thumbnail_file_path))
    conn.commit()
    write_log(f"成功保存视频:{title}")
    conn.close()


def delete_from_db(title):
    conn = sqlite3.connect(database)
    cursor = conn.cursor()

    # 执行删除操作
    cursor.execute("DELETE FROM videos WHERE title = ?", (title,))

    # 提交更改并关闭连接
    conn.commit()
    conn.close()


def get_system_setting():
    conn = sqlite3.connect(database)
    c = conn.cursor()

    # 定义要获取的键列表
    keys = [
        'storage_space_used',
        'video_count',
        'database_created_date',
        'disk_write_count',
        'disk_read_count',
        'Network_out_count'
    ]

    # 初始化一个字典来保存结果
    settings = {}

    try:
        # 使用IN子句一次性查询所有需要的键
        placeholders = ', '.join(['?'] * len(keys))
        query = f"SELECT key, value FROM system_settings WHERE key IN ({placeholders})"
        c.execute(query, keys)

        # 获取所有结果并填充到字典中
        rows = c.fetchall()
        for row in rows:
            settings[row[0]] = row[1]

        # 如果某些键不存在，则为它们设置默认值
        for key in keys:
            if key not in settings:
                settings[key] = '0'  # 或者其他合适的默认值

    except sqlite3.Error as e:
        print(f"An error occurred: {e}")
    finally:
        conn.close()

    return settings


@app.route('/', methods=['GET'])
def index():  # put application's code here
    return render_template("index.html")


@app.route('/dashboard', methods=['GET'])
def dash():
    return render_template("dashboard.html")


@app.route('/webfonts/<filename>', methods=['GET'])
def webfonts(filename):
    file_path = os.path.join('webfonts', filename)
    if os.path.exists(file_path):
        return send_file(file_path)
    else:
        return jsonify({"success": False, "message": "This file doesn't exist!'"}, 404)


@app.route('/files/<file_name>', methods=['GET'])
def get_video(file_name):
    video_path = os.path.join('files', file_name)
    # 检查文件是否存在
    if not os.path.exists(video_path):
        return jsonify({"success": False, "message": "This video doesn't exist!'"}, 404)

    # 设置适当的MIME类型，这里假设是MP4格式
    mime_type = 'video/mp4'

    # 使用send_file进行流式传输
    return send_file(video_path, mimetype=mime_type, as_attachment=False)


@app.route('/thumbnail/<file_name>', methods=['GET'])
def get_thumbnail(file_name):
    video_path = os.path.join('thumbnail', file_name)
    # 检查文件是否存在
    if not os.path.exists(video_path):
        return jsonify({"success": False, "message": "This thumbnail doesn't exist!'"}, 404)

    # 设置适当的MIME类型，这里假设是MP4格式
    mime_type = 'image/jpeg'

    # 使用send_file进行流式传输
    return send_file(video_path, mimetype=mime_type, as_attachment=False)


@app.route('/api/get_random_video', methods=['GET'])
def get_randon_video():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    # 提取一个视频出来
    c.execute("SELECT * FROM videos ORDER BY RANDOM() LIMIT 1")
    video = c.fetchone()
    c.execute("UPDATE videos SET watch = watch + 1 WHERE id = ?", (video[0],))
    conn.close()
    title = video[1]
    cover = video[2]
    watch = video[3]
    url = f"/{video_path}/{title}.mp4"
    return jsonify({"status": 200, "title": title, "cover": cover, "watch": watch, "url": url})


@app.route('/api/upload_videos', methods=['POST'])
def upload_videos():
    if 'files[]' not in request.files:
        return "No file part", 400

    files = request.files.getlist('files[]')
    for file in files:
        if file.filename == '':
            file.filename = f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}.mp4"

        if file:
            title = os.path.splitext(file.filename)[0]
            file_path = os.path.join(video_path, f"{title}.mp4")
            file.save(file_path)
            insert_video(title)

    return jsonify({"status": 200, "message": "Files successfully uploaded"})


@app.route('/api/get_video_list', methods=['GET'])
def get_video_list():
    page = int(request.args.get('page', 1))
    page_size = int(request.args.get('page_size', 20))

    conn = sqlite3.connect(database)
    c = conn.cursor()

    # 获取总记录数
    c.execute("SELECT COUNT(*) FROM videos")
    total = c.fetchone()[0]

    # 查询分页数据
    offset = (page - 1) * page_size
    c.execute("SELECT * FROM videos ORDER BY id DESC LIMIT ? OFFSET ?", (page_size, offset))
    videos = c.fetchall()
    conn.close()

    formatted_videos = [{
        "id": video[0],
        "title": video[1],
        "cover": video[2],
        "watch": video[3],
        "url": f"files/{video[1]}.mp4"
    } for video in videos]

    return jsonify({"message": "success", "videos": formatted_videos, "total": total})


@app.route('/api/get_random_video_list', methods=['GET'])
def get_random_video_list():
    page_size = int(request.args.get('page_size', 20))

    conn = sqlite3.connect(database)
    c = conn.cursor()

    try:
        # 获取总记录数
        c.execute("SELECT COUNT(*) FROM videos")
        total = c.fetchone()[0]

        if total == 0:
            return jsonify({"message": "no videos available", "videos": [], "total": 0})

        # 随机选择 page_size 个视频
        query = "SELECT * FROM videos ORDER BY RANDOM() LIMIT ?"
        c.execute(query, (page_size,))
        videos = c.fetchall()

        formatted_videos = [{
            "id": video[0],
            "title": video[1],
            "cover": video[2],
            "watch": video[3],
            "url": f"files/{sanitize_filename(video[1])}.mp4"  # 确保文件名安全
        } for video in videos]

        return jsonify({"message": "success", "videos": formatted_videos, "total": total})

    except Exception as e:
        print(f"Error fetching random videos: {e}")
        return jsonify({"message": "error", "videos": [], "total": 0}), 500

    finally:
        conn.close()


def sanitize_filename(filename):
    """清理文件名中的特殊字符以确保安全"""
    valid_chars = "-_.() %s%s" % (string.ascii_letters, string.digits)
    sanitized = ''.join(c if c in valid_chars else '_' for c in filename)
    return sanitized.strip().rstrip('.')


@app.route('/api/get_video/<int:id>', methods=['GET'])
def get_video_by_id(id):
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT * FROM videos WHERE id = ?", (id,))
    video = c.fetchone()
    if video:
        title = video[1]
        cover = video[2]
        watch = video[3]
        url = f"/{video_path}/{title}.mp4"
        return jsonify({"status": 200, "title": title, "cover": cover, "watch": watch, "url": url})
    else:
        return jsonify({"status": 404, "message": "Video not found"}), 404


@app.route('/api/manage/delete', methods=["POST"])
def delete_video():
    data = request.get_json()

    # 提取URL中的title部分
    url = data.get('url')
    if not url:
        return jsonify({"error": "URL not provided"}), 400

    # 假设URL格式为 "/files/title.mp4"
    if not url.startswith("/files/") or not url.endswith(".mp4"):
        return jsonify({"error": "Invalid URL format"}), 400

    # 提取title部分
    title = os.path.basename(url).replace(".mp4", "")
    print(f"title是：{title}")
    conn = sqlite3.connect(database)
    thumbnail_path = conn.execute("SELECT cover FROM videos WHERE title = ?", (title,)).fetchone()
    # 确保路径分隔符正确
    thumbnail = thumbnail_path[0]

    # 执行数据库删除操作
    delete_from_db(title)
    os.remove(f"files/{title}.mp4")
    os.remove(f"{thumbnail}")
    write_log("成功删除:{}".format(title))

    return jsonify({"code": 200, "message": "Video deleted successfully"}), 200


@app.route('/api/download_task', methods=["POST"])
def download_task():
    data = request.get_json()
    videos = data.get('videos')
    conn = sqlite3.connect(database)
    c = conn.cursor()
    failed_count = 0

    for video in videos:
        url = video.get('url')
        title = video.get('title')

        if url and title:
            # 解析URL并获取路径部分
            parsed_url = urlparse(url)
            url_path = parsed_url.path

            # 构建用于匹配的模式，包含域名和路径
            match_pattern = f"%{parsed_url.netloc}{url_path}%"

            # 使用构建的模式进行匹配
            c.execute("SELECT * FROM downloads WHERE url LIKE ?", (match_pattern,))

            if c.fetchone():
                failed_count += 1
                write_log(f"视频URL {url} 已存在，跳过")
                continue

            # 检查标题是否存在并在必要时修改
            original_title = title
            counter = 1
            while True:
                c.execute("SELECT * FROM downloads WHERE title = ?", (title,))
                if c.fetchone():
                    title = f"{original_title}({counter})"
                    counter += 1
                else:
                    break

            c.execute("INSERT INTO downloads (url, title) VALUES (?, ?)", (url, title))
            conn.commit()
            write_log("已成功记录视频：{}".format(title))
            print("已成功记录视频：{}".format(title))
        else:
            failed_count += 1
            write_log(f"视频{title}信息有错误")
            print(f"视频{title}信息有错误")

    conn.close()

    if failed_count > 0:
        return jsonify({"code": 201, "message": f"有{failed_count}条插入失败,已存在视频"}), 201
    else:
        return jsonify({"code": 200, "message": "所有视频已成功记录"}), 200


@app.route('/api/download_status', methods=['GET'])
def download_status():
    page = int(request.args.get('page', 1))
    count = int(request.args.get('count', 20))
    offset = (page - 1) * count

    conn = sqlite3.connect(database)
    c = conn.cursor()

    # Get total count
    c.execute("SELECT COUNT(*) FROM downloads")
    total = c.fetchone()[0]

    # Get paginated results
    query = "SELECT id, title, url, status FROM downloads ORDER BY id DESC LIMIT ? OFFSET ?"
    c.execute(query, (count, offset))
    results = c.fetchall()
    conn.close()

    downloads = []
    for row in results:
        downloads.append({
            'id': row[0],
            'title': row[1],
            'url': row[2],
            'status': row[3]
        })

    return jsonify({
        'downloads': downloads,
        'total': total
    })


@app.route("/api/download_all", methods=['POST'])
def download_all():
    conn = sqlite3.connect(database)
    c = conn.cursor()
    c.execute("SELECT * FROM downloads WHERE status != 1")
    videos = c.fetchall()
    conn.close()
    for video in videos:
        download(video[0], video[1], video[2])
    return jsonify({"code": 200, "message": "success"})


def create_xpcloud():
    conn = sqlite3.connect(database)
    c = conn.cursor()

    # 提取所有标题
    c.execute("SELECT title FROM videos")
    titles = c.fetchall()

    # 将所有标题合并为一个字符串
    all_titles = ' '.join([title[0] for title in titles])

    # 去除标点符号和多余的空格
    all_titles = re.sub(r'[^\w\s]', '', all_titles)
    all_titles = re.sub(r'\s+', ' ', all_titles).strip()

    # 去除语气助词（假设语气助词列表为 ['啊', '吧', '嘛', '呢', '哦', '呀', '吗']）
    tones = ['啊', '吧', '嘛', '呢', '哦', '呀', '吗']
    for tone in tones:
        all_titles = all_titles.replace(tone, '')

    # 分词
    words = jieba.lcut(all_titles)

    # 绘制词云
    wordcloud = WordCloud(font_path='msyh.ttc', width=800, height=400, background_color='white').generate(
        ' '.join(words))


    # 获取当前日期
    current_date = datetime.datetime.now().strftime('%Y-%m-%d')
    wordcloud_filename = f'./static/wordcloud_{current_date}.jpg'

    # 删除所有 ./static/wordcloud_yyyy-mm-dd.jpg 的图片
    static_dir = './static'
    for filename in os.listdir(static_dir):
        if filename.startswith('wordcloud_') and filename.endswith('.jpg'):
            file_path = os.path.join(static_dir, filename)
            os.remove(file_path)

    # 保存词云图像到指定路径
    wordcloud.to_file(wordcloud_filename)

    conn.close()

    return wordcloud_filename


@app.route('/api/statistics', methods=['GET'])
def statistics():
    update()  # 更新统计数据

    # 创建词云并获取Base64编码的字符串
    wordcloud_file = create_xpcloud()

    # 获取系统设置
    system_settings = get_system_setting()

    # 获取磁盘总空间和已用空间（单位为字节）
    storage_info = shutil.disk_usage('/')
    storage_used_str = system_settings.get('storage_space_used', '0')

    try:
        # 确保 storage_used 是浮点数，并且将其从 MB 转换为字节
        storage_used_mb = float(storage_used_str)
        storage_used_bytes = storage_used_mb * (1024 * 1024)

        # 计算存储使用百分比，并确保不会除以零
        if storage_info.total > 0:
            storage_total_percent = (storage_used_bytes / storage_info.total) * 100
        else:
            storage_total_percent = 0.0

        # 格式化为 xx.xx，保留两位小数
        storage_total_percent_formatted = round(storage_total_percent, 2)

    except ValueError as e:
        print(f"Error calculating storage percentage: {e}")
        storage_total_percent_formatted = 0.00

    # 返回JSON响应
    response_data = {
        "code": 200,
        "wordcloud": wordcloud_file,
        "storage_space_used": storage_used_str,
        "video_count": system_settings.get('video_count', '0'),
        "database_created_date": system_settings.get('database_created_date', ''),
        "disk_write_count": system_settings.get('disk_write_count', '0'),
        "disk_read_count": system_settings.get('disk_read_count', '0'),
        "Network_out_count": system_settings.get('Network_out_count', '0'),
        "storage_space_used_percent": storage_total_percent_formatted
    }

    return jsonify(response_data)


if __name__ == '__main__':
    init(database)
    update()
    app.run(debug=True, host="0.0.0.0", port=28257)
