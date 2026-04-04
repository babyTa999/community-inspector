#!/bin/bash
# IceWhale CRM - ZimaBoard 2 一键安装脚本
# Usage: ./install-zimaboard.sh

set -e

echo "🐋 IceWhale CRM Installer for ZimaBoard 2"
echo "=========================================="

# 检查是否在 ZimaBoard 上
if [[ $(uname -m) != "x86_64" ]]; then
    echo "⚠️  Warning: This script is designed for ZimaBoard 2 (x86_64)"
    read -p "Continue anyway? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# 检查 Docker
echo "📦 Checking Docker..."
if ! command -v docker &> /dev/null; then
    echo "Installing Docker..."
    curl -fsSL https://get.docker.com | sh
    sudo usermod -aG docker $USER
    echo "✅ Docker installed. Please log out and log back in, then re-run this script."
    exit 0
fi

# 检查 Docker Compose
echo "📦 Checking Docker Compose..."
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    echo "Installing Docker Compose..."
    sudo apt-get update
    sudo apt-get install -y docker-compose-plugin
fi

# 创建工作目录
INSTALL_DIR="${HOME}/icewhale-crm"
echo "📁 Creating directory: $INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
cd "$INSTALL_DIR"

# 下载配置文件
echo "⬇️  Downloading configuration files..."
if [ ! -f "docker-compose.yml" ]; then
    curl -fsSL https://raw.githubusercontent.com/babyTa999/icewhale-CRM/main/docker-compose.yml -o docker-compose.yml
fi

# 创建数据目录
echo "📂 Setting up data directories..."
mkdir -p data/{ollama,qdrant,n8n}

# 创建环境文件
echo "⚙️  Creating environment file..."
if [ ! -f ".env" ]; then
    cat > .env << 'EOF'
# IceWhale CRM Configuration
AI_MODE=local
ANTHROPIC_API_KEY=
N8N_USER=admin
N8N_PASSWORD=icewhale123
N8N_HOST=localhost
DATABASE_URL=sqlite:///data/crm.db
QDRANT_URL=http://qdrant:6333
OLLAMA_URL=http://ollama:11434
EOF
    echo "✅ Created .env file. Edit it to customize settings."
fi

# 启动服务
echo "🚀 Starting services..."
docker compose up -d qdrant n8n

# 等待 Ollama 并拉取模型
echo "🤖 Setting up Ollama and downloading AI models..."
echo "⏳ This may take 10-30 minutes depending on your internet speed..."
docker compose up -d ollama

# 等待 Ollama 就绪
echo "⏳ Waiting for Ollama to be ready..."
until curl -s http://localhost:11434/api/tags > /dev/null 2>&1; do
    sleep 5
    echo "  Still waiting..."
done

# 拉取模型
echo "📥 Downloading DeepSeek-Coder 6.7B (this will take a while)..."
curl -X POST http://localhost:11434/api/pull -d '{"name": "deepseek-coder:6.7b"}' || true

echo "📥 Downloading nomic-embed-text..."
curl -X POST http://localhost:11434/api/pull -d '{"name": "nomic-embed-text"}' || true

# 构建并启动 CRM
echo "🏗️  Building CRM application..."
docker compose build crm
docker compose up -d crm

# 显示状态
echo ""
echo "✅ Installation complete!"
echo ""
echo "📊 Services:"
echo "  - CRM:        http://localhost:8080"
echo "  - n8n:        http://localhost:5678"
echo "  - Qdrant:     http://localhost:6333"
echo "  - Ollama:     http://localhost:11434"
echo ""
echo "🔧 Useful commands:"
echo "  cd $INSTALL_DIR"
echo "  docker compose logs -f crm    # View CRM logs"
echo "  docker compose ps             # Check service status"
echo "  docker compose down           # Stop all services"
echo "  docker compose up -d          # Start all services"
echo ""
echo "⚠️  Default n8n credentials:"
echo "  Username: admin"
echo "  Password: icewhale123"
echo ""
echo "🎉 Enjoy IceWhale CRM!"
