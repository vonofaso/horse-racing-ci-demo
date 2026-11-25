# Лабораторная работа №2: обязательные ограничения

## 1. Приложение не работает от root

Приложение запускается через `project-app.service` от системного пользователя
`appsvc`:

```ini
[Service]
User=appsvc
Group=appsvc
```

Команду `sudo systemctl start project-app` выполняет администратор, но systemd
переключает сам процесс приложения на `appsvc`.

Проверка:

```bash
systemctl show project-app -p User -p Group
ps -o user,pid,cmd -p "$(systemctl show project-app -p MainPID --value)"
```

Ожидается `User=appsvc`, а в столбце `USER` — `appsvc`, не `root`.

Запрещено запускать приложение так:

```bash
sudo /opt/project/app/.venv/bin/python -m app
```

## 2. Лишние порты не открываются

Политика обеих VM: входящие соединения запрещены по умолчанию, исходящие
разрешены.

```bash
sudo ufw default deny incoming
sudo ufw default allow outgoing
```

### APP-VM

Разрешены:

- `22/tcp` — администрирование по SSH;
- `8000/tcp` на `tailscale0` — HTTP-приложение для клиентов tailnet.

Проверка:

```bash
sudo ufw status numbered
sudo ss -lntp
```

Порт `8000` не должен быть разрешён на обычном сетевом интерфейсе.

### DB-VM

Разрешены:

- `22/tcp` — администрирование по SSH;
- `5432/tcp` на `tailscale0` — только от точного Tailscale-IP APP-VM.

Пример допустимого правила:

```text
APP_TS_IP -> DB-VM:5432/tcp on tailscale0
```

Проверка:

```bash
sudo ufw status numbered
sudo ss -lntp
```

Запрещены широкие правила вида:

```text
5432/tcp ALLOW Anywhere
5432/tcp ALLOW 100.64.0.0/10
```

Дополнительное ограничение PostgreSQL в `pg_hba.conf`:

```text
host    project_db    appproject    APP_TS_IP/32    scram-sha-256
```

## 3. Пароли не хранятся в репозитории

В Git находится только `.env.example` с фиктивными значениями. Настоящая
конфигурация APP-VM хранится отдельно:

```text
/etc/project/project.env
```

Права файла:

```bash
sudo chown root:appsvc /etc/project/project.env
sudo chmod 640 /etc/project/project.env
sudo stat -c '%A %U %G %n' /etc/project/project.env
```

Ожидается:

```text
-rw-r----- root appsvc /etc/project/project.env
```

Проверка отслеживаемых файлов:

```bash
cd /opt/project/app
git ls-files | grep -E '(^|/)\.env$|project\.env' || true
```

Команда не должна находить реальный `.env` или `project.env`.

Проверка типичных присваиваний секретов:

```bash
git grep -nE 'DB_PASSWORD=|DATABASE_URL=.*@|PASSWORD=' || true
```

Допустимы только очевидно фиктивные значения в `.env.example` и документации.
Если реальный пароль когда-либо попал в коммит, простого удаления файла
недостаточно: пароль необходимо немедленно заменить в PostgreSQL.

Запрещено:

- коммитить `.env`, `project.env`, дампы БД и приватные SSH-ключи;
- записывать настоящий пароль в README, скрипты и unit-файл systemd;
- передавать приватные SSH-ключи другому участнику;
- выводить секреты в журнал приложения.

## 4. Проверка перед защитой

На APP-VM:

```bash
systemctl is-active project-app
systemctl is-enabled project-app
systemctl show project-app -p User -p Group
sudo ufw status numbered
sudo ss -lntp
curl -i http://127.0.0.1:8000/health
```

На DB-VM:

```bash
systemctl is-active postgresql
systemctl is-enabled postgresql
sudo ufw status numbered
sudo ss -lntp
```

Критерии приёмки:

1. Процесс приложения принадлежит `appsvc`.
2. После перезагрузки приложение и PostgreSQL запускаются автоматически.
3. После `kill -9` приложение автоматически перезапускается.
4. Клиент tailnet получает `200 OK` от `/health`.
5. PostgreSQL доступен с APP-VM и недоступен с постороннего узла.
6. Реальные пароли отсутствуют среди файлов, отслеживаемых Git.
