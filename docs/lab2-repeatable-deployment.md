# Лабораторная работа №2: повторяемое развёртывание

## Общие шаги для обеих VM

### 1. Обновление и базовые пакеты

```bash
sudo apt update
sudo apt full-upgrade -y
sudo apt install -y curl ca-certificates git ufw openssh-server
```

Это устанавливает средства загрузки, Git, firewall и SSH-сервер.

### 2. Административный пользователь

```bash
sudo adduser deployadmin
sudo usermod -aG sudo deployadmin
```

Публичный ключ администратора добавляется в
`/home/deployadmin/.ssh/authorized_keys`. После успешной проверки входа по ключу
создаётся `/etc/ssh/sshd_config.d/99-security.conf`:

```text
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
```

```bash
sudo sshd -t
sudo systemctl reload ssh
```

### 3. Tailscale

```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
sudo systemctl enable --now tailscaled
tailscale ip -4
tailscale status
```

Обе VM авторизуются в одном tailnet. Связность проверяется в обе стороны:

```bash
tailscale ping IP_ВТОРОЙ_VM
```

## DB-VM: сервер PostgreSQL

### 1. Установка и автозапуск

```bash
sudo apt install -y postgresql postgresql-client
sudo systemctl enable --now postgresql
```

### 2. База и минимальная прикладная роль

```bash
sudo -u postgres psql
```

В консоли PostgreSQL:

```sql
CREATE ROLE appproject
    LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
\password appproject
CREATE DATABASE project_db OWNER appproject;
REVOKE ALL ON DATABASE project_db FROM PUBLIC;
GRANT CONNECT ON DATABASE project_db TO appproject;
\q
```

Команда `\password` запрашивает пароль интерактивно и не требует записывать его
в скрипт или историю команд.

### 3. Сетевой доступ PostgreSQL

```bash
sudo -u postgres psql -c "ALTER SYSTEM SET listen_addresses = '0.0.0.0';"
sudo -u postgres psql -tAc "SHOW hba_file;"
```

В показанный `pg_hba.conf` добавить строку, заменив `APP_TS_IP`:

```text
host    project_db    appproject    APP_TS_IP/32    scram-sha-256
```

`0.0.0.0` устраняет гонку запуска PostgreSQL и интерфейса Tailscale после
перезагрузки. Доступ всё равно ограничивается одновременно `pg_hba.conf` и UFW.

```bash
sudo systemctl restart postgresql
sudo -u postgres psql -P pager=off -c \
  "SELECT line_number,type,database,user_name,address,auth_method,error
   FROM pg_hba_file_rules ORDER BY line_number;"
```

### 4. Firewall DB-VM

Сначала определить имя обычного интерфейса (`enp0s1`, `ens3` и т. п.):

```bash
ip -br address
```

Затем настроить UFW, заменив `enp0s1` и `APP_TS_IP`:

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on enp0s1 to any port 22 proto tcp
sudo ufw allow in on tailscale0 to any port 22 proto tcp
sudo ufw allow in on tailscale0 from APP_TS_IP to any port 5432 proto tcp
sudo ufw enable
sudo ufw status numbered
```

Порт `5432` разрешён только серверу приложения.

### 5. Проверка DB-VM

```bash
systemctl is-active postgresql
systemctl is-enabled postgresql
pg_isready -h 127.0.0.1 -p 5432 -t 5
pg_isready -h DB_TS_IP -p 5432 -t 5
sudo ss -lntp | grep 5432
```

## APP-VM: сервер приложения

### 1. Системный пользователь и каталог

```bash
sudo useradd --system --home-dir /opt/project --create-home \
  --shell /usr/sbin/nologin appsvc
sudo install -d -o appsvc -g appsvc -m 0750 /opt/project/app
```

Приложение работает от `appsvc`, а не от root.

### 2. Получение исходного кода

```bash
sudo -u appsvc git clone REPOSITORY_URL /opt/project/app
```

Для обновления уже развёрнутого приложения:

```bash
sudo -u appsvc git -C /opt/project/app pull --ff-only
```

### 3. Python 3.12 и зависимости

Python 3.12 устанавливается через `uv`, поскольку системный Python 3.14 не
совместим с закреплённой версией `pydantic-core` проекта.

```bash
sudo -u appsvc env HOME=/opt/project \
  sh -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'

sudo -u appsvc env HOME=/opt/project sh -c \
  'cd /opt/project/app && /opt/project/.local/bin/uv venv --python 3.12 --seed .venv'

sudo -u appsvc env HOME=/opt/project sh -c \
  'cd /opt/project/app && .venv/bin/python -m pip install -r requirements.txt'
```

### 4. Конфигурация вне исходного кода

```bash
sudo install -d -o root -g appsvc -m 0750 /etc/project
sudo nano /etc/project/project.env
```

Содержимое (значения заменить локально):

```ini
APP_NAME="Скачки API"
APP_VERSION=v0.1.0
APP_HOST=0.0.0.0
APP_PORT=8000
APP_RELOAD=false
LOG_LEVEL=info
DATABASE_URL=postgresql://appproject:DB_PASSWORD@DB_TS_IP:5432/project_db?connect_timeout=5
```

```bash
sudo chown root:appsvc /etc/project/project.env
sudo chmod 640 /etc/project/project.env
```

Реальный `project.env` не копируется в репозиторий.

### 5. systemd-служба

Создать `/etc/systemd/system/project-app.service`:

```ini
[Unit]
Description=Horse Racing Application
Wants=network-online.target
After=network-online.target tailscaled.service

[Service]
Type=simple
User=appsvc
Group=appsvc
WorkingDirectory=/opt/project/app
EnvironmentFile=/etc/project/project.env
ExecStart=/opt/project/app/.venv/bin/python -m app
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now project-app
sudo systemctl status project-app --no-pager
```

### 6. Firewall APP-VM

```bash
ip -br address
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow in on enp0s1 to any port 22 proto tcp
sudo ufw allow in on tailscale0 to any port 22 proto tcp
sudo ufw allow in on tailscale0 to any port 8000 proto tcp
sudo ufw enable
sudo ufw status numbered
```

`enp0s1` следует заменить реальным именем обычного интерфейса. Порт `8000`
доступен клиентам tailnet, но не публикуется через обычный интерфейс VM.

## Общие финальные проверки

### Проверка приложения и БД

С DB-VM или другого разрешённого клиента Tailscale:

```bash
curl -i http://APP_TS_IP:8000/health
```

Ожидается `HTTP/1.1 200 OK` и:

```json
{"status":"ok","database":"ok"}
```

### Проверка аварийного перезапуска

На APP-VM:

```bash
systemctl show project-app -p MainPID -p NRestarts
sudo kill -9 "$(systemctl show project-app -p MainPID --value)"
sleep 7
systemctl show project-app -p MainPID -p NRestarts
systemctl is-active project-app
```

PID должен измениться, `NRestarts` — увеличиться, состояние — стать `active`.

### Проверка поведения без БД

На DB-VM:

```bash
sudo systemctl stop postgresql
```

Проверить `/health` и журнал приложения, затем восстановить БД:

```bash
sudo systemctl start postgresql
```

### Проверка автозапуска

Перезагрузить обе VM:

```bash
sudo reboot
```

После загрузки проверить:

```bash
systemctl is-active tailscaled
systemctl is-enabled tailscaled
```

На APP-VM дополнительно:

```bash
systemctl is-active project-app
systemctl is-enabled project-app
```

На DB-VM дополнительно:

```bash
systemctl is-active postgresql
systemctl is-enabled postgresql
```

