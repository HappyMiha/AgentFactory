# Автодеплой, бекап і rollback для Lokvetia Core

Для Core та Lokiravia запускаються GitHub Actions, які:

- перевіряють, чи змінився Git HEAD порівняно з останнім деплоєм;
- роблять timestamped backup вказаних шляхів даних;
- виконують підготовку і активацію релізу;
- запускають health check;
- при помилці виконують rollback коду (за вашим скриптом) і відновлюють бекап даних.

## Файли

- Пайплайн: `.github/workflows/autodeploy.yml`
- Робочий скрипт: `scripts/autodeploy.py`
- Стан: `.github/autodeploy/state.json`
- Бекапи: `.github/autodeploy/backups/...`
- Сторінка статусів: `docs/deploy-dashboard.html`

## Необхідні репозиторійні змінні GitHub (Settings → Secrets and variables → Actions → Variables)

| Змінна | Призначення |
|---|---|
| `DEPLOY_DATA_PATHS` | Список шляхів для бекапу, розділені комою/крапкою з комою/новим рядком. Напр. `.agent-factory/state.db,.agent-factory-data` |
| `DEPLOY_PREPARE_COMMAND` | Підготовча команда перед релізом (необов’язково). |
| `DEPLOY_ACTIVATE_COMMAND` | Команда фактичного rollout (обов’язково). |
| `DEPLOY_ROLLBACK_COMMAND` | Команда rollback коду/runtime (рекомендується встановити для критичних сервісів). |
| `DEPLOY_HEALTH_COMMAND` | Команда перевірки, що сервіс працює після rollout. |
| `DEPLOY_RELEASE_NOTES_COMMAND` | Команда, яка повертає release-notes (необов’язково; за замовчуванням бере commit message). |

Всі ці змінні використовує `scripts/autodeploy.py` через середовище.

## Рекомендований підхід для збереження клієнтських даних

- backup має бути **snapshot of data paths**, які не містять runtime cache;
- rollback повинен повертати дані на рівні файлових баз (`*.db`, `*.sqlite3`) до стану до rollout;
- `DEPLOY_ACTIVATE_COMMAND` має виконувати атомарний переключатель (blue-green, symlink, контейнерний reload), без прямого `kill` довгих фон-сервісів;
- `DEPLOY_HEALTH_COMMAND` має перевіряти працездатний endpoint (наприклад `/health`);
- `DEPLOY_ROLLBACK_COMMAND` повинен бути ідемпотентним (повторний виклик без шкоди).

## Мінімальна логіка (приклад)

```sh
DEPLOY_PREPARE_COMMAND="git fetch origin main && git reset --hard origin/main"
DEPLOY_ACTIVATE_COMMAND="supervisorctl restart lokvetia-core"
DEPLOY_ROLLBACK_COMMAND="supervisorctl restart lokvetia-core"
DEPLOY_HEALTH_COMMAND="curl -fsS http://127.0.0.1:8765/healthz"
DEPLOY_RELEASE_NOTES_COMMAND="git log -1 --pretty=%B"
```

## Як дивитися статус

Відкрийте `docs/deploy-dashboard.html` у GitHub Pages (або вручну перегляньте в репозиторії).
На сторінці видно:

- який проєкт зараз деплоїться;
- поточний статус (`success`, `failure`, `in_progress`);
- текст помилки та commit;
- release notes.

## Безпекові нотатки

- Зберігайте секрети (ключі доступу до сервісів, токени AI, DB credentials) як GitHub Secrets і не вшивайте в `vars`.
- Перед увімкненням автодеплою зробіть пробний manual `workflow_dispatch`.
- Перший rollout краще виконувати через окремий підготовчий commit, щоб перевірити сумісність команд і restore сценарію.
