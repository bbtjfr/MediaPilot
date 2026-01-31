# app/Dockerfile
# MediaPilot Bot 的 Docker 镜像定义

# 使用轻量的 Python 3.10 镜像作为基础
FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制所有应用代码
COPY . .

# 容器启动时运行的命令
CMD ["python", "bot.py"]
