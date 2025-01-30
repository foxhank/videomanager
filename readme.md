

# 视频管理系统

视频管理系统是一个基于Flask框架开发的Web应用，旨在提供视频上传、管理和统计等功能。

## 项目结构
```
videomanager/
│
├── app.py               # Flask应用主文件
├── requirements.txt     # 包含所有依赖包及其版本
├── .gitignore           # Git忽略文件配置
├── webfonts             # 使用的字体文件等
├── static               # 使用的静态资源文件
├── templates            # 前端html文件
├── database.db          # SQLite数据库（启动后创建）
└── ...                  # 其他目录和文件
```

## 环境准备

### 安装依赖
在开始之前，请确保您的环境中已安装Python 3.x。然后，通过以下命令安装所需的Python包：
```bash
pip install -r requirements.txt
```


## 如何启动项目

1. **进入项目根目录**
   打开命令行工具并导航至项目的根目录：
   ```bash
   cd videomanager
   ```

2. **启动Flask应用**
   在项目根目录下运行以下命令来启动Flask服务器：
   ```bash
   python main.py
   ```

   随后您可以在浏览器中访问`http://localhost:28257`来查看您的应用。

   3. 进入管理后台
      访问`http://localhost:28257/dashboard` 进入管理后台，可以对上传的视频进行管理。


