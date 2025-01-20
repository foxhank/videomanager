import json


def get_disk_write_from_proc(device_name='sda'):
    with open('/proc/diskstats', 'r') as f:
        for line in f:
            columns = line.split()
            if len(columns) > 2 and columns[2] == device_name:
                sectors_written = int(columns[9])  # 写入的扇区数
                write_kb = sectors_written * 512 / 1024  # 转换为KB
                return write_kb
    return None


def get_disk_read_from_proc(device_name='sda'):
    with open('/proc/diskstats', 'r') as f:
        for line in f:
            columns = line.split()
            if len(columns) > 2 and columns[2] == device_name:
                sectors_read = int(columns[5])  # 读取的扇区数
                read_kb = sectors_read * 512 / 1024  # 转换为KB
                return read_kb
    return None


def get_network_out_from_proc(interface_name='enp2s0'):
    with open('/proc/net/dev', 'r') as f:
        for line in f:
            if interface_name in line:
                parts = line.split()
                network_out_used = int(parts[9]) / 1024  # 转换为KB
                return network_out_used
    return None


def load_state(TEMP_FILE_PATH):
    """从临时文件加载之前的状态"""
    try:
        with open(TEMP_FILE_PATH, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(state, TEMP_FILE_PATH):
    """将当前状态保存到临时文件"""
    with open(TEMP_FILE_PATH, 'w') as f:
        json.dump(state, f)
