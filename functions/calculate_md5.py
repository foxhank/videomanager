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