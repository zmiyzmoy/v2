#!/bin/bash

# Убедимся, что мы в правильной директории
cd ~/ai_agent_infra_mvp/ || { echo "Ошибка: Директория ~/ai_agent_infra_mvp/ не найдена"; exit 1; }

echo "Обновление файла .env для использования MySQL с Evolution API..."
# Удаляем старый .env, если он есть, чтобы избежать смешивания строк (лучше перезаписать)
rm -f .env
cat << 'EOF_DOTENV' > .env
# --- Общие настройки ---
TZ=Europe/Moscow

# --- MongoDB (для Python API) ---
MONGO_ROOT_USER=admin_user 
MONGO_ROOT_PASSWORD=supersecretpassword123! # !!! СМЕНИТЕ ЭТОТ ПАРОЛЬ !!!
API_MONGO_DB_NAME=ai_agent_mvp_db 
API_MONGO_DIALOG_COLLECTION=dialog_history_mvp

# --- MySQL для Evolution API ---
MYSQL_DATABASE_EVOLUTION=evolution_mysql_db
MYSQL_USER_EVOLUTION=evolutionmysqluser
MYSQL_PASSWORD_EVOLUTION=evoMySQLpass123      # !!! СМЕНИТЕ НА СВОЙ НАДЕЖНЫЙ !!!
MYSQL_ROOT_PASSWORD=superRootMySQLsecret    # !!! СМЕНИТЕ НА СВОЙ НАДЕЖНЫЙ !!!

# --- n8n ---
N8N_UI_USER=n8nadmin 
N8N_UI_PASSWORD=changemeN8Npassword! # !!! СМЕНИТЕ ЭТОТ ПАРОЛЬ !!!
N8N_BASIC_AUTH_ACTIVE=true

# --- Evolution API ---
WHATSAPP_EVOLUTION_API_KEY=MySecretEvolutionAPIKey123 # !!! СМЕНИТЕ ЭТОТ КЛЮЧ !!!
EVOLUTION_PORT=8080 
EVOLUTION_HOST_PORT=8081

# --- Ваш Python AI Core API Service ---
API_LOG_LEVEL=INFO
OPENROUTER_API_KEY=your_openrouter_api_key_here # !!! ВСТАВЬТЕ ВАШ РЕАЛЬНЫЙ КЛЮЧ OPENROUTER !!!
API_DEFAULT_LLM_MODEL=deepseek/deepseek-chat
LANGCHAIN_API_KEY=your_langsmith_api_key_here # !!! ВСТАВЬТЕ ВАШ РЕАЛЬНЫЙ КЛЮЧ LANGSMITH !!!
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=MVP_AI_Agent_Prod_Server_Unique 
API_MVP_CLIENT_ID=salon_krasoty_mvp
API_MVP_CLIENT_NAME="Салон Красоты 'SuperStar' (MVP)"
API_MVP_CLIENT_PERSONA="дружелюбный и профессиональный консультант салона красоты"
API_MVP_CLIENT_TONE="заботливый и экспертный"
API_MVP_BUSINESS_TYPE="beauty_salon"
API_DEFAULT_LANG=ru
API_SERVICE_PORT=8000 
API_HOST_PORT=8000 
EOF_DOTENV
echo ".env файл обновлен."
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
echo "!!! ВНИМАНИЕ: Откройте файл .env (nano .env) и ЗАМЕНИТЕ ВСЕ ПАРОЛИ И КЛЮЧИ  !!!"
echo "!!! на ваши реальные и безопасные значения ПЕРЕД запуском docker-compose up !!!"
echo "!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!"
# read -p "Нажмите Enter, когда будете готовы продолжить после редактирования .env файла..."


