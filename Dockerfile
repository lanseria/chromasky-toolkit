# 使用官方的 Python 3.12 slim 版本作为基础镜像
FROM m.daocloud.io/docker.io/library/python:3.12

# 设置环境变量，防止 Python 生成 .pyc 文件和进行输出缓冲
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# 设置容器内的工作目录
WORKDIR /app

# --- 1. 配置 APT 镜像源  ---
RUN echo "\
Types: deb\n\
URIs: https://mirrors.tuna.tsinghua.edu.cn/debian/\n\
Suites: bookworm bookworm-updates bookworm-backports\n\
Components: main contrib non-free non-free-firmware\n\
Signed-By: /usr/share/keyrings/debian-archive-keyring.gpg\n\
" > /etc/apt/sources.list.d/debian.sources

# 为应用创建一个非 root 的系统用户和用户组，增强安全性
RUN addgroup --system app && adduser --system --group app

# 更新 apt 包列表并安装 cartopy 等库可能需要的系统依赖
# 安装后清理 apt 缓存以减小镜像体积
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgeos-dev \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*


# --- 2. 安装 Python 构建依赖 ---
# 在此阶段我们只需要 pip 和 wheel 工具
RUN pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple --upgrade pip wheel

# 首先只复制依赖定义文件
COPY pyproject.toml .

# 安装 Python 依赖
RUN pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple .

# 复制应用程序的源代码和工具脚本
COPY src/ src/
COPY tools/ tools/

# 在构建镜像时就运行地图数据下载脚本
# 这样地图数据就会被包含在最终的镜像里，无需每次启动容器都下载
RUN python tools/setup_map_data.py

# 创建运行时需要的数据和输出目录
# 这些目录后续可以通过挂载卷（Volume）来持久化数据
RUN mkdir -p /app/src/data /app/src/outputs

# 将整个工作目录的所有权交给刚刚创建的 app 用户
RUN chown -R app:app /app

# 切换到非 root 用户
USER app

ENV PYTHONPATH=/app/src

# 声明容器运行时监听的端口
EXPOSE 8000

# 容器启动时运行的命令
# 启动 uvicorn 服务器，并监听在 0.0.0.0 以便从容器外部访问
ENTRYPOINT ["uvicorn", "chromasky_toolkit.server:app", "--host", "0.0.0.0", "--port", "8000"]