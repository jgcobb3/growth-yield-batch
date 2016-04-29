BROKER_URL = 'redis://localhost:6379/0>'
BROKER_TRANSPORT_OPTIONS = {'visibility_timeout': 3600}
CELERY_RESULT_BACKEND = 'redis://localhost:6379/0>'
CELERY_DISABLE_RATE_LIMITS = True
CELERY_IMPORTS=("tasks",)  # look for a /var/celery/tasks.py