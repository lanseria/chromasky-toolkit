# 使用官方的 Python 3.12 slim 版本作为基础镜像
FROM m.daocloud.io/docker.io/library/python:3.12

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    HOME=/app \
    PYTHONPATH=/app/src \
    # --- 核心修复：为 Matplotlib 和 Cartopy 指定统一、可写的配置/数据目录 ---
    MPLCONFIGDIR=/app/config/matplotlib \
    CARTOPY_DATA_DIR=/app/data/cartopy_data

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

# 更新 apt 包列表并安装 cartopy 等库可能需要的系统依赖
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libgeos-dev \
    tzdata \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 这解决了 /nonexistent 的问题
RUN addgroup --system app && adduser --system --group --home /app app

RUN mkdir -p /app/config/matplotlib /app/data/cartopy_data /app/map_data /app/fonts /app/outputs

# 安装 Python 依赖
COPY pyproject.toml .
RUN pip install -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple --upgrade pip wheel && \
    pip install --no-cache-dir -i https://mirrors.tuna.tsinghua.edu.cn/pypi/web/simple .

# 预下载 Cartopy 数据到我们指定的新目录
RUN python -c "import cartopy.io.shapereader as shpreader; \
    shpreader.natural_earth(resolution='50m', category='physical', name='land'); \
    shpreader.natural_earth(resolution='50m', category='physical', name='ocean'); \
    shpreader.natural_earth(resolution='50m', category='physical', name='coastline');"

# 复制应用程序的源代码和工具脚本
COPY src/ src/
COPY tools/ tools/
COPY .env src/.env

# 在构建镜像时就运行地图和字体数据下载脚本
RUN python tools/setup_map_data.py

# 将整个工作目录的所有权交给刚刚创建的 app 用户
RUN chown -R app:app /app/data /app/outputs /app/map_data /app/fonts /app/cartopy_data

# 切换到非 root 用户
USER app

ENV PYTHONPATH=/app/src

# 声明容器运行时监听的端口
EXPOSE 8000

# --- 新增: 为数据和输出目录声明卷 ---
# 这明确表示这些目录用于存储持久化数据
VOLUME /app/data
VOLUME /app/outputs

# 容器启动时运行的命令
ENTRYPOINT ["uvicorn", "chromasky_toolkit.server:app", "--host", "0.0.0.0", "--port", "8000"]