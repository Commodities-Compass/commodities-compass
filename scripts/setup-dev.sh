#!/bin/bash

# Development setup script for Commodities Compass

set -e

echo "🚀 Setting up Commodities Compass development environment..."

# Check prerequisites
echo "📋 Checking prerequisites..."

if ! command -v node &> /dev/null; then
    echo "❌ Node.js is not installed. Please install Node.js 18+ first."
    exit 1
fi

if ! command -v poetry &> /dev/null; then
    echo "❌ Poetry is not installed. Please install Poetry first."
    echo "   Run: curl -sSL https://install.python-poetry.org | python3 -"
    exit 1
fi

if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

echo "✅ Prerequisites check passed!"

# Install dependencies
echo "📦 Installing dependencies..."
pnpm install

# Backend setup
echo "🐍 Setting up backend..."
cd backend
poetry install
cd ..

# Frontend setup
echo "⚛️  Setting up frontend..."
cd frontend
pnpm install
cd ..

# Environment files
echo "🔧 Setting up environment files..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "📝 Created .env file. Please edit it with your configuration."
fi

if [ ! -f backend/.env ]; then
    cp backend/.env.example backend/.env
    echo "📝 Created backend/.env file. Please edit it with your configuration."
fi

if [ ! -f frontend/.env ]; then
    cp frontend/.env.example frontend/.env
    echo "📝 Created frontend/.env file. Please edit it with your configuration."
fi

# Git hooks
echo "🪝 Setting up git hooks..."

# Clear any existing git hooks path that might conflict
git config --unset-all core.hooksPath 2>/dev/null || true

# Initialize husky
pnpm exec husky init

# Update pre-commit hook with our custom commands
cat > .husky/pre-commit << 'EOF'
#!/usr/bin/env sh
# Run pre-commit hooks for backend
cd backend && poetry run pre-commit run --all-files

# Run frontend linting
cd ../frontend && pnpm run lint
EOF

chmod +x .husky/pre-commit

# Install pre-commit hooks for backend
cd backend
git config --unset-all core.hooksPath 2>/dev/null || true
poetry run pre-commit install
cd ..

echo "✅ Development environment setup complete!"
echo ""
echo "🔧 Next steps:"
echo "1. Edit .env, backend/.env, and frontend/.env with your configuration"
echo "2. Start PostgreSQL and Redis: docker-compose up -d"
echo "3. Configure your Auth0 application"
echo "4. Run 'pnpm dev' to start the development servers"