echo "Обновление файла docker-compose.yml для использования MySQL с Evolution API..."
rm -f docker-compose.yml
cat << 'EOF_DOCKER_COMPOSE' > docker-compose.yml
services:
  n8n:
    image: n8nio/n8n:1.46.0 
    container_name: mvp_n8n
    restart: unless-stopped
    ports:
      - "5678:5678"
    environment:
      - N8N_HOST=${N8N_SUBDOMAIN:-localhost}.${N8N_DOMAIN_NAME:-localhost} 
      - N8N_PORT=5678
      - N8N_PROTOCOL=${N8N_PROTOCOL:-http}
      - NODE_ENV=${NODE_ENV:-production}
      - WEBHOOK_URL=http://${N8N_HOST:-n8n}:${N8N_PORT:-5678}/ 
      - GENERIC_TIMEZONE=${TZ:-Europe/Moscow}
      - N8N_BASIC_AUTH_ACTIVE=${N8N_BASIC_AUTH_ACTIVE:-true}
      - N8N_BASIC_AUTH_USER=${N8N_UI_USER:-admin}
      - N8N_BASIC_AUTH_PASSWORD=${N8N_UI_PASSWORD:-changemeNOW}
    volumes:
      - ./n8n_data:/home/node/.n8n 
    networks:
      - app_network

  evolution_api:
    image: atendai/evolution-api:latest 
    container_name: mvp_evolution_api
    restart: unless-stopped
    environment:
      - SERVER_PORT=${EVOLUTION_PORT:-8080}
      - CORS_ENABLED=true 
      - AUTH_API_KEY=${WHATSAPP_EVOLUTION_API_KEY}
      - WEBHOOK_GLOBAL_URL=http://n8n:5678/webhook-test/whatsapp_incoming_mvp 
      - WEBHOOK_MESSAGE_RECEIVED=true
      - WEBHOOK_MESSAGE_CREATE=true
      - WEBHOOK_CONNECTION_QRCODE=true
      
      - DATABASE_ENABLED=true
      - DATABASE_TYPE=mysql 
      - DB_HOST=mysql_db        
      - DB_PORT=3306          
      - DB_USERNAME=${MYSQL_USER_EVOLUTION}
      - DB_PASSWORD=${MYSQL_PASSWORD_EVOLUTION}
      - DB_DATABASE=${MYSQL_DATABASE_EVOLUTION}
      # Альтернативные имена переменных, если стандартные DB_ не сработают для этого образа:
      # - TYPEORM_CONNECTION=mysql
      # - TYPEORM_HOST=mysql_db
      # - TYPEORM_PORT=3306
      # - TYPEORM_USERNAME=${MYSQL_USER_EVOLUTION}
      # - TYPEORM_PASSWORD=${MYSQL_PASSWORD_EVOLUTION}
      # - TYPEORM_DATABASE=${MYSQL_DATABASE_EVOLUTION}
    volumes:
      - ./evolution_data:/evolution/instances 
    depends_on:
      - mysql_db 
    networks:
      - app_network
    ports: 
      - "8081:8080"

  mysql_db:
    image: mysql:8.0 
    container_name: mvp_mysql_db
    restart: unless-stopped
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_ROOT_PASSWORD}
      - MYSQL_DATABASE=${MYSQL_DATABASE_EVOLUTION} 
      - MYSQL_USER=${MYSQL_USER_EVOLUTION}
      - MYSQL_PASSWORD=${MYSQL_PASSWORD_EVOLUTION}
    command: --default-authentication-plugin=mysql_native_password
    volumes:
      - mysql_data:/var/lib/mysql 
    networks:
      - app_network

  mongodb:
    image: mongo:6.0 
    container_name: mvp_mongodb
    restart: unless-stopped
    environment:
      - MONGO_INITDB_ROOT_USERNAME=${MONGO_ROOT_USER}
      - MONGO_INITDB_ROOT_PASSWORD=${MONGO_ROOT_PASSWORD}
    volumes:
      - ./mongo_data:/data/db 
    networks:
      - app_network

  ai_core_api:
    build:
      context: ./ai_core_api_service 
      dockerfile: Dockerfile.apicenter
    container_name: mvp_ai_core_api
    restart: unless-stopped
    environment:
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=${API_LOG_LEVEL:-INFO}
      - MONGO_CONNECTION_STRING=mongodb://${MONGO_ROOT_USER}:${MONGO_ROOT_PASSWORD}@mongodb:27017/?authSource=admin&directConnection=true
      - MONGO_DATABASE_NAME=${API_MONGO_DB_NAME:-ai_agent_mvp_db}
      - MONGO_DIALOG_HISTORY_COLLECTION=${API_MONGO_DIALOG_COLLECTION:-dialog_history_mvp}
      - OPENROUTER_API_KEY=${OPENROUTER_API_KEY}
      - DEFAULT_LLM_MODEL=${API_DEFAULT_LLM_MODEL:-deepseek/deepseek-chat}
      - LANGCHAIN_API_KEY=${LANGCHAIN_API_KEY}
      - LANGCHAIN_TRACING_V2=${LANGCHAIN_TRACING_V2:-true}
      - LANGCHAIN_ENDPOINT=${LANGCHAIN_ENDPOINT:-https://api.smith.langchain.com}
      - LANGCHAIN_PROJECT=${LANGCHAIN_PROJECT:-MVP_AI_Agent_Core}
      - I18N_PATH_API=/app/app/core/locales 
      - DEFAULT_LANG_API=${API_DEFAULT_LANG:-ru}
      - MVP_CLIENT_ID=${API_MVP_CLIENT_ID:-salon_krasoty_mvp}
      - MVP_CLIENT_NAME=${API_MVP_CLIENT_NAME:-Салон Красоты 'SuperStar' (MVP)}
      - MVP_CLIENT_PERSONA=${API_MVP_CLIENT_PERSONA:-дружелюбный и профессиональный консультант}
      - MVP_CLIENT_TONE=${API_MVP_CLIENT_TONE:-заботливый и экспертный}
      - MVP_BUSINESS_TYPE=${API_MVP_BUSINESS_TYPE:-beauty_salon}
      - API_HOST=0.0.0.0 
      - API_PORT=${API_SERVICE_PORT:-8000} 
    depends_on:
      - mongodb 
    networks:
      - app_network
    ports: 
      - "8000:8000"

volumes: 
  mysql_data:

networks:
  app_network:
    driver: bridge
EOF_DOCKER_COMPOSE
echo "docker-compose.yml файл обновлен."

echo ""
echo "Все необходимые файлы конфигурации обновлены."
echo "Пожалуйста, НЕ ЗАБУДЬТЕ отредактировать файл .env и заменить все плейсхолдеры паролей и API-ключей!"
echo "Пример команды для редактирования: nano .env"
echo "После этого вы можете выполнить: docker compose up -d --build"
