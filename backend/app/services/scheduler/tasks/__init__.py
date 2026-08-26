"""定时任务注册表自动加载。

import 此模块时，所有 ``@register_task`` 装饰的函数将自动注册。
"""

from app.services.scheduler.tasks.news_crawl import *  # noqa: F401, F403
from app.services.scheduler.tasks.rag_reconcile import *  # noqa: F401, F403
from app.services.scheduler.tasks.fund_ranking_sync import *  # noqa: F401, F403
from app.services.scheduler.tasks.fund_catalog_sync import *  # noqa: F401, F403
from app.services.scheduler.tasks.fund_history_sync import *  # noqa: F401, F403
