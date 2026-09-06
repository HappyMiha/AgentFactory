"""Dated connection guidance, never account or execution authorization."""
from copy import deepcopy
from datetime import datetime, timezone

VERSION = 'provider-connections-2026-09-06'
REVIEWED_ON = '2026-09-06'
REVIEW_DUE = '2026-10-06'

_OPENAI_API = 'https://developers.openai.com/api/docs/quickstart'
_CODEX_AUTH = 'https://learn.chatgpt.com/docs/auth'
_CLAUDE_API = 'https://platform.claude.com/docs/en/manage-claude/authentication'
_CLAUDE_CODE = 'https://code.claude.com/docs/en/authentication'

_PRODUCTS = (
    {'id': 'chatgpt', 'title': 'Маю ChatGPT', 'provider': None, 'flow': 'separate_api_or_official_cli',
     'explanation': 'Підписка на чат не є ключем API й не підтверджує кредит для API. Для програми потрібен окремий API-доступ або окремо перевірене підключення через офіційний Codex.',
     'steps': ['Для API відкрийте варіант «Маю OpenAI API».', 'Для Codex перегляньте офіційний вхід нижче. Не копіюйте сюди пароль, cookies чи файл входу.'],
     'sources': [_CODEX_AUTH, _OPENAI_API]},
    {'id': 'openai-api', 'title': 'Маю OpenAI API', 'provider': 'openai', 'flow': 'provider_api_key',
     'explanation': 'Ключ API створюється у вашому кабінеті OpenAI. Оплата й доступ до моделей визначаються цим API-акаунтом.',
     'steps': ['Увійдіть у кабінет провайдера за офіційною інструкцією. Перевірте API-бюджет і дозволи.', 'Створіть ключ для потрібного проєкту. Вводьте його лише в захищене поле нижче після перевірки доступу.', 'Збереження ключа ще не перевіряє модель і не запускає AI.'],
     'sources': [_OPENAI_API, _CODEX_AUTH]},
    {'id': 'claude-chat', 'title': 'Маю чат Claude', 'provider': None, 'flow': 'separate_api_or_official_cli',
     'explanation': 'Вхід у чат Claude не є ключем Claude API. Офіційний Claude Code має власні способи входу; цей майстер не переносить його сесію.',
     'steps': ['Для API відкрийте варіант «Маю Claude API».', 'Для Claude Code користуйтеся офіційним входом у самому інструменті; перевірте, який акаунт оплачує роботу.'],
     'sources': [_CLAUDE_API, _CLAUDE_CODE]},
    {'id': 'anthropic-api', 'title': 'Маю Claude API', 'provider': 'anthropic', 'flow': 'provider_api_key',
     'explanation': 'Ключ створюється у Claude Console. Для першого підключення потрібен ключ, обмежений потрібним робочим простором; інші способи доступу цей майстер не налаштовує.',
     'steps': ['Увійдіть у Claude Console за офіційною інструкцією. Перевірте бюджет і права.', 'У налаштуваннях API keys створіть ключ для потрібного робочого простору та строк дії. Вводьте його лише в поле ключа.', 'Збереження ключа ще не підтверджує роботу моделі.'],
     'sources': [_CLAUDE_API, _CLAUDE_CODE]},
    {'id': 'codex-cli', 'title': 'Маю Codex CLI', 'provider': None, 'flow': 'official_cli_login',
     'explanation': 'Вхід виконується в офіційному Codex через браузер або ключ API. Це окремий спосіб доступу; цей майстер поки його автоматично не підключає.',
     'steps': ['У Codex CLI виконайте codex login і завершіть вхід у провайдера.', 'Для комп’ютера без браузера офіційна інструкція описує codex login --device-auth; доступність залежить від налаштувань акаунта.', 'Не вставляйте сюди одноразовий код, пароль або файл сесії. Повернення з входу не означає, що AgentFactory перевірив роботу інструмента.'],
     'sources': [_CODEX_AUTH]},
    {'id': 'claude-code', 'title': 'Маю Claude Code', 'provider': None, 'flow': 'official_cli_login',
     'explanation': 'Увійдіть у самому офіційному Claude Code. Його акаунт або налаштований API визначають оплату; цей майстер поки не пов’язує цю сесію з AgentFactory.',
     'steps': ['Відкрийте офіційну інструкцію входу Claude Code.', 'Перевірте активний спосіб входу та оплату. Не копіюйте токени сесії в поле API-ключа.', 'Окрема перевірка виконання й незалежного рецензування ще потрібна.'],
     'sources': [_CLAUDE_CODE]},
    {'id': 'other', 'title': 'Інший продукт або ще не знаю', 'provider': None, 'flow': 'unsupported',
     'explanation': 'Цей спосіб ще не описаний і не перевірений. Не купуйте підписку лише заради непідтвердженого підключення.',
     'steps': ['Можна зберегти задум і продовжити ручне планування без AI.', 'Підключення потребує окремої офіційної інструкції та перевірки.'], 'sources': []},
)


def connection_catalog(*, now=None):
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError('Aware catalogue time required')
    current = REVIEWED_ON <= instant.astimezone(timezone.utc).date().isoformat() < REVIEW_DUE
    products = deepcopy(list(_PRODUCTS))
    for product in products:
        product['key_storage_option'] = current and product['flow'] == 'provider_api_key'
        product['integration_status'] = 'key_storage_only' if product['key_storage_option'] else 'guidance_only'
    return {'version': VERSION, 'reviewed_on': REVIEWED_ON, 'review_due': REVIEW_DUE,
            'current': current, 'products': products, 'execution_ready': False,
            'qualified_capabilities': [], 'connection_checks': {name: 'not_run' for name in
                ('authentication', 'quota', 'model_access', 'coding', 'independent_review', 'network')},
            'notice': 'Оберіть те, чим уже користуєтеся. Це пояснення способу підключення, а не перевірка вашого акаунта.' if current else
                'Інструкції потребують нового огляду. Автоматичний вибір способу підключення призупинено; збережений доступ можна переглянути або відключити.'}
