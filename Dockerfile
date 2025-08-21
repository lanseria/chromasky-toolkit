# 使用官方的 Python 3.12 slim 版本作为基础镜像
FROM m.daocloud.io/docker.io/library/python:3.12

# 设置环境变量，防止 Python 生成 .pyc 文件和进行输出缓冲
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# --- 关键修复 1: 为 Cartopy 指定一个明确的数据目录 ---
ENV CARTOPY_DATA_DIR=/app/cartopy_data

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

# --- 关键修复 2: 创建用户时，为其指定一个有效的主目录 ---
# 使用 --home /app 将用户的主目录设置为工作目录 /app
# 这解决了 /nonexistent 的问题
RUN addgroup --system app && adduser --system --group --home /app app

# 更新 apt 包列表并安装 cartopy 等库可能需要的系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgeos-dev \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# --- 2. 安装 Python 构建依赖 ---
RUN pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple --upgrade pip wheel

# 首先只复制依赖定义文件
COPY pyproject.toml .

# 安装 Python 依赖
RUN pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple .

# --- 在构建镜像时以 root 身份预下载 Cartopy 所需的地图数据 ---
RUN python -c "import cartopy.io.shapereader as shpreader; \
    shpreader.natural_earth(resolution='50m', category='physical', name='land'); \
    shpreader.natural_earth(resolution='50m', category='physical', name='ocean'); \
    shpreader.natural_earth(resolution='50m', category='physical', name='coastline');"

# 复制应用程序的源代码和工具脚本
COPY src/ src/
COPY tools/ tools/
COPY .env src/

# 在构建镜像时就运行地图和字体数据下载脚本
RUN python tools/setup_map_data.py

# 创建运行时需要的数据和输出目录
RUN mkdir -p /app/src/data /app/src/outputs

# 将整个工作目录的所有权交给刚刚创建的 app 用户
RUN chown -R app:app /app

# --- 关键修复 3: 为用户明确设置 HOME 环境变量 ---
ENV HOME=/app

# 切换到非 root 用户
USER app

ENV PYTHONPATH=/app/src

# 声明容器运行时监听的端口
EXPOSE 8000

# 容器启动时运行的命令
ENTRYPOINT ["uvicorn", "chromasky_toolkit.server:app", "--host", "0.0.0.0", "--port", "8000"]